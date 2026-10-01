def test_can_import_speech_recognizer_from_vendor() -> None:
    from typeless_local._vendor.jarvis_core.speech_recognizer import SpeechRecognizer  # noqa: F401


def test_can_import_media_ducking_from_vendor() -> None:
    from typeless_local._vendor.jarvis_core.media_ducking import SystemAudioDucker  # noqa: F401


def test_an_output_without_volume_control_is_left_alone_and_said_once(caplog) -> None:
    from typeless_local._vendor.jarvis_core.media_ducking import SystemAudioDucker

    scripts = []

    def runner(script: str) -> str:
        scripts.append(script)
        return "missing value,missing value"

    ducker = SystemAudioDucker(platform="darwin", runner=runner)
    with caplog.at_level("INFO"):
        assert ducker.duck() is False
        assert ducker.duck() is False
    assert ducker.unsupported is True
    assert len(scripts) == 2, "only the reads ran: nothing was muted"
    assert not [r for r in caplog.records if r.levelname == "WARNING"]
    assert sum("no volume control" in r.getMessage() for r in caplog.records) == 1
