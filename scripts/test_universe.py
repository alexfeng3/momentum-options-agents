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
from options_agents.selection import rank, realised_vol
from options_agents.tearsheet import render, tearsheet

ROOT = Path(__file__).resolve().parents[1]
BROAD = ROOT / "data" / "broad"


def momentum(book, syms, S, E, top_n=6, rebal=21, market_filter=True,
             start_equity=100_000.0, cost_bps=5.0, min_px=5.0,
             max_vol=None, min_dv=0.0):
    """Delisting is handled at LAST TRADED PRICE, not zero.

    Marking a delisted holding to zero books total losses on acquisitions
    (ATVI, VMW, XLNX, TWTR all just stop having bars) and manufactured a fake
    -76% drawdown in an earlier version of this script.
    """
    days = [d for d in book.days if S <= d <= E]
    cash, hold, last, curve = start_equity, {}, None, []
    for d in days:
        val = cash + sum(q * (book.last_price(s, d) or 0) for s, q in hold.items())
        if last is None or (d - last).days >= rebal:
            ok = True
            if market_filter:
                b = book.closes_until("SPY", d, 200)
                ok = len(b) >= 200 and b[-1] > sum(b) / len(b)
            for s, q in list(hold.items()):
                px = book.last_price(s, d)
                if px:
                    cash += q * px * (1 - cost_bps / 10_000)
            hold = {}
            cands = {}
            for s in syms:
                if book.is_delisted(s, d):
                    continue
                c = book.closes_until(s, d, 300)
                if len(c) < 260 or c[-1] < min_px or not book.close(s, d):
                    continue
                if max_vol is not None:
                    rv = realised_vol(c, 60)
                    if rv is None or rv > max_vol:
                        continue
                if min_dv > 0:
                    rec = book.px[s]
                    ds = [x for x in rec if x <= d][-20:]
                    adv = sum(rec[x]["close"] * rec[x].get("volume", 0)
                              for x in ds) / max(1, len(ds))
                    if adv < min_dv:
                        continue
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
    """Equal-weight buy-and-hold: the survivorship-bias control.

    Delisted names are carried at LAST TRADED PRICE. Marking them to zero
    understates the benchmark, which flatters every strategy measured against it.
    """
    days = [d for d in book.days if S <= d <= E]
    hold, last, val, curve = {}, None, eq, []
    for d in days:
        if hold:
            val = sum(q * (book.last_price(s, d) or 0) for s, q in hold.items())
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
    rows.append(tearsheet(momentum(bb, narrow, S, E, top_n=6), spy, None,
                          "Momentum top-6 NARROW*"))
    rows.append(tearsheet(momentum(bb, broad, S, E, top_n=6), spy, None,
                          "Momentum top-6 broad"))
    rows.append(tearsheet(momentum(bb, broad, S, E, top_n=10, min_px=10,
                                   max_vol=0.60, min_dv=50e6), spy, None,
                          "top-10 $50M ADV vol<=60%"))
    rows.append(tearsheet(momentum(bb, broad, S, E, top_n=10, min_px=10,
                                   max_vol=0.50, min_dv=100e6), spy, None,
                          "top-10 $100M ADV vol<=50%"))
    print("\n" + render(rows, f"UNIVERSE TEST  {S} -> {E}  (Alpaca IEX daily)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
