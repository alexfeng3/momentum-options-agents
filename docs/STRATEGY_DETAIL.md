# Strategy detail — full evidence reference

> **Start with [../STRATEGY.md](../STRATEGY.md)** for the one-page summary. This
> document is the exhaustive version: every parameter, every backtest variant,
> every failed experiment and every bug that produced a fake result.
>
> **The tables in §6 compare SLEEVES IN ISOLATION** so each one's contribution can
> be attributed. None of those rows is the deployed system — the live
> configuration runs all three sleeves together and is backtested in §6.6.

# Momentum + PEAD + Defined-Risk Options Strategy

**Last updated: 2026-08-28 | Status: PAPER ONLY (Alpaca paper, agent pipeline live) | Config: `momentum-top6 + core_weight 0.80 + PEAD/SUE sleeve + 20Δ put-spread overlay @ 15% max collateral`**

This document is the authoritative reference for the strategy as backtested and as
running in the agent pipeline. `AGENTS.md` covers operational setup; this document
covers what the strategy is, why it works, and what the evidence actually says —
including everything that did not work.

**Every headline number in this document is quoted next to its survivorship-bias
control.** A return quoted without that control is misleading by construction; see
§2.3 and §6.4.

---

## 1. Strategy Overview

Three components, each with a distinct job:

1. **Momentum core (the return engine).** Rank a liquid universe on point-in-time
   momentum, hold the top N equal-weight, rebalance monthly, and sit in cash when
   the market is below its 200-day average. This supplies direction and almost all
   of the return.
2. **PEAD sleeve (the low-beta alpha).** Buy names showing a genuine post-earnings
   surprise — measured from **real SEC EDGAR filings**, not a vendor calendar —
   and hold through the drift window. Beta ~0.2, so it diversifies the core.
3. **Defined-risk options overlay (the carry).** Sell 20-delta put credit spreads
   on names the model already holds. Max loss is the spread width, always.

The thesis for the overlay is specific: the model is already bullish on these
names, and a short put spread expresses that view with **positive** theta instead
of paying it. Buying calls on the same names was tested and failed badly (§7.1).

**What this strategy is not:** it is not market-neutral, not a Sharpe-maximising
book, and not a large-cap quality strategy. It is a concentrated, high-beta,
high-volatility momentum portfolio with an options carry overlay. Its edge
disappears when screened to large calm names (§6.4).

---

## 2. Universe

### 2.1 Live universe (mechanically screened)

Built by `scripts/fetch_broad_universe.py` with **no judgement about which names
are interesting**:

| Filter | Value |
|---|---|
| Exchange | NASDAQ, NYSE, AMEX, ARCA, BATS |
| Symbol form | ≤5 characters, alphabetic |
| History | ≥400 daily bars from 2020-08 |
| Liquidity | median dollar volume ≥ $3M |
| Status | **active AND inactive** (delisted names included) |

**Result: 951 symbols, 29 of them dead (3.0%).**

Runtime screens applied at selection time (`strategy_config.py`):

| Screen | Default | Config key |
|---|---|---|
| Minimum price | $10 | `min_price` |
| Maximum 60d realised vol | 60% | `max_vol` |
| Minimum history | 260 bars | (hard-coded in `selection.py`) |
| Delisting staleness | >15 days without a bar | `HistoricalBook.is_delisted` |

### 2.2 Backtest universe (legacy, biased)

The 39-name universe inherited from the original project (`AAPL … XLY`) is
**hand-picked with hindsight** and contains the AI-era winners. It is retained
only because it has 2005–2026 history where the broad universe starts 2020-08.
Any result on it must be read against §2.3.

### 2.3 The bias control — non-negotiable

Every table reports **equal-weight buy-and-hold of the same universe** next to SPY.
Only the margin over the equal-weight row is attributable to the strategy.

| Same rule applied to | Return (2021-09 → 2026-08) | maxDD | β | α (ann) |
|---|---|---|---|---|
| 951 mechanically-screened names | **+59.8%** | −25.3% | 0.98 | −1.0% |
| 39 hand-picked names | **+249.1%** | −35.9% | 1.60 | +12.5% |

**That ~190pp gap is pure hindsight, before any strategy runs.** It is the single
largest number in this document and it belongs to the universe, not the model.

---

## 3. Entry Logic

### 3.1 Momentum scoring (deterministic, no LLM)

Computed in `selection.py` from closes up to and including the decision day:

```
score = 0.45 × (mom_12_1 / max(vol, 0.15))
      + 0.25 × (mom_3m   / max(vol, 0.15))
      + 0.20 × trend
      + 0.10 × (rs       / max(vol, 0.15))
```

| Term | Definition | Why |
|---|---|---|
| `mom_12_1` | return from t−252 to t−21 | 12-month momentum **skipping the last month** — short-term reversal makes the most recent 20 sessions actively harmful (Jegadeesh–Titman construction) |
| `mom_3m` | return over the last 63 sessions | medium-horizon confirmation |
| `trend` | 1.0 if px>SMA50>SMA200; 0.5 if px>SMA200; else 0.0 | structural filter, not a return term |
| `rs` | `mom_12_1` − SPY's `mom_12_1` | relative strength |
| `vol` | 60-day annualised realised vol, floored at 0.15 | **volatility normalisation** — without it a 120%-vol lottery ticket outranks a compounder purely for being noisy |

### 3.2 Entry gate (applied in order)

| # | Gate | Threshold | Config key |
|---|---|---|---|
| G1 | Market regime | SPY > its own 200-day SMA, else **100% cash** | `market_filter` |
| G2 | Delisted | last bar within 15 days | — |
| G3 | History | ≥260 bars | — |
| G4 | Price | ≥ $10 | `min_price` |
| G5 | Volatility | 60d realised ≤ 60% | `max_vol` |
| G6 | Uptrend | `trend > 0` | `require_uptrend` |
| G7 | Rank | top N by score | `top_n` |

### 3.3 PEAD entry (SEC-sourced)

Surprise is measured **two independent ways and both must agree**:

```
SUE = (EPS_q − EPS_{q−4}) / stdev(last 8 seasonal surprises)      # Bernard & Thomas (1989)
```

| # | Gate | Default | Config key |
|---|---|---|---|
| P1 | Fundamental surprise | `SUE ≥ 0.5` | `sue_min` |
| P2 | Market confirmation | announcement gap ≥ +1.0% | `gap_min` |
| P3 | Volume confirmation | ≥1.3× 20-day average | `vol_ratio_min` |
| P4 | Recency | within 3 days of the announcement | `pead_entry_days` |

**Announcement detection.** SEC gives the *filing* date; the press release precedes
it (median lag **14 days**). The announcement is located as the largest
volume-confirmed overnight gap in the window ending at the filing date, and entry
is the day **after**. This is deliberately conservative: the initial jump is never
captured, only the drift — which is what PEAD actually is.

### 3.4 Options overlay entry

| # | Gate | Default | Config key |
|---|---|---|---|
| O1 | Underlying already held | must be a CORE or PEAD name | — |
| O2 | IV rank | ≥20 (top 80% of its own trailing year) | `iv_rank_min` |
| O3 | Short strike | 20-delta put | `short_delta` |
| O4 | Width | 10% of spot, **capped at $25** | `width_pct`, `max_width_dollars` |
| O5 | Tenor | 30 DTE | `dte` |
| O6 | Minimum credit | > $0.05 | — |

The `$25` width cap exists because a $528 stock at 10% gives a $5,280 per-contract
max loss — larger than the whole per-spread risk budget — so the risk agent
rejected it every cycle and the overlay silently never traded those names.

### 3.5 Position sizing

| Sleeve | Size | Config key |
|---|---|---|
| Momentum core | `core_weight / top_n` of equity per name (default 80% / 6 = 13.3%) | `core_weight`, `top_n` |
| PEAD | 5% of equity per event | `pead_weight` |
| Per-name cap | 20% of equity | `max_position_pct` |
| Spread | 3% of equity risk per spread | `risk_per_spread` |
| Overlay total | 15% of equity in reserved collateral | `max_overlay_risk` |
| Cash floor | 2% never spent | `cash_floor` |
| Rebalance band | ±25% of target before trading | `rebalance_band` |

The **rebalance band** matters: without it, a position already at target is
re-bought in full every cycle and the book churns for nothing.

---

## 4. Exit Logic

| Rule | Trigger | Action |
|---|---|---|
| **X_REGIME** | SPY < 200-day SMA | exit **everything**, hold cash |
| **X_RANK** | name drops out of the top-N ranking | full exit |
| **X_TRIM** | position >25% above target weight | sell **only the excess** |
| **X_SPREAD_PT** | spread buyable at 50% of credit | close the spread |
| **X_SPREAD_EXP** | spread reaches expiry | settle at intrinsic |
| **X_PEAD_TIME** | 40 days after entry | full exit |
| **X_PEAD_STOP** | −15% from entry | full exit |

Exits are **never blocked** by exposure caps, position limits, or the cash floor —
they reduce risk. `X_TRIM` sells only the excess; liquidating the whole position
would have it bought straight back next cycle, paying costs both ways (§7.6).

---

## 5. Backtest Methodology

### 5.1 Data

| Source | Coverage | Used for |
|---|---|---|
| Alpaca IEX daily bars | 2020-08 → present, 951 symbols | broad-universe test |
| Legacy `.pkl` daily bars | 2005-01 → 2026-08, 47 symbols | long-history test |
| CBOE vol indices (VIX/VXN/VIX9D/VIX3M) | 2005 → 2026 | index IV surface |
| 13-week T-bill (`_IRX`) | 2005 → 2026 | risk-free rate, idle-cash yield |
| **SEC EDGAR XBRL** | 2009 → 2026, 31 names | PEAD: quarterly diluted EPS + filing dates |

**There is no historical option chain on this machine.** Contracts are model-priced
(§5.2). This is the single largest methodological caveat.

### 5.2 Pricing engine

- Black-Scholes-Merton with greeks, `pricing.py`, stdlib only. Put-call parity
  holds to 7e-15; delta inversion is exact to 1e-3.
- **Index IV**: matching vol index, shaped by a term structure from VIX9D/VIX3M
  and a linear skew in log-moneyness (equity index puts trade above ATM).
- **Single-name IV**: `realised_vol(60d) × 1.10`, charged on entry *and* exit so
  the model never buys cheap and sells rich through an artifact.

### 5.3 Frictions

| Cost | Value |
|---|---|
| Option slippage | 5% of theoretical credit, **each way** |
| Option fees | $0.05 per contract per leg |
| Stock transaction cost | 5 bps each way |
| Idle cash | earns the 13-week T-bill |

### 5.4 Capital accounting — the single pot

`portfolio.py` enforces, with assertions that **raise**:

- `cash >= 0` — you cannot spend money you do not have.
- Every short spread reserves `(width − credit) × 100 × contracts` in cash.
- **Reserved cash cannot also buy stock.**
- Stock is bought only from unreserved cash.

This exists because an earlier engine allocated 100% of equity to stock and *then*
sold spreads collateralised by money already spent. That silent leverage inflated
CAGR by **~8 percentage points** and reversed the overlay conclusion (§7.5).

### 5.5 Splits

| Split | Window | Role |
|---|---|---|
| Train | 2011-01 → 2018-12 | parameter selection |
| Validate | 2019-01 → 2021-12 | first blind check |
| Test | 2022-01 → 2026-06 | run once, never tuned on |

---

## 6. Backtest Results

Legend: `Sh(pt)` = per-trade Sharpe · `PF` = profit factor · `DD` = max drawdown ·
`AnnSh` = annualised Sharpe (daily marks, ×√252, rf=2%) · `β`/`α` = CAPM vs SPY.

### 6.1 Train (2011-01-03 → 2018-12-31)

| Period | Days | Trades | Return | WR | Sharpe(pt) | PF | DD | Ann.Sharpe | β | α (ann) | SPY |
|---|---|---|---|---|---|---|---|---|---|---|---|
| SPY buy & hold | 2919 | 0 | +131.3% | — | — | — | −19.3% | 0.66 | 1.00 | +0.0% | +131.3% |
| Equal-wt universe\* | 2919 | 0 | +245.5% | — | — | — | −29.2% | 0.74 | 1.23 | +4.1% | +131.3% |
| Momentum top-6 | 2919 | 0 | +233.2% | — | — | — | −19.9% | 0.74 | 0.77 | +8.2% | +131.3% |
| **Momentum + spreads** | 2919 | **432** | **+313.7%** | 95.4% | 0.215 | 1.99 | −17.4% | **0.86** | 0.79 | **+11.0%** | +131.3% |
| PEAD stocks | 2919 | 80 | +54.7% | 68.8% | 0.338 | 2.90 | −6.9% | 0.73 | 0.13 | +2.4% | +131.3% |
| PEAD + spreads | 2919 | 155 | +74.8% | 83.2% | 0.500 | 3.37 | −10.3% | 0.86 | 0.18 | +3.5% | +131.3% |

### 6.2 Validate (2019-01-01 → 2021-12-31)

| Period | Days | Trades | Return | WR | Sharpe(pt) | PF | DD | Ann.Sharpe | β | α (ann) | SPY |
|---|---|---|---|---|---|---|---|---|---|---|---|
| SPY buy & hold | 1094 | 0 | +99.7% | — | — | — | −33.7% | 1.07 | 1.00 | +0.0% | +99.7% |
| Equal-wt universe\* | 1094 | 0 | +384.0% | — | — | — | −41.0% | 1.71 | 1.24 | +31.0% | +99.7% |
| Momentum top-6 | 1094 | 0 | +288.5% | — | — | — | −47.4% | 1.26 | 0.63 | +44.5% | +99.7% |
| Momentum + spreads | 1094 | 128 | +263.3% | 93.0% | 0.172 | 1.29 | −47.8% | 1.22 | 0.65 | +40.1% | +99.7% |
| PEAD stocks | 1094 | 44 | **−1.0%** | 47.7% | −0.031 | **0.88** | −16.5% | −0.21 | 0.16 | **−5.4%** | +99.7% |
| PEAD + spreads | 1094 | 86 | +4.4% | 70.9% | 0.176 | 1.09 | −15.5% | −0.00 | 0.17 | −4.0% | +99.7% |

**PEAD failed in Validate.** It is left in the table. A strategy that works in two
of three regimes is the normal case; deleting the bad window is how you get
surprised live.

### 6.3 Test (2022-01-03 → 2026-06-11) — run once, never tuned on

| Period | Days | Trades | Return | WR | Sharpe(pt) | PF | DD | Ann.Sharpe | β | α (ann) | SPY |
|---|---|---|---|---|---|---|---|---|---|---|---|
| SPY buy & hold | 1620 | 0 | +63.7% | — | — | — | −24.5% | 0.61 | 1.00 | +0.0% | +63.7% |
| Equal-wt universe\* | 1620 | 0 | +154.2% | — | — | — | −37.1% | 0.74 | 1.62 | +7.7% | +63.7% |
| **Momentum top-6** | 1620 | 0 | **+1124.9%** | — | — | — | −30.3% | **1.77** | 0.84 | **+67.6%** | +63.7% |
| Momentum + spreads | 1620 | 205 | +1105.9% | 94.6% | 0.332 | 2.67 | −32.7% | 1.80 | 0.82 | +66.9% | +63.7% |
| PEAD stocks | 1620 | 66 | +108.7% | 56.1% | 0.282 | 2.57 | −10.7% | 1.16 | 0.21 | +14.3% | +63.7% |
| **PEAD + spreads** | 1620 | 126 | +121.8% | 73.0% | 0.245 | 2.42 | **−12.7%** | 1.19 | **0.23** | +15.7% | +63.7% |

\* *39 hand-picked names — the bias control. Read §2.3 before quoting any row.*

### 6.4 Broad-universe validation (2021-09 → 2026-08, 951 mechanical names)

The question that matters: **does the edge survive a universe nobody curated?**

| Portfolio | Return | maxDD | Sharpe | β | α (ann) |
|---|---|---|---|---|---|
| SPY buy & hold | +70.7% | −25.4% | 0.60 | 1.00 | — |
| Equal-weight 951 (bias control) | +59.8% | −25.3% | 0.50 | 0.98 | −1.0% |
| Equal-weight 39 hand-picked | +249.1% | −35.9% | 0.89 | 1.60 | +12.5% |
| Momentum top-6, **hand-picked** | +726.8% | −39.0% | 1.30 | 0.93 | +45.7% |
| **Momentum top-6, mechanical** | **+329.2%** | −38.2% | **0.93** | 0.85 | **+28.7%** |
| top-10, $50M ADV, vol ≤60% | +112.9% | **−21.2%** | 0.73 | 0.64 | +9.4% |
| top-10, $100M ADV, vol ≤50% | +48.1% | −33.0% | 0.42 | 0.60 | **+1.3%** |

**Verdict: the edge survives, but ~40% of the hand-picked alpha was universe
selection** (+45.7% → +28.7%). And screening to large calm names collapses alpha to
+1.3% — statistically nothing. **The edge lives in volatility.**

### 6.5 Overlay attribution

The overlay's contribution, measured on the same universe with and without it:

| Split | Momentum only | + spreads | Δ |
|---|---|---|---|
| Train | +233.2% | +313.7% | **+80.5pp** |
| Validate | +288.5% | +263.3% | **−25.2pp** |
| Test | +1124.9% | +1105.9% | **−19.0pp** |
| PEAD Train | +54.7% | +74.8% | **+20.1pp** |
| PEAD Validate | −1.0% | +4.4% | **+5.4pp** |
| PEAD Test | +108.7% | +121.8% | **+13.1pp** |

**The overlay is additive on PEAD in all three splits, and NOT reliably additive on
the momentum core.** The mechanism is capital, not signal: spread collateral ties
up 15% of equity that would otherwise compound in a high-returning core, whereas
the PEAD sleeve holds cash most of the time so its collateral is free. Sizing
sweeps confirm it — on the momentum book the overlay helps at every collateral
level in Train and is flat-to-negative at every level in Test.

### 6.6 THE LIVE CONFIGURATION — all three sleeves, one pot of capital

Everything above measures one sleeve at a time. This is what the agents actually
run: momentum core (80%) + PEAD sleeve (5%/event) + put-spread overlay (15%
collateral), sharing a single pot of capital under the §5.4 rules.

| Period | Days | Trades | Return | WR | Sharpe(pt) | PF | DD | Ann.Sharpe | β | α (ann) | SPY |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Train 2011-2018 | 2919 | 463 | +360.1% | 95.2% | 0.223 | 2.12 | −15.3% | 0.95 | 0.83 | +12.0% | +131.3% |
| Validate 2019-2021 | 1094 | 150 | +221.7% | 92.7% | 0.137 | 1.20 | −47.0% | 1.17 | 0.69 | +32.0% | +99.7% |
| **Test 2022-2026** | 1620 | 229 | **+1072.1%** | 94.3% | 0.351 | 2.47 | −30.6% | **1.88** | 0.83 | **+64.5%** | +63.7% |
| Full 2011-2026 | 5638 | 874 | +16302.4% | 93.8% | 0.190 | 2.05 | −47.4% | 1.25 | 0.80 | +28.4% | +661.1% |

`python scripts/run_live_config.py`

**Forced liquidations: 1 in 15 years.** When a spread settles at a loss the cash
must come from somewhere, and a fully-invested book has to sell stock — a margin
call. The backtest models this explicitly (largest holding first, at that day's
price). One occurrence across 5,638 sessions says the 15% collateral cap is sized
sanely; a strategy that needed frequent forced sales would be mis-sized.

---

## 7. Optimization History and Key Learnings

### 7.1 Buying calls on momentum names — FAILED
60Δ, 60 DTE, +100% target / −50% stop: **13.57% CAGR vs 29.00% for equal-weight**.
Theta cost plus cutting winners at +100% while being stopped at −50% is exactly
backwards for momentum's fat right tail. Removing both improved it to 25.19% —
still below the basket.

### 7.2 Long calls as leverage — FAILED (ruin)
Sizing by delta notional at 2–3×: CAGR up to **92% at a −98% drawdown**. Rolling
long premium through a downtrend compounds to zero. Not a strategy.

### 7.3 Deep-ITM LEAPS as stock replacement — FAILED
80Δ, 365 DTE, 1× notional: **37.11% vs 45.56% for the shares.** Pays ~8pp of theta
for the same exposure and can go to zero where shares cannot.

### 7.4 SPY protective puts — FAILED
15–30Δ quarterly roll: cost 2–5pp of CAGR **and made drawdown worse** (−54.3% vs
−52.9%). These drawdowns are idiosyncratic momentum crashes, not market beta;
index puts hedge the wrong risk.

### 7.5 The leverage leak — INVALIDATED EARLIER RESULTS
The engine allocated 100% of equity to stock and then sold spreads against money
already spent. Correcting it cut 15-year CAGR from 48.03% to 39.66% (~8pp) and
**reversed** the conclusion in §6.5: the overlay went from "additive in both
periods" to "additive only where cash is idle". Every pre-correction number in
earlier drafts is void.

### 7.6 Bugs that produced fake results
| Bug | Symptom | Fix |
|---|---|---|
| `value()` returned the negative closing cost | 100% win rate, −0.00% DD, Sortino 678 | sign corrected; `value()→settle()` convergence now tested |
| `next_expiry` overshot to 11 DTE | zero trades reported as a clean 0.00% return | first Friday ≥ min_dte; zero-trade runs print a gate tally |
| Delisted holdings marked to **zero** | −91% drawdown; acquisitions (ATVI, VMW, XLNX) booked as total losses | liquidate at **last traded price** |
| Same bug in the **benchmark** | −65.6% DD for a 951-name basket while SPY fell 25%, flattering every strategy | same fix; control now +59.8% / −25.3% / β 0.98 |
| Synthetic per-trade records in the tearsheet | fake 100% win rate, undefined PF | real trade records |
| `TRIM` sold the whole position | $90k sold to reach a $50k target, re-bought next cycle | sells only the excess |
| `is_delisted` had no staleness tolerance | **0 of 951** names scored — yesterday's bar looked delisted | 15-day tolerance |

### 7.7 Parameter findings that held up
- **Any-day entry beats Monday-only**: PF 1.278 vs 1.185.
- **No stop on credit spreads**: a 2× stop turns recoverable positions into
  realised losses and flips PF below 1.0. Width already bounds risk.
- **Narrow spreads beat wide**: 2% width PF 1.201 vs 3% width PF 1.048.
- **IV-rank gate is required**: without it PF < 1.0 out-of-sample. The variance
  risk premium is concentrated in elevated-vol regimes.
- **Term structure was backwards from my hypothesis**: selling only in contango
  gave PF 0.965; selling only into *backwardation* gave the highest PF measured
  (1.424) but traded too rarely to carry a portfolio. Worth revisiting.
- **Iron condors lose**: PF 0.63–0.76. Selling calls into a bull market is a
  losing trade; the put side carried the entire book.

---

## 8. Known Limitations and Risks

### 8.1 Survivorship bias (primary risk)
~40% of the hand-picked universe's alpha is selection bias (§6.4). The broad
universe still has only a 3.0% delisting rate against a realistic 5–8%/yr, and the
failure list is curated, favouring *memorable* failures. Returns here are still
biased upward; the direction of the error is known, the magnitude is not.

### 8.2 Model-priced options
No historical chain exists. Black-Scholes on a VIX-derived (index) or
realised-vol-derived (single-name) surface. Good for 10–30 delta, but not a
tick-accurate replay. Treat option P&L as an edge estimate.

### 8.3 Drawdown
−38.2% on the broad universe, −47.8% in Validate. This is a concentrated high-beta
book that maximises return, not survivability. Most allocators could not hold it.

### 8.4 Regime sensitivity
Underperforms in low-volatility melt-ups, when the market runs away from a
concentrated book and short premium is not paid. PEAD lost money outright in
2019–2021.

### 8.5 Asymmetric overlay payoff
A 20Δ spread collects 9–16% of its width. The 94% win rate is the flip side of a
~10:1 loss-to-gain ratio per trade. Losses are bounded by the width, but a cluster
in one drawdown is the real risk.

### 8.6 Data window
Alpaca IEX daily history starts ~2020-07, so the broad-universe test covers **one
regime** (~6 years, a bull market with two corrections). IEX quotes are not the
NBBO.

### 8.7 Live vs backtest
The backtest rebalances at daily closes; the live agent trades intraday at market
orders. No modelling of borrow, early assignment on short puts, or corporate
actions beyond split adjustment.

---

## 9. Risk Management

### 9.1 Per-position limits
| Limit | Value | Config key |
|---|---|---|
| Max single position | 20% of equity | `max_position_pct` |
| Max positions | 10 | `max_positions` |
| Minimum ticket | $100 | `min_ticket` |
| Per-spread risk | 3% of equity | `risk_per_spread` |
| Max spread width | $25 | `max_width_dollars` |

### 9.2 Portfolio limits
| Limit | Value | Config key |
|---|---|---|
| Core sleeve | 80% of equity | `core_weight` |
| Overlay collateral | 15% of equity | `max_overlay_risk` |
| Cash floor | 2% never spent | `cash_floor` |
| **Capital reuse** | **structurally impossible** | `portfolio.py` assertions |

### 9.3 Paper-trading gates
No order is submitted unless **all four** pass (`broker.py::verify_paper`):

1. `PAPER_TRADING=true`
2. Base URL is Alpaca's paper endpoint
3. Account number starts `PA`
4. It matches `ALPACA_ACCOUNT_NUMBER` **and** its SHA-256 is in
   `ALLOWED_ACCOUNT_HASHES` (tracked source — `.env` can narrow, never widen)

Adversarially verified: live endpoint, `PAPER_TRADING=false`, blank account, a
different paper account, env/credential mismatch, and the live account number are
all refused.

### 9.4 Agent authority boundaries
| Agent | May do | May **not** do |
|---|---|---|
| Market Data | fetch, compute indicators | decide anything |
| Strategy | propose trades from rules | check risk, size against the account, touch the network |
| Judgment (LLM) | **veto**, flag caution, narrate | generate a trade, size one, overrule risk |
| Risk | approve / reduce / reject | place orders |
| Execution | submit approved orders | invent logic; it **raises** on an unapproved decision |
| Position | report, reconcile | create orders |

---

## 10. Changelog

- **2026-08-28** — Adversarial review. Fixed `TRIM` liquidating whole positions and
  a quadratic `_align` (580ms → 2.6ms on 4k points). Verified: no look-ahead
  (scores bit-identical with future bars deleted), no PEAD event dated before it
  was public, 0 overspends in 300 randomised approval sequences, all six
  paper-guard attack vectors refused, beta exact on synthetics.
- **2026-08-28** — Broad-universe validation (§6.4). Momentum alpha survives on 951
  mechanically-screened names (+28.7%/yr) but ~40% of the hand-picked alpha was
  selection bias. Fixed delisting-to-zero in the committed scripts and the
  equal-weight benchmark.
- **2026-08-28** — Five-agent pipeline live on Alpaca paper; hashed account
  allowlist; repo history rebuilt clean for publication.
- **2026-08-28** — PEAD made backtestable on real SEC EDGAR XBRL data (§3.3).
  Out-of-sample β 0.23, α +15.7%/yr, DD −12.7%.
- **2026-08-28** — Strict single-pot capital accounting (§5.4). Reversed the
  overlay conclusion (§6.5, §7.5).
- **2026-08-27** — Momentum + premium replaces the index put-spread overlay after
  the latter was judged too low-return (+0.65pp CAGR out-of-sample).
