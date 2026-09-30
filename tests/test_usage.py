from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from typeless_local import usage
from typeless_local.trace import DictationTrace, SessionRecord

NOW = datetime(2026, 9, 30, 15, 0)


def _log(db: Path, when: datetime, model: str = "gpt-5.6-terra", tokens=(1500, 1469, 90), **fields) -> None:
    prompt, cached, completion = tokens
    DictationTrace(db).log(
        SessionRecord(
            started_at=when.timestamp(), ended_at=when.timestamp() + 1, raw_asr_text="说了一句", refined_text="说了一句。",
            refine_model=model, prompt_tokens=prompt, cached_tokens=cached, completion_tokens=completion, **fields,
        )
    )


def test_cost_bills_cached_input_at_a_tenth() -> None:
    # 31 uncached + 1469 cached input, 90 output on terra.
    assert usage.cost("gpt-5.6-terra", 1500, 1469, 90) == pytest.approx((31 * 2 + 1469 * 0.2 + 90 * 12) / 1e6)
    assert usage.cost("some-new-model", 100, 0, 10) is None
    assert usage.cost("some-new-model", 1_000_000, 0, 0, {"some-new-model": [1.5, 6]}) == pytest.approx(1.5)
    assert usage.price_for("x", {"x": {"input": 1, "output": 4}}) == (1.0, 0.1, 4.0)


def test_summary_counts_today_the_week_and_each_day(tmp_path) -> None:
    db = tmp_path / "trace.db"
    _log(db, NOW - timedelta(hours=1))
    _log(db, NOW - timedelta(hours=2), model="gpt-5.4-mini", tokens=(900, 0, 60))
    _log(db, NOW - timedelta(days=3))
    _log(db, NOW - timedelta(days=40))  # outside the 30 days
    _log(db, NOW - timedelta(hours=3), model="", tokens=(0, 0, 0))  # refine off: counted, costs nothing
    _log(db, NOW - timedelta(hours=4), error="dropped: too quiet")  # never a dictation

    s = usage.summary(db, now=NOW)
    terra = usage.cost("gpt-5.6-terra", 1500, 1469, 90)
    mini = usage.cost("gpt-5.4-mini", 900, 0, 60)
    assert s["today"]["n"] == 3 and s["today"]["refined"] == 2
    assert s["today"]["cost"] == pytest.approx(terra + mini)
    assert s["week"]["n"] == 4 and s["month"]["n"] == 4
    assert len(s["daily"]) == 30 and s["daily"][-1]["day"] == "2026-09-30"
    assert s["daily"][-4]["n"] == 1
    assert [m["model"] for m in s["models"]] == ["gpt-5.6-terra", "gpt-5.4-mini"]
    assert s["models"][0]["cached"] == 2 * 1469


def test_rows_from_before_tokens_were_recorded_are_counted_not_priced(tmp_path) -> None:
    db = tmp_path / "trace.db"
    _log(db, NOW - timedelta(hours=1))
    import sqlite3

    conn = sqlite3.connect(db)
    conn.execute("UPDATE sessions SET prompt_tokens = NULL, cached_tokens = NULL, completion_tokens = NULL")
    conn.commit()
    conn.close()
    today = usage.summary(db, now=NOW)["today"]
    assert today["n"] == 1 and today["untracked"] == 1 and today["cost"] == 0
    assert usage.today_line(db, now=NOW) == "今天 1 次"


def test_an_unpriced_model_makes_the_cost_unknown(tmp_path) -> None:
    db = tmp_path / "trace.db"
    _log(db, NOW - timedelta(hours=1), model="deepseek-chat")
    assert usage.summary(db, now=NOW)["today"]["cost"] is None
    assert usage.summary(db, {"deepseek-chat": [0.27, 1.1]}, now=NOW)["today"]["cost"] > 0


def test_menu_line_and_money() -> None:
    assert usage.money(None) == "" and usage.money(0.004) == "<$0.01" and usage.money(0.123) == "$0.12"
    assert usage.today_line(None) == "今天还没有听写"


def test_menu_line_with_spend(tmp_path) -> None:
    db = tmp_path / "trace.db"
    for hour in range(1, 4):
        _log(db, NOW - timedelta(hours=hour))
    assert usage.today_line(db, now=NOW) == "今天 3 次 · 约 <$0.01"


def test_no_history_is_an_empty_summary(tmp_path) -> None:
    s = usage.summary(tmp_path / "missing.db", now=NOW)
    assert s["month"]["n"] == 0 and len(s["daily"]) == 30
