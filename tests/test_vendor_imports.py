def test_can_import_speech_recognizer_from_vendor() -> None:
    from typeless_local._vendor.jarvis_core.speech_recognizer import SpeechRecognizer  # noqa: F401


def test_can_import_media_ducking_from_vendor() -> None:
    from typeless_local._vendor.jarvis_core.media_ducking import SystemAudioDucker  # noqa: F401
