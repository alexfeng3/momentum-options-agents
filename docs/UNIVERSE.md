# Does the edge survive a universe I did not pick?

The 39-name universe inherited from the original project was hand-picked in 2026.
It contains NVDA, PLTR, COIN, AVGO — the winners of the AI era. Any long-only
strategy on it looks brilliant. This document tests the strategy on a universe
built by a mechanical rule instead.

## Building the control universe

`scripts/fetch_broad_universe.py` takes every US equity Alpaca lists on a major
exchange (active **and** inactive), pulls daily bars from 2020-08, and keeps
anything with ≥400 bars and median dollar volume ≥ $3M. No judgement about which
names are interesting. Result: **921 symbols**.

Alpaca's inactive-asset list turned out to be ~85% OTC shells and omits most
notable failures — FRCB, SIVBQ and BBBYQ are absent from it, though the *data* API
still serves their bars. `scripts/augment_failures.py` therefore requests a
curated list of known bankruptcies, failed SPACs, meme collapses, bank failures
and buyouts by name, adding 30 more (24 of which stopped trading). Final universe:
**951 symbols, 29 of them dead (3.0%)**.

**This is still imperfect.** A true point-in-time universe would have a higher
delisting rate than 3%, and the failure list is curated, which favours *memorable*
failures. But it removes the thing that mattered most: nobody chose these names
because they went up.

## Result (2021-09 to 2026-08, Alpaca IEX daily)

| Portfolio | Return | maxDD | Sharpe | Beta | Alpha (ann) |
|---|---|---|---|---|---|
| SPY buy & hold | +70.7% | −25.4% | 0.60 | 1.00 | — |
| Momentum top-6, **39 hand-picked names** | +726.8% | −39.0% | 1.30 | 0.93 | +45.7% |
| Momentum top-6, **951 mechanical names** | **+329.2%** | −38.2% | **0.93** | 0.85 | **+28.7%** |
| top-10, $50M ADV, vol ≤ 60% | +112.9% | **−21.2%** | 0.73 | 0.64 | +9.4% |
| top-10, $100M ADV, vol ≤ 50% | +48.1% | −33.0% | 0.42 | 0.60 | +1.3% |

**The edge survives.** On a universe nobody curated, momentum still returns
+329.2% against SPY's +70.7%, with a better Sharpe (0.93 vs 0.60) and +28.7%
annual alpha.

**But roughly 40% of the headline alpha was universe selection** (+45.7% → +28.7%).
Anyone quoting the narrow-universe number without this table is overstating the
strategy by a large margin.

**And the edge lives in volatility.** Screening to the largest, calmest names
($100M ADV, vol ≤ 50%) collapses alpha to +1.3% — statistically nothing. This is
not a large-cap quality strategy dressed up as momentum; it is a
high-volatility-momentum strategy, and its returns come from taking risk that most
allocators would not hold. The $50M / vol ≤ 60% variant is the sensible
risk-adjusted compromise: less return, but a drawdown (−21.2%) smaller than SPY's.

## A bug worth recording

The first broad-universe run produced −76% to −91% drawdowns and absurd alpha
(+468%/yr). Those were not real. When a held name delisted, `close()` returned
`None` and the position was marked to **zero**. Most series that end are
*acquisitions* — ATVI, VMW, XLNX, TWTR — which paid out at a premium, so the
backtest was booking total losses on takeovers.

Fix: `HistoricalBook.last_price()` liquidates a delisted holding at its **last
traded price**. Bankruptcies end near zero anyway, so the same rule handles both.
After the fix the drawdown fell from −76.6% to −38.2%, which is the honest number.

This is exactly the kind of bug that makes a survivorship-bias control produce
*worse* results than the biased universe and gets dismissed as "the broad universe
just doesn't work".

## Reproduce

```bash
python scripts/fetch_broad_universe.py && python scripts/augment_failures.py
```

```bash
python scripts/test_universe.py
```
