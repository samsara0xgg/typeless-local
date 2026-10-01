from __future__ import annotations

import sys
from types import SimpleNamespace

from typeless_local import reach


def test_machine_tells_apple_silicon_rosetta_and_intel_apart(monkeypatch) -> None:
    monkeypatch.setattr(reach.platform, "machine", lambda: "arm64")
    assert reach.machine() == "apple"

    monkeypatch.setattr(reach.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(reach, "_sysctl_int", lambda name: 1 if name == "sysctl.proc_translated" else None)
    assert reach.machine() == "rosetta"

    monkeypatch.setattr(reach, "_sysctl_int", lambda name: None)  # the key does not exist on Intel
    assert reach.machine() == "intel"


def _foundation(monkeypatch, country, zone) -> None:
    locale = SimpleNamespace(countryCode=lambda: country)
    monkeypatch.setitem(sys.modules, "Foundation", SimpleNamespace(
        NSLocale=SimpleNamespace(currentLocale=lambda: locale),
        NSTimeZone=SimpleNamespace(localTimeZone=lambda: SimpleNamespace(name=lambda: zone)),
    ))


def test_mainland_china_by_region_or_by_clock(monkeypatch) -> None:
    _foundation(monkeypatch, "CN", "America/Los_Angeles")
    assert reach.in_mainland_china() is True
    _foundation(monkeypatch, "US", "Asia/Shanghai")
    assert reach.in_mainland_china() is True
    _foundation(monkeypatch, "HK", "Asia/Hong_Kong")
    assert reach.in_mainland_china() is False
    _foundation(monkeypatch, None, None)
    assert reach.in_mainland_china() is False


def test_model_endpoint_follows_the_setting_and_the_region(monkeypatch) -> None:
    monkeypatch.setattr(reach, "_USER_ENDPOINT", "")
    monkeypatch.setattr(reach, "in_mainland_china", lambda: True)
    assert reach.model_endpoint("auto") == reach.MIRROR
    assert reach.model_endpoint("huggingface") == reach.HUGGING_FACE

    monkeypatch.setattr(reach, "in_mainland_china", lambda: False)
    assert reach.model_endpoint("auto") == reach.HUGGING_FACE
    assert reach.model_endpoint("mirror") == reach.MIRROR


def test_an_endpoint_the_user_set_themselves_wins(monkeypatch) -> None:
    monkeypatch.setattr(reach, "_USER_ENDPOINT", "https://hub.example.com")
    assert reach.model_endpoint("mirror") == "https://hub.example.com"


def test_use_model_source_repoints_an_already_imported_hub(monkeypatch) -> None:
    monkeypatch.setattr(reach, "_USER_ENDPOINT", "")
    monkeypatch.setenv("HF_ENDPOINT", reach.HUGGING_FACE)  # restored after the test
    constants = SimpleNamespace(
        ENDPOINT=reach.HUGGING_FACE,
        HUGGINGFACE_CO_URL_TEMPLATE=reach.HUGGING_FACE + "/{repo_id}/resolve/{revision}/{filename}",
    )
    monkeypatch.setitem(sys.modules, "huggingface_hub.constants", constants)

    assert reach.use_model_source("mirror") == reach.MIRROR

    assert reach.os.environ["HF_ENDPOINT"] == reach.MIRROR
    assert constants.ENDPOINT == reach.MIRROR
    assert constants.HUGGINGFACE_CO_URL_TEMPLATE.startswith(reach.MIRROR + "/{repo_id}")


def test_the_trial_region_is_the_us_and_canada(monkeypatch) -> None:
    _foundation(monkeypatch, "US", "Asia/Tokyo")
    assert reach.in_trial_region() is True
    _foundation(monkeypatch, "CA", "America/Toronto")
    assert reach.in_trial_region() is True
    _foundation(monkeypatch, "MX", "America/Mexico_City")
    assert reach.in_trial_region() is False
    _foundation(monkeypatch, "GB", "America/New_York")
    assert reach.in_trial_region() is False
    _foundation(monkeypatch, None, "America/Indiana/Indianapolis")
    assert reach.in_trial_region() is True
    _foundation(monkeypatch, None, "America/Sao_Paulo")
    assert reach.in_trial_region() is False
