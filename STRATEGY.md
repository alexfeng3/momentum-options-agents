# Strategy — one page

**Status: paper trading only, live on Alpaca paper. Momentum core only.** Detailed evidence, parameter
tables and every failed experiment: [docs/STRATEGY_DETAIL.md](docs/STRATEGY_DETAIL.md).

---

## What this is (deployed since 2026-09-30)

**A concentrated momentum stock portfolio, rebalanced monthly. Nothing else.**

The system was built as three sleeves. Only the first is running:

| Sleeve | Status | What it does |
|---|---|---|
| **Momentum core** | **ON — 80% of equity** | Buy the 6 strongest-momentum stocks, rebalance every 21 days, go to cash when SPY < its 200-day average |
| PEAD sleeve | OFF (`pead_enabled`) | Would buy after a real SEC earnings beat. Cannot fire: earnings data exists for only 32 names, unrelated to the ranked universe |
| Options overlay | OFF for new spreads (`overlay_enabled`) | Sold 20-delta put spreads against holdings. 1 of 22 orders filled; not reliably additive on this book (`docs/STRATEGY_DETAIL.md` §6.5) |

An already-open put spread is still closed by the exit rules (50% of the credit
earned, or 5 days to expiry).

## What it does, in order

1. **Refresh prices.** Append the newly finished sessions to the local cache
   (`data/broad/`, 951 names + SPY). Never today's partial bar. If a split has
   changed a symbol's prices, re-fetch its whole history.
2. **Fail closed.** If the newest SPY bar is more than 5 days old, propose **no
   stock trades** (no buys, exits or trims) and report `data_stale`. Spread exits
   still run.
3. **Is it a rebalance cycle?** Yes if none is recorded, 21+ days have passed since
   the last, or it is the same day as the last (so a part-filled rebalance can
   finish). If not, leave the stock book alone. The cron job runs 3x a day; the
   book changes about once a month. The date lives in `state/rebalance.json`,
   written only by a live cycle with the market open and fresh data.
4. **On a rebalance cycle:** rank every liquid US stock on 12-month momentum
   (skipping the last month), 3-month momentum, trend and strength vs SPY, all
   divided by volatility. Filters: price ≥ $10, 60-day vol ≤ 60%.
5. If SPY is below its 200-day average → **sell everything, hold cash.**
6. Otherwise buy the top 6 (80% / 6 each), sell any holding that left the top 6.

## Results

### What is deployed: momentum core, monthly, 951 mechanical names

`python scripts/run_deployed_config.py` — top 6, 80% invested, price ≥ $10, vol ≤ 60%,
21-day rebalance, SPY-200 filter; 2021-09-01 → 2026-08-27; 5 bps costs.

| | Return | maxDD | Sharpe | β | α (ann) |
|---|---|---|---|---|---|
| SPY | +70.7% | −25.4% | 0.60 | 1.00 | — |
| Equal-weight the 951 names | +59.8% | −25.3% | 0.50 | 0.98 | −1.0% |
| **Deployed, first rebalance 2021-09-01** | **+196.5%** | −16.5% | 1.07 | 0.49 | +18.5% |

**The start day matters.** Shifting the first rebalance by 0–20 trading days moves
the total return between **+116% and +214%** (median +154%). One start date is one
sample; expect a wide range, not +196%.

For reference, the same engine at 100% invested, no vol cap and price ≥ $5 gives
+329.2% (maxDD −38.2%). The deployed filters give up return for a much smaller
drawdown.

### Not the deployed system: the 39-name tables

Earlier versions of this page led with returns of +1,072% (test) and +16,302%
(full history). **Those are not the deployed configuration.** They come from a
39-name universe hand-picked in 2026 (it contains the AI-era winners), and they run
all three sleeves. They remain in `docs/STRATEGY_DETAIL.md` §6 as evidence for what
each sleeve did in isolation. On the mechanical 951-name universe, roughly 40% of
that headline alpha was universe selection (+45.7% → +28.7%/yr for the unfiltered
top-6).

## What this is not

- **Not market-neutral.** It falls when the market falls (β 0.49 in the deployed
  backtest, higher in other configurations).
- **Not low-drawdown.** −16.5% in the deployed backtest, but −38% with the filters
  off, and the 951-name history covers one ~5-year regime.
- **Not a large-cap strategy.** Screening to big, calm names collapses the alpha
  to +1.3%/yr. The edge lives in volatility.
- **Not proven in low-vol bull markets.** It lags when the market melts up.
- **Not a tested live result.** The backtest is on IEX daily bars and ignores
  slippage beyond 5 bps. In paper, the account was liquidated by a stale-data bug
  on 2026-09-14 (below) and has been in cash since; the monthly momentum book has
  not yet run live.

## Incident: 2026-09-14 stale-data liquidation

The price cache was never refreshed (last bar 2026-08-27). On 2026-09-14 the
"no bar for 15 days = delisted" test fired for every name, the ranking came back
empty, and the strategy sold every holding as "no longer in the top-N". Two more
defects sat behind it: the live agents exited any name outside the top 6 on every
cycle (the backtest only does so monthly), and delisting was measured against the
wall clock instead of the data. Fixed 2026-09-30: prices refresh each cycle, stale
data fails closed, delisting is measured from the newest SPY bar, and the stock
book follows the 21-day calendar. Regression tests: `tests/test_agents.py`,
`tests/test_data_refresh.py`.

## Safety

Four gates before any order: `PAPER_TRADING=true`, paper endpoint, account starts
`PA`, and its SHA-256 is in a tracked allowlist. Capital cannot be spent twice —
`portfolio.py` raises rather than allowing it. The risk agent can veto anything;
the execution agent raises if handed an unapproved decision.
