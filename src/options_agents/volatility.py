"""Implied-volatility model driven by the listed vol indices.

There is no historical option-chain data on this machine, so implied vol is
reconstructed from the matching vol index (SPY<->VIX, QQQ<->VXN, IWM<->VIX with a
beta adjustment), then shaped across strike and tenor:

  * TERM STRUCTURE — VIX is a 30-day measure. Short-dated options normally trade
    at LOWER vol in calm markets and HIGHER vol in stress (the term structure
    inverts). VIX9D/VIX3M give the real slope where available; a calibrated
    fallback is used before 2011.

  * SKEW — equity index puts trade above ATM vol and calls below it. A flat-vol
    model would badly misprice a put credit spread: it would understate the credit
    received on the short leg AND overstate it on the long leg. Skew is modelled
    as a linear function of moneyness in log space, which is the first-order term
    of the observed smile and is what matters for 10-30 delta structures.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# index ETF -> its listed vol index
VOL_INDEX = {"SPY": "_VIX", "QQQ": "_VXN", "IWM": "_VIX"}
# IWM has no listed vol index in this dataset; RUT vol runs ~1.15x VIX
VOL_BETA = {"SPY": 1.00, "QQQ": 1.00, "IWM": 1.15}

# Equity-index skew: ~ -1.2 vol points per 10% down in moneyness at 30 DTE,
# steepening as expiry approaches. Calibrated to the shape of listed SPX skew.
SKEW_SLOPE_30D = 1.20
SKEW_TENOR_EXP = -0.35


@dataclass(frozen=True)
class VolSurface:
    """Vol surface for one underlying on one date."""
    atm_30d: float          # decimal, e.g. 0.18
    slope_9d: float | None  # VIX9D / VIX, when available
    slope_3m: float | None  # VIX3M / VIX, when available

    def term_factor(self, dte: float) -> float:
        """Scale 30-day ATM vol to `dte` days using the observed term slope."""
        dte = max(dte, 0.5)
        if dte <= 30:
            # interpolate in sqrt-time between the 9-day and 30-day points
            s9 = self.slope_9d if self.slope_9d else self._fallback_9d()
            if dte >= 9:
                w = (math.sqrt(dte) - 3.0) / (math.sqrt(30.0) - 3.0)
                return s9 + w * (1.0 - s9)
            return s9
        s3 = self.slope_3m if self.slope_3m else 1.05
        w = min(1.0, (math.sqrt(dte) - math.sqrt(30.0)) /
                (math.sqrt(91.0) - math.sqrt(30.0)))
        return 1.0 + w * (s3 - 1.0)

    def _fallback_9d(self) -> float:
        """Pre-2011 there is no VIX9D. In calm markets short vol trades below
        30-day vol; in stress it trades above. Keyed off the ATM level itself."""
        if self.atm_30d <= 0.15:
            return 0.88
        if self.atm_30d >= 0.35:
            return 1.15
        return 0.88 + (self.atm_30d - 0.15) * (1.15 - 0.88) / 0.20

    def iv(self, spot: float, strike: float, dte: float) -> float:
        """Implied vol for one contract, with term structure and skew applied."""
        base = self.atm_30d * self.term_factor(dte)
        m = math.log(strike / spot)                       # <0 for downside strikes
        slope = SKEW_SLOPE_30D * (max(dte, 1.0) / 30.0) ** SKEW_TENOR_EXP
        return max(0.02, base - slope * m * base)


def realised_vol(closes: list[float], window: int = 20) -> float | None:
    """Close-to-close annualised realised vol over the last `window` returns."""
    if len(closes) < window + 1:
        return None
    rets = [math.log(closes[i] / closes[i - 1]) for i in range(-window, 0)]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var * 252.0)


def iv_rank(history: list[float], current: float, lookback: int = 252) -> float | None:
    """Percentile rank of `current` within the trailing `lookback` window (0-100).

    Rank, not percentile-of-range: robust to a single spike defining the max.
    """
    w = history[-lookback:]
    if len(w) < 60:
        return None
    return 100.0 * sum(1 for v in w if v < current) / len(w)
