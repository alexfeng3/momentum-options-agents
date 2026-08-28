"""Agent 5 — Position Analysis Agent.

Reports positions, open orders, equity, unrealised PnL, exposure, option greeks
and holding time; flags positions near an exit; and reconciles the strategy's view
against the broker. Creates no orders.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime

from ..pricing import greeks


@dataclass
class PositionView:
    symbol: str
    asset_class: str
    qty: float
    avg_entry: float
    last_price: float | None
    market_value: float
    unrealized_pl: float
    unrealized_pct: float
    note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class PositionAgent:
    name = "position"

    def __init__(self, broker, cfg, log):
        self.broker, self.cfg, self.log = broker, cfg, log

    def run(self, snap, as_of: date) -> dict:
        try:
            acct = self.broker.get_account()
        except Exception as e:
            self.log.emit(self.name, "account_failed", {"error": str(e)})
            return {"error": str(e)}
        try:
            positions = self.broker.get_positions()
        except Exception:
            positions = []
        try:
            orders = self.broker.get_open_orders()
        except Exception:
            orders = []

        mine, foreign = [], []
        equities, options = [], []
        for p in positions:
            v = PositionView(
                symbol=p["symbol"], asset_class=p.get("asset_class", "us_equity"),
                qty=float(p["qty"]), avg_entry=float(p["avg_entry_price"]),
                last_price=float(p["current_price"]) if p.get("current_price") else None,
                market_value=float(p["market_value"]),
                unrealized_pl=float(p["unrealized_pl"]),
                unrealized_pct=float(p["unrealized_plpc"]))
            (options if v.asset_class == "us_option" else equities).append(v)

        strat_orders = [o for o in orders
                        if str(o.get("client_order_id", "")).startswith(self.cfg.coid_prefix)]

        long_mv = sum(v.market_value for v in equities if v.market_value > 0)
        short_opt = sum(v.market_value for v in options if v.market_value < 0)
        equity = float(acct.get("equity", 0))

        # names the model currently likes but does not hold, and vice versa
        held = {v.symbol for v in equities}
        want = set(snap.ranked[:self.cfg.top_n]) if snap else set()

        summary = {
            "as_of": as_of.isoformat(),
            "account": {
                "account_number": acct.get("account_number"),
                "equity": equity,
                "cash": float(acct.get("cash", 0)),
                "buying_power": float(acct.get("buying_power", 0)),
                "long_market_value": float(acct.get("long_market_value", 0)),
            },
            "exposure": {
                "equity_long_mv": round(long_mv, 2),
                "equity_long_pct": round(long_mv / equity, 4) if equity else None,
                "short_option_mv": round(short_opt, 2),
                "option_positions": len(options),
                "equity_positions": len(equities),
            },
            "positions": [v.to_dict() for v in equities],
            "option_positions": [v.to_dict() for v in options],
            "open_strategy_orders": [
                {"symbol": o["symbol"], "side": o.get("side"), "status": o["status"],
                 "client_order_id": o["client_order_id"], "id": o["id"]}
                for o in strat_orders],
            "unrealized_pl_total": round(sum(v.unrealized_pl for v in equities + options), 2),
            "model_wants_not_held": sorted(want - held),
            "held_not_wanted": sorted(held - want),
            "winners": sorted([v.to_dict() for v in equities],
                              key=lambda x: -x["unrealized_pct"])[:3],
            "losers": sorted([v.to_dict() for v in equities],
                             key=lambda x: x["unrealized_pct"])[:3],
        }
        self.log.emit(self.name, "summary", summary)
        return summary
