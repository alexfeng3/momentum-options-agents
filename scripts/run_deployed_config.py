#!/usr/bin/env python
"""Backtest what is actually deployed: momentum core only, rebalanced monthly.

The live agents run ONE sleeve (the options overlay and the PEAD sleeve are off):
the top 6 momentum names, 80% of equity, price >= $10, 60-day vol <= 60%, rebalanced
every 21 calendar days, cash when SPY is under its 200-day average.

This reuses the engine in scripts/test_universe.py (`momentum`), so the backtest
and the live agents follow the same calendar. It runs on the 951-name mechanical
universe, not the hand-picked 39, and prints:

  1. the tearsheet, with SPY and the equal-weight universe as controls, and
  2. the spread of total returns when the first rebalance is shifted by 0-20
     trading days. A monthly strategy's result depends on which day of the cycle
     it happens to start on; one start date is one sample.
"""
from __future__ import annotations

import argparse
import statistics as st
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from options_agents.marketdata import HistoricalBook
from options_agents.metrics import spy_buy_hold
from options_agents.strategy_config import LiveConfig
from options_agents.tearsheet import render, tearsheet
from test_universe import BROAD, equal_weight, momentum

S, E = date(2021, 9, 1), date(2026, 8, 27)
OFFSETS = range(0, 21)


def deployed(book, syms, start, end, cfg):
    """The deployed configuration, taken from LiveConfig so they cannot drift."""
    return momentum(book, syms, start, end, top_n=cfg.top_n, rebal=cfg.rebalance_days,
                    market_filter=cfg.market_filter, min_px=cfg.min_price,
                    max_vol=cfg.max_vol, invest=cfg.core_weight)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=str(BROAD),
                    help="daily-bar CSV cache (default data/broad)")
    a = ap.parse_args()
    data = Path(a.data_dir)
    cfg = LiveConfig()
    syms = sorted(p.stem for p in data.glob("*.csv"))
    book = HistoricalBook(syms + ["SPY"], data_dir=data)
    print(f"universe: {len(syms)} symbols in {data}")
    print(f"deployed filters: top {cfg.top_n}, {cfg.core_weight:.0%} invested, "
          f"price >= ${cfg.min_price:.0f}, 60d vol <= {cfg.max_vol:.0%}, "
          f"rebalance every {cfg.rebalance_days} days, SPY-200 regime filter")

    spy = spy_buy_hold(book, S, E, 100_000)
    rows = [tearsheet(spy, spy, None, "SPY buy & hold"),
            tearsheet(equal_weight(book, syms, S, E), spy, None,
                      f"EW universe ({len(syms)})"),
            tearsheet(deployed(book, syms, S, E, cfg), spy, None,
                      "DEPLOYED (offset 0)")]
    print("\n" + render(rows, f"DEPLOYED CONFIGURATION  {S} -> {E}  (Alpaca IEX daily)"))

    # Same end date, first rebalance k trading days later.
    days = [d for d in book.days if S <= d <= E]
    rets = []
    for k in OFFSETS:
        start = days[k]
        c = deployed(book, syms, start, E, cfg)
        rets.append((k, start, c[-1][1] / c[0][1] - 1))
    vals = [r for _, _, r in rets]
    print(f"\nFIRST REBALANCE SHIFTED BY 0-20 TRADING DAYS (end {E})")
    print(f"  {'offset':>6}  {'first rebalance':<16}{'total return':>13}")
    for k, d, r in rets:
        print(f"  {k:>6}  {d.isoformat():<16}{r:>+13.1%}")
    print(f"  min {min(vals):+.1%}   median {st.median(vals):+.1%}   "
          f"max {max(vals):+.1%}   (n={len(vals)})")
    print("\n  This is NOT the 39-name headline table in STRATEGY.md: that universe was "
          "hand-picked in 2026\n  and runs all three sleeves. This is the mechanical "
          "951-name universe, momentum core only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
