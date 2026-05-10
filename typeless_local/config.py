"""Configuration loading for the standalone Typeless-style app."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class RefineConfig:
    """OpenAI-compatible refinement model settings."""

    model: str
    base_url: str | None
    api_key_env: str
    max_tokens: int


@dataclass(frozen=True)
class AppConfig:
    """Resolved runtime configuration."""

    root: Path
    jarvis_root: Path
    jarvis_config: dict[str, Any]
    refine: RefineConfig
    sample_rate: int = 16000
    max_recording_seconds: float = 540.0
    min_recording_seconds: float = 0.25
    low_volume_threshold: float = 0.02
    debug_hotkey: bool = False


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


def load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file into a dictionary."""

    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected mapping in {path}")
    return loaded


def _resolve_refine_config(jarvis_config: dict[str, Any]) -> RefineConfig:
    llm = dict(jarvis_config.get("llm") or {})
    presets = dict(llm.get("presets") or {})
    preset_name = str(llm.get("default_preset") or "fast")
    preset = dict(presets.get(preset_name) or presets.get("fast") or {})

    model = str(preset.get("model") or llm.get("model") or "gpt-5.4-mini")
    base_url = preset.get("base_url") or llm.get("base_url") or "https://api.openai.com/v1"
    api_key_env = str(preset.get("api_key_env") or "OPENAI_API_KEY")
    max_tokens = int(preset.get("max_tokens") or llm.get("max_tokens") or 512)

    return RefineConfig(
        model=model,
        base_url=str(base_url) if base_url else None,
        api_key_env=api_key_env,
        max_tokens=max_tokens,
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


def load_config() -> AppConfig:
    """Load app config and the Jarvis config it depends on."""

    app_root = resolve_app_root()
    jarvis_root = resolve_jarvis_root(app_root)
    jarvis_config_path = jarvis_root / "config.yaml"
    jarvis_config = _absolutize_jarvis_paths(load_yaml(jarvis_config_path), jarvis_root)
    audio_config = dict(jarvis_config.get("audio") or {})
    return AppConfig(
        root=app_root,
        jarvis_root=jarvis_root,
        jarvis_config=jarvis_config,
        refine=_resolve_refine_config(jarvis_config),
        min_recording_seconds=float(audio_config.get("min_duration") or 0.25),
        low_volume_threshold=float(audio_config.get("low_volume_threshold") or 0.02),
        debug_hotkey=os.environ.get("TYPELESS_LOCAL_DEBUG_HOTKEY") == "1",
    )
