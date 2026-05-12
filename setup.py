"""py2app build config for Typeless Local."""

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
    ],
    "excludes": [
        "tkinter",
        "PIL",
        "matplotlib",
        "pytest",
        "setuptools",
        "pip",
        "wheel",
    ],
    "plist": {
        "CFBundleName": "Typeless Local",
        "CFBundleDisplayName": "Typeless Local",
        "CFBundleIdentifier": "com.alllllenshi.typeless-local",
        "CFBundleShortVersionString": "0.2.0",
        "CFBundleVersion": "0.2.0",
        "LSUIElement": True,
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
        "NSMicrophoneUsageDescription":
            "Typeless Local records audio when you press F5 to dictate.",
        "NSAppleEventsUsageDescription":
            "Typeless Local pastes refined dictation into the focused app.",
    },
    "iconfile": str(ROOT / "assets" / "AppIcon.icns"),
}

setup(
    app=APP,
    name="Typeless Local",
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
