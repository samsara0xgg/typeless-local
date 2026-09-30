"""py2app build config for 言字 (Yana)."""

import sys
from pathlib import Path

# py2app's modulegraph walks ASTs deeply through numpy / mlx / pyobjc;
# default 1000 trips on some transitive imports.
sys.setrecursionlimit(10000)

from setuptools import setup

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from typeless_local import RELEASE, brand  # noqa: E402

APP = [str(ROOT / "typeless_local" / "__main__.py")]
WEB = ROOT / "typeless_local" / "web"
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
    # The capsule and the windows' pages; webview.web_root() finds them here
    # when the package directory does not carry them.
    ("web", sorted(str(path) for path in WEB.iterdir() if path.suffix in {".html", ".js", ".css", ".svg"})),
    # 言字 on a Chinese system, Yana everywhere else.
    ("zh-Hans.lproj", [str(ROOT / "assets" / "zh-Hans.lproj" / "InfoPlist.strings")]),
    ("en.lproj", [str(ROOT / "assets" / "en.lproj" / "InfoPlist.strings")]),
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
        "WebKit",
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
        "CFBundleName": brand.ENGLISH_NAME,
        "CFBundleDisplayName": brand.ENGLISH_NAME,
        # Kept from the Typlus days: macOS ties the granted permissions to it.
        "CFBundleIdentifier": brand.BUNDLE_ID,
        "CFBundleShortVersionString": RELEASE,
        "CFBundleVersion": RELEASE,
        "CFBundleDevelopmentRegion": "en",
        "CFBundleLocalizations": ["en", "zh-Hans"],
        "LSHasLocalizedDisplayName": True,
        "LSUIElement": True,
        # MLX has no Intel build: never start under Rosetta on Apple silicon.
        "LSRequiresNativeExecution": True,
        "LSArchitecturePriority": ["arm64"],
        "LSMinimumSystemVersion": "13.0",
        "NSHighResolutionCapable": True,
        "NSMicrophoneUsageDescription":
            f"{brand.ENGLISH_NAME} records audio while you dictate with F5.",
        "NSAppleEventsUsageDescription":
            f"{brand.ENGLISH_NAME} puts the finished text into the app you are typing in.",
    },
    "iconfile": str(ROOT / "assets" / "AppIcon.icns"),
}

setup(
    app=APP,
    name=brand.ENGLISH_NAME,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
