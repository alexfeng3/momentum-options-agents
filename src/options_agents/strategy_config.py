"""Live strategy configuration. Mirrors the backtested parameters."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


def _f(k, d):
    return float(os.getenv(k, d))


def _i(k, d):
    return int(float(os.getenv(k, d)))


def _b(k, d):
    return os.getenv(k, str(d)).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class LiveConfig:
    # --- universe (mechanically screened; see docs/UNIVERSE.md) ----------
    universe: tuple[str, ...] = ()
    min_price: float = 10.0
    max_vol: float | None = 0.60
    min_dollar_volume: float = 50_000_000.0

    # --- momentum core ---------------------------------------------------
    top_n: int = 6
    core_weight: float = 0.80        # fraction of equity in the core sleeve
    max_positions: int = 10
    max_position_pct: float = 0.20
    rebalance_days: int = 21
    # Do not trade a position already within this fraction of its target weight.
    # Without a band the book churns every cycle and pays costs for nothing.
    rebalance_band: float = 0.25
    market_filter: bool = True

    # --- PEAD sleeve -----------------------------------------------------
    pead_weight: float = 0.05
    pead_window: int = 10            # look back this far for a recent event
    pead_entry_days: int = 3         # enter within N days of the announcement
    sue_min: float = 0.5
    gap_min: float = 0.01
    vol_ratio_min: float = 1.3

    # --- options overlay -------------------------------------------------
    overlay_enabled: bool = True
    short_delta: float = 0.20
    width_pct: float = 0.10
    # Hard cap on spread width in dollars. Without it, high-priced names produce
    # a per-contract max loss larger than the per-spread risk budget and are
    # silently rejected every cycle.
    max_width_dollars: float = 25.0
    dte: int = 30
    iv_rank_min: float = 20.0
    risk_per_spread: float = 0.03
    max_overlay_risk: float = 0.15
    iv_premium: float = 1.10
    slippage: float = 0.05
    # How far to concede from the spread's mid toward its natural (immediately
    # marketable) price. 0.0 asks the mid and rarely fills; 1.0 crosses both legs
    # and fills at once. Was `limit_giveup`, a fraction of a Black-Scholes credit
    # that had no relation to any real bid/ask.
    limit_cross: float = 0.50

    # --- capital ---------------------------------------------------------
    cash_floor: float = 0.02         # always keep this fraction unspent
    min_ticket: float = 100.0

    # --- plumbing --------------------------------------------------------
    coid_prefix: str = "moqa"        # momentum-options quant agent
    fill_poll_seconds: float = 8.0
    data_dir: Path = field(default_factory=lambda: ROOT / "data" / "broad")

    @classmethod
    def from_env(cls, universe: tuple[str, ...]) -> "LiveConfig":
        return cls(
            universe=universe,
            top_n=_i("TOP_N", 6),
            core_weight=_f("CORE_WEIGHT", 0.80),
            max_positions=_i("MAX_POSITIONS", 10),
            max_position_pct=_f("MAX_POSITION_PCT", 0.20),
            market_filter=_b("MARKET_FILTER", True),
            overlay_enabled=_b("OVERLAY_ENABLED", True),
            short_delta=_f("SHORT_DELTA", 0.20),
            width_pct=_f("WIDTH_PCT", 0.10),
            dte=_i("DTE", 30),
            iv_rank_min=_f("IV_RANK_MIN", 20.0),
            limit_cross=_f("LIMIT_CROSS", 0.50),
            risk_per_spread=_f("RISK_PER_SPREAD", 0.03),
            max_overlay_risk=_f("MAX_OVERLAY_RISK", 0.15),
            min_price=_f("MIN_PRICE", 10.0),
            max_vol=_f("MAX_VOL", 0.60),
        )
