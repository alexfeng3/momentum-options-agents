"""Agent 2 — Strategy Agent.

Turns the market snapshot into concrete proposals:
  * CORE   — equal-weight stock positions in the top-N momentum names.
  * PEAD   — a stock position when a real SEC earnings event shows a positive SUE
             AND a volume-confirmed positive gap.
  * SPREAD — a defined-risk short put spread on a name already selected, but only
             where the backtest says it pays: when free cash would otherwise sit
             idle (see docs/DIRECTIONAL.md — the overlay is a drag on a fully
             invested momentum book, and additive on the cash-heavy PEAD sleeve).

Applies the rules only. Checks no risk limits, sizes nothing against the live
account, and places no orders. Pure enough to be reused by the backtester.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Literal

from ..pricing import price, strike_for_delta
from ..selection import realised_vol

Kind = Literal["CORE", "PEAD", "SPREAD", "EXIT", "TRIM"]


@dataclass
class Proposal:
    symbol: str
    kind: Kind
    side: str                     # BUY | SELL | SELL_TO_OPEN
    target_weight: float | None   # fraction of equity, for stock legs
    reason: str
    signals: dict = field(default_factory=dict)
    structure: dict | None = None   # spread legs, when kind == SPREAD

    def to_dict(self) -> dict:
        return asdict(self)


class StrategyAgent:
    name = "strategy"

    def __init__(self, cfg, log):
        self.cfg, self.log = cfg, log

    def run(self, snap, held: dict[str, float], book, as_of: date,
            held_value: dict[str, float] | None = None,
            equity: float | None = None) -> list[Proposal]:
        """`held_value` is the CURRENT dollar value of each holding and `equity`
        the account total. Without them the agent cannot tell a fresh entry from
        a position already at target weight, and re-buys the whole book every
        cycle."""
        cfg = self.cfg
        out: list[Proposal] = []
        held_value = held_value or {}

        # ---- regime gate: SPY below its 200-day SMA means no new risk --------
        if cfg.market_filter and not snap.spy_above_sma200:
            for sym in held:
                out.append(Proposal(sym, "EXIT", "SELL", 0.0,
                                    "Regime filter: SPY is below its 200-day SMA — "
                                    "the strategy holds cash.",
                                    {"spy_above_sma200": False}))
            self.log.emit(self.name, "proposals",
                          {"regime": "risk_off", "count": len(out),
                           "all": [p.to_dict() for p in out]})
            return out

        # ---- core momentum sleeve -------------------------------------------
        picks = [s for s in snap.ranked if s in snap.names][:cfg.top_n]
        weight = cfg.core_weight / max(1, len(picks)) if picks else 0.0
        for sym in picks:
            n = snap.names[sym]
            rank_txt = (f"Momentum rank {picks.index(sym)+1}/{len(picks)}: 12-1 return "
                        f"{(n.mom_12_1 or 0):+.1%}, 3-month {(n.mom_3m or 0):+.1%}, "
                        f"vol {(n.realised_vol or 0):.0%}, trend {n.trend}.")
            sig = {"score": n.momentum_score, "mom_12_1": n.mom_12_1,
                   "mom_3m": n.mom_3m, "vol": n.realised_vol, "trend": n.trend}

            # Net against what is already held. Emitting the full target weight
            # for a position already at target re-buys the entire book every cycle.
            if equity:
                target_val = equity * weight
                cur = held_value.get(sym, 0.0)
                gap = target_val - cur
                band = max(cfg.min_ticket, target_val * cfg.rebalance_band)
                if abs(gap) < band:
                    sig["already_at_target"] = True
                    continue                       # in band: leave it alone
                if gap < 0:
                    out.append(Proposal(
                        sym, "TRIM", "SELL", weight,
                        f"{rank_txt} Position is ${-gap:,.0f} above its "
                        f"${target_val:,.0f} target — trimming.", sig))
                    continue
                sig["gap_to_target"] = round(gap, 2)
                sig["current_value"] = round(cur, 2)
                out.append(Proposal(sym, "CORE", "BUY", gap / equity,
                                    f"{rank_txt} Adding ${gap:,.0f} to reach the "
                                    f"${target_val:,.0f} target.", sig))
                continue
            out.append(Proposal(sym, "CORE", "BUY", weight, rank_txt, sig))

        # ---- exits: held names that dropped out of the ranking ---------------
        for sym in held:
            if sym not in picks:
                out.append(Proposal(sym, "EXIT", "SELL", 0.0,
                                    "No longer in the top-N momentum ranking.",
                                    {"in_ranking": False}))

        # ---- PEAD sleeve -----------------------------------------------------
        for sym, n in snap.names.items():
            e = n.recent_earnings
            if not e or e.get("days_since", 99) > cfg.pead_entry_days:
                continue
            if (e.get("sue") or -9) < cfg.sue_min:
                continue
            if (e.get("gap_pct") or -9) < cfg.gap_min:
                continue
            if (e.get("vol_ratio") or 0) < cfg.vol_ratio_min:
                continue
            if sym in picks:
                continue
            out.append(Proposal(
                sym, "PEAD", "BUY", cfg.pead_weight,
                f"Post-earnings drift: SUE {e['sue']:+.2f} with a "
                f"{e['gap_pct']:+.1%} volume-confirmed gap "
                f"({e['vol_ratio']:.1f}x) {e['days_since']}d ago.",
                {"sue": e["sue"], "gap_pct": e["gap_pct"],
                 "vol_ratio": e["vol_ratio"], "days_since": e["days_since"]}))

        # ---- defined-risk short put spreads ---------------------------------
        if cfg.overlay_enabled:
            for p in [x for x in out if x.kind in ("CORE", "PEAD")]:
                st = self._spread(p.symbol, snap, book, as_of)
                if st:
                    out.append(Proposal(
                        p.symbol, "SPREAD", "SELL_TO_OPEN", None,
                        f"Short {cfg.short_delta:.0%}-delta put spread on a name the "
                        f"model is already long — bullish exposure with positive "
                        f"theta instead of paying it.",
                        {"iv": st["iv"], "iv_rank": st["iv_rank"]}, st))

        self.log.emit(self.name, "proposals", {
            "regime": "risk_on",
            "core": sum(1 for p in out if p.kind == "CORE"),
            "pead": sum(1 for p in out if p.kind == "PEAD"),
            "spreads": sum(1 for p in out if p.kind == "SPREAD"),
            "exits": sum(1 for p in out if p.kind == "EXIT"),
            "all": [p.to_dict() for p in out]})
        return out

    def _spread(self, sym, snap, book, as_of) -> dict | None:
        cfg = self.cfg
        n = snap.names.get(sym)
        if not n or not n.last_price or not n.iv_estimate:
            return None
        if n.iv_rank is not None and n.iv_rank < cfg.iv_rank_min:
            return None
        spot, iv = n.last_price, n.iv_estimate
        T = cfg.dte / 365.0
        r = book.risk_free(as_of)
        ks = round(strike_for_delta(spot, T, r, iv, cfg.short_delta, "put"), 2)
        # Width scales with price, but a $528 stock at 10% gives a $5,280 max loss
        # per contract — larger than the whole per-spread risk budget, so the risk
        # agent rejects it every time. Cap the width so one contract always fits.
        width = max(1.0, round(spot * cfg.width_pct, 2))
        if cfg.max_width_dollars:
            width = min(width, cfg.max_width_dollars)
        kl = round(ks - width, 2)
        if kl <= 0:
            return None
        credit = (price(spot, ks, T, r, iv, "put")
                  - price(spot, kl, T, r, iv, "put")) * (1 - cfg.slippage)
        if credit <= 0.05:
            return None
        return {"underlying": sym, "spot": spot, "iv": iv,
                "iv_rank": n.iv_rank, "short_strike": ks, "long_strike": kl,
                "width": width, "est_credit": round(credit, 2),
                "max_loss_per_contract": round((width - credit) * 100, 2),
                "expiry_target": (as_of + timedelta(days=cfg.dte)).isoformat(),
                "dte": cfg.dte}
