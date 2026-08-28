"""Full performance metric suite, including benchmark-relative beta and alpha."""
from __future__ import annotations

import math
import statistics as st
from datetime import date

TRADING_DAYS = 252


def _rets(curve: list[tuple[date, float]]) -> list[float]:
    return [curve[i][1] / curve[i - 1][1] - 1
            for i in range(1, len(curve)) if curve[i - 1][1] > 0]


def _align(a: list[tuple[date, float]], b: list[tuple[date, float]]):
    bm = dict(b)
    days = [d for d, _ in a if d in bm]
    ra, rb = [], []
    for i in range(1, len(days)):
        pa0, pa1 = dict(a)[days[i - 1]], dict(a)[days[i]]
        pb0, pb1 = bm[days[i - 1]], bm[days[i]]
        if pa0 > 0 and pb0 > 0:
            ra.append(pa1 / pa0 - 1)
            rb.append(pb1 / pb0 - 1)
    return ra, rb


def beta_alpha(strategy, benchmark, rf_annual: float = 0.02):
    """OLS beta and annualised Jensen's alpha of strategy vs benchmark."""
    ra, rb = _align(strategy, benchmark)
    if len(ra) < 30:
        return None, None
    mb = st.mean(rb)
    var = sum((x - mb) ** 2 for x in rb) / len(rb)
    if var <= 0:
        return None, None
    ma = st.mean(ra)
    cov = sum((ra[i] - ma) * (rb[i] - mb) for i in range(len(ra))) / len(ra)
    beta = cov / var
    rf_d = rf_annual / TRADING_DAYS
    alpha_d = (ma - rf_d) - beta * (mb - rf_d)
    return beta, (1 + alpha_d) ** TRADING_DAYS - 1


def max_drawdown(curve) -> float:
    peak, mdd = curve[0][1], 0.0
    for _, v in curve:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1)
    return mdd


def tearsheet(curve, benchmark, trades=None, label="", rf_annual=0.02) -> dict:
    """The full row: period, days, trades, return, WR, per-trade Sharpe, PF,
    drawdown, annualised Sharpe, beta, annualised alpha, and benchmark return."""
    rets = _rets(curve)
    days = (curve[-1][0] - curve[0][0]).days
    yrs = days / 365.25 if days else 0
    total = curve[-1][1] / curve[0][1] - 1
    sd = st.pstdev(rets) if len(rets) > 1 else 0.0
    ann_sharpe = (((st.mean(rets) - rf_annual / TRADING_DAYS) / sd)
                  * math.sqrt(TRADING_DAYS)) if sd > 0 else 0.0
    b, a = beta_alpha(curve, benchmark, rf_annual)
    bench_total = benchmark[-1][1] / benchmark[0][1] - 1 if benchmark else None

    n = wr = pf = spt = None
    if trades:
        pnl = [t.pnl for t in trades]
        n = len(pnl)
        wins = [p for p in pnl if p > 0]
        losses = [p for p in pnl if p <= 0]
        wr = len(wins) / n
        pf = (sum(wins) / abs(sum(losses))) if losses and sum(losses) else None
        # per-trade Sharpe: mean/sd of trade returns on capital at risk
        tr = [getattr(t, "return_on_premium", None) for t in trades]
        if any(x is None for x in tr):
            base = st.mean([abs(p) for p in pnl]) or 1.0
            tr = [p / base for p in pnl]
        s = st.pstdev(tr) if len(tr) > 1 else 0.0
        spt = (st.mean(tr) / s) if s > 0 else 0.0

    return {
        "label": label,
        "start": curve[0][0], "end": curve[-1][0], "days": days,
        "trades": n, "total_return": total,
        "cagr": ((curve[-1][1] / curve[0][1]) ** (1 / yrs) - 1) if yrs > 0 else 0.0,
        "win_rate": wr, "sharpe_per_trade": spt, "profit_factor": pf,
        "max_drawdown": max_drawdown(curve), "ann_sharpe": ann_sharpe,
        "ann_vol": sd * math.sqrt(TRADING_DAYS),
        "beta": b, "alpha_ann": a, "benchmark_return": bench_total,
    }


def render(rows: list[dict], title: str = "") -> str:
    """Render tearsheet rows as a fixed-width table."""
    h = (f"{'Period':<26}{'Days':>6}{'Trades':>7}{'Return':>9}{'WR':>7}"
         f"{'Sh(pt)':>8}{'PF':>7}{'DD':>8}{'AnnSh':>7}{'Beta':>7}"
         f"{'Alpha(a)':>10}{'SPY':>9}")
    out = ([title, "=" * len(h)] if title else []) + [h, "-" * len(h)]
    for r in rows:
        def f(v, spec, dash="—"):
            return dash.rjust(len(format(0, spec))) if v is None else format(v, spec)
        out.append(
            f"{r['label']:<26}{r['days']:>6}"
            f"{(r['trades'] if r['trades'] is not None else 0):>7}"
            f"{r['total_return']:>+9.1%}{f(r['win_rate'], '>7.1%')}"
            f"{f(r['sharpe_per_trade'], '>8.3f')}{f(r['profit_factor'], '>7.2f')}"
            f"{r['max_drawdown']:>8.1%}{r['ann_sharpe']:>7.2f}"
            f"{f(r['beta'], '>7.2f')}{f(r['alpha_ann'], '>+10.1%')}"
            f"{f(r['benchmark_return'], '>+9.1%')}")
    return "\n".join(out)
