#!/usr/bin/env python
"""Does the momentum alpha survive on a universe that was NOT hand-picked?

Compares the original 39 hindsight-chosen names against a 951-name universe built
by a mechanical liquidity rule from Alpaca (including delisted names), over the
same window. If the edge is real it should survive; if it was universe selection,
it will collapse.
"""
from __future__ import annotations
import sys
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from options_agents.marketdata import HistoricalBook
from options_agents.metrics import spy_buy_hold, summarise
from options_agents.selection import rank
from options_agents.tearsheet import render, tearsheet

ROOT = Path(__file__).resolve().parents[1]
BROAD = ROOT / "data" / "broad"


def momentum(book, syms, S, E, top_n=6, rebal=21, market_filter=True,
             start_equity=100_000.0, cost_bps=5.0):
    days = [d for d in book.days if S <= d <= E]
    cash, hold, last, curve = start_equity, {}, None, []
    for d in days:
        val = cash + sum(q * (book.close(s, d) or 0) for s, q in hold.items())
        if last is None or (d - last).days >= rebal:
            ok = True
            if market_filter:
                b = book.closes_until("SPY", d, 200)
                ok = len(b) >= 200 and b[-1] > sum(b) / len(b)
            for s, q in list(hold.items()):
                px = book.close(s, d)
                if px:
                    cash += q * px * (1 - cost_bps / 10_000)
                else:                      # delisted mid-hold: mark to zero
                    pass
            hold = {}
            cands = {}
            for s in syms:
                c = book.closes_until(s, d, 300)
                if len(c) >= 260 and c[-1] >= 5.0 and book.close(s, d):
                    cands[s] = c
            picks = rank(cands, book.closes_until("SPY", d, 300), top_n) if (cands and ok) else []
            if picks:
                per = cash / len(picks)
                for p in picks:
                    px = book.close(p.symbol, d)
                    q = per / (px * (1 + cost_bps / 10_000))
                    hold[p.symbol] = q
                    cash -= q * px * (1 + cost_bps / 10_000)
            last = d
        curve.append((d, val))
    return curve


def equal_weight(book, syms, S, E, eq=100_000.0, rebal=63):
    days = [d for d in book.days if S <= d <= E]
    hold, last, val, curve = {}, None, eq, []
    for d in days:
        if hold:
            val = sum(q * (book.close(s, d) or 0) for s, q in hold.items())
        if last is None or (d - last).days >= rebal:
            live = [s for s in syms if book.close(s, d)]
            if live:
                per = val / len(live)
                hold = {s: per / book.close(s, d) for s in live}
            last = d
        curve.append((d, val))
    return curve


def main():
    S, E = date(2021, 9, 1), date(2026, 8, 27)
    broad = sorted(p.stem for p in BROAD.glob("*.csv"))
    print(f"broad universe: {len(broad)} symbols")
    bb = HistoricalBook(broad + ["SPY"], data_dir=BROAD)
    narrow = ["AAPL","AMD","AMZN","AVAV","AVGO","CEG","CHPT","COIN","ENPH","FCEL",
              "FSLR","GOOGL","KTOS","LCID","LMT","LRCX","MARA","META","MRVL","MSFT",
              "MU","NVDA","PLTR","PLUG","RKLB","RUN","SMCI","SMH","SPCE","STX",
              "TSLA","TSM","VST","WDC","XLE","XLF","XLK","XLV","XLY"]
    narrow = [s for s in narrow if s in set(broad)]
    spy = spy_buy_hold(bb, S, E, 100_000)
    rows = [tearsheet(spy, spy, None, "SPY buy & hold"),
            tearsheet(equal_weight(bb, broad, S, E), spy, None, f"EW broad ({len(broad)})"),
            tearsheet(equal_weight(bb, narrow, S, E), spy, None, f"EW narrow ({len(narrow)})")]
    for n in (6, 10, 20):
        rows.append(tearsheet(momentum(bb, broad, S, E, top_n=n), spy, None,
                              f"Momentum top-{n} BROAD"))
    rows.append(tearsheet(momentum(bb, narrow, S, E, top_n=6), spy, None,
                          "Momentum top-6 narrow"))
    print("\n" + render(rows, f"UNIVERSE TEST  {S} -> {E}  (Alpaca IEX daily)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
