from __future__ import annotations

import json
import zipfile

from typeless_local import diagnostics

KEY = "sk-proj-abcdefghijklmnop1234"


def test_export_leaves_out_keys_and_history(tmp_path) -> None:
    data = tmp_path / ".typlus"
    data.mkdir()
    (data / "app.log.1").write_text("older line\n")
    (data / "app.log").write_text(f"newer line\nsent key {KEY}\nzhipu 0123456789abcdef0123456789abcdef.AbCdEfGhIjKlMnOp\n")
    (data / "config.yaml").write_text(f"llm:\n  default_preset: deepseek-flash\n# {KEY}\n")
    (data / "trace.db").write_text("every dictation ever")

    path = diagnostics.export(
        data / "diagnostics",
        name="Yana",
        version="0.3.0",
        summary={"refine": {"keys_set": {"OPENAI_API_KEY": True}}, "note": f"env {KEY}"},
        log_path=data / "app.log",
        user_config_path=data / "config.yaml",
        secrets=[KEY, ""],
    )

    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        log = archive.read("app.log").decode()
        config = archive.read("config.yaml").decode()
        summary = json.loads(archive.read("summary.json"))
    assert names == {"README.txt", "summary.json", "config.yaml", "app.log"}
    assert log.index("older line") < log.index("newer line")
    assert KEY not in log + config + json.dumps(summary)
    assert "0123456789abcdef0123456789abcdef" not in log
    assert "default_preset: deepseek-flash" in config
    assert summary["refine"]["keys_set"] == {"OPENAI_API_KEY": True}


def test_redact_catches_key_shaped_text_it_was_not_told_about() -> None:
    assert diagnostics.redact("key=sk-live-0123456789abcdef!", []) == f"key={diagnostics.REDACTED}!"
    assert diagnostics.redact("short sk-12", []) == "short sk-12"
