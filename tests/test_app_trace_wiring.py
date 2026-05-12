from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from typeless_local.config import (
    AppConfig, RefineConfig, UserPaths, resolve_app_root,
)
from typeless_local.mac_integration import FocusContext


def _make_app_config(tmp_path: Path) -> AppConfig:
    user_paths = UserPaths(
        config_dir=tmp_path,
        vocab_path=tmp_path / "vocab.yaml",
        trace_db_path=tmp_path / "trace.db",
        log_path=tmp_path / "app.log",
        stopwords_dir=tmp_path / "stops",
        user_config_path=tmp_path / "config.yaml",
    )
    return AppConfig(
        root=resolve_app_root(),
        jarvis_root=Path("/nonexistent"),
        jarvis_config={},
        refine=RefineConfig("gpt-5.4-mini", "https://api.openai.com/v1", "OPENAI_API_KEY", 128),
        user_paths=user_paths,
    )


def _read_rows(db: Path) -> list[dict]:
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM sessions").fetchall()]
    finally:
        conn.close()


def test_successful_pipeline_writes_trace_row(tmp_path: Path) -> None:
    cfg = _make_app_config(tmp_path)
    # vocab seeded
    cfg.user_paths.vocab_path.write_text(
        "user:\n  - Jarvis\nauto: []\n", encoding="utf-8"
    )

    # Avoid touching macOS APIs by patching imports at the app boundary.
    with patch("typeless_local.app.TypelessLocalApp._build_components") as build:
        from typeless_local.app import TypelessLocalApp

        fake_asr = MagicMock()
        fake_asr.transcribe.return_value = SimpleNamespace(
            text="hi jarvas", language="en", confidence=0.9,
        )
        fake_asr.model_name = "fake:test"

        fake_refiner = MagicMock()
        fake_refiner.refine.return_value = SimpleNamespace(
            text="Hi Jarvis.", raw_text="hi jarvas", model="gpt-5.4-mini",
        )

        build.return_value = SimpleNamespace(
            asr=fake_asr,
            refiner=fake_refiner,
            recorder=MagicMock(get_volume_level=MagicMock(return_value=0.1),
                               is_quality_ok=MagicMock(return_value=(True, "ok"))),
        )

        app = TypelessLocalApp(cfg, headless=True)

    audio = np.zeros(8000, dtype=np.float32)
    ctx = FocusContext(app_name="TextEdit", window_title="Untitled", can_insert_text=False)
    app._process_audio(audio, ctx, session_id=1)

    rows = _read_rows(cfg.user_paths.trace_db_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["raw_asr_text"] == "hi jarvas"
    assert row["refined_text"] == "Hi Jarvis."
    assert row["hotwords_count"] == 1
    assert "Jarvis" in row["vocab_terms_used"]
    assert row["error"] is None


def test_low_quality_audio_still_logs_trace_row(tmp_path: Path) -> None:
    cfg = _make_app_config(tmp_path)
    with patch("typeless_local.app.TypelessLocalApp._build_components") as build:
        from typeless_local.app import TypelessLocalApp

        fake_asr = MagicMock(model_name="fake:test")
        fake_refiner = MagicMock()
        build.return_value = SimpleNamespace(
            asr=fake_asr,
            refiner=fake_refiner,
            recorder=MagicMock(
                get_volume_level=MagicMock(return_value=0.0),
                is_quality_ok=MagicMock(return_value=(False, "silence")),
            ),
        )
        app = TypelessLocalApp(cfg, headless=True)

    audio = np.zeros(800, dtype=np.float32)
    ctx = FocusContext(app_name="x", window_title="y", can_insert_text=False)
    app._process_audio(audio, ctx, session_id=1)

    rows = _read_rows(cfg.user_paths.trace_db_path)
    assert len(rows) == 1
    assert rows[0]["error"] and "silence" in rows[0]["error"]
    # ASR / refine never ran
    fake_asr.transcribe.assert_not_called()


def test_exception_path_logs_error_row(tmp_path: Path) -> None:
    cfg = _make_app_config(tmp_path)
    with patch("typeless_local.app.TypelessLocalApp._build_components") as build:
        from typeless_local.app import TypelessLocalApp

        fake_asr = MagicMock(model_name="fake:test")
        fake_asr.transcribe.side_effect = RuntimeError("boom")
        build.return_value = SimpleNamespace(
            asr=fake_asr,
            refiner=MagicMock(),
            recorder=MagicMock(
                get_volume_level=MagicMock(return_value=0.1),
                is_quality_ok=MagicMock(return_value=(True, "ok")),
            ),
        )
        app = TypelessLocalApp(cfg, headless=True)

    audio = np.zeros(8000, dtype=np.float32)
    ctx = FocusContext(app_name="x", window_title="y", can_insert_text=False)
    with pytest.raises(RuntimeError):
        app._process_audio(audio, ctx, session_id=1)

    rows = _read_rows(cfg.user_paths.trace_db_path)
    assert len(rows) == 1
    assert "boom" in (rows[0]["error"] or "")
