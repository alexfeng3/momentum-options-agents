"""Agent 3 — Risk Oversight Agent. VETO AUTHORITY.

Reviews every proposal against paper-mode verification, market hours, the LLM
judgment layer, position and exposure caps, per-name concentration, and — most
importantly — the SINGLE-POT CAPITAL RULE: money cannot be used twice.

The Execution Agent refuses anything not carrying an APPROVE or REDUCE from here,
so the veto is structural rather than advisory. Explains every rejection.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Literal

from ..portfolio import CONTRACT_MULT, Portfolio

Action = Literal["APPROVE", "REDUCE", "REJECT"]


@dataclass
class Decision:
    symbol: str
    kind: str
    action: Action
    reason: str
    qty: float | None = None            # shares, for stock legs
    contracts: int | None = None        # for spreads
    notional: float | None = None
    collateral: float | None = None
    checks: list[dict] = field(default_factory=list)

    @property
    def approved(self) -> bool:
        return self.action in ("APPROVE", "REDUCE")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["approved"] = self.approved
        return d


class RiskAgent:
    name = "risk"

    def __init__(self, cfg, log):
        self.cfg, self.log = cfg, log

    def run(self, proposals, pf: Portfolio, prices: dict[str, float],
            equity: float, *, paper_verified: bool, market_open: bool,
            llm_review=None, as_of: date | None = None) -> list[Decision]:
        cfg = self.cfg
        out: list[Decision] = []

        # Exits first: they free capital and reduce risk, so they are never blocked
        # by exposure or concentration limits.
        for p in [x for x in proposals if x.kind == "SPREAD_EXIT"]:
            out.append(self._spread_exit(p, paper_verified, market_open))

        for p in [x for x in proposals if x.kind in ("EXIT", "TRIM")]:
            out.append(self._exit(p, pf, prices, paper_verified, market_open, equity))

        held_after = dict(pf.shares)
        for d in out:
            if d.approved and d.qty:
                held_after.pop(d.symbol, None)

        n_open = len(held_after)
        # Simulate capital as approvals accrue so two proposals cannot both spend
        # the same dollar.
        sim = Portfolio(cash=pf.cash, shares=dict(held_after),
                        reservations=list(pf.reservations))
        for d in out:
            if d.approved and d.qty and d.symbol in pf.shares:
                px = prices.get(d.symbol)
                if px:
                    try:
                        sim.sell_stock(d.symbol, d.qty, px)
                    except Exception:
                        pass

        for p in [x for x in proposals if x.kind not in ("EXIT", "TRIM", "SPREAD_EXIT")]:
            d = self._entry(p, sim, prices, equity, n_open,
                            paper_verified, market_open, llm_review)
            out.append(d)
            if d.approved:
                if p.kind in ("CORE", "PEAD") and d.qty:
                    try:
                        sim.buy_stock(p.symbol, d.qty, prices[p.symbol])
                        n_open += 1
                    except Exception as e:
                        d.action, d.reason = "REJECT", f"capital check failed: {e}"
                elif p.kind == "SPREAD" and d.contracts:
                    st = p.structure or {}
                    try:
                        sim.open_short_spread(
                            f"{p.symbol}-spread",
                            st["est_credit"] * CONTRACT_MULT * d.contracts,
                            d.collateral or 0.0)
                    except Exception as e:
                        d.action, d.reason = "REJECT", f"collateral check failed: {e}"

        self.log.emit(self.name, "decisions", {
            "equity": round(equity, 2), "cash": round(pf.cash, 2),
            "free_cash": round(pf.free_cash, 2), "reserved": round(pf.reserved, 2),
            "open_positions": len(pf.shares),
            "approved": sum(1 for d in out if d.approved),
            "rejected": sum(1 for d in out if not d.approved),
            "llm_available": bool(llm_review and llm_review.available),
            "decisions": [d.to_dict() for d in out]})
        return out

    # ------------------------------------------------------------------ exits
    def _spread_exit(self, p, paper_verified, market_open) -> Decision:
        """Closing a short spread returns collateral and removes a liability, so
        it is never subject to exposure, concentration or cash limits. The only
        hard gates are the ones that protect the account itself."""
        st = p.structure or {}
        if not paper_verified:
            return Decision(p.symbol, p.kind, "REJECT",
                            "Paper trading is not verified — all orders blocked.")
        if not market_open:
            return Decision(p.symbol, p.kind, "REJECT", "Market is closed.")
        n = int(st.get("contracts") or 0)
        if n < 1:
            return Decision(p.symbol, p.kind, "REJECT",
                            f"No open {p.symbol} spread to close.")
        return Decision(p.symbol, p.kind, "APPROVE",
                        f"Close approved — {n} contract(s), risk-reducing and "
                        f"not subject to exposure caps. {p.reason}",
                        contracts=n)

    def _exit(self, p, pf, prices, paper_verified, market_open,
              equity: float = 0.0) -> Decision:
        chk = []
        if not paper_verified:
            return Decision(p.symbol, p.kind, "REJECT",
                            "Paper trading is not verified — all orders blocked.", checks=chk)
        if not market_open:
            return Decision(p.symbol, p.kind, "REJECT", "Market is closed.", checks=chk)
        held = pf.shares.get(p.symbol, 0.0)
        if held <= 0:
            return Decision(p.symbol, p.kind, "REJECT",
                            f"No {p.symbol} position to exit.", checks=chk)

        if p.kind == "EXIT":
            return Decision(p.symbol, p.kind, "APPROVE",
                            "Exit approved — risk-reducing, not subject to exposure caps.",
                            qty=held, checks=chk)

        # TRIM sells only the EXCESS over target. Selling `held` here liquidates a
        # position the model still wants to own, and the rebalance would buy it
        # straight back next cycle, paying costs both ways.
        px = prices.get(p.symbol)
        if not px or not equity:
            return Decision(p.symbol, p.kind, "REJECT",
                            f"Cannot size a trim for {p.symbol} without a price "
                            f"and account equity.", checks=chk)
        target_val = equity * (p.target_weight or 0.0)
        excess_val = held * px - target_val
        if excess_val <= self.cfg.min_ticket:
            return Decision(p.symbol, p.kind, "REJECT",
                            f"Excess ${max(0.0, excess_val):,.2f} is below the "
                            f"${self.cfg.min_ticket:,.0f} minimum ticket — leaving it.",
                            checks=chk)
        qty = min(held, excess_val / px)
        return Decision(p.symbol, p.kind, "APPROVE",
                        f"Trimming {qty:.4f} sh (${excess_val:,.2f}) back to the "
                        f"${target_val:,.2f} target; keeping "
                        f"{held - qty:.4f} sh.", qty=qty, checks=chk)

    # ---------------------------------------------------------------- entries
    def _entry(self, p, sim: Portfolio, prices, equity, n_open,
               paper_verified, market_open, llm_review) -> Decision:
        cfg = self.cfg
        chk: list[dict] = []

        def rej(msg):
            return Decision(p.symbol, p.kind, "REJECT", msg, checks=chk)

        def add(cid, ok, detail):
            chk.append({"id": cid, "pass": bool(ok), "detail": detail})
            return ok

        if not add("R1", paper_verified, "paper verified"):
            return rej("Paper trading is not verified — all orders blocked.")
        if not add("R2", market_open, "market open"):
            return rej("Market is closed.")

        # LLM veto — advisory layer with hard veto, never a sizing input
        if llm_review and llm_review.available:
            j = llm_review.judgments.get(p.symbol)
            if j and j.vetoed:
                add("R3", False, f"llm veto: {j.reason}")
                return rej(f"Judgment Agent veto ({j.confidence:.0%} confidence): {j.reason}")
            if j and j.verdict == "caution":
                add("R3", True, f"llm caution: {j.reason}")

        px = prices.get(p.symbol)
        if not add("R4", px and px > 0, f"price={px}"):
            return rej(f"No usable price for {p.symbol}.")

        if p.kind in ("CORE", "PEAD"):
            if not add("R5", n_open < cfg.max_positions,
                       f"{n_open}/{cfg.max_positions}"):
                return rej(f"At the {cfg.max_positions}-position limit.")
            target = equity * (p.target_weight or 0.0)
            cap = equity * cfg.max_position_pct
            if target > cap:
                target = cap
            budget = min(target, max(0.0, sim.free_cash - equity * cfg.cash_floor))
            if not add("R6", budget >= cfg.min_ticket,
                       f"budget={budget:.2f} free_cash={sim.free_cash:.2f}"):
                return rej(
                    f"Only ${budget:,.2f} of unreserved cash available (free cash "
                    f"${sim.free_cash:,.2f}); minimum ticket is ${cfg.min_ticket:,.0f}. "
                    f"Capital is committed elsewhere and will not be double-spent.")
            qty = budget / px
            action = "REDUCE" if budget < target - 1e-6 else "APPROVE"
            return Decision(p.symbol, p.kind, action,
                            (f"{'Reduced to' if action=='REDUCE' else 'Approved'} "
                             f"${budget:,.2f} ({qty:.4f} sh) — "
                             f"{n_open+1}/{cfg.max_positions} positions, free cash "
                             f"${sim.free_cash:,.2f}."),
                            qty=qty, notional=budget, checks=chk)

        if p.kind == "SPREAD":
            st = p.structure or {}
            per_risk = st.get("max_loss_per_contract", 0.0)
            per_credit = st.get("est_credit", 0.0) * CONTRACT_MULT
            if not add("R7", per_risk > 0, f"per_contract_risk={per_risk}"):
                return rej("Spread has no defined risk — refusing.")
            room = equity * cfg.max_overlay_risk - sim.reserved
            if not add("R8", room >= per_risk, f"overlay_room={room:.2f}"):
                return rej(
                    f"Overlay risk budget exhausted: ${sim.reserved:,.2f} reserved "
                    f"against a ${equity*cfg.max_overlay_risk:,.2f} cap.")
            budget_n = int((equity * cfg.risk_per_spread) // per_risk)
            room_n = int(room // per_risk)
            affordable = sim.max_contracts(per_risk, per_credit)
            n = min(budget_n, room_n, affordable)
            if not add("R9", n >= 1,
                       f"budget_n={budget_n} room_n={room_n} affordable={affordable} "
                       f"free_cash={sim.free_cash:.2f}"):
                # Report the constraint that actually bound. Saying "cannot
                # collateralise" while quoting ample free cash is worse than no
                # message at all — it sends you debugging the wrong subsystem.
                if budget_n < 1:
                    return rej(
                        f"One contract risks ${per_risk:,.2f}, more than the "
                        f"${equity*cfg.risk_per_spread:,.2f} per-spread risk budget "
                        f"({cfg.risk_per_spread:.0%} of equity). The spread is too wide "
                        f"for this account — not a cash problem.")
                if room_n < 1:
                    return rej(
                        f"Overlay risk budget exhausted: ${sim.reserved:,.2f} of "
                        f"${equity*cfg.max_overlay_risk:,.2f} already reserved.")
                return rej(
                    f"Cannot collateralise one contract: needs ${per_risk:,.2f} but "
                    f"only ${sim.free_cash:,.2f} of unreserved cash is available.")
            action = "REDUCE" if n < budget_n else "APPROVE"
            return Decision(p.symbol, p.kind, action,
                            (f"{'Reduced to' if action=='REDUCE' else 'Approved'} {n} "
                             f"contract(s), ${per_risk*n:,.2f} collateral reserved "
                             f"from ${sim.free_cash:,.2f} free cash."),
                            contracts=n, collateral=per_risk * n, checks=chk)

        return rej(f"Unknown proposal kind {p.kind}.")
