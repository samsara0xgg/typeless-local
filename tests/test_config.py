from __future__ import annotations

from pathlib import Path

from typeless_local.config import _absolutize_jarvis_paths, _resolve_refine_config, resolve_jarvis_root


def test_resolve_refine_config_uses_jarvis_fast_preset() -> None:
    cfg = {
        "llm": {
            "default_preset": "fast",
            "presets": {
                "fast": {
                    "model": "gpt-5.4-mini",
                    "base_url": "https://api.openai.com/v1",
                    "api_key_env": "OPENAI_API_KEY",
                    "max_tokens": 1024,
                }
            },
        }
    }

    refine = _resolve_refine_config(cfg)

    assert refine.model == "gpt-5.4-mini"
    assert refine.base_url == "https://api.openai.com/v1"
    assert refine.api_key_env == "OPENAI_API_KEY"
    assert refine.max_tokens == 1024


def test_absolutize_jarvis_paths_disables_jarvis_command_language_bias_by_default() -> None:
    cfg = {
        "asr": {
            "language": "zh",
            "mlx_whisper_initial_prompt": "以下是普通话的简体中文转录。",
            "sensevoice_model_dir": "data/sensevoice",
        },
        "audio": {"vad_model_path": "models/vad.onnx"},
    }

    resolved = _absolutize_jarvis_paths(cfg, Path("/repo/jarvis"))

    assert resolved["asr"]["language"] == ""
    assert resolved["asr"]["mlx_whisper_initial_prompt"] == ""
    assert resolved["asr"]["sensevoice_model_dir"] == "/repo/jarvis/data/sensevoice"
    assert resolved["audio"]["vad_model_path"] == "/repo/jarvis/models/vad.onnx"


def test_resolve_jarvis_root_prefers_explicit_environment(monkeypatch, tmp_path) -> None:
    jarvis_root = tmp_path / "jarvis"
    jarvis_root.mkdir()
    monkeypatch.setenv("JARVIS_PROJECT_ROOT", str(jarvis_root))

    assert resolve_jarvis_root(tmp_path / "typeless-local") == jarvis_root.resolve()
