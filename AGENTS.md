# Working in this repository

## Paper only, one account only — non-negotiable

There is no live-trading code path and none should be added. Orders require all
four gates in `broker.py::verify_paper()`. Gate 4 compares a **SHA-256** against
`ALLOWED_ACCOUNT_HASHES` — a tracked source constant, not an env var, so `.env`
can narrow the allowlist but never widen it. Adding a hash is a reviewable change;
treat a PR that does it as real-money-adjacent.

## One pot of money

`portfolio.py` is the capital model and its assertions must never be softened into
warnings. Reserved collateral is not spendable. Stock is bought from unreserved
cash only.

This exists because the backtester once allocated 100% of equity to stock and then
sold spreads against money already spent — silent leverage worth ~8pp of CAGR that
reversed a conclusion about whether the overlay works. `tests/test_portfolio.py`
pins every rule.

## Agent boundaries

- `agents/strategy.py` — rules only. No risk checks, no network, no sizing against
  the live account.
- `agents/risk.py` — veto authority. Returns APPROVE / REDUCE / REJECT with a
  reason for every rejection, and simulates capital as approvals accrue so two
  proposals cannot spend the same dollar.
- `agents/execution.py` — orders only. No signal logic, no limit logic. It raises
  if handed an unapproved decision.
- `llm.py` — veto and narration only. It must never generate or size a trade;
  an LLM in the trade-generation path cannot be backtested honestly.

If you find yourself adding a threshold to the execution agent, it belongs in
`strategy_config.py` and is enforced by the risk agent.

## Evidence discipline

`docs/` records what **failed** as well as what worked, and every headline number
carries its bias control. When you change a parameter, re-run
`scripts/report.py` and `scripts/test_universe.py` and update the docs in the same
commit. A result quoted without its equal-weight-universe benchmark is misleading
by construction.

Rejection messages must name the constraint that actually bound. "Cannot
collateralise" while quoting ample free cash sends the next reader debugging the
wrong subsystem.

## Before committing

```bash
python -m pytest tests/ -q
```
