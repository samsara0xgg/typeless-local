# Vendored Jarvis core

Source: ../../../../jarvis @ 2a5bfbd on 2026-05-12.

These files are copied verbatim from the Jarvis project so the .app bundle
doesn't depend on a sibling jarvis/ checkout. To resync:

1. `cp -r ../../../jarvis/core/{speech_recognizer.py,media_ducking.py,...} typeless_local/_vendor/jarvis_core/`
2. Update import statements: `from core.X` -> `from typeless_local._vendor.jarvis_core.X`.
3. Update the date and commit hash at the top of this file.

Do not modify vendored files for typeless-local-specific behavior. If you
need typeless-local-specific changes to the ASR or ducker, wrap them in
typeless_local/ files instead so resyncs are clean.
