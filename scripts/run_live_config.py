#!/usr/bin/env python
"""Backtest the ACTUAL live configuration: all three sleeves in one account.

Every other backtest in this repo measures ONE sleeve so its contribution can be
attributed. None of them is the deployed system. This runs what the agents
actually run:

    momentum core (core_weight of equity, top_n names)
  + PEAD sleeve   (pead_weight per qualifying SEC earnings event)
  + put-spread overlay on names either sleeve holds (max_overlay_risk collateral)

sharing ONE pot of capital, with the same single-use rules the live risk agent
enforces.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from options_agents.backtest_directional import equal_weight_universe
from options_agents.earnings import build_events
from options_agents.marketdata import HistoricalBook
from options_agents.metrics import spy_buy_hold
from options_agents.portfolio import CONTRACT_MULT, Portfolio
from options_agents.pricing import price, strike_for_delta
from options_agents.selection import rank, realised_vol
from options_agents.tearsheet import render, tearsheet
from options_agents.volatility import iv_rank

UNIVERSE = ["AAPL","AMD","AMZN","AVAV","AVGO","CEG","CHPT","COIN","ENPH","FCEL",
            "FSLR","GOOGL","KTOS","LCID","LMT","LRCX","MARA","META","MRVL","MSFT",
            "MU","NVDA","PLTR","PLUG","RKLB","RUN","SMCI","SMH","SPCE","STX",
            "TSLA","TSM","VST","WDC","XLE","XLF","XLK","XLV","XLY"]
PEAD_U = ["AAPL","AMD","AMZN","AVAV","AVGO","CEG","CHPT","COIN","FCEL","FSLR",
          "GOOGL","KTOS","LCID","LMT","LRCX","MARA","META","MRVL","MSFT","MU",
          "NVDA","PLTR","PLUG","RKLB","RUN","SMCI","SPCE","STX","TSLA","VST","WDC"]


@dataclass
class Sp:
    sym: str; ks: float; kl: float; exp: date; n: int
    credit: float; width: float; opened: date; collateral: float


@dataclass
class Tr:
    pnl: float
    return_on_premium: float


@dataclass
class Pead:
    sym: str; entry: date; expiry: date


def run(book, S, E, *, top_n=6, core_weight=0.80, pead_weight=0.05,
        rebalance_days=21, market_filter=True, overlay=True,
        short_delta=0.20, width_pct=0.10, max_width=25.0, dte=30,
        iv_rank_min=20.0, risk_per_spread=0.03, max_overlay_risk=0.15,
        profit_target=0.50, iv_premium=1.10, slip=0.05, cost_bps=5.0,
        cash_floor=0.02, sue_min=0.5, gap_min=0.01, vol_ratio_min=1.3,
        pead_hold=40, pead_stop=-0.15, start=100_000.0):
    days = [d for d in book.days if S <= d <= E]
    pf = Portfolio(cash=start)
    spreads: list[Sp] = []
    peads: list[Pead] = []
    trades: list[Tr] = []
    ivh = {s: [] for s in UNIVERSE}
    last = None
    curve = []

    events: dict[date, list] = {}
    for s in PEAD_U:
        for e in build_events(s, book):
            if e.announce_date and e.sue is not None and e.gap_pct is not None:
                events.setdefault(e.announce_date, []).append(e)

    def iv_of(sym, d):
        rv = realised_vol(book.closes_until(sym, d, 90), 60)
        return max(0.10, rv * iv_premium) if rv else None

    def cost(sp, d):
        spot = book.last_price(sp.sym, d)
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

    def liability(d):
        return sum(max(0.0, min(cost(s, d), s.width)) * CONTRACT_MULT * s.n
                   for s in spreads)

    def prices(d):
        return {s: (book.last_price(s, d) or 0.0) for s in pf.shares}

    def sell_spread(sym, d, equity):
        if not overlay or any(s.sym == sym for s in spreads):
            return
        spot = book.close(sym, d); iv = iv_of(sym, d)
        if spot is None or iv is None:
            return
        rk = iv_rank(ivh.get(sym, [])[:-1], iv)
        if rk is None or rk < iv_rank_min:
            return
        T = dte / 365.0; r = book.risk_free(d)
        ks = round(strike_for_delta(spot, T, r, iv, short_delta, "put"), 2)
        w = min(max(1.0, round(spot * width_pct, 2)), max_width)
        kl = round(ks - w, 2)
        if kl <= 0:
            return
        cr = (price(spot, ks, T, r, iv, "put")
              - price(spot, kl, T, r, iv, "put")) * (1 - slip)
        if cr <= 0.05:
            return
        # include exit slippage in the reservation (see strategy.py)
        per = (w * (1 + slip) - cr) * CONTRACT_MULT
        n = int((equity * risk_per_spread) // per)
        n = min(n, int(max(0.0, equity * max_overlay_risk - pf.reserved) // per))
        n = min(n, pf.max_contracts(per, cr * CONTRACT_MULT))
        if n < 1:
            return
        pf.open_short_spread(f"{sym}-sp", cr * CONTRACT_MULT * n, per * n)
        spreads.append(Sp(sym, ks, kl, d + timedelta(days=dte), n, cr, w, d, per * n))

    def raise_cash(need: float, d: date) -> None:
        """Liquidate stock, largest holding first, until `need` is available.

        A spread closing at a loss draws cash that the account may have fully
        deployed into stock. A real broker resolves that with a margin call and
        forced liquidation; ignoring it lets the backtest run on money it does
        not have. Modelling it here means losses are funded the way they would
        be live -- by selling the book at the worst possible moment.
        """
        for _ in range(len(pf.shares) + 1):
            if pf.cash >= need - 1e-6:
                return
            if not pf.shares:
                return
            sym = max(pf.shares, key=lambda s: pf.shares[s] * (book.last_price(s, d) or 0))
            px = book.last_price(sym, d)
            if not px:
                pf.shares.pop(sym, None)
                continue
            short = need - pf.cash
            qty = min(pf.shares[sym], short / (px * (1 - cost_bps / 10_000)) * 1.01)
            if qty <= 0:
                return
            pf.sell_stock(sym, qty, px, cost_bps)
            forced[0] += 1

    forced = [0]
    prev = None
    for d in days:
        for s in UNIVERSE:
            v = iv_of(s, d)
            if v:
                ivh[s].append(v)
        if prev is not None:
            pf.cash += max(0.0, pf.free_cash) * book.risk_free(d) * ((d - prev).days / 365.0)
        prev = d

        # --- close spreads
        for sp in list(spreads):
            c = cost(sp, d)
            left = (sp.exp - d).days
            if left <= 0 or (sp.credit > 0 and (sp.credit - c) / sp.credit >= profit_target):
                pay = max(0.0, min(c, sp.width)) * (1 + slip) * CONTRACT_MULT * sp.n
                # fund the settlement before releasing the reservation
                raise_cash(pay + pf.reserved - sp.collateral, d)
                pf.close_short_spread(f"{sp.sym}-sp", pay)
                spreads.remove(sp)
                cr = sp.credit * CONTRACT_MULT * sp.n
                trades.append(Tr(cr - pay, (cr - pay) / max(1e-9, sp.collateral)))

        # --- PEAD exits
        for p in list(peads):
            px = book.last_price(p.sym, d)
            if px is None:
                continue
            if d >= p.expiry:
                if p.sym in pf.shares:
                    pf.sell_stock(p.sym, pf.shares[p.sym], px, cost_bps)
                peads.remove(p)

        equity = pf.equity(prices(d), liability(d))

        # --- monthly core rebalance
        if last is None or (d - last).days >= rebalance_days:
            ok = True
            if market_filter:
                b = book.closes_until("SPY", d, 200)
                ok = len(b) >= 200 and b[-1] > sum(b) / len(b)
            pead_syms = {p.sym for p in peads}
            for s in list(pf.shares):
                if s in pead_syms:
                    continue
                px = book.last_price(s, d)
                if px:
                    pf.sell_stock(s, pf.shares[s], px, cost_bps)
            cands = {}
            for s in UNIVERSE:
                if book.is_delisted(s, d):
                    continue
                c = book.closes_until(s, d, 300)
                if len(c) >= 260 and c[-1] >= 5.0 and book.close(s, d):
                    cands[s] = c
            picks = rank(cands, book.closes_until("SPY", d, 300), top_n) if (cands and ok) else []
            equity = pf.equity(prices(d), liability(d))
            if picks:
                budget = max(0.0, pf.free_cash - equity * (max_overlay_risk + cash_floor))
                per = budget / len(picks)
                for p in picks:
                    px = book.close(p.symbol, d)
                    if not px or per <= 0:
                        continue
                    q = min(per, pf.free_cash) / (px * (1 + cost_bps / 10_000))
                    if q > 0:
                        pf.buy_stock(p.symbol, q, px, cost_bps)
                for p in picks:
                    sell_spread(p.symbol, d, equity)
            last = d

        # --- PEAD entries (day after a qualifying announcement)
        yday = [x for x in book.days if x < d]
        if yday and (not market_filter or ok if last == d else True):
            for e in events.get(yday[-1], []):
                if len(peads) >= 8 or e.symbol in pf.shares:
                    continue
                if e.sue < sue_min or e.gap_pct < gap_min:
                    continue
                if (e.vol_ratio or 0) < vol_ratio_min:
                    continue
                px = book.close(e.symbol, d)
                if px is None or px < 5:
                    continue
                eq = pf.equity(prices(d), liability(d))
                alloc = min(eq * pead_weight,
                            max(0.0, pf.free_cash - eq * cash_floor))
                if alloc < 100:
                    continue
                pf.buy_stock(e.symbol, alloc / px, px, cost_bps)
                peads.append(Pead(e.symbol, d, d + timedelta(days=pead_hold)))
                sell_spread(e.symbol, d, eq)

        curve.append((d, pf.equity(prices(d), liability(d))))
    return curve, trades, forced[0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2011-01-03")
    ap.add_argument("--end", default="2026-06-11")
    a = ap.parse_args()
    book = HistoricalBook(sorted(set(UNIVERSE + PEAD_U + ["SPY"])))
    splits = [("Train (2011-2018)", date(2011, 1, 3), date(2018, 12, 31)),
              ("Validate (2019-2021)", date(2019, 1, 1), date(2021, 12, 31)),
              ("Test (2022-2026)", date(2022, 1, 3), date(2026, 6, 11)),
              ("FULL (2011-2026)", date(2011, 1, 3), date(2026, 6, 11))]
    rows = []
    for name, S, E in splits:
        spy = spy_buy_hold(book, S, E, 100_000)
        c, tr, forced = run(book, S, E)
        rows.append(tearsheet(c, spy, tr, name))
        if forced:
            print(f"  [{name}] {forced} forced stock liquidations to fund spread losses")
        rows.append(tearsheet(spy, spy, None, "   └ SPY benchmark"))
    print("\n" + render(rows, "LIVE CONFIGURATION — all three sleeves, one pot of capital"))
    print("\n  momentum core (80%) + PEAD sleeve (5%/event) + 20d put-spread overlay (15% collateral)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
