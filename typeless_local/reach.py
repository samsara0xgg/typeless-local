"""What this Mac can run and which services it can reach.

The speech model runs on MLX, which needs Apple silicon, and downloads from
Hugging Face; refinement starts on OpenAI. Neither Hugging Face nor OpenAI
answers from mainland China, so there the model comes from a mirror and a new
install starts on DeepSeek.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import os
import platform
import sys

LOGGER = logging.getLogger(__name__)

HUGGING_FACE = "https://huggingface.co"
MIRROR = "https://hf-mirror.com"
# What Settings offers for the model download; "auto" means the mirror in mainland China.
MODEL_SOURCES = ("auto", "huggingface", "mirror")
# Where a new install in mainland China starts: OpenAI does not serve it.
CHINA_PRESET = "deepseek-flash"
_CHINA_TIME_ZONES = frozenset({"Asia/Shanghai", "Asia/Urumqi", "Asia/Chongqing", "Asia/Harbin", "Asia/Kashgar", "PRC"})
# An HF_ENDPOINT set before launch is the user's own choice and always wins.
_USER_ENDPOINT = os.environ.get("HF_ENDPOINT", "").strip().rstrip("/")


def machine() -> str:
    """"apple" on Apple silicon, "rosetta" when translated on one, "intel" otherwise."""

    if platform.machine() == "arm64":
        return "apple"
    return "rosetta" if _sysctl_int("sysctl.proc_translated") == 1 else "intel"


def _sysctl_int(name: str) -> int | None:
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c"))
        value = ctypes.c_int(0)
        size = ctypes.c_size_t(ctypes.sizeof(value))
        if libc.sysctlbyname(name.encode(), ctypes.byref(value), ctypes.byref(size), None, ctypes.c_size_t(0)):
            return None
        return value.value
    except Exception:
        return None


def in_mainland_china() -> bool:
    """The Mac's region is China, or its clock is on China time."""

    try:
        from Foundation import NSLocale, NSTimeZone  # noqa: PLC0415

        country = NSLocale.currentLocale().countryCode()
        zone = NSTimeZone.localTimeZone().name()
    except Exception:
        return False
    return (isinstance(country, str) and country == "CN") or (isinstance(zone, str) and zone in _CHINA_TIME_ZONES)


# US and Canadian clocks, for a Mac whose region cannot be read.
_TRIAL_TIME_ZONE_PREFIXES = ("America/Indiana/", "America/Kentucky/", "America/North_Dakota/")
_TRIAL_TIME_ZONES = frozenset({
    "America/New_York", "America/Chicago", "America/Denver", "America/Los_Angeles", "America/Phoenix",
    "America/Anchorage", "America/Juneau", "America/Detroit", "America/Boise", "America/Adak", "Pacific/Honolulu",
    "America/Toronto", "America/Vancouver", "America/Edmonton", "America/Winnipeg", "America/Halifax",
    "America/St_Johns", "America/Regina", "America/Moncton", "America/Whitehorse", "America/Yellowknife",
})


def in_trial_region() -> bool:
    """Where the free trial runs: a US or Canadian Mac. The worker has the final say."""

    try:
        from Foundation import NSLocale, NSTimeZone  # noqa: PLC0415

        country = NSLocale.currentLocale().countryCode()
        zone = NSTimeZone.localTimeZone().name()
    except Exception:
        return False
    if isinstance(country, str) and country:
        return country in ("US", "CA")
    zone = zone if isinstance(zone, str) else ""
    return zone in _TRIAL_TIME_ZONES or zone.startswith(_TRIAL_TIME_ZONE_PREFIXES)


def model_endpoint(source: str) -> str:
    """Where the speech model downloads from for the ``model_source`` preference."""

    if _USER_ENDPOINT:
        return _USER_ENDPOINT
    if source == "mirror" or (source == "auto" and in_mainland_china()):
        return MIRROR
    return HUGGING_FACE


def use_model_source(source: str) -> str:
    """Point huggingface_hub at the endpoint for ``source``, before or after it is imported."""

    endpoint = model_endpoint(source)
    os.environ["HF_ENDPOINT"] = endpoint
    # huggingface_hub reads HF_ENDPOINT once, at import; mlx_whisper may have
    # imported it already.
    constants = sys.modules.get("huggingface_hub.constants")
    if constants is not None and getattr(constants, "ENDPOINT", endpoint) != endpoint:
        constants.ENDPOINT = endpoint
        constants.HUGGINGFACE_CO_URL_TEMPLATE = endpoint + "/{repo_id}/resolve/{revision}/{filename}"
    LOGGER.info("The speech model downloads from %s", endpoint)
    return endpoint
