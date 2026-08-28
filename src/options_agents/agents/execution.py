"""Agent 4 — Execution Agent.

Submits ONLY risk-approved orders to Alpaca paper trading. Stock legs are simple
market orders; option spreads are multi-leg (mleg) limit orders, which is what
Alpaca requires for defined-risk structures.

Contains no strategy logic and no risk logic. If handed an unapproved decision it
RAISES rather than submitting — the veto is structural.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

from ..broker import NotPaperTradingError
from ..eventlog import ET


@dataclass
class OrderResult:
    symbol: str
    kind: str
    side: str
    qty: float | None
    contracts: int | None
    order_id: str | None
    client_order_id: str
    status: str
    submitted_at: str
    filled_qty: float = 0.0
    filled_avg_price: float | None = None
    legs: list[dict] | None = None
    dry_run: bool = False
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class ExecutionAgent:
    name = "execution"

    def __init__(self, broker, cfg, log, dry_run: bool = True):
        self.broker, self.cfg, self.log, self.dry_run = broker, cfg, log, dry_run

    def run(self, decisions, snap) -> list[OrderResult]:
        approved = [d for d in decisions if d.approved]
        if not approved:
            self.log.emit(self.name, "nothing_to_execute",
                          {"decisions_seen": len(decisions)})
            return []
        try:
            open_syms = {o["symbol"] for o in self.broker.get_open_orders()
                         if str(o.get("client_order_id", "")).startswith(self.cfg.coid_prefix)}
        except Exception as e:
            self.log.emit(self.name, "open_order_check_failed", {"error": str(e)})
            open_syms = set()

        out = []
        # exits first so their capital is available to the entries
        for d in sorted(approved, key=lambda x: 0 if x.kind == "EXIT" else 1):
            out.append(self._submit(d, snap, open_syms))
        return out

    def _submit(self, d, snap, open_syms) -> OrderResult:
        if not d.approved:
            raise RuntimeError(f"Execution refused: {d.symbol} is {d.action}.")
        now = datetime.now(ET)
        coid = f"{self.cfg.coid_prefix}-{d.kind.lower()}-{d.symbol}-{int(time.time()*1000)}"

        if d.symbol in open_syms:
            r = OrderResult(d.symbol, d.kind, "-", d.qty, d.contracts, None, coid,
                            "skipped_duplicate", now.isoformat(),
                            error="an open strategy order already exists")
            self.log.emit(self.name, "order_skipped", r.to_dict())
            return r

        if d.kind == "SPREAD":
            return self._submit_spread(d, snap, coid, now)
        return self._submit_stock(d, coid, now)

    # ------------------------------------------------------------------ stock
    def _submit_stock(self, d, coid, now) -> OrderResult:
        side = "sell" if d.kind == "EXIT" else "buy"
        req = {"symbol": d.symbol, "side": side, "qty": d.qty,
               "notional": d.notional, "client_order_id": coid,
               "dry_run": self.dry_run}
        self.log.emit(self.name, "order_request", req)
        if self.dry_run:
            print(f"  [DRY-RUN] {side.upper():<4} {d.symbol:<6} "
                  f"{d.qty:.4f} sh  ({d.kind})")
            r = OrderResult(d.symbol, d.kind, side, d.qty, None, None, coid,
                            "dry_run", now.isoformat(), dry_run=True)
            self.log.emit(self.name, "order_response", r.to_dict())
            return r
        if not self.broker.verified:
            raise NotPaperTradingError("paper mode not verified at submit time")
        try:
            o = self.broker.submit_equity_order(symbol=d.symbol, side=side,
                                                qty=d.qty, client_order_id=coid)
        except Exception as e:
            r = OrderResult(d.symbol, d.kind, side, d.qty, None, None, coid,
                            "error", now.isoformat(), error=str(e))
            self.log.emit(self.name, "order_error", r.to_dict())
            return r
        o = self.broker.poll_fill(o["id"], self.cfg.fill_poll_seconds)
        r = OrderResult(d.symbol, d.kind, side, d.qty, None, o["id"],
                        o["client_order_id"], o["status"], o["submitted_at"],
                        float(o.get("filled_qty") or 0),
                        float(o["filled_avg_price"]) if o.get("filled_avg_price") else None)
        self.log.emit(self.name, "order_response", r.to_dict())
        return r

    # ----------------------------------------------------------------- spread
    def _submit_spread(self, d, snap, coid, now) -> OrderResult:
        st = getattr(d, "structure", None) or self._structure_from(snap, d.symbol)
        if not st:
            r = OrderResult(d.symbol, d.kind, "sell_to_open", None, d.contracts,
                            None, coid, "error", now.isoformat(),
                            error="no structure available")
            self.log.emit(self.name, "order_error", r.to_dict())
            return r
        try:
            legs = self._resolve_contracts(st)
        except Exception as e:
            r = OrderResult(d.symbol, d.kind, "sell_to_open", None, d.contracts,
                            None, coid, "error", now.isoformat(),
                            error=f"contract lookup failed: {e}")
            self.log.emit(self.name, "order_error", r.to_dict())
            return r

        # Credit spread: Alpaca mleg uses a net-debit convention, so a credit is a
        # negative limit price. Give up a little edge to get filled.
        limit = -abs(st["est_credit"]) * (1 - self.cfg.limit_giveup)
        req = {"symbol": d.symbol, "contracts": d.contracts, "legs": legs,
               "limit_price": round(limit, 2), "client_order_id": coid,
               "dry_run": self.dry_run, "structure": st}
        self.log.emit(self.name, "order_request", req)

        if self.dry_run:
            print(f"  [DRY-RUN] SELL {d.symbol:<6} put spread {st['long_strike']}"
                  f"/{st['short_strike']} x{d.contracts} @ net credit "
                  f"{abs(limit):.2f}  (max loss ${(d.collateral or 0):,.0f})")
            r = OrderResult(d.symbol, d.kind, "sell_to_open", None, d.contracts,
                            None, coid, "dry_run", now.isoformat(),
                            legs=legs, dry_run=True)
            self.log.emit(self.name, "order_response", r.to_dict())
            return r

        if not self.broker.verified:
            raise NotPaperTradingError("paper mode not verified at submit time")
        try:
            o = self.broker.submit_spread_order(legs=legs, qty=d.contracts,
                                                limit_price=limit,
                                                client_order_id=coid)
        except Exception as e:
            r = OrderResult(d.symbol, d.kind, "sell_to_open", None, d.contracts,
                            None, coid, "error", now.isoformat(), legs=legs,
                            error=str(e))
            self.log.emit(self.name, "order_error", r.to_dict())
            return r
        o = self.broker.poll_fill(o["id"], self.cfg.fill_poll_seconds)
        r = OrderResult(d.symbol, d.kind, "sell_to_open", None, d.contracts,
                        o["id"], o["client_order_id"], o["status"],
                        o["submitted_at"], float(o.get("filled_qty") or 0),
                        None, legs=legs)
        self.log.emit(self.name, "order_response", r.to_dict())
        return r

    def _structure_from(self, snap, sym):
        return None

    def _resolve_contracts(self, st) -> list[dict]:
        """Map model strikes onto real listed OCC contracts."""
        target = date.fromisoformat(st["expiry_target"])
        lo = (target - timedelta(days=10)).isoformat()
        hi = (target + timedelta(days=10)).isoformat()
        contracts = self.broker.get_option_contracts(
            st["underlying"], expiration_gte=lo, expiration_lte=hi,
            option_type="put",
            strike_gte=st["long_strike"] * 0.85,
            strike_lte=st["short_strike"] * 1.15)
        if not contracts:
            raise RuntimeError("no listed put contracts in the target window")
        # one expiry: the one closest to target with the most strikes
        by_exp: dict[str, list] = {}
        for c in contracts:
            by_exp.setdefault(c["expiration_date"], []).append(c)
        exp = min(by_exp, key=lambda e: (abs((date.fromisoformat(e) - target).days),
                                         -len(by_exp[e])))
        chain = sorted(by_exp[exp], key=lambda c: float(c["strike_price"]))
        short = min(chain, key=lambda c: abs(float(c["strike_price"]) - st["short_strike"]))
        long_ = min(chain, key=lambda c: abs(float(c["strike_price"]) - st["long_strike"]))
        if short["symbol"] == long_["symbol"]:
            raise RuntimeError("short and long legs resolved to the same contract")
        if float(long_["strike_price"]) >= float(short["strike_price"]):
            raise RuntimeError("long strike is not below the short strike — not a credit spread")
        return [
            {"symbol": short["symbol"], "ratio_qty": "1", "side": "sell",
             "position_intent": "sell_to_open"},
            {"symbol": long_["symbol"], "ratio_qty": "1", "side": "buy",
             "position_intent": "buy_to_open"},
        ]
