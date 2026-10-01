from __future__ import annotations

from pathlib import Path

import yaml

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


def test_absolutize_jarvis_paths_keeps_the_configured_language(monkeypatch) -> None:
    monkeypatch.delenv("TYPELESS_LOCAL_ASR_LANGUAGE", raising=False)
    cfg = {
        "asr": {
            "language": "zh",
            "mlx_whisper_initial_prompt": "以下是普通话的简体中文转录。",
            "sensevoice_model_dir": "data/sensevoice",
        },
        "audio": {"vad_model_path": "models/vad.onnx"},
    }

    resolved = _absolutize_jarvis_paths(cfg, Path("/repo/jarvis"))

    assert resolved["asr"]["language"] == "zh"
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
    assert paths.vocab_path == tmp_path / ".typlus" / "vocab.yaml"
    assert paths.trace_db_path == tmp_path / ".typlus" / "trace.db"
    assert paths.log_path == tmp_path / ".typlus" / "app.log"
    assert paths.stopwords_dir.name == "assets"


def test_resolve_user_paths_creates_directory(monkeypatch, tmp_path):
    from typeless_local import config as cfg_mod
    monkeypatch.setenv("HOME", str(tmp_path))
    cfg_mod.resolve_user_paths()
    assert (tmp_path / ".typlus").is_dir()


def test_rename_carries_the_old_config_directory_over(monkeypatch, tmp_path):
    """The rename must not read as a fresh install: keys, vocabulary and the
    whole trace history live in the directory being renamed."""

    from typeless_local import config as cfg_mod
    monkeypatch.setenv("HOME", str(tmp_path))
    legacy = tmp_path / ".typeless-local"
    legacy.mkdir()
    (legacy / "env").write_text("OPENAI_API_KEY=sk-kept\n", encoding="utf-8")
    (legacy / "trace.db").write_bytes(b"sqlite-bytes")

    paths = cfg_mod.resolve_user_paths()

    assert paths.config_dir == tmp_path / ".typlus"
    assert (tmp_path / ".typlus" / "env").read_text(encoding="utf-8") == "OPENAI_API_KEY=sk-kept\n"
    assert (tmp_path / ".typlus" / "trace.db").read_bytes() == b"sqlite-bytes"
    assert not legacy.exists()


def test_rename_leaves_an_existing_new_directory_alone(monkeypatch, tmp_path):
    """Someone who already runs Typlus must not have it overwritten by a stale
    pre-rename directory that happens to still be on disk."""

    from typeless_local import config as cfg_mod
    monkeypatch.setenv("HOME", str(tmp_path))
    legacy = tmp_path / ".typeless-local"
    legacy.mkdir()
    (legacy / "env").write_text("OPENAI_API_KEY=sk-stale\n", encoding="utf-8")
    current = tmp_path / ".typlus"
    current.mkdir()
    (current / "env").write_text("OPENAI_API_KEY=sk-current\n", encoding="utf-8")

    cfg_mod.resolve_user_paths()

    assert (current / "env").read_text(encoding="utf-8") == "OPENAI_API_KEY=sk-current\n"
    assert legacy.exists()


def test_load_config_reads_own_config_not_jarvis(monkeypatch, tmp_path):
    from typeless_local import config as cfg_mod
    monkeypatch.setenv("HOME", str(tmp_path))
    jarvis_root = tmp_path / "jarvis"
    jarvis_root.mkdir()  # no config.yaml here: jarvis no longer ships one
    monkeypatch.setenv("JARVIS_PROJECT_ROOT", str(jarvis_root))

    bundled = cfg_mod.load_config()
    assert bundled.refine.model == "gpt-5.6-terra"  # from assets/config.yaml

    user_cfg = tmp_path / ".typlus" / "config.yaml"
    user_cfg.write_text("llm:\n  default_preset: fast\n  presets:\n    fast:\n      model: user-override\n")
    loaded = cfg_mod.load_config()
    assert loaded.refine.model == "user-override"
    assert "deepseek-flash" in cfg_mod.preset_names(loaded.jarvis_config)  # bundled presets still there


def test_user_config_only_overrides_the_keys_it_names(monkeypatch, tmp_path):
    """A new default in the bundled file reaches users who never changed that key."""
    from typeless_local import config as cfg_mod
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "jarvis").mkdir()
    monkeypatch.setenv("JARVIS_PROJECT_ROOT", str(tmp_path / "jarvis"))
    paths = cfg_mod.resolve_user_paths()
    paths.user_config_path.write_text("audio:\n  input_channel: 2\nllm:\n  presets:\n    deepseek-flash:\n      max_tokens: 900\n")

    loaded = cfg_mod.load_config()

    assert loaded.input_channel == 2
    assert loaded.low_volume_threshold == 0.003  # still the bundled value
    assert loaded.refine.preset == "gpt-5.6-terra"
    flash = cfg_mod.refine_config_for(loaded.jarvis_config, "deepseek-flash")
    assert (flash.max_tokens, flash.base_url) == (900, "https://api.deepseek.com/v1")


def test_merge_config_keeps_defaults_under_an_empty_section() -> None:
    from typeless_local.config import merge_config
    base = {"audio": {"min_duration": 0.15, "keep_recordings": 0}, "llm": {"default_preset": "a"}}

    merged = merge_config(base, {"audio": None, "llm": {"default_preset": "b"}, "ui": {"sounds": "off"}})

    assert merged == {"audio": {"min_duration": 0.15, "keep_recordings": 0}, "llm": {"default_preset": "b"}, "ui": {"sounds": "off"}}
    assert base["llm"]["default_preset"] == "a"


def test_unreadable_user_config_falls_back_and_is_kept_aside(monkeypatch, tmp_path):
    from typeless_local import config as cfg_mod
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "jarvis").mkdir()
    monkeypatch.setenv("JARVIS_PROJECT_ROOT", str(tmp_path / "jarvis"))
    paths = cfg_mod.resolve_user_paths()
    paths.user_config_path.write_text("audio: [unclosed\n")

    assert cfg_mod.load_config().refine.preset == "gpt-5.6-terra"

    cfg_mod.save_input_device(paths, "USB Mic")
    assert "unclosed" in paths.user_config_path.with_name("config.yaml.unreadable").read_text()
    assert cfg_mod.load_config().input_device == "USB Mic"


def test_bundled_config_keeps_the_silence_gate_at_the_code_default(monkeypatch, tmp_path):
    """A fresh install reads assets/config.yaml, so a stale value there overrides the fix in code."""
    import dataclasses
    from typeless_local import config as cfg_mod
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "jarvis").mkdir()
    monkeypatch.setenv("JARVIS_PROJECT_ROOT", str(tmp_path / "jarvis"))

    default = {f.name: f.default for f in dataclasses.fields(cfg_mod.AppConfig)}["low_volume_threshold"]
    assert cfg_mod.load_config().low_volume_threshold == default


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


def test_save_default_preset_writes_only_that_key_and_load_config_reads_it(monkeypatch, tmp_path):
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
    assert "deepseek-flash" in cfg_mod.preset_names(loaded.jarvis_config)  # from the bundled file
    written = yaml.safe_load(paths.user_config_path.read_text(encoding="utf-8"))
    assert written == {"llm": {"default_preset": "gpt-5.6-luna"}}


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


def test_a_new_install_can_start_on_another_preset_but_a_chosen_one_stays(monkeypatch, tmp_path):
    from typeless_local import config as cfg_mod
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "jarvis").mkdir()
    monkeypatch.setenv("JARVIS_PROJECT_ROOT", str(tmp_path / "jarvis"))

    fresh = cfg_mod.adopt_default_preset(cfg_mod.load_config(), "deepseek-flash")
    assert (fresh.refine.preset, fresh.refine.api_key_env) == ("deepseek-flash", "DEEPSEEK_API_KEY")
    assert cfg_mod.load_config().refine.preset == "deepseek-flash"  # remembered

    paths = cfg_mod.resolve_user_paths()
    cfg_mod.save_default_preset(paths, "gpt-5.6-luna")
    assert cfg_mod.adopt_default_preset(cfg_mod.load_config(), "deepseek-flash").refine.preset == "gpt-5.6-luna"
    assert cfg_mod.adopt_default_preset(cfg_mod.load_config(), "no-such-preset").refine.preset == "gpt-5.6-luna"


def test_resolve_jarvis_root_falls_back_without_a_checkout(monkeypatch, tmp_path) -> None:
    # A friend's Mac has no ~/Projects/jarvis; launch must not fail on it.
    monkeypatch.delenv("JARVIS_PROJECT_ROOT", raising=False)
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")
    app_root = tmp_path / "Yana.app" / "Contents" / "Resources" / "lib" / "python3.13"
    app_root.mkdir(parents=True)

    assert resolve_jarvis_root(app_root) == app_root


def test_a_preset_an_update_removed_falls_back_to_terra(monkeypatch, tmp_path):
    """gpt-5.6-sol was taken out in 0.4.0."""
    from typeless_local import config as cfg_mod
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("JARVIS_PROJECT_ROOT", str(tmp_path))
    cfg_mod.save_default_preset(cfg_mod.resolve_user_paths(), "gpt-5.6-sol")
    loaded = cfg_mod.load_config()
    assert loaded.refine.preset == "gpt-5.6-terra" and loaded.refine.model == "gpt-5.6-terra"
