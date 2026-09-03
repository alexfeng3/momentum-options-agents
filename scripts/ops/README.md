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

The times deliberately avoid the open, when option spreads are widest, and give
the overlay three chances a day to fill.

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
HEDGE_FUND_DRY_RUN=1 /Users/alexfeng/project-workspace/.venv/bin/python \
  ~/.hermes/scripts/hedge_fund_cycle_to_discord.py
```

Prints the Discord message to the terminal and submits nothing.

## Why this is safe to leave running

- The four paper gates in `broker.py::verify_paper()` still apply to every
  order; exit code 2 is reported to Discord as a loud failure, never swallowed.
- The risk agent rejects every proposal when the market is closed, so a run on a
  holiday does nothing.
- Capital cannot be double-spent — `portfolio.py` raises rather than allowing it.
