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
# 64-bit Mach-O, plus the fat/universal wrapper around it.
MACHO_MAGIC = {
    b"\xcf\xfa\xed\xfe",
    b"\xfe\xed\xfa\xcf",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
}
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
        and (path.suffix in {".so", ".dylib"} or _is_macho(path))
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


def _is_macho(path: Path) -> bool:
    """Mach-O by magic number. The execute bit is deliberately not consulted:
    Python.framework/Versions/3.13/Python is mode 644 and still has to be
    signed, and skipping it alone is enough to fail notarization."""

    try:
        with path.open("rb") as handle:
            return handle.read(4) in MACHO_MAGIC
    except OSError:
        return False


def audit_signatures(app: Path) -> None:
    """Refuse to upload if any Mach-O in the bundle is not Developer ID signed.

    Notarization reports this one file at a time, twenty minutes per round
    trip, so the whole class is enumerated here instead of guessed at. Binaries
    inside py2app's bundle zip are included: they are not files on disk, so
    codesign silently never saw them, which is exactly how the first
    submission failed.
    """

    import zipfile

    bad: list[str] = []
    for path in sorted((app / "Contents").rglob("*")):
        if not path.is_file() or path.is_symlink() or not _is_macho(path):
            continue
        proc = subprocess.run(
            ["codesign", "-dv", "--verbose=2", str(path)],
            capture_output=True,
            text=True,
        )
        if "Authority=Developer ID Application" not in proc.stderr:
            bad.append(f"{path.relative_to(app)} (unsigned or ad-hoc)")

    for archive in sorted((app / "Contents").rglob("*.zip")):
        try:
            with zipfile.ZipFile(archive) as zf:
                for name in zf.namelist():
                    with zf.open(name) as handle:
                        if handle.read(4) in MACHO_MAGIC:
                            bad.append(f"{archive.relative_to(app)} -> {name} (inside a zip)")
        except zipfile.BadZipFile:
            continue

    if bad:
        raise SystemExit(
            "signature audit failed; notarization would reject these:\n  "
            + "\n  ".join(bad)
        )
    print("signature audit: every Mach-O in the bundle is Developer ID signed")

    # The other half of what notarization rejects is archives it cannot open:
    # scipy .npz fixtures and CPython's sparse zip64 test parts both came back
    # as errors. Only a warning, because plenty of data files are legitimate.
    suspect = [
        str(path.relative_to(app))
        for path in sorted((app / "Contents").rglob("*"))
        if path.is_file() and path.suffix in {".npz", ".part"}
    ]
    if suspect:
        print("warning: notarization will try to unpack these and may object:")
        for name in suspect:
            print(f"  {name}")


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
    unzip_native_packages(app)
    patch_native_dylibs(app)
    prune_bundle(app)
    smoke_test(app)

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
    audit_signatures(app)
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


def unzip_native_packages(app: Path) -> None:
    """Move packages carrying dylibs out of py2app's bundle zip onto disk.

    codesign only ever sees files, so a .dylib sitting inside python313.zip is
    never signed and notarization rejects the whole submission. Listing these
    in py2app's `packages` is not an option: mlx is a namespace package, and
    py2app's collect_packagedirs still goes through imp.find_module, which
    cannot find one.

    Whole packages are moved rather than just their binaries. Python resolves a
    package from a single sys.path entry, so leaving the code in the zip while
    the libraries sat on disk would have the code look for them at a path that
    no longer holds them.
    """

    import zipfile

    zip_path = app / "Contents" / "Resources" / "lib" / "python313.zip"
    lib_dir = app / "Contents" / "Resources" / "lib" / "python3.13"
    if not zip_path.exists():
        print(f"warning: {zip_path} not found; nothing to move out")
        return

    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        roots = sorted(
            {
                name.split("/", 1)[0]
                for name in names
                if "/" in name
                and not name.endswith("/")
                and _zip_entry_is_macho(archive, name)
            }
        )
        if not roots:
            print("no native packages left in the bundle zip")
            return
        moving = [n for n in names if n.split("/", 1)[0] in roots]
        keeping = [n for n in names if n.split("/", 1)[0] not in roots]
        archive.extractall(lib_dir, members=moving)
        rebuilt = zip_path.with_suffix(".zip.new")
        with zipfile.ZipFile(rebuilt, "w", zipfile.ZIP_DEFLATED) as out:
            for name in keeping:
                out.writestr(archive.getinfo(name), archive.read(name))
    rebuilt.replace(zip_path)
    print(f"moved out of the bundle zip: {', '.join(roots)}")


def _zip_entry_is_macho(archive, name: str) -> bool:
    try:
        with archive.open(name) as handle:
            return handle.read(4) in MACHO_MAGIC
    except (KeyError, OSError):
        return False


def smoke_test(app: Path) -> None:
    """Run what the app cannot start without, through the bundle's own Python.

    py2app's modulegraph finds imports by reading source, so anything a C
    extension imports during its own initialisation is silently left out and
    only fails once a user presses the key. mlx is asked to compute, not just
    to import, because loading the module succeeds well before its Metal
    library does.
    """

    python = app / "Contents" / "MacOS" / "python"
    env = {**os.environ, "PYTHONHOME": str(app / "Contents" / "Resources")}
    code = (
        "import mlx.core as mx, mlx_whisper, sounddevice, llvmlite.binding\n"
        "assert (mx.array([1.0, 2.0]) * 2).tolist() == [2.0, 4.0]\n"
    )
    result = subprocess.run(
        [str(python), "-c", code], env=env, capture_output=True, text=True
    )
    if result.returncode != 0:
        raise SystemExit("bundle smoke test failed:\n" + result.stderr.strip())
    print("smoke test: mlx computes, and mlx_whisper/sounddevice/llvmlite import")


def prune_bundle(app: Path) -> None:
    """Drop test payloads that nothing imports and notarization chokes on.

    Apple opens every archive it finds in the bundle. scipy ships .npz test
    fixtures its unpacker cannot read, and the submission comes back Invalid
    over a file the app never touches.
    """

    lib = app / "Contents" / "Resources" / "lib" / "python3.13"
    removed = 0
    for tests_dir in sorted(lib.glob("scipy/**/tests")):
        if tests_dir.is_dir():
            shutil.rmtree(tests_dir)
            removed += 1
    print(f"pruned {removed} scipy test directories")


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
    # core.so resolves its libraries through @rpath -> @loader_path/lib, so
    # lib/ has to sit next to core.so itself. py2app puts extension modules in
    # lib-dynload while the Python half of the package lives elsewhere, so the
    # directory is found from core.so rather than assumed.
    lib_root = app / "Contents" / "Resources" / "lib" / "python3.13"
    core = next(iter(sorted(lib_root.rglob("mlx/core*.so"))), None)
    if core is None:
        print(f"warning: mlx/core.so not found under {lib_root}; mlx will fail to load")
        return
    bundle_mlx = core.parent
    dst_lib = bundle_mlx / "lib"
    if dst_lib.exists():
        shutil.rmtree(dst_lib)
    shutil.copytree(src_lib, dst_lib, symlinks=True)
    print(f"copied {src_lib} -> {dst_lib}")


if __name__ == "__main__":
    sys.exit(main())
