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


def main() -> int:
    bake_version()
    clean()
    app = build()
    sign(app)
    print(f"\nBuilt: {app}")
    print("Move to /Applications/ or run with: open '" + str(app) + "'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
