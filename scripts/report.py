#!/usr/bin/env python
"""Full backtest tearsheet across a train / validate / test split."""
from __future__ import annotations
import sys
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from options_agents.backtest_directional import equal_weight_universe
from options_agents.backtest_pead import PeadBacktest, PeadConfig
from options_agents.marketdata import HistoricalBook
from options_agents.metrics import spy_buy_hold
from options_agents.tearsheet import render, tearsheet
import run_combined as rc

PEAD_U = ["AAPL","AMD","AMZN","AVAV","AVGO","CEG","CHPT","COIN","FCEL","FSLR",
          "GOOGL","KTOS","LCID","LMT","LRCX","MARA","META","MRVL","MSFT","MU",
          "NVDA","PLTR","PLUG","RKLB","RUN","SMCI","SPCE","STX","TSLA","VST","WDC"]
SPLITS = [("Train (2011-2018)",  date(2011,1,3),  date(2018,12,31)),
          ("Validate (2019-2021)", date(2019,1,1), date(2021,12,31)),
          ("Test (2022-2026)",   date(2022,1,3),  date(2026,6,11))]


def main():
    book = HistoricalBook(sorted(set(rc.UNIVERSE + PEAD_U + ["SPY"])))
    for name, S, E in SPLITS:
        spy = spy_buy_hold(book, S, E, 100_000)
        if not spy:
            continue
        ew = equal_weight_universe(book, rc.UNIVERSE, S, E, 100_000)
        rows = [tearsheet(spy, spy, None, "SPY buy & hold"),
                tearsheet(ew, spy, None, "Equal-wt universe*")]

        c, _ = rc.run(book, S, E, top_n=6, overlay=False)
        rows.append(tearsheet(c, spy, None, "Momentum top-6"))
        c, tr = rc.run(book, S, E, top_n=6, overlay=True)
        rows.append(tearsheet(c, spy, tr, "Momentum + spreads"))

        for ov, lbl in ((False, "PEAD stocks"), (True, "PEAD + spreads")):
            bt = PeadBacktest(PeadConfig(universe=tuple(PEAD_U), overlay=ov), book)
            r = bt.run(S, E)
            if r["equity_curve"]:
                rows.append(tearsheet(r["equity_curve"], spy, r["trades"], lbl))
        print("\n" + render(rows, f"{name}   {S} -> {E}"))
    print("\n  * Equal-weight universe is the SURVIVORSHIP-BIAS CONTROL: the same 39")
    print("    hindsight-chosen names, held equally. Beating SPY is mostly this;")
    print("    only the margin over THIS row is attributable to the strategy.")
    print("  Beta / Alpha are measured against SPY. Sh(pt) = per-trade Sharpe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
