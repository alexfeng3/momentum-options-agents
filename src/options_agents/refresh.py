"""Keeps the local daily-bar cache (data/broad/*.csv) current.

The rankings are computed from that cache, and nothing else ever updated it, so it
went stale on 2026-08-27. This runs at the start of every cycle and appends the
sessions that have finished since the last cached bar.

Three rules matter:
  * Never write a bar dated today (US/Eastern) or later. Today's daily bar is
    partial while the market is open, and a partial bar would enter the rankings
    as if it were a close.
  * Re-fetch the last cached date as an overlap. If the cached close and the new
    close for that date disagree, the cached history is in old units (a split
    happened since it was written), so that symbol's whole history is re-fetched.
  * A symbol with no new bars (delisted) is left alone.

Same feed and split adjustment as scripts/fetch_broad_universe.py, via
`broker.get_stock_bars`.
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

HEADER = "date,open,high,low,close,volume"
DEAD_AFTER_DAYS = 30       # a name this far behind the newest cached bar is dead


def _line(b: dict) -> str:
    return f"{b['t'][:10]},{b['o']},{b['h']},{b['l']},{b['c']},{b['v']}"


def _last_row(path: Path):
    """(last cached date, its close, number of data rows), or None."""
    rows = [x for x in path.read_text().splitlines()[1:] if x.strip()]
    if not rows:
        return None
    f = rows[-1].split(",")
    try:
        return date.fromisoformat(f[0].split()[0]), float(f[4]), len(rows)
    except (ValueError, IndexError):
        return None


def _write(path: Path, lines: list[str]) -> None:
    tmp = path.with_suffix(".csv.tmp")
    tmp.write_text("\n".join(lines) + "\n")
    os.replace(tmp, path)          # a crash never leaves a half-written file


def _chunks(xs: list[str], n: int):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def refresh_bars(broker, symbols: list[str], cfg, today: date) -> dict:
    """Append finished sessions to the cache. Returns counts for the event log.

    `today` is the current US/Eastern date; bars dated on or after it are dropped.
    """
    data_dir = Path(cfg.data_dir)
    today_iso = today.isoformat()
    last: dict[str, tuple[date, float, int]] = {}
    for s in sorted(set(symbols)):
        f = data_dir / f"{s}.csv"
        if f.exists():
            row = _last_row(f)
            if row:
                last[s] = row

    out = {"symbols": 0, "dead_skipped": 0, "updated": 0, "bars_added": 0,
           "rewritten": [], "rewrite_skipped": [], "batch_errors": [],
           "newest_bar": None}
    if not last:
        return out

    newest_cached = max(d for d, _, _ in last.values())
    active = [s for s in last if (newest_cached - last[s][0]).days <= DEAD_AFTER_DAYS]
    out["dead_skipped"] = len(last) - len(active)
    out["symbols"] = len(active)
    start = min(last[s][0] for s in active).isoformat()

    mismatched: list[str] = []
    for batch in _chunks(active, cfg.refresh_batch):
        try:
            data = broker.get_stock_bars(batch, start)
        except Exception as e:
            out["batch_errors"].append(f"{batch[0]}..: {e}")
            continue
        for sym in batch:
            bars = [b for b in data.get(sym, []) if b["t"][:10] < today_iso]
            if not bars:
                continue                       # nothing new: leave it alone
            ld, lc, n = last[sym]
            overlap = next((b for b in bars if b["t"][:10] == ld.isoformat()), None)
            if overlap and lc > 0 and abs(overlap["c"] / lc - 1) > cfg.split_tolerance:
                mismatched.append(sym)         # history is in stale units
                continue
            new = [b for b in bars if b["t"][:10] > ld.isoformat()]
            if not new:
                continue
            f = data_dir / f"{sym}.csv"
            lines = [x for x in f.read_text().splitlines() if x.strip()]
            _write(f, lines + [_line(b) for b in new])
            last[sym] = (date.fromisoformat(new[-1]["t"][:10]), float(new[-1]["c"]),
                         n + len(new))
            out["updated"] += 1
            out["bars_added"] += len(new)

    for batch in _chunks(mismatched, cfg.refresh_batch):
        try:
            data = broker.get_stock_bars(batch, cfg.history_start)
        except Exception as e:
            out["batch_errors"].append(f"rewrite {batch[0]}..: {e}")
            out["rewrite_skipped"].extend(batch)
            continue
        for sym in batch:
            bars = [b for b in data.get(sym, []) if b["t"][:10] < today_iso]
            # A truncated history would replace a good one and drop the name from
            # the rankings (needs 260 bars), so refuse anything much shorter.
            if len(bars) < 0.9 * last[sym][2]:
                out["rewrite_skipped"].append(sym)
                continue
            _write(data_dir / f"{sym}.csv", [HEADER] + [_line(b) for b in bars])
            last[sym] = (date.fromisoformat(bars[-1]["t"][:10]),
                         float(bars[-1]["c"]), len(bars))
            out["rewritten"].append(sym)

    if "SPY" in last:
        out["newest_bar"] = last["SPY"][0].isoformat()
    return out
