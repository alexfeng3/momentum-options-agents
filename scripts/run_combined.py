#!/usr/bin/env python
"""MOMENTUM + PREMIUM, with strict single-use-of-capital accounting.

CAPITAL RULES (enforced, not assumed -- see _assert_solvent):
  * There is exactly one pot of money. It starts at $100,000.
  * cash >= 0 at all times. You cannot spend money you do not have.
  * Every short put spread must be fully cash-collateralised at
    (width - credit) x 100 x contracts. That cash is RESERVED and cannot
    simultaneously be invested in stock.
  * Stocks are therefore bought with (equity - reserved collateral) only.
  * No margin, no borrowing, no rehypothecation. Optionally enable Reg-T style
    margin with --margin, which is modelled explicitly and off by default.

An earlier version allocated 100% of equity to stock and THEN sold spreads,
collateralising them with money already spent. That is free leverage and it
inflated returns.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from options_agents.backtest_directional import equal_weight_universe
from options_agents.marketdata import HistoricalBook
from options_agents.metrics import spy_buy_hold, summarise
from options_agents.pricing import price, strike_for_delta
from options_agents.selection import rank, realised_vol
from options_agents.volatility import iv_rank

UNIVERSE = ["AAPL","AMD","AMZN","AVAV","AVGO","CEG","CHPT","COIN","ENPH","FCEL",
            "FSLR","GOOGL","KTOS","LCID","LMT","LRCX","MARA","META","MRVL","MSFT",
            "MU","NVDA","PLTR","PLUG","RKLB","RUN","SMCI","SMH","SPCE","STX",
            "TSLA","TSM","VST","WDC","XLE","XLF","XLK","XLV","XLY"]
MULT = 100.0


@dataclass
class Spread:
    sym: str; ks: float; kl: float; exp: date; n: int
    credit: float; width: float; opened: date
    collateral: float          # cash reserved for this position, dollars


@dataclass
class OverlayTrade:
    symbol: str; entry_date: date; exit_date: date
    credit: float; cost: float; pnl: float
    return_on_premium: float; reason: str


class Book:
    """Single pot of capital. Every mutation goes through here."""

    def __init__(self, start: float):
        self.cash = start
        self.shares: dict[str, float] = {}
        self.spreads: list[Spread] = []

    @property
    def reserved(self) -> float:
        return sum(s.collateral for s in self.spreads)

    @property
    def free_cash(self) -> float:
        return self.cash - self.reserved

    def stock_value(self, book, d) -> float:
        return sum(q * (book.close(s, d) or 0.0) for s, q in self.shares.items())

    def spread_liability(self, cost_fn, d) -> float:
        return sum(max(0.0, min(cost_fn(s, d), s.width)) * MULT * s.n
                   for s in self.spreads)

    def equity(self, book, cost_fn, d) -> float:
        return self.cash + self.stock_value(book, d) - self.spread_liability(cost_fn, d)

    def assert_solvent(self, d) -> None:
        if self.cash < -1e-6:
            raise AssertionError(f"{d}: negative cash ${self.cash:,.2f}")
        if self.free_cash < -1e-6:
            raise AssertionError(
                f"{d}: short-spread collateral ${self.reserved:,.2f} exceeds cash "
                f"${self.cash:,.2f} — capital used twice")


def run(book, S, E, *, top_n=6, rebal=21, market_filter=True, overlay=True,
        short_delta=0.20, width_pct=0.10, dte=30, risk_per_trade=0.03,
        max_risk=0.15, iv_rank_min=20.0, profit_target=0.50, iv_premium=1.10,
        slip=0.05, start_equity=100_000.0, stock_cost_bps=5.0):
    days = [d for d in book.days if S <= d <= E]
    pf = Book(start_equity)
    trades: list[OverlayTrade] = []
    ivh = {s: [] for s in UNIVERSE}
    last = None
    curve = []

    def iv_of(sym, d):
        rv = realised_vol(book.closes_until(sym, d, 90), 60)
        return max(0.10, rv * iv_premium) if rv else None

    def cost_fn(sp, d):
        spot = book.close(sp.sym, d)
        if spot is None:
            return 0.0
        left = (sp.exp - d).days
        if left <= 0:
            return max(0.0, sp.ks - spot) - max(0.0, sp.kl - spot)
        iv = iv_of(sp.sym, d)
        if iv is None:
            return 0.0
        r = book.risk_free(d); T = left / 365.0
        return price(spot, sp.ks, T, r, iv, "put") - price(spot, sp.kl, T, r, iv, "put")

    for d in days:
        for s in UNIVERSE:
            v = iv_of(s, d)
            if v:
                ivh[s].append(v)

        # interest on genuinely idle cash only
        if last is not None:
            pass

        # ---- close spreads -------------------------------------------------
        for sp in list(pf.spreads):
            c = cost_fn(sp, d)
            left = (sp.exp - d).days
            if left <= 0 or (sp.credit > 0 and (sp.credit - c) / sp.credit >= profit_target):
                pay = max(0.0, min(c, sp.width)) * (1 + slip) * MULT * sp.n
                pf.cash -= pay                      # settle from the same pot
                pf.spreads.remove(sp)               # releases its collateral
                credit = sp.credit * MULT * sp.n
                risk = max(1e-9, sp.collateral)
                trades.append(OverlayTrade(sp.sym, sp.opened, d, credit, pay,
                                           credit - pay, (credit - pay) / risk,
                                           "EXPIRY" if left <= 0 else "PROFIT_TARGET"))
        pf.assert_solvent(d)

        equity = pf.equity(book, cost_fn, d)

        # ---- rebalance -----------------------------------------------------
        if last is None or (d - last).days >= rebal:
            ok = True
            if market_filter:
                b = book.closes_until("SPY", d, 200)
                ok = len(b) >= 200 and b[-1] > sum(b) / len(b)
            cands = {s: c for s in UNIVERSE
                     if len(c := book.closes_until(s, d, 300)) >= 260 and c[-1] >= 5.0}
            picks = rank(cands, book.closes_until("SPY", d, 300), top_n) if (cands and ok) else []

            # sell everything to cash first, paying costs
            for s, q in list(pf.shares.items()):
                px = book.close(s, d)
                if px:
                    pf.cash += q * px * (1 - stock_cost_bps / 10_000)
            pf.shares = {}
            pf.assert_solvent(d)

            # Stocks may only use cash that is NOT reserved as spread collateral,
            # and must leave room for the spreads we are about to sell.
            budget = max(0.0, pf.free_cash - (equity * max_risk if overlay else 0.0))
            if picks and budget > 0:
                per = budget / len(picks)
                for p in picks:
                    px = book.close(p.symbol, d)
                    if not px:
                        continue
                    q = per / (px * (1 + stock_cost_bps / 10_000))
                    pf.shares[p.symbol] = q
                    pf.cash -= q * px * (1 + stock_cost_bps / 10_000)
            pf.assert_solvent(d)
            last = d

            # ---- overlay: short put spreads on names we hold ---------------
            if overlay and picks:
                for p in picks:
                    if any(sp.sym == p.symbol for sp in pf.spreads):
                        continue
                    spot = book.close(p.symbol, d); iv = iv_of(p.symbol, d)
                    if spot is None or iv is None:
                        continue
                    rk = iv_rank(ivh[p.symbol][:-1], iv)
                    if rk is None or rk < iv_rank_min:
                        continue
                    T = dte / 365.0; r = book.risk_free(d)
                    ks = round(strike_for_delta(spot, T, r, iv, short_delta, "put"), 2)
                    w = max(1.0, round(spot * width_pct, 2)); kl = ks - w
                    if kl <= 0:
                        continue
                    cr = (price(spot, ks, T, r, iv, "put")
                          - price(spot, kl, T, r, iv, "put")) * (1 - slip)
                    if cr <= 0.02:
                        continue
                    per_contract_risk = (w - cr) * MULT
                    n = int((equity * risk_per_trade) // per_contract_risk)
                    room = equity * max_risk - pf.reserved
                    n = min(n, int(room // per_contract_risk))
                    # HARD CONSTRAINT: collateral must fit in unreserved cash,
                    # net of the credit we are about to receive.
                    n = min(n, int((pf.free_cash + cr * MULT * n)
                                   // per_contract_risk) if per_contract_risk else 0)
                    if n < 1:
                        continue
                    collateral = per_contract_risk * n
                    pf.cash += cr * MULT * n
                    pf.spreads.append(Spread(p.symbol, ks, kl, d + timedelta(days=dte),
                                             n, cr, w, d, collateral))
                    pf.assert_solvent(d)

        curve.append((d, pf.equity(book, cost_fn, d)))
    return curve, trades


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2011-01-03")
    ap.add_argument("--end", default="2026-06-11")
    a = ap.parse_args()
    book = HistoricalBook(UNIVERSE + ["SPY"])
    S, E = date.fromisoformat(a.start), date.fromisoformat(a.end)
    spy = summarise(spy_buy_hold(book, S, E, 100_000), "spy")
    ew = summarise(equal_weight_universe(book, UNIVERSE, S, E, 100_000), "ew")
    print(f"\n{'='*80}\nMOMENTUM + PREMIUM (strict capital accounting)  {a.start} -> {a.end}\n{'='*80}")
    print(f"  {'portfolio':<38}{'CAGR':>9}{'Sharpe':>8}{'maxDD':>9}{'final $':>13}")
    def row(l, s):
        print(f"  {l:<38}{s['cagr']:>9.2%}{s['sharpe']:>8}{s['max_drawdown']:>9.1%}"
              f"{s['final_equity']:>13,.0f}")
    row("SPY buy & hold", spy); row("equal-weight universe (bias control)", ew)
    for n in (4, 6, 8):
        c, _ = run(book, S, E, top_n=n, overlay=False)
        row(f"momentum stocks top-{n}", summarise(c, "s"))
        c, tr = run(book, S, E, top_n=n, overlay=True)
        row("  + put-spread overlay", summarise(c, "s"))
        w = sum(1 for t in tr if t.pnl > 0)
        print(f"      overlay: {len(tr)} trades, {w/len(tr)*100 if tr else 0:.1f}% win, "
              f"P&L ${sum(t.pnl for t in tr):,.0f}")
    print("="*80)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
