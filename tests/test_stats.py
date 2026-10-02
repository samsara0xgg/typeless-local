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


def test_turning_stats_off_during_a_send_stops_it_and_leaves_no_file(tmp_path) -> None:
    from datetime import date

    from typeless_local.stats import DailyStats

    stats = DailyStats(tmp_path / "stats.json", "0.4.0")
    stats.record(dictations=1, today=date(2026, 9, 1))
    stats.record(dictations=1, today=date(2026, 9, 2))
    posted = []

    def post(url, payload):
        posted.append(payload["day"])
        stats.forget()  # the user turns it off while the first day is in flight

    stats.send("https://x/stats", today=date(2026, 9, 3), post=post)

    assert posted == ["2026-09-01"]
    assert not (tmp_path / "stats.json").exists()
    stats.record(dictations=1, today=date(2026, 9, 3))
    assert not (tmp_path / "stats.json").exists()


def test_posts_carry_an_app_user_agent(monkeypatch) -> None:
    """Cloudflare answers urllib's default User-Agent with 403 (error 1010)."""

    from typeless_local import stats

    seen = {}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout, context):
        seen["agent"] = request.get_header("User-agent")
        return _Response()

    monkeypatch.setattr(stats.urllib.request, "urlopen", fake_urlopen)
    stats._post("https://example.invalid/stats", {})

    assert seen["agent"].startswith("Yana/")
