# Strategy — one page

**Status: paper trading only, live on Alpaca paper.** Detailed evidence, parameter
tables and every failed experiment: [docs/STRATEGY_DETAIL.md](docs/STRATEGY_DETAIL.md).

---

## What this is

**A concentrated momentum stock portfolio that sells put spreads against its own
holdings, plus a small earnings-drift sleeve.**

One account, three sleeves, one pot of money:

| Sleeve | Capital | What it does | Why it's there |
|---|---|---|---|
| **Momentum core** | 80% | Buy the 6 strongest-momentum stocks, rebalance monthly, go to cash when SPY < its 200-day average | The return engine — almost all the profit |
| **PEAD sleeve** | 5% per event | Buy stocks 1 day after a real SEC earnings beat, hold 40 days | Low-beta (β 0.2) diversifier that works when momentum doesn't |
| **Options overlay** | 15% as collateral | Sell 20-delta put credit spreads on stocks the other two sleeves already own | Collects premium on names we're already bullish on. Max loss = spread width, always |

The options are **sold, not bought**. We're already long these names; a short put
spread expresses the same view and *collects* time decay instead of paying it.
Buying calls on the same names was tested and lost badly.

## What it does, in order

1. Rank every liquid US stock on 12-month momentum (skipping the last month),
   3-month momentum, trend, and strength vs SPY — all divided by volatility.
2. If SPY is below its 200-day average → **sell everything, hold cash.** Stop.
3. Otherwise buy the top 6, equal weight.
4. Check SEC filings for earnings surprises; buy any that qualify.
5. On each stock now held, sell a 30-day 20-delta put spread if its implied vol is
   in the top 80% of its own year.
6. Exit a stock when it leaves the top 6. Close a spread at 50% profit or expiry.

## Results — the configuration above, backtested as one system

| Period | Days | Trades | Return | WR | PF | DD | Ann.Sharpe | β | α (ann) | SPY |
|---|---|---|---|---|---|---|---|---|---|---|
| Train 2011–18 | 2919 | 463 | +360.1% | 95.2% | 2.12 | −15.3% | 0.95 | 0.83 | +12.0% | +131.3% |
| Validate 2019–21 | 1094 | 150 | +221.7% | 92.7% | 1.20 | −47.0% | 1.17 | 0.69 | +32.0% | +99.7% |
| **Test 2022–26** | 1620 | 229 | **+1072.1%** | 94.3% | 2.47 | −30.6% | **1.88** | 0.83 | **+64.5%** | +63.7% |
| Full 2011–26 | 5638 | 874 | +16302.4% | 93.8% | 2.05 | −47.4% | 1.25 | 0.80 | +28.4% | +661.1% |

Test was run once and never tuned on. `python scripts/run_live_config.py`

### The number that matters most

Those returns are on a **39-name universe hand-picked in 2026** — it contains the
AI-era winners. On a **951-name universe screened mechanically** (including
delisted and bankrupt names), over 2021–2026:

| | Return | maxDD | Sharpe | α (ann) |
|---|---|---|---|---|
| SPY | +70.7% | −25.4% | 0.60 | — |
| Equal-weight the 951 names | +59.8% | −25.3% | 0.50 | −1.0% |
| Equal-weight the 39 hand-picked | +249.1% | −35.9% | 0.89 | +12.5% |
| **Momentum on the 951** | **+329.2%** | −38.2% | **0.93** | **+28.7%** |

**The edge is real — but roughly 40% of the headline was universe selection.**
Expect ~+29%/yr alpha, not the hand-picked number.

## What this is not

- **Not market-neutral.** β 0.8. It falls when the market falls.
- **Not low-drawdown.** −47% in the worst period. Most people cannot hold that.
- **Not a large-cap strategy.** Screening to big, calm names collapses the alpha
  to +1.3%/yr. The edge lives in volatility.
- **Not proven in low-vol bull markets.** It lags when the market melts up.
- **Not validated on real option prices.** No historical option chain exists on
  this machine, so spread P&L is modelled with Black-Scholes. Treat it as an
  estimate.
- **Not yet filled in paper.** The three spreads submitted on 2026-08-28 all
  expired unfilled. The execution defects behind that were fixed on 2026-09-03
  (`docs/STRATEGY_DETAIL.md` §3.4.1), but until a spread actually fills, what is
  running live is the momentum core plus the PEAD sleeve.

## Safety

Four gates before any order: `PAPER_TRADING=true`, paper endpoint, account starts
`PA`, and its SHA-256 is in a tracked allowlist. Capital cannot be spent twice —
`portfolio.py` raises rather than allowing it. The risk agent can veto anything;
the execution agent raises if handed an unapproved decision.
