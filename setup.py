"""py2app build config for Typlus."""

import sys
from pathlib import Path

# py2app's modulegraph walks ASTs deeply through numpy / mlx / pyobjc;
# default 1000 trips on some transitive imports.
sys.setrecursionlimit(10000)

from setuptools import setup

ROOT = Path(__file__).resolve().parent
APP = [str(ROOT / "typeless_local" / "__main__.py")]
DATA_FILES = [
    (
        "Resources",
        [
            str(ROOT / "assets" / "AppIcon.icns"),
            str(ROOT / "assets" / "config.yaml"),
            str(ROOT / "assets" / "stopwords-en.txt"),
            str(ROOT / "assets" / "stopwords-zh.txt"),
        ],
    ),
]

OPTIONS = {
    "argv_emulation": False,
    "packages": [
        "typeless_local",
        "numpy",
        "sounddevice",
        "objc",
        "openai",
        "yaml",
        "mlx_whisper",
        # mlx, llvmlite and _sounddevice_data also carry dylibs, but they
        # cannot be listed here: mlx is a namespace package and py2app's
        # collect_packagedirs still uses imp.find_module, which cannot find
        # one. build_app.py moves them out of the bundle zip after the build.
    ],
    "includes": [
        "ctypes",
        "sqlite3",
        "json",
        "re",
        "logging.handlers",
        "AppKit",
        "Quartz",
        "ApplicationServices",
        "PyObjCTools",
        "PyObjCTools.AppHelper",
        "Foundation",
        # mlx loads these via its internal __load mechanism; modulegraph misses
        # them by static analysis. Listing them explicitly so they end up in
        # the bundle zip alongside the wrapper-only mlx/__init__.pyc.
        "mlx._reprlib_fix",
        "mlx.utils",
        # core.so imports this from C during its own initialisation; without it
        # the extension raises "error while initializing the extension".
        "mlx.__array_api_info",
        "mlx.optimizers",
    ],
    "excludes": [
        # CPython's own test suite, which ships extension modules of its own.
        "test",
        "tkinter",
        "PIL",
        "matplotlib",
        "pytest",
        "setuptools",
        "pip",
        "wheel",
    ],
    "plist": {
        "CFBundleName": "Typlus",
        "CFBundleDisplayName": "Typlus",
        "CFBundleIdentifier": "com.alllllenshi.typlus",
        "CFBundleShortVersionString": "0.2.0",
        "CFBundleVersion": "0.2.0",
        "LSUIElement": True,
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
        "NSMicrophoneUsageDescription":
            "Typlus records audio when you press F5 to dictate.",
        "NSAppleEventsUsageDescription":
            "Typlus pastes refined dictation into the focused app.",
    },
    "iconfile": str(ROOT / "assets" / "AppIcon.icns"),
}

setup(
    app=APP,
    name="Typlus",
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
