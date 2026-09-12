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


def test_config_resolves_user_paths(monkeypatch, tmp_path):
    from typeless_local import config as cfg_mod
    monkeypatch.setenv("HOME", str(tmp_path))
    paths = cfg_mod.resolve_user_paths()
    assert paths.vocab_path == tmp_path / ".typeless-local" / "vocab.yaml"
    assert paths.trace_db_path == tmp_path / ".typeless-local" / "trace.db"
    assert paths.log_path == tmp_path / ".typeless-local" / "app.log"
    assert paths.stopwords_dir.name == "assets"


def test_resolve_user_paths_creates_directory(monkeypatch, tmp_path):
    from typeless_local import config as cfg_mod
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg_mod.resolve_user_paths()
    assert (tmp_path / ".typeless-local").is_dir()


def test_load_config_reads_own_config_not_jarvis(monkeypatch, tmp_path):
    from typeless_local import config as cfg_mod
    monkeypatch.setenv("HOME", str(tmp_path))
    jarvis_root = tmp_path / "jarvis"
    jarvis_root.mkdir()  # no config.yaml here: jarvis no longer ships one
    monkeypatch.setenv("JARVIS_PROJECT_ROOT", str(jarvis_root))

    bundled = cfg_mod.load_config()
    assert bundled.refine.model == "gpt-5.6-terra"  # from assets/config.yaml

    user_cfg = tmp_path / ".typeless-local" / "config.yaml"
    user_cfg.write_text("llm:\n  presets:\n    fast:\n      model: user-override\n")
    assert cfg_mod.load_config().refine.model == "user-override"


def test_refine_config_for_preset_and_names() -> None:
    from typeless_local.config import preset_names, refine_config_for
    cfg = {"llm": {"default_preset": "a", "presets": {
        "a": {"model": "gpt-5.4-mini", "max_tokens": 64},
        "b": {"model": "deepseek-flash", "base_url": "https://api.deepseek.com/v1",
              "api_key_env": "DEEPSEEK_API_KEY", "reasoning_effort": "none",
              "extra_body": {"thinking": {"type": "disabled"}}},
    }}}

    assert preset_names(cfg) == ["a", "b"]
    b = refine_config_for(cfg, "b")
    assert (b.preset, b.model, b.api_key_env) == ("b", "deepseek-flash", "DEEPSEEK_API_KEY")
    assert b.reasoning_effort == "none" and b.extra_body == {"thinking": {"type": "disabled"}}
    assert refine_config_for(cfg, "a").extra_body is None


def test_save_default_preset_seeds_user_config_and_load_config_reads_it(monkeypatch, tmp_path):
    from typeless_local import config as cfg_mod
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "jarvis").mkdir()
    monkeypatch.setenv("JARVIS_PROJECT_ROOT", str(tmp_path / "jarvis"))
    paths = cfg_mod.resolve_user_paths()
    assert not paths.user_config_path.exists()

    cfg_mod.save_default_preset(paths, "gpt-5.6-luna")

    loaded = cfg_mod.load_config()
    assert loaded.refine.preset == "gpt-5.6-luna"
    assert loaded.refine.model == "gpt-5.6-luna"
    assert "deepseek-flash" in cfg_mod.preset_names(loaded.jarvis_config)  # seeded from assets


def test_load_env_file_fills_missing_only(monkeypatch, tmp_path):
    from typeless_local.config import load_env_file
    env = tmp_path / "env"
    env.write_text("# comment\nTL_TEST_NEW=from-file\nTL_TEST_SET=from-file\n\nbroken line\n")
    monkeypatch.delenv("TL_TEST_NEW", raising=False)
    monkeypatch.setenv("TL_TEST_SET", "from-shell")

    load_env_file(env)

    import os
    assert os.environ["TL_TEST_NEW"] == "from-file"
    assert os.environ["TL_TEST_SET"] == "from-shell"
