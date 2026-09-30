# Scheduled operation

The agent cycle is not a daemon. It runs on a **Hermes cron** job — no resident
process, no launchd plist — and each run posts its result to Discord.

| | |
|---|---|
| Job id | `a8f94e342ba6` |
| Schedule | `45 6,9,12 * * 1-5` (local PT) — **9:45, 12:45 and 15:45 ET**, weekdays |
| Script | `~/.hermes/scripts/hedge_fund_cycle_to_discord.py` (tracked copy here) |
| Mode | `--no-agent`: the script *is* the job, stdout delivered verbatim |
| Command run | `python -m options_agents.cli cycle --no-llm --execute` |
| Deployed copy | differs from the tracked copy only in the two path constants at the top; keep both in step |

The times deliberately avoid the open, when option spreads are widest.

## What a run does (since 2026-09-30)

Each run is the same three-times-a-day cycle, but the **stock book changes only
about once a month**:

1. **Refresh prices.** New finished sessions are appended to `data/broad/*.csv`
   (never today's partial bar; a split rewrites that symbol's history). An API
   error is logged and the cycle carries on with the existing cache.
2. **Fail closed.** If the newest SPY bar is more than 5 days old the cycle
   proposes no stock trades at all. The Discord message then opens with a
   `STALE PRICE DATA` line. Open put spreads are still closed.
3. **Rebalance only every 21 days.** The Discord message says whether this was a
   rebalance cycle and when the next is due. On a rebalance cycle it ranks, exits
   names that left the top 6 (or everything if SPY < 200-day) and buys the top 6.
   Other cycles leave the stocks alone. The date is in `state/rebalance.json`
   (gitignored); it is written only by a live cycle with the market open and fresh
   data, never by a dry run. Delete the file to force a rebalance on the next live
   cycle.
4. **Overlay and PEAD are off.** No new spreads, no earnings trades. An existing
   spread is closed at 50% profit or 5 days to expiry.

On a normal day with nothing to do, expect "No orders" and a
`rebalance cycle: no` line. That is the system working.

The 2026-09-14 incident this replaced: the price cache was never refreshed, every
name looked delisted, and the whole account was sold as "no longer in the top-N".

**No LLM is in the trading path.** `--no-agent` means Hermes runs the script
directly rather than handing it to a model, and `--no-llm` skips the Judgment
Agent. This is the same boundary `AGENTS.md` draws: an LLM in the
trade-generation path cannot be backtested honestly.

## Managing it

```bash
hermes cron list                      # status and next run
hermes cron pause a8f94e342ba6        # stop it
hermes cron resume a8f94e342ba6
hermes cron run a8f94e342ba6          # fire once on the next tick
hermes cron runs a8f94e342ba6         # execution history
```

Pausing the job is the kill switch. Editing `~/.hermes/cron/jobs.json` by hand
is not — the gateway holds jobs in memory and will overwrite it.

## Testing without trading

```bash
HEDGE_FUND_DRY_RUN=1 ~/project-workspace/.venv/bin/python \
  ~/.hermes/scripts/hedge_fund_cycle_to_discord.py
```

Prints the Discord message to the terminal and submits nothing. A dry run still
refreshes the price cache (that is not trading) but never writes
`state/rebalance.json`.

To see the cycle itself: `PYTHONPATH=src python -m options_agents.cli cycle --no-llm`.

## Why this is safe to leave running

- The four paper gates in `broker.py::verify_paper()` still apply to every
  order; exit code 2 is reported to Discord as a loud failure, never swallowed.
- The risk agent rejects every proposal when the market is closed, so a run on a
  holiday does nothing.
- Stale prices stop all stock trading rather than letting a bad ranking sell the
  book (see above).
- Capital cannot be double-spent — `portfolio.py` raises rather than allowing it.
