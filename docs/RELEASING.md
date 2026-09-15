# Releasing Typlus

How to ship a build other people can download and open. Everything here was
learned the expensive way on 2026-09-14; follow it and a release is two
commands.

## One-time setup

Done once per machine. If `security find-identity -v -p codesigning` lists a
`Developer ID Application` identity and `xcrun notarytool history
--keychain-profile "Typlus"` works, skip this whole section.

### 1. Developer ID Application certificate

Required to distribute outside the App Store. An **Apple Development**
certificate is not a substitute: it signs fine locally, cannot be notarized,
and produces a build that fails on every Mac but the one that built it.

1. Keychain Access → Certificate Assistant → **Request a Certificate From a
   Certificate Authority**. Enter the Apple ID email, choose **Saved to disk**,
   and keep the `.certSigningRequest` file.
2. developer.apple.com → Certificates, Identifiers & Profiles → Certificates →
   **+** → under **Software**, **Developer ID Application** (it is further down
   the list than the development certificates). Upload the CSR.
3. Download the `.cer` and double-click it, or
   `security import <file> -k ~/Library/Keychains/login.keychain-db`.

Only the team's Account Holder can create one. If the option is missing from
the list, the paid membership is not active.

### 2. Notary credentials

```sh
xcrun notarytool store-credentials "Typlus" \
  --apple-id <apple-id> --team-id <team-id>
```

It asks for an **app-specific password** from appleid.apple.com, not the Apple
ID password. Type it at the prompt; never paste it into a file or a chat.

The **Team ID is not the string in the parentheses of the certificate name** —
that is the developer's personal ID. It is the certificate's OU field:

```sh
security find-certificate -c "Developer ID Application" -p \
  | openssl x509 -noout -subject -nameopt multiline \
  | grep organizationalUnitName
```

Getting this wrong returns `HTTP status code: 403. Invalid or inaccessible
developer team ID`.

### 3. Build virtualenv

py2app needs a Python with `libpython.dylib`; the uv-standalone builds do not
ship one, so use Homebrew's. Put it somewhere persistent — a venv under `/tmp`
disappears on reboot.

```sh
PYBUILD=/opt/homebrew/bin/python3.13
$PYBUILD -m venv ~/.typlus-build-venv
~/.typlus-build-venv/bin/pip install \
  pyobjc-core pyobjc-framework-Cocoa pyobjc-framework-Quartz \
  pyobjc-framework-ApplicationServices pyobjc-framework-WebKit \
  numpy sounddevice openai pyyaml mlx-whisper py2app
```

## Releasing

1. Bump `VERSION` in `scripts/build_app.py` and `CFBundleShortVersionString` /
   `CFBundleVersion` in `setup.py`.
2. Build, sign, notarize, staple, and package:

   ```sh
   ~/.typlus-build-venv/bin/python scripts/build_app.py --release
   ```

   Roughly 25 minutes, unattended. It stops before uploading anything if the
   bundle is not shippable.

3. Publish:

   ```sh
   gh release create v0.3.0 --title "Typlus 0.3.0" \
     --notes-file notes.md dist/Typlus-0.3.0.dmg
   ```

The first `codesign` call of the session raises a keychain prompt asking for the
**login keychain password** (the Mac login password). Choose **Always Allow**,
or it asks again for each of the ~250 binaries.

## What `--release` does, and why

| Step | Why it exists |
| --- | --- |
| `unzip_native_packages` | py2app puts some packages inside `Resources/python313.zip`. Binaries in there are not files on disk, so `codesign` never sees them and notarization rejects them as unsigned. Whole packages are moved out, because Python resolves a package from one `sys.path` entry and a split package looks for its libraries where they no longer are. |
| `patch_native_dylibs` | py2app omits `mlx/lib`. `mlx/core.so` finds its libraries through `@loader_path/lib`, so they must sit next to `core.so` — which py2app places in `lib-dynload`, not beside the Python half of the package. |
| `prune_bundle` | Notarization opens every archive it finds. scipy's `.npz` test fixtures and CPython's sparse zip64 test parts cannot be opened, and it reports that as an error. |
| `smoke_test` | Runs the bundle's own interpreter under its own `PYTHONHOME` and makes mlx *compute*, not merely import. modulegraph finds imports by reading source, so anything a C extension imports during initialisation is silently left out and would only fail when a user presses the key. |
| `sign_release` | Signs nested binaries before the bundle containing them. `--deep` walks py2app's tree in the wrong order and Apple deprecated it. Hardened runtime plus `assets/entitlements.plist`, which grants what CPython and mlx need: JIT, unsigned executable memory, and library validation off. |
| `audit_signatures` | Walks every Mach-O in the bundle, *including inside the zip*, and refuses to upload unless each carries a Developer ID signature. Notarization answers in twenty minutes, one file at a time; this answers immediately for the whole class. |

## Traps that cost a full notarization round trip

- **Binaries inside `python313.zip`.** Adding them to py2app's `packages` does
  not work for `mlx`: it is a namespace package, and py2app's
  `collect_packagedirs` still calls `imp.find_module`, which cannot find one
  (`ImportError: No module named 'mlx'` at build time).
- **The execute bit is not part of being Mach-O.**
  `Python.framework/Versions/3.13/Python` is mode 644. Filtering on `os.X_OK`
  skips it, and that one file fails the entire submission.
- **New mlx imports `mlx.__array_api_info` from C** during initialisation.
  modulegraph cannot see it, so it must be listed in `setup.py` `includes`.
  Rebuilding against a newer mlx can add more; the smoke test is what catches
  them.
- **`Contents/MacOS/python` is not the app's environment.** Run it plain and
  `sys.path` points at Homebrew's Python, so imports "fail" for reasons that
  have nothing to do with the bundle. Always set
  `PYTHONHOME=<app>/Contents/Resources`.

## Verifying a release

Checking the `.dmg` is not enough — Gatekeeper judges the `.app`, and the disk
image can pass while the app inside does not.

```sh
hdiutil attach dist/Typlus-0.2.0.dmg
codesign --verify --deep --strict --verbose=2 /Volumes/Typlus/Typlus.app
spctl -a -vv /Volumes/Typlus/Typlus.app          # want: accepted, Notarized Developer ID
xcrun stapler validate /Volumes/Typlus/Typlus.app # want: the ticket, so it works offline
hdiutil detach /Volumes/Typlus
```

To reproduce what a downloader sees, stamp the quarantine attribute a browser
would add and ask again:

```sh
cp dist/Typlus-0.2.0.dmg /tmp/sim.dmg
xattr -w com.apple.quarantine "0083;00000000;Safari;|com.apple.Safari" /tmp/sim.dmg
spctl -a -vv -t open --context context:primary-signature /tmp/sim.dmg
```

**"Typlus.app is damaged and can't be opened" right after dragging it to
Applications is usually an incomplete copy, not a signing problem.** The bundle
is 1.3 GB; Finder shows the icon before the copy finishes. Verify with the
commands above before assuming the build is bad.

## Diagnosing a rejected notarization

`status: Invalid` comes with a submission id. The log names every file and why:

```sh
xcrun notarytool log <submission-id> --keychain-profile "Typlus"
```

## Facts worth keeping

- The app is arm64 only (the local ASR runtime is Apple Silicon only) and
  targets macOS 13+.
- Installed size ~1.3 GB, disk image ~573 MB. It carries its own Python runtime
  and ASR stack; the Whisper weights are *not* bundled and download on first
  launch.
- Everything the app writes lives in `~/.typlus/`.
- Changing `CFBundleIdentifier` makes macOS treat the build as a new app, so
  Microphone and Accessibility have to be granted again.
