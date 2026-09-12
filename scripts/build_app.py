#!/usr/bin/env python
"""Build the Typeless Local self-contained .app via py2app."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
VERSION_FILE = ROOT / "typeless_local" / "_version.py"
BUNDLE_ID = "com.alllllenshi.typeless-local"


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
        f'VERSION = "0.2.0+{h}"\n',
        encoding="utf-8",
    )
    print(f"baked version: 0.2.0+{h}")


def clean() -> None:
    for d in (BUILD, DIST):
        if d.exists():
            print(f"rm -rf {d}")
            shutil.rmtree(d)


def build() -> Path:
    subprocess.check_call([sys.executable, "setup.py", "py2app"], cwd=ROOT)
    app = DIST / "Typeless Local.app"
    if not app.exists():
        raise SystemExit(f"build did not produce {app}")
    return app


def sign(app: Path) -> None:
    subprocess.check_call(
        ["codesign", "--force", "--deep", "--sign", "-", str(app)]
    )


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


def main() -> int:
    bake_version()
    clean()
    app = build()
    patch_native_dylibs(app)
    sign(app)
    print(f"\nBuilt: {app}")
    print("Move to /Applications/ or run with: open '" + str(app) + "'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
