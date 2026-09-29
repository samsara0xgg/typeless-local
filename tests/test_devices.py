from __future__ import annotations

from types import SimpleNamespace

from typeless_local import devices


def _fake_portaudio(monkeypatch) -> list[str]:
    calls: list[str] = []
    fake = SimpleNamespace(
        _terminate=lambda: calls.append("terminate"),
        _initialize=lambda: calls.append("initialize"),
    )
    monkeypatch.setattr(devices, "_sounddevice", lambda: fake)
    monkeypatch.setattr(devices, "_last_signature", None)
    return calls


def test_refresh_is_skipped_while_coreaudio_reports_no_change(monkeypatch) -> None:
    calls = _fake_portaudio(monkeypatch)
    signature = [((10, 11), (10,), (11,))]
    monkeypatch.setattr(devices, "hardware_signature", lambda: signature[0])

    assert devices.refresh_if_changed() is True
    assert devices.refresh_if_changed() is False
    signature[0] = ((10, 11, 12), (12,), (11,))  # a mic was plugged in
    assert devices.refresh_if_changed() is True

    assert calls == ["terminate", "initialize"] * 2


def test_refresh_happens_every_time_when_coreaudio_is_unreadable(monkeypatch) -> None:
    calls = _fake_portaudio(monkeypatch)
    monkeypatch.setattr(devices, "hardware_signature", lambda: None)

    assert devices.refresh_if_changed() is True
    assert devices.refresh_if_changed() is True

    assert calls == ["terminate", "initialize"] * 2


def test_hardware_signature_is_none_without_coreaudio(monkeypatch) -> None:
    monkeypatch.setattr(devices, "_load_coreaudio", lambda: None)

    assert devices.hardware_signature() is None
