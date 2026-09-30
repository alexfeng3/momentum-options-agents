"""Rebalance calendar for the momentum core.

The backtest rebalances every `rebalance_days` calendar days and does nothing in
between. The cron job runs three times a day, so the live agents need to remember
when they last rebalanced. That date lives in a small JSON file under state/.

Only a real (non-dry-run) cycle, with the market open and fresh data, writes it.
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path


def load_last_rebalance(path: Path) -> date | None:
    """The recorded date, or None if there is no file or it cannot be read."""
    try:
        return date.fromisoformat(json.loads(Path(path).read_text())["last_rebalance"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_last_rebalance(path: Path, d: date) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"last_rebalance": d.isoformat()}) + "\n")
    os.replace(tmp, path)


def is_rebalance_cycle(as_of: date, last: date | None, rebalance_days: int) -> bool:
    """True when the book should be re-ranked and traded.

    `as_of == last` counts: later cycles on the rebalance day can finish a
    partly filled rebalance (the 25% band stops them re-buying what filled).
    """
    if last is None:
        return True
    return as_of == last or (as_of - last).days >= rebalance_days


def next_rebalance_date(last: date | None, rebalance_days: int) -> date | None:
    """First day the next rebalance can happen, or None if none is recorded yet."""
    return last + timedelta(days=rebalance_days) if last else None
