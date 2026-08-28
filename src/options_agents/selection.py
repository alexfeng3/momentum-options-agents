"""Point-in-time stock selection: momentum + trend + relative strength.

Every score is computed from closes up to and including day `d`. Nothing in this
module can see the future — that is what makes the backtest meaningful given the
universe is itself chosen with hindsight (see docs/DIRECTIONAL.md).
"""
from __future__ import annotations

import math
import statistics as st
from dataclasses import dataclass
from datetime import date


@dataclass
class Score:
    symbol: str
    total: float
    mom_12_1: float          # 12-month return skipping the last month
    mom_3m: float
    trend: float             # 1 if px > SMA50 > SMA200
    rs: float                # relative strength vs the benchmark
    vol: float               # annualised realised vol (for normalisation)
    above_sma50: bool
    detail: dict


def _ret(closes: list[float], lo: int, hi: int = 0) -> float | None:
    """Return over the window [-lo, -hi]. hi=0 means 'to today'."""
    if len(closes) < lo + 1:
        return None
    a = closes[-lo - 1]
    b = closes[-1] if hi == 0 else closes[-hi - 1]
    return (b / a - 1.0) if a > 0 else None


def _sma(closes: list[float], n: int) -> float | None:
    return sum(closes[-n:]) / n if len(closes) >= n else None


def realised_vol(closes: list[float], window: int = 60) -> float | None:
    if len(closes) < window + 1:
        return None
    r = [math.log(closes[i] / closes[i - 1]) for i in range(-window, 0)]
    return st.pstdev(r) * math.sqrt(252) if len(r) > 1 else None


def score_symbol(sym: str, closes: list[float],
                 bench: list[float] | None = None) -> Score | None:
    """Composite momentum score. Needs ~1 year of history to be defined."""
    if len(closes) < 260:
        return None
    m12_1 = _ret(closes, 252, 21)     # 12-month, skipping the last month
    m3 = _ret(closes, 63)
    if m12_1 is None or m3 is None:
        return None
    s50, s200 = _sma(closes, 50), _sma(closes, 200)
    if s50 is None or s200 is None:
        return None
    px = closes[-1]
    trend = 1.0 if (px > s50 > s200) else (0.5 if px > s200 else 0.0)
    vol = realised_vol(closes, 60) or 0.40

    rs = 0.0
    if bench and len(bench) >= 253:
        b12 = _ret(bench, 252, 21)
        if b12 is not None:
            rs = m12_1 - b12

    # Volatility-normalise momentum so a 100%-vol name does not automatically
    # outrank a steady compounder purely for being noisy.
    total = (0.45 * (m12_1 / max(vol, 0.15))
             + 0.25 * (m3 / max(vol, 0.15))
             + 0.20 * trend
             + 0.10 * (rs / max(vol, 0.15)))
    return Score(symbol=sym, total=total, mom_12_1=m12_1, mom_3m=m3, trend=trend,
                 rs=rs, vol=vol, above_sma50=px > (s50 or px),
                 detail={"px": px, "sma50": s50, "sma200": s200})


def rank(candidates: dict[str, list[float]], bench: list[float] | None,
         top_n: int, min_vol: float = 0.0,
         require_uptrend: bool = True) -> list[Score]:
    out = []
    for sym, closes in candidates.items():
        sc = score_symbol(sym, closes, bench)
        if sc is None:
            continue
        if require_uptrend and sc.trend <= 0.0:
            continue
        if sc.vol < min_vol:
            continue
        out.append(sc)
    out.sort(key=lambda s: -s.total)
    return out[:top_n]
