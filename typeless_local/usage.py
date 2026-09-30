"""How much the app used the refinement API: dictations and estimated cost per day.

Counted from trace.db, which records each refine call's token usage as the API
reported it, so this is this app's own spend, not the whole account's. Prices
are what the provider lists per million tokens; the cost is an estimate
(exchange rates, discounts and free tiers are not known here).
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from pathlib import Path
import sqlite3

from typeless_local.i18n import t

LOGGER = logging.getLogger(__name__)

# US dollars per million tokens: (input, cached input, output). Cached input is
# billed at a tenth of input on these models.
PRICES: dict[str, tuple[float, float, float]] = {
    "gpt-5.4-mini": (0.75, 0.075, 4.5),
    "gpt-5.6-terra": (2.0, 0.2, 12.0),
    "gpt-5.6-luna": (0.2, 0.02, 1.2),
}
DAYS = 30


def price_for(model: str, overrides: dict | None = None) -> tuple[float, float, float] | None:
    """The model's price, from ``llm.prices`` in the config first, then the table above.

    An override is ``{model: [input, cached, output]}`` or ``{model: {input:, cached:, output:}}``;
    a missing cached price is taken as a tenth of input.
    """

    raw = (overrides or {}).get(model)
    if isinstance(raw, dict):
        raw = [raw.get("input"), raw.get("cached"), raw.get("output")]
    if isinstance(raw, (list, tuple)) and len(raw) in (2, 3):
        try:
            if len(raw) == 2 or raw[2] is None:
                values = [float(raw[0]), float(raw[0]) / 10, float(raw[-1])]
            else:
                values = [float(raw[0]), float(raw[1]) if raw[1] is not None else float(raw[0]) / 10, float(raw[2])]
            return values[0], values[1], values[2]
        except (TypeError, ValueError):
            LOGGER.warning("Ignoring an unreadable price for %s: %r", model, raw)
    return PRICES.get(model)


def cost(model: str, prompt: int, cached: int, completion: int, overrides: dict | None = None) -> float | None:
    price = price_for(model, overrides)
    if price is None:
        return None
    cached = min(max(cached, 0), max(prompt, 0))
    return ((prompt - cached) * price[0] + cached * price[1] + completion * price[2]) / 1_000_000


def summary(db_path: Path | None, overrides: dict | None = None, now: datetime | None = None, days: int = DAYS) -> dict:
    """Today, the last 7 and the last ``days`` days, and one bar per day.

    ``cost`` is None for a period in which some tokens were spent on a model
    with no known price; ``untracked`` counts refined dictations from before
    token usage was recorded, which are in ``n`` but not in the cost.
    """

    now = now or datetime.now()
    today = now.date()
    first = today - timedelta(days=days - 1)
    per_day = {first + timedelta(days=i): _bucket() for i in range(days)}
    models: dict[str, dict] = {}
    for row in _rows(db_path, datetime.combine(first, datetime.min.time()).timestamp()):
        day = datetime.fromtimestamp(row["started_at"]).date()
        if day not in per_day:
            continue
        model = row["refine_model"] or ""
        tokens = (row["prompt_tokens"], row["cached_tokens"], row["completion_tokens"])
        _add(per_day[day], model, tokens, overrides)
        if model:
            _add(models.setdefault(model, {**_bucket(), "model": model}), model, tokens, overrides)

    daily = [{"day": day.isoformat(), **per_day[day]} for day in sorted(per_day)]
    return {
        "today": _total(daily[-1:]),
        "week": _total(daily[-7:]),
        "month": _total(daily),
        "daily": daily,
        "models": sorted(models.values(), key=lambda m: -m["refined"]),
        "days": days,
    }


def _bucket() -> dict:
    return {"n": 0, "refined": 0, "untracked": 0, "prompt": 0, "cached": 0, "completion": 0, "cost": 0.0}


def _add(bucket: dict, model: str, tokens: tuple, overrides: dict | None) -> None:
    bucket["n"] += 1
    if not model:
        return
    bucket["refined"] += 1
    prompt, cached, completion = tokens
    if prompt is None:
        bucket["untracked"] += 1
        return
    prompt, cached, completion = int(prompt or 0), int(cached or 0), int(completion or 0)
    bucket["prompt"] += prompt
    bucket["cached"] += cached
    bucket["completion"] += completion
    spent = cost(model, prompt, cached, completion, overrides)
    if spent is None:
        if prompt or completion:
            bucket["cost"] = None
    elif bucket["cost"] is not None:
        bucket["cost"] += spent


def _total(daily: list[dict]) -> dict:
    out = _bucket()
    for day in daily:
        for key in ("n", "refined", "untracked", "prompt", "cached", "completion"):
            out[key] += day[key]
        out["cost"] = None if out["cost"] is None or day["cost"] is None else out["cost"] + day["cost"]
    return out


def _rows(db_path: Path | None, since: float) -> list[sqlite3.Row]:
    """Dictations that produced text since ``since``; [] when there is no history."""

    if db_path is None or not Path(db_path).exists():
        return []
    try:
        conn = sqlite3.connect(str(db_path), isolation_level=None, timeout=2.0)
        conn.row_factory = sqlite3.Row
        try:
            have = {row[1] for row in conn.execute("PRAGMA table_info(sessions)")}
            if not have:
                return []
            tokens = (
                "prompt_tokens, cached_tokens, completion_tokens"
                if "prompt_tokens" in have
                else "NULL AS prompt_tokens, NULL AS cached_tokens, NULL AS completion_tokens"
            )
            return conn.execute(
                f"SELECT started_at, refine_model, {tokens} FROM sessions "
                "WHERE started_at >= ? AND COALESCE(refined_text, raw_asr_text, '') != '' "
                "AND COALESCE(error, '') NOT LIKE 'dropped%'",
                (since,),
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        LOGGER.warning("Could not read usage from %s", db_path, exc_info=True)
        return []


def money(value: float | None) -> str:
    """"$0.04", "<$0.01", or "" when unknown."""

    if value is None:
        return ""
    if value == 0:
        return "$0"
    if value < 0.01:
        return "<$0.01"
    return f"${value:.2f}"


def today_line(db_path: Path | None, overrides: dict | None = None, now: datetime | None = None) -> str:
    """The menu's one line: "今天 23 次 · 约 $0.04"."""

    total = summary(db_path, overrides, now=now, days=1)["today"]
    n = total["n"]
    if not n:
        return t("今天还没有听写", "No dictations today")
    spent = money(total["cost"])
    cost = t(f" · 约 {spent}", f" · about {spent}") if spent and total["refined"] > total["untracked"] else ""
    return t(f"今天 {n} 次", f"Today: {n} dictation{'s' if n != 1 else ''}") + cost

