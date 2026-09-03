#!/usr/bin/env python3
"""Run one alpaca-hedge-fund agent cycle and report it to Discord.

Hermes no-agent job: this script IS the job and its stdout is delivered
verbatim. No LLM is involved in the trading decision — the cycle is the
deterministic agent pipeline, and `AGENTS.md` in that repo deliberately keeps an
LLM out of the trade-generation path.

Set HEDGE_FUND_DRY_RUN=1 to run the cycle without submitting orders.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT = Path("/Users/alexfeng/project-workspace/alpaca-hedge-fund")
PYTHON = Path("/Users/alexfeng/project-workspace/.venv/bin/python")
FAILURE_PREFIX = "🚨 Hedge Fund cycle FAILED"
TIMEOUT = 600
DRY_RUN = os.environ.get("HEDGE_FUND_DRY_RUN", "").strip() in ("1", "true", "yes")

# Discord rejects anything over 2000 characters, and a truncated trading report
# is worse than a short one.
LIMIT = 1900


def fail(error: str) -> int:
    print(f"{FAILURE_PREFIX}\n{error}")
    return 1


def money(x) -> str:
    try:
        return f"${float(x):,.0f}"
    except (TypeError, ValueError):
        return "?"


def render(res: dict) -> str:
    acct = (res.get("summary") or {}).get("account") or {}
    expo = (res.get("summary") or {}).get("exposure") or {}
    orders = res.get("orders") or []
    decisions = res.get("decisions") or []

    regime = "RISK-ON" if res.get("spy_above_sma200") else "RISK-OFF (SPY<SMA200)"
    mkt = "OPEN" if res.get("market_open") else "CLOSED"
    mode = "DRY RUN" if res.get("dry_run") else "PAPER"

    L = [f"📊 **Hedge Fund** · {res.get('as_of')} · {mode}",
         f"regime {regime} · market {mkt} · run `{res.get('run_id')}`"]

    submitted = [o for o in orders
                 if o.get("status") not in ("dry_run", "error", "skipped_duplicate")]
    errored = [o for o in orders if o.get("status") == "error"]

    if submitted:
        L.append(f"\n**Orders ({len(submitted)})**")
        for o in submitted:
            size = (f"{o['qty']:.2f} sh" if o.get("qty")
                    else f"{o.get('contracts')} contracts")
            filled = "filled" if o.get("status") == "filled" else o.get("status")
            L.append(f"· {o.get('side')} {o.get('symbol')} {size} — {filled}")
    elif res.get("market_open"):
        L.append("\nNo orders — nothing crossed a threshold this cycle.")
    else:
        L.append("\nMarket closed; every proposal was refused, as designed.")

    if errored:
        L.append(f"\n**Order errors ({len(errored)})**")
        for o in errored[:4]:
            L.append(f"· {o.get('symbol')}: {o.get('error')}")

    # Only surface rejections that are worth a human's attention. "Market is
    # closed" on a holiday is the system working, not news.
    noise = ("Market is closed.", "Paper trading is not verified")
    rejected = [d for d in decisions
                if not d.get("approved")
                and not any(d.get("reason", "").startswith(n) for n in noise)]
    if rejected:
        L.append(f"\n**Refused ({len(rejected)})**")
        for d in rejected[:4]:
            L.append(f"· {d.get('kind')} {d.get('symbol')}: {d.get('reason')}")

    L.append(f"\nequity {money(acct.get('equity'))} · "
             f"cash {money(acct.get('cash'))} · "
             f"{expo.get('equity_positions', 0)} equities, "
             f"{expo.get('option_positions', 0)} option legs")
    pl = (res.get("summary") or {}).get("unrealized_pl_total")
    if pl is not None:
        L.append(f"unrealised P&L {'+' if pl >= 0 else '−'}{money(abs(pl))}")

    out = "\n".join(L)
    return out if len(out) <= LIMIT else out[:LIMIT] + "\n…(truncated)"


def main() -> int:
    if not PYTHON.exists():
        return fail(f"Python not found: {PYTHON}")
    if not PROJECT.exists():
        return fail(f"Project not found: {PROJECT}")

    cmd = [str(PYTHON), "-m", "options_agents.cli", "cycle", "--no-llm", "--json"]
    if not DRY_RUN:
        cmd.append("--execute")

    env = dict(os.environ, PYTHONPATH=str(PROJECT / "src"))
    try:
        proc = subprocess.run(cmd, cwd=str(PROJECT), env=env, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        return fail(f"Cycle timed out after {exc.timeout}s")
    except Exception as exc:  # defensive: this runs unattended
        return fail(str(exc))

    stdout, stderr = proc.stdout.strip(), proc.stderr.strip()

    # Exit code 2 is the paper-gate refusal. It is a safety stop, not a crash,
    # and it must never be quietly swallowed.
    if proc.returncode == 2:
        return fail(f"REFUSED by the paper-trading gates.\n{stderr or stdout}")
    if proc.returncode != 0:
        return fail(stderr or stdout or f"exit code {proc.returncode}")

    # The cycle echoes progress lines before the JSON, so take the last object.
    start = stdout.find("{")
    if start < 0:
        return fail(f"No JSON in cycle output.\n{stdout[-800:]}")
    try:
        res = json.loads(stdout[start:])
    except json.JSONDecodeError as exc:
        return fail(f"Could not parse cycle output: {exc}\n{stdout[-800:]}")

    print(render(res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
