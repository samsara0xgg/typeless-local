"""Configuration loading for the standalone Typeless-style app."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
from typing import Any

import yaml

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class RefineConfig:
    """OpenAI-compatible refinement model settings."""

    model: str
    base_url: str | None
    api_key_env: str
    max_tokens: int
    preset: str = ""
    reasoning_effort: str | None = None
    extra_body: dict[str, Any] | None = None


@dataclass(frozen=True)
class UserPaths:
    """Filesystem paths Typlus writes to at runtime."""

    config_dir: Path
    vocab_path: Path
    corrections_path: Path
    trace_db_path: Path
    log_path: Path
    stopwords_dir: Path
    user_config_path: Path
    env_path: Path


@dataclass(frozen=True)
class AppConfig:
    """Resolved runtime configuration."""

    root: Path
    jarvis_root: Path
    jarvis_config: dict[str, Any]
    refine: RefineConfig
    sample_rate: int = 16000
    max_recording_seconds: float = 540.0
    min_recording_seconds: float = 0.15
    low_volume_threshold: float = 0.02
    debug_hotkey: bool = False
    user_paths: UserPaths | None = None
    input_device: str = ""
    aec_pairs: tuple[dict[str, str], ...] = ()


def resolve_app_root() -> Path:
    """Return the project root for this standalone app."""

    return Path(__file__).resolve().parents[1]


def resolve_jarvis_root(app_root: Path | None = None) -> Path:
    """Resolve the Jarvis checkout used only as a dependency source."""

    explicit = os.environ.get("JARVIS_PROJECT_ROOT", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()

    root = app_root or resolve_app_root()
    sibling = (root.parent / "jarvis").resolve()
    if sibling.exists():
        return sibling

    home_projects = Path.home() / "Projects" / "jarvis"
    if home_projects.exists():
        return home_projects.resolve()

    raise FileNotFoundError(
        "Jarvis root not found. Set JARVIS_PROJECT_ROOT to reuse the ASR pipeline."
    )


def migrate_legacy_config_dir() -> Path:
    """Carry an install from before the Typlus rename over, and return the dir.

    Everything the user owns lives in there -- the API key, the vocabulary, the
    hand corrections, and the whole dictation history -- so a rename that left
    it behind would read as data loss, not as a new name.

    Callable from anywhere and safe to repeat: whoever touches the config
    directory first must call this before creating it, or the move is skipped
    for a directory that only exists because a log file was opened.
    """

    home = Path(os.environ.get("HOME") or Path.home()).expanduser()
    config_dir = home / ".typlus"
    legacy = home / ".typeless-local"
    if config_dir.exists() or not legacy.is_dir():
        return config_dir
    try:
        legacy.rename(config_dir)
        LOGGER.info("Moved %s to %s after the rename", legacy, config_dir)
    except OSError:
        LOGGER.exception("Could not move %s to %s; starting empty", legacy, config_dir)
    return config_dir


def resolve_user_paths(app_root: Path | None = None) -> UserPaths:
    """Return all on-disk paths Typlus touches outside its install."""

    home = Path(os.environ.get("HOME") or Path.home()).expanduser()
    config_dir = migrate_legacy_config_dir()
    config_dir.mkdir(parents=True, exist_ok=True)
    root = app_root or resolve_app_root()

    # assets dir: py2app puts DATA_FILES at .app/Contents/Resources/Resources/
    # (root is .app/Contents/Resources/lib/python3.13); dev mode uses repo assets/
    bundled = root.parents[1] / "Resources"
    stopwords_dir = bundled if (bundled / "stopwords-en.txt").exists() else (root / "assets")

    return UserPaths(
        config_dir=config_dir,
        vocab_path=config_dir / "vocab.yaml",
        corrections_path=config_dir / "corrections.yaml",
        trace_db_path=config_dir / "trace.db",
        log_path=config_dir / "app.log",
        stopwords_dir=stopwords_dir,
        user_config_path=config_dir / "config.yaml",
        env_path=config_dir / "env",
    )


def load_env_file(path: Path) -> None:
    """Fill os.environ from KEY=value lines; variables already set win."""

    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file into a dictionary."""

    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected mapping in {path}")
    return loaded


def preset_names(jarvis_config: dict[str, Any]) -> list[str]:
    """Return the refinement preset names in config order."""

    return list(dict((jarvis_config.get("llm") or {}).get("presets") or {}))


def refine_config_for(jarvis_config: dict[str, Any], preset_name: str) -> RefineConfig:
    """Resolve the named preset (menu switching); falls back like the default."""

    return _resolve_refine_config(jarvis_config, preset_name)


def _update_user_config(user_paths: UserPaths, section: str, key: str, value: Any) -> None:
    """Set one key in the user config, seeding the file from the bundled one."""

    path = user_paths.user_config_path
    source = path if path.exists() else user_paths.stopwords_dir / "config.yaml"
    data = load_yaml(source)
    data.setdefault(section, {})[key] = value
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def save_default_preset(user_paths: UserPaths, preset_name: str) -> None:
    """Persist the chosen preset, seeding the user config from the bundled one."""

    _update_user_config(user_paths, "llm", "default_preset", preset_name)


def save_input_device(user_paths: UserPaths, device_name: str) -> None:
    """Persist the chosen capture device; "" means follow the system default."""

    _update_user_config(user_paths, "audio", "input_device", device_name)


def _resolve_refine_config(jarvis_config: dict[str, Any], preset_name: str | None = None) -> RefineConfig:
    llm = dict(jarvis_config.get("llm") or {})
    presets = dict(llm.get("presets") or {})
    preset_name = str(preset_name or llm.get("default_preset") or "fast")
    if preset_name not in presets and "fast" in presets:
        preset_name = "fast"
    preset = dict(presets.get(preset_name) or {})

    model = str(preset.get("model") or llm.get("model") or "gpt-5.4-mini")
    base_url = preset.get("base_url") or llm.get("base_url") or "https://api.openai.com/v1"
    api_key_env = str(preset.get("api_key_env") or "OPENAI_API_KEY")
    max_tokens = int(preset.get("max_tokens") or llm.get("max_tokens") or 512)

    reasoning_effort = preset.get("reasoning_effort")
    extra_body = preset.get("extra_body")
    return RefineConfig(
        model=model,
        base_url=str(base_url) if base_url else None,
        api_key_env=api_key_env,
        max_tokens=max_tokens,
        preset=preset_name,
        reasoning_effort=str(reasoning_effort) if reasoning_effort else None,
        extra_body=dict(extra_body) if extra_body else None,
    )


def _absolutize_jarvis_paths(config: dict[str, Any], jarvis_root: Path) -> dict[str, Any]:
    """Return a config copy with Jarvis model paths rooted at `jarvis_root`."""

    copied = dict(config)
    asr = dict(copied.get("asr") or {})
    for key in ("sensevoice_model_dir",):
        value = asr.get(key)
        if value and not Path(str(value)).is_absolute():
            asr[key] = str((jarvis_root / str(value)).resolve())
    asr["language"] = os.environ.get("TYPELESS_LOCAL_ASR_LANGUAGE", "").strip()
    asr["mlx_whisper_initial_prompt"] = os.environ.get(
        "TYPELESS_LOCAL_MLX_INITIAL_PROMPT",
        "",
    ).strip()
    copied["asr"] = asr

    audio = dict(copied.get("audio") or {})
    value = audio.get("vad_model_path")
    if value and not Path(str(value)).is_absolute():
        audio["vad_model_path"] = str((jarvis_root / str(value)).resolve())
    copied["audio"] = audio
    return copied


def _read_aec_pairs(config: dict[str, Any]) -> tuple[dict[str, str], ...]:
    """Input/output pairings whose capture device cancels the speakers itself."""

    ducking = config.get("audio_ducking") or {}
    raw = ducking.get("aec_pairs") if isinstance(ducking, dict) else None
    pairs: list[dict[str, str]] = []
    for entry in raw or []:
        if not isinstance(entry, dict):
            continue
        source = str(entry.get("input") or "").strip()
        sink = str(entry.get("output") or "").strip()
        if source and sink:
            pairs.append({"input": source, "output": sink})
    return tuple(pairs)


def load_config() -> AppConfig:
    """Load ~/.typlus/config.yaml, else the config.yaml shipped in assets."""

    app_root = resolve_app_root()
    jarvis_root = resolve_jarvis_root(app_root)
    user_paths = resolve_user_paths(app_root)
    load_env_file(user_paths.env_path)  # API keys for Finder launches, fill-only
    config_path = user_paths.user_config_path
    if not config_path.exists():
        config_path = user_paths.stopwords_dir / "config.yaml"
    jarvis_config = _absolutize_jarvis_paths(load_yaml(config_path), jarvis_root)
    audio_config = dict(jarvis_config.get("audio") or {})
    return AppConfig(
        root=app_root,
        jarvis_root=jarvis_root,
        jarvis_config=jarvis_config,
        refine=_resolve_refine_config(jarvis_config),
        min_recording_seconds=float(audio_config.get("min_duration") or 0.15),
        low_volume_threshold=float(audio_config.get("low_volume_threshold") or 0.02),
        input_device=str(audio_config.get("input_device") or "").strip(),
        aec_pairs=_read_aec_pairs(jarvis_config),
        debug_hotkey=os.environ.get("TYPELESS_LOCAL_DEBUG_HOTKEY") == "1",
        user_paths=user_paths,
    )
