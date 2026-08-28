"""Command line for the momentum + options agent system.

    python -m options_agents.cli cycle              # dry run (default)
    python -m options_agents.cli cycle --execute    # submit to Alpaca PAPER
    python -m options_agents.cli status
    python -m options_agents.cli universe
"""
from __future__ import annotations

import argparse
import json
import sys

from .broker import AlpacaBroker, NotPaperTradingError
from .orchestrator import load_universe, run_cycle
from .strategy_config import LiveConfig

BAR = "=" * 78


def _print(res, cfg):
    print(f"\n{BAR}\nCYCLE {res['run_id']}  {res['as_of']}  "
          f"{'DRY RUN' if res['dry_run'] else 'PAPER EXECUTION'}  "
          f"market={'OPEN' if res['market_open'] else 'CLOSED'}  "
          f"regime={'RISK-ON' if res['spy_above_sma200'] else 'RISK-OFF (SPY<SMA200)'}\n{BAR}")

    snap = res["snapshot"]
    print(f"\nTOP MOMENTUM ({len(snap['ranked'])} scored from {len(cfg.universe)} names)")
    print(f"  {'sym':<7}{'score':>8}{'12-1':>9}{'3m':>9}{'vol':>8}{'IVrank':>8}{'px':>10}")
    for s in snap["ranked"][:10]:
        n = snap["names"][s]
        print(f"  {s:<7}{(n['momentum_score'] or 0):>8.2f}{(n['mom_12_1'] or 0):>8.1%}"
              f"{(n['mom_3m'] or 0):>9.1%}{(n['realised_vol'] or 0):>8.0%}"
              f"{(n['iv_rank'] if n['iv_rank'] is not None else -1):>8.0f}"
              f"{(n['last_price'] or 0):>10.2f}")

    j = res["llm"]
    tag = f"regime={j['regime']}" if j["available"] else f"ABSTAINED ({j['error']})"
    print(f"\nJUDGMENT AGENT  {tag}")
    if j.get("note"):
        print(f"  {j['note']}")

    print(f"\nPROPOSALS")
    for p in res["proposals"]:
        w = f"{p['target_weight']:.1%}" if p.get("target_weight") is not None else "-"
        print(f"  {p['kind']:<7}{p['side']:<13}{p['symbol']:<7}{w:>7}  {p['reason']}")
    if not res["proposals"]:
        print("  none")

    print(f"\nRISK DECISIONS")
    for d in res["decisions"]:
        mark = {"APPROVE": "APPROVED", "REDUCE": "REDUCED ", "REJECT": "REJECTED"}[d["action"]]
        print(f"  {mark} {d['kind']:<7}{d['symbol']:<7}{d['reason']}")
    if not res["decisions"]:
        print("  none")

    print(f"\nORDERS")
    for o in res["orders"]:
        size = (f"{o['qty']:.4f} sh" if o.get("qty")
                else f"{o.get('contracts')} contracts")
        print(f"  {o['side']:<13}{o['symbol']:<7}{size:<16}status={o['status']}")
        if o.get("error"):
            print(f"      error: {o['error']}")
    if not res["orders"]:
        print("  none")

    s = res["summary"]
    if "account" in s:
        a, e = s["account"], s["exposure"]
        print(f"\nPORTFOLIO   equity ${a['equity']:,.2f}   cash ${a['cash']:,.2f}")
        print(f"  equity positions {e['equity_positions']}  "
              f"long MV ${e['equity_long_mv']:,.2f} "
              f"({(e['equity_long_pct'] or 0):.1%} of equity)   "
              f"option positions {e['option_positions']}")
        print(f"  unrealised P&L ${s['unrealized_pl_total']:,.2f}")
        if s.get("held_not_wanted"):
            print(f"  held but no longer ranked: {', '.join(s['held_not_wanted'])}")
    print(f"\n  log: {res['log_file']}\n{BAR}\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="options_agents")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cycle", help="run one full agent cycle")
    c.add_argument("--execute", action="store_true",
                   help="submit orders to Alpaca PAPER (default is a dry run)")
    c.add_argument("--no-llm", action="store_true", help="skip the judgment agent")
    c.add_argument("--json", action="store_true")
    sub.add_parser("status", help="account and positions")
    sub.add_parser("universe", help="show the screened universe")
    a = ap.parse_args(argv)

    cfg = LiveConfig()
    universe = load_universe(cfg)
    cfg = LiveConfig.from_env(tuple(universe))

    if a.cmd == "universe":
        print(f"{len(universe)} symbols in {cfg.data_dir}")
        for i in range(0, min(len(universe), 200), 20):
            print("  " + " ".join(universe[i:i + 20]))
        return 0

    if a.cmd == "status":
        b = AlpacaBroker()
        acct = b.verify_paper()
        print(f"account {acct['account_number']}  equity ${float(acct['equity']):,.2f}  "
              f"cash ${float(acct['cash']):,.2f}")
        for p in b.get_positions():
            print(f"  {p['symbol']:<22}{p.get('asset_class',''):<12}"
                  f"qty {p['qty']:>10}  mv ${float(p['market_value']):>12,.2f}  "
                  f"P&L {float(p['unrealized_plpc']):>+7.2%}")
        return 0

    dry = not a.execute
    if not dry:
        print("\n*** LIVE PAPER EXECUTION ENABLED — orders go to the Alpaca PAPER "
              "account. ***\n")
    try:
        res = run_cycle(cfg, dry_run=dry, use_llm=not a.no_llm)
    except NotPaperTradingError as e:
        print(f"\nREFUSED: {e}\n", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(res, indent=2, default=str))
    else:
        _print(res, cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
