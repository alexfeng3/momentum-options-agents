"""Real earnings events from SEC EDGAR XBRL, and SUE-based surprise.

`scripts/fetch_earnings.py` caches quarterly diluted EPS plus the SEC FILING DATE
for each period. Two facts make this usable for PEAD without look-ahead:

  * The filing date is when the data became public. Nothing before it is used.
  * PEAD trades the DRIFT, not the announcement jump, so entering after the event
    is the strategy, not a compromise.

The press release (8-K) usually precedes the 10-Q by a few days, so the actual
announcement is located as the biggest volume-confirmed gap in the window ending
at the filing date. Entry is the day AFTER that, which is strictly conservative:
the initial jump is never captured.
"""
from __future__ import annotations

import json
import statistics as st
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EARN = ROOT / "data" / "earnings"


@dataclass
class EarningsEvent:
    symbol: str
    period_end: date
    filed: date
    eps: float
    sue: float | None            # standardised unexpected earnings
    yoy_growth: float | None
    announce_date: date | None   # detected volume-confirmed gap day
    gap_pct: float | None        # the announcement reaction
    vol_ratio: float | None


def _d(s: str | None) -> date | None:
    return datetime.fromisoformat(s).date() if s else None


def load_events(symbol: str) -> list[dict]:
    f = EARN / f"{symbol}.json"
    if not f.exists():
        return []
    return json.loads(f.read_text()).get("rows", [])


def build_events(symbol: str, book) -> list[EarningsEvent]:
    """Quarterly events with SUE and a detected announcement day."""
    rows = load_events(symbol)
    if not rows:
        return []
    # keep true quarterly periods (~85-95 days) and sort by period end
    q = []
    for r in rows:
        s, e = _d(r.get("start")), _d(r.get("end"))
        if not s or not e:
            continue
        n = (e - s).days
        if 80 <= n <= 100:
            q.append({"end": e, "filed": _d(r["filed"]), "eps": float(r["val"])})
    q.sort(key=lambda x: x["end"])
    # dedupe by period end, keeping the earliest filing
    ded = {}
    for r in q:
        if r["end"] not in ded or r["filed"] < ded[r["end"]]["filed"]:
            ded[r["end"]] = r
    q = [ded[k] for k in sorted(ded)]

    out: list[EarningsEvent] = []
    for i, r in enumerate(q):
        # SUE: seasonal random walk. Surprise = EPS(q) - EPS(q-4), scaled by the
        # standard deviation of the last 8 such surprises. Bernard & Thomas (1989).
        sue = yoy = None
        if i >= 4:
            surprises = []
            for j in range(max(4, i - 7), i + 1):
                surprises.append(q[j]["eps"] - q[j - 4]["eps"])
            cur = r["eps"] - q[i - 4]["eps"]
            if len(surprises) >= 4:
                sd = st.pstdev(surprises)
                sue = (cur / sd) if sd > 1e-9 else None
            prev = q[i - 4]["eps"]
            if abs(prev) > 1e-9:
                yoy = (r["eps"] - prev) / abs(prev)

        ann, gap, vr = _detect_announcement(symbol, r["filed"], book)
        out.append(EarningsEvent(symbol=symbol, period_end=r["end"], filed=r["filed"],
                                 eps=r["eps"], sue=sue, yoy_growth=yoy,
                                 announce_date=ann, gap_pct=gap, vol_ratio=vr))
    return out


def _detect_announcement(symbol: str, filed: date, book, window: int = 35):
    """Largest volume-confirmed overnight gap in (filed-window, filed].

    Uses only bars at or before the filing date, so nothing after the event
    influences the choice.
    """
    px = book.px.get(symbol, {})
    days = sorted(d for d in px if filed - timedelta(days=window) < d <= filed)
    if len(days) < 5:
        return None, None, None
    all_days = sorted(px)
    best = (0.0, None, None)
    for d in days:
        i = all_days.index(d)
        if i < 21:
            continue
        prev_c = px[all_days[i - 1]]["close"]
        if prev_c <= 0:
            continue
        gap = px[d]["open"] / prev_c - 1.0
        vols = [px[all_days[k]].get("volume", 0) for k in range(i - 20, i)]
        av = sum(vols) / len(vols) if vols else 0
        vr = (px[d].get("volume", 0) / av) if av > 0 else 0
        if vr < 1.3:
            continue
        if abs(gap) > abs(best[0]):
            best = (gap, d, vr)
    return best[1], best[0] if best[1] else None, best[2]
