#!/usr/bin/env python
"""Build the Typlus self-contained .app via py2app.

Plain ``build_app.py`` produces an ad-hoc signed bundle, which is fine on the
machine that built it and refused by Gatekeeper anywhere else. ``--release``
signs with a Developer ID, notarizes, staples, and wraps the result in a disk
image that a stranger can download and open by double-clicking.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
VERSION_FILE = ROOT / "typeless_local" / "_version.py"
ENTITLEMENTS = ROOT / "assets" / "entitlements.plist"
BUNDLE_ID = "com.alllllenshi.typlus"
APP_NAME = "Typlus"
VERSION = "0.2.0"
# The keychain profile `xcrun notarytool store-credentials` wrote.
NOTARY_PROFILE = os.environ.get("TYPLUS_NOTARY_PROFILE", "Typlus")


def short_hash() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True
        ).strip()
        dirty = (
            subprocess.run(
                ["git", "diff-index", "--quiet", "HEAD"], cwd=ROOT
            ).returncode
            != 0
        )
        return f"{out}{'+dirty' if dirty else ''}"
    except Exception:
        return "unknown"


def bake_version() -> None:
    h = short_hash()
    VERSION_FILE.write_text(
        f'"""Build-time version marker. Overwritten by scripts/build_app.py."""\n\n'
        f'VERSION = "{VERSION}+{h}"\n',
        encoding="utf-8",
    )
    print(f"baked version: {VERSION}+{h}")


def clean() -> None:
    for d in (BUILD, DIST):
        if d.exists():
            print(f"rm -rf {d}")
            shutil.rmtree(d)


def build() -> Path:
    subprocess.check_call([sys.executable, "setup.py", "py2app"], cwd=ROOT)
    app = DIST / f"{APP_NAME}.app"
    if not app.exists():
        raise SystemExit(f"build did not produce {app}")
    return app


def signing_identity() -> str | None:
    """The Developer ID Application identity, or None when none is installed.

    An "Apple Development" certificate is deliberately not accepted: it signs
    fine locally but cannot be notarized, so a build using it would look like
    a release and fail on every machine but this one.
    """

    override = os.environ.get("TYPLUS_SIGN_IDENTITY")
    if override:
        return override
    out = subprocess.run(
        ["security", "find-identity", "-v", "-p", "codesigning"],
        capture_output=True,
        text=True,
    ).stdout
    for line in out.splitlines():
        if "Developer ID Application" in line and '"' in line:
            return line.split('"')[1]
    return None


def sign_adhoc(app: Path) -> None:
    print("signing ad-hoc: this bundle will only run on this Mac")
    subprocess.check_call(["codesign", "--force", "--deep", "--sign", "-", str(app)])


def sign_release(app: Path, identity: str) -> None:
    """Sign every nested binary, then the bundle, with the hardened runtime."""

    print(f"signing with: {identity}")
    # Nested code has to be signed before whatever contains it. --deep walks in
    # an order py2app's tree does not satisfy, and Apple deprecated it anyway.
    nested = sorted(
        path
        for path in (app / "Contents").rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and (path.suffix in {".so", ".dylib"} or _is_macho_executable(path))
    )
    for path in nested:
        subprocess.check_call(
            [
                "codesign", "--force", "--timestamp",
                "--options", "runtime",
                "--sign", identity, str(path),
            ]
        )
    print(f"signed {len(nested)} nested binaries")
    subprocess.check_call(
        [
            "codesign", "--force", "--timestamp",
            "--options", "runtime",
            "--entitlements", str(ENTITLEMENTS),
            "--sign", identity, str(app),
        ]
    )
    subprocess.check_call(["codesign", "--verify", "--strict", "--verbose=2", str(app)])


def _is_macho_executable(path: Path) -> bool:
    if not os.access(path, os.X_OK):
        return False
    try:
        with path.open("rb") as handle:
            magic = handle.read(4)
    except OSError:
        return False
    # 64-bit Mach-O, and the fat/universal wrapper around it.
    return magic in {
        b"\xcf\xfa\xed\xfe",
        b"\xfe\xed\xfa\xcf",
        b"\xca\xfe\xba\xbe",
        b"\xbe\xba\xfe\xca",
    }


def notarize(target: Path) -> None:
    """Submit to Apple, wait for the verdict, and staple it onto the file."""

    with tempfile.TemporaryDirectory() as tmp:
        payload = target
        if target.is_dir():
            payload = Path(tmp) / f"{target.stem}.zip"
            subprocess.check_call(
                ["ditto", "-c", "-k", "--keepParent", str(target), str(payload)]
            )
        print(f"submitting {payload.name} to Apple; this waits for the verdict")
        subprocess.check_call(
            [
                "xcrun", "notarytool", "submit", str(payload),
                "--keychain-profile", NOTARY_PROFILE,
                "--wait",
            ]
        )
    subprocess.check_call(["xcrun", "stapler", "staple", str(target)])
    print(f"stapled {target.name}")


def make_dmg(app: Path) -> Path:
    """A disk image with an Applications shortcut, the usual way to install."""

    dmg = DIST / f"{APP_NAME}-{VERSION}.dmg"
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp) / APP_NAME
        staging.mkdir()
        shutil.copytree(app, staging / app.name, symlinks=True)
        (staging / "Applications").symlink_to("/Applications")
        subprocess.check_call(
            [
                "hdiutil", "create",
                "-volname", APP_NAME,
                "-srcfolder", str(staging),
                "-ov", "-format", "UDZO",
                str(dmg),
            ]
        )
    return dmg


def verify_gatekeeper(target: Path) -> None:
    """What a downloader's Mac will decide. Advisory: prints, never fails."""

    result = subprocess.run(
        ["spctl", "-a", "-vv", "-t", "install" if target.suffix == ".dmg" else "exec", str(target)],
        capture_output=True,
        text=True,
    )
    print((result.stderr or result.stdout).strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--release",
        action="store_true",
        help="Developer ID sign, notarize, staple, and build a .dmg",
    )
    args = parser.parse_args()

    bake_version()
    clean()
    app = build()
    patch_native_dylibs(app)

    if not args.release:
        sign_adhoc(app)
        print(f"\nBuilt: {app}")
        print(f"Run with: open '{app}'")
        return 0

    identity = signing_identity()
    if identity is None:
        raise SystemExit(
            "no 'Developer ID Application' certificate in the keychain.\n"
            "Create one at developer.apple.com > Certificates, download it, and\n"
            "double-click to install. An 'Apple Development' certificate cannot\n"
            "be notarized and will not work on anyone else's Mac."
        )
    sign_release(app, identity)
    notarize(app)
    dmg = make_dmg(app)
    subprocess.check_call(
        ["codesign", "--force", "--timestamp", "--sign", identity, str(dmg)]
    )
    notarize(dmg)

    print("\nGatekeeper verdict on what people will download:")
    verify_gatekeeper(dmg)
    print(f"\nBuilt: {dmg}")
    return 0


def patch_native_dylibs(app: Path) -> None:
    """py2app doesn't copy mlx's lib/ subfolder (libmlx.dylib, libjaccl.dylib,
    metallib). Locate them in the build-time site-packages and copy them next
    to mlx/core.so so its @loader_path/lib rpath resolves."""

    import sysconfig

    site_packages = Path(sysconfig.get_paths()["purelib"])
    src_lib = site_packages / "mlx" / "lib"
    if not src_lib.exists():
        print(f"warning: mlx/lib not found at {src_lib}; mlx will fail to load")
        return
    bundle_mlx = (
        app
        / "Contents"
        / "Resources"
        / "lib"
        / "python3.13"
        / "lib-dynload"
        / "mlx"
    )
    if not bundle_mlx.exists():
        print(f"warning: bundled mlx not found at {bundle_mlx}; skipping dylib copy")
        return
    dst_lib = bundle_mlx / "lib"
    if dst_lib.exists():
        shutil.rmtree(dst_lib)
    shutil.copytree(src_lib, dst_lib, symlinks=True)
    print(f"copied {src_lib} -> {dst_lib}")


if __name__ == "__main__":
    sys.exit(main())
