"""Performance metrics and the head-to-head comparison against SPY."""
from __future__ import annotations

import math
import statistics as stats
from datetime import date


def _cagr(curve: list[tuple[date, float]]) -> float:
    if len(curve) < 2:
        return 0.0
    yrs = (curve[-1][0] - curve[0][0]).days / 365.25
    if yrs <= 0 or curve[0][1] <= 0:
        return 0.0
    return (curve[-1][1] / curve[0][1]) ** (1 / yrs) - 1


def _max_dd(vals: list[float]) -> float:
    peak, mdd = vals[0], 0.0
    for v in vals:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1)
    return mdd


def _daily_returns(curve: list[tuple[date, float]]) -> list[float]:
    return [curve[i][1] / curve[i - 1][1] - 1
            for i in range(1, len(curve)) if curve[i - 1][1] > 0]


def summarise(curve: list[tuple[date, float]], label: str) -> dict:
    vals = [v for _, v in curve]
    rets = _daily_returns(curve)
    sd = stats.pstdev(rets) if len(rets) > 1 else 0.0
    sharpe = (stats.mean(rets) / sd * math.sqrt(252)) if sd > 0 else 0.0
    downside = [r for r in rets if r < 0]
    dsd = stats.pstdev(downside) if len(downside) > 1 else 0.0
    sortino = (stats.mean(rets) / dsd * math.sqrt(252)) if dsd > 0 else 0.0
    mdd = _max_dd(vals)
    cagr = _cagr(curve)
    return {
        "label": label,
        "start": curve[0][0].isoformat(), "end": curve[-1][0].isoformat(),
        "start_equity": round(vals[0], 2), "final_equity": round(vals[-1], 2),
        "total_return": round(vals[-1] / vals[0] - 1, 4),
        "cagr": round(cagr, 4),
        "ann_vol": round(sd * math.sqrt(252), 4),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "max_drawdown": round(mdd, 4),
        "calmar": round(cagr / abs(mdd), 3) if mdd else None,
    }


def spy_buy_hold(book, start: date, end: date, equity: float) -> list[tuple[date, float]]:
    """Buy-and-hold SPY over the same window, same starting capital."""
    days = [d for d in book.days if start <= d <= end and book.close("SPY", d)]
    if not days:
        return []
    p0 = book.close("SPY", days[0])
    return [(d, equity * book.close("SPY", d) / p0) for d in days]


def _weekly(curve: list[tuple[date, float]]) -> dict[tuple[int, int], float]:
    """Map ISO (year, week) -> return over that week."""
    by: dict[tuple[int, int], list[tuple[date, float]]] = {}
    for d, v in curve:
        by.setdefault(d.isocalendar()[:2], []).append((d, v))
    out = {}
    for k, pts in by.items():
        pts.sort()
        if len(pts) >= 2 and pts[0][1] > 0:
            out[k] = pts[-1][1] / pts[0][1] - 1
    return out


def head_to_head(strategy: list[tuple[date, float]],
                 benchmark: list[tuple[date, float]]) -> dict:
    """The claim under test: how often does the strategy beat SPY over one week?

    This is the honest form of 'beats the S&P on a one-week run'. A single week is
    dominated by noise; the fraction of weeks won over 15 years is a real,
    falsifiable statistic.
    """
    ws, wb = _weekly(strategy), _weekly(benchmark)
    common = sorted(set(ws) & set(wb))
    if not common:
        return {"weeks": 0}
    wins = [k for k in common if ws[k] > wb[k]]
    diffs = [ws[k] - wb[k] for k in common]
    s_rets = [ws[k] for k in common]
    b_rets = [wb[k] for k in common]
    # paired t-statistic on the weekly return difference
    md = stats.mean(diffs)
    sd = stats.pstdev(diffs)
    t = md / (sd / math.sqrt(len(diffs))) if sd > 0 else 0.0
    return {
        "weeks": len(common),
        "weeks_beating_spy": len(wins),
        "pct_weeks_beating_spy": round(100 * len(wins) / len(common), 2),
        "mean_weekly_strategy": round(100 * stats.mean(s_rets), 4),
        "mean_weekly_spy": round(100 * stats.mean(b_rets), 4),
        "mean_weekly_excess_pp": round(100 * md, 4),
        "weekly_excess_t_stat": round(t, 2),
        "strategy_weekly_vol": round(100 * stats.pstdev(s_rets), 4),
        "spy_weekly_vol": round(100 * stats.pstdev(b_rets), 4),
        "worst_strategy_week": round(100 * min(s_rets), 2),
        "worst_spy_week": round(100 * min(b_rets), 2),
    }


def trade_stats(trades: list) -> dict:
    if not trades:
        return {"trades": 0}
    pnl = [t.pnl for t in trades]
    wins = [p for p in pnl if p > 0]
    losses = [p for p in pnl if p <= 0]
    by_reason: dict[str, dict] = {}
    for t in trades:
        r = by_reason.setdefault(t.reason, {"n": 0, "pnl": 0.0})
        r["n"] += 1
        r["pnl"] += t.pnl
    return {
        "trades": len(trades),
        "win_rate": round(len(wins) / len(trades), 4),
        "total_pnl": round(sum(pnl), 2),
        "avg_win": round(stats.mean(wins), 2) if wins else 0.0,
        "avg_loss": round(stats.mean(losses), 2) if losses else 0.0,
        "profit_factor": (round(sum(wins) / abs(sum(losses)), 3)
                          if losses and sum(losses) else None),
        "avg_held_days": round(stats.mean([t.held_days for t in trades]), 2),
        "by_exit_reason": {k: {"n": v["n"], "pnl": round(v["pnl"], 2)}
                           for k, v in sorted(by_reason.items())},
    }
