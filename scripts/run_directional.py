#!/usr/bin/env python
"""Momentum-selected long-call strategy vs SPY *and* vs the equal-weight universe."""
from __future__ import annotations
import argparse, sys
from datetime import date
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from options_agents.backtest_directional import (DirectionalBacktest,
                                                 DirectionalConfig,
                                                 equal_weight_universe)
from options_agents.marketdata import HistoricalBook
from options_agents.metrics import spy_buy_hold, summarise

UNIVERSE = ["AAPL","AMD","AMZN","AVAV","AVGO","CEG","CHPT","COIN","ENPH","FCEL",
            "FSLR","GOOGL","KTOS","LCID","LMT","LRCX","MARA","META","MRVL","MSFT",
            "MU","NVDA","PLTR","PLUG","RKLB","RUN","SMCI","SMH","SPCE","STX",
            "TSLA","TSM","VST","WDC","XLE","XLF","XLK","XLV","XLY"]
BAR = "="*78

def stats(bt_curve, book, cfg, trades, label):
    spy = spy_buy_hold(book, bt_curve[0][0], bt_curve[-1][0], cfg.starting_equity)
    ew = equal_weight_universe(book, list(cfg.universe), bt_curve[0][0],
                               bt_curve[-1][0], cfg.starting_equity)
    s, b, e = summarise(bt_curve,"s"), summarise(spy,"spy"), summarise(ew,"ew")
    print(f"\n{label}  ({s['start']} -> {s['end']})")
    print(f"  {'':<16}{'STRATEGY':>13}{'SPY':>12}{'EW UNIVERSE':>14}")
    for k, pct in (("cagr",1),("total_return",1),("ann_vol",1),("sharpe",0),
                   ("max_drawdown",1),("calmar",0)):
        f = (lambda x: f"{x:>12.2%}" if pct and isinstance(x,float) else f"{str(x):>13}")
        g = (lambda x: f"{x:>11.2%}" if pct and isinstance(x,float) else f"{str(x):>12}")
        h = (lambda x: f"{x:>13.2%}" if pct and isinstance(x,float) else f"{str(x):>14}")
        print(f"  {k:<16}{f(s[k])}{g(b[k])}{h(e[k])}")
    print(f"  {'final equity':<16}{s['final_equity']:>13,.0f}{b['final_equity']:>12,.0f}"
          f"{e['final_equity']:>14,.0f}")
    print(f"  vs SPY: {s['cagr']-b['cagr']:+.2%} CAGR   |   "
          f"vs EQUAL-WEIGHT UNIVERSE: {s['cagr']-e['cagr']:+.2%} CAGR  <- the real test")
    if trades:
        pnl=[t.pnl for t in trades]; wins=[p for p in pnl if p>0]
        losses=[p for p in pnl if p<=0]
        best=max(trades,key=lambda t:t.return_on_premium)
        print(f"  trades={len(trades)} win={len(wins)/len(trades):.1%} "
              f"PF={sum(wins)/abs(sum(losses)):.2f} " if losses and sum(losses) else "")
        print(f"  trades={len(trades)}  win_rate={len(wins)/len(trades):.1%}  "
              f"avg_win=${sum(wins)/len(wins) if wins else 0:,.0f}  "
              f"avg_loss=${sum(losses)/len(losses) if losses else 0:,.0f}")
        print(f"  best trade: {best.symbol} {best.entry_date} -> {best.exit_date} "
              f"{best.return_on_premium:+.0%} on premium")
        by={}
        for t in trades: by.setdefault(t.reason,[0,0.0]); by[t.reason][0]+=1; by[t.reason][1]+=t.pnl
        print("  exits: " + "  ".join(f"{k}:n={v[0]},pnl={v[1]:+,.0f}" for k,v in sorted(by.items())))
    return s,b,e

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--start", default="2011-01-03"); ap.add_argument("--end", default="2026-06-11")
    ap.add_argument("--delta", type=float, default=0.60)
    ap.add_argument("--dte", type=int, default=60)
    ap.add_argument("--premium-pct", type=float, default=0.04)
    ap.add_argument("--top-n", type=int, default=4)
    ap.add_argument("--profit-target", type=float, default=1.00)
    ap.add_argument("--stop-loss", type=float, default=-0.50)
    ap.add_argument("--no-market-filter", action="store_true")
    a=ap.parse_args()
    book=HistoricalBook(UNIVERSE+["SPY"])
    cfg=DirectionalConfig(universe=tuple(UNIVERSE), top_n=a.top_n, target_delta=a.delta,
        dte=a.dte, premium_pct=a.premium_pct, max_positions=a.top_n,
        profit_target=a.profit_target, stop_loss=a.stop_loss,
        market_filter=not a.no_market_filter)
    bt=DirectionalBacktest(cfg,book)
    r=bt.run(date.fromisoformat(a.start), date.fromisoformat(a.end))
    print(f"\n{BAR}\nMOMENTUM-SELECTED LONG CALLS   delta={a.delta} dte={a.dte} "
          f"prem={a.premium_pct:.0%} topN={a.top_n} pt={a.profit_target:+.0%} "
          f"stop={a.stop_loss:+.0%}\n{BAR}")
    stats(r["equity_curve"], book, cfg, r["trades"], "RESULT")
    if r["rejects"]: print(f"  rejects: {r['rejects']}")
    print(BAR)
    return 0
if __name__=="__main__": raise SystemExit(main())
