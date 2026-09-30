from __future__ import annotations

from datetime import date
import json

from typeless_local.stats import DailyStats


def test_counts_only_numbers_and_sends_finished_days_once(tmp_path) -> None:
    stats = DailyStats(tmp_path / "stats.json", "0.4.0")
    stats.record(dictations=1, chars=12, trial_spend=0.001, today=date(2026, 10, 1))
    stats.record(dictations=1, chars=8, today=date(2026, 10, 1))
    stats.record(today=date(2026, 10, 2))  # opened, no dictation
    sent = []

    assert stats.send("https://x/stats", today=date(2026, 10, 2), post=lambda url, p: sent.append(p)) == 1
    assert sent[0]["day"] == "2026-10-01" and sent[0]["dictations"] == 2 and sent[0]["chars"] == 20
    assert set(sent[0]) == {"id", "day", "version", "dictations", "chars", "trial_spend"}
    # Today is not finished; the sent day is gone.
    assert list(json.loads((tmp_path / "stats.json").read_text())["days"]) == ["2026-10-02"]
    assert stats.send("https://x/stats", today=date(2026, 10, 2), post=lambda url, p: sent.append(p)) == 0


def test_a_failed_send_keeps_the_day_for_later(tmp_path) -> None:
    stats = DailyStats(tmp_path / "stats.json", "0.4.0")
    stats.record(dictations=3, chars=30, today=date(2026, 10, 1))

    def offline(url, payload):
        raise OSError("offline")

    assert stats.send("https://x/stats", today=date(2026, 10, 3), post=offline) == 0
    assert "2026-10-01" in json.loads((tmp_path / "stats.json").read_text())["days"]
