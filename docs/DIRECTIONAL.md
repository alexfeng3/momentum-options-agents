# Momentum + Premium — evidence

**Strategy.** Every 21 days, rank the universe by point-in-time momentum
(12-1 month return, 3-month return, trend, relative strength, all volatility
normalised). Hold the top N as the core. On each name held, sell a 20-delta
30-DTE **put credit spread** when that name's implied vol is in the top 80% of its
own trailing year, closing at 50% of credit captured.

Direction comes from selection; the options add **positive** carry on a name the
model already likes. Buying calls on the same names was tested and failed badly.

---

## THE DOMINANT CAVEAT — read this before the numbers

**The universe is survivorship-biased and the bias is larger than the strategy.**
These 42 names were chosen by hand in 2026. They include NVDA, PLTR, COIN, AVGO,
TSLA — the winners of the AI era. Any long-only strategy on them looks brilliant.

That is why every table below reports **equal-weight buy-and-hold of the same 42
names** alongside SPY. Only the margin over the equal-weight basket is
attributable to the strategy. The margin over SPY is mostly the universe.

### Attribution ladder, out-of-sample (2020-06 to 2026-06)

| Layer | CAGR | Added by this layer |
|---|---|---|
| SPY buy & hold | 15.18% | — |
| Equal-weight universe | 41.56% | **+26.38pp — pure hindsight, not skill** |
| + momentum selection (top-6) | 74.81% | +33.25pp — selection |
| + put-spread overlay | **85.58%** | +10.77pp — options |

Roughly **a third of the headline return is universe bias.** Say so.

---

## Train / test

Selection logic and parameters were set on 2011-2019. 2020-2026 was run once.

### TRAIN 2011-2019
| Portfolio | CAGR | Sharpe | maxDD | Calmar |
|---|---|---|---|---|
| SPY | 13.14% | 0.937 | −19.4% | 0.679 |
| Equal-weight universe | 21.49% | 1.018 | −29.2% | 0.735 |
| Momentum top-6 stocks | 21.49% | 1.045 | −19.7% | 1.092 |
| **+ put-spread overlay** | **27.52%** | **1.129** | −19.8% | **1.390** |

### TEST 2020-2026 (never tuned on)
| Portfolio | CAGR | Sharpe | maxDD | Calmar |
|---|---|---|---|---|
| SPY | 15.18% | 0.799 | −33.7% | 0.450 |
| Equal-weight universe | 41.56% | 1.172 | −40.3% | 1.032 |
| Momentum top-6 stocks | 74.81% | 1.615 | −45.7% | 1.636 |
| **+ put-spread overlay** | **85.58%** | **1.634** | −51.9% | **1.649** |

**The overlay is additive in both periods** — +6.03pp in-sample, +10.77pp
out-of-sample — and improves Sharpe and Calmar in both. That consistency is the
strongest single piece of evidence here, because it does not depend on the
universe: it is measured against the same universe with and without options.

---

## What failed — tested, not assumed

| Idea | Result | Why |
|---|---|---|
| **Buy calls on momentum names** (60Δ, 60 DTE, +100% target / −50% stop) | 13.57% CAGR vs 29.00% for equal-weight | Theta cost plus cutting winners at +100% while being stopped at −50%. Exactly backwards for momentum's fat right tail. |
| **Long calls as leverage** (2-3× delta notional) | CAGR up to 92% at **−98% drawdown** | Rolling long premium through a downtrend compounds total losses. Ruin, not a strategy. |
| **Deep-ITM LEAPS as stock replacement** (80Δ, 365 DTE, 1× notional) | 37.11% vs 45.56% for the shares | Pays ~8pp of theta for the same exposure, and can go to zero where shares cannot. |
| **Removing stops / profit targets on long calls** | 13.75% → 25.19% | Big improvement, still below equal-weight. Confirms the stop/target were harmful, not that long calls work. |
| **SPY protective put hedge** (15-30Δ, quarterly roll) | Cost 2-5pp CAGR, drawdown got **worse** (−54.3% vs −52.9%) | These drawdowns are idiosyncratic momentum crashes, not market beta. Index puts hedge the wrong risk. |

---

## Honest limitations

1. **Survivorship bias dominates** — see the attribution ladder. Prospectively you
   would not have known this universe. The defensible claims are the *relative*
   ones: momentum over equal-weight, and overlay over no-overlay.
2. **Drawdown is severe.** −51.9% out-of-sample. This is a concentrated,
   high-beta, high-volatility book. It is not a Sharpe-maximising strategy; it is
   a return-maximising one with drawdowns most people cannot hold through.
3. **The overlay has a fat left tail.** A 20Δ spread collects 9-16% of its width —
   MSFT collects $3.05 to risk $30.89. The 94% win rate is the flip side of a ~10:1
   loss-to-gain ratio per trade. Losses are bounded by the width, but a cluster of
   them in one drawdown is the real risk.
4. **Single-name IV is modelled**, as `realised_vol(60d) × 1.10`, and charged on
   entry and exit. Real single-name options have wider spreads and an IV term
   structure this does not capture. 5% slippage is applied both ways.
5. **PEAD is not backtested.** No historical earnings dates exist on this machine —
   the cache holds only each name's *next* date. Any PEAD signal is live-only and
   must not be presented as backtested.
6. **No transaction cost on the stock leg** beyond the option frictions, and no
   modelling of borrow, assignment, or corporate actions.

## Reproduce

```bash
python scripts/run_combined.py --start 2011-01-03 --end 2026-06-11
```
