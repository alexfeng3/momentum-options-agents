"""Single-pot capital model. Shared by the backtester and the live agents.

There is one pot of money. It is never used twice. Every rule here is enforced by
an assertion that raises rather than by a comment that hopes:

  * cash >= 0 at all times.
  * A short option spread must reserve (width - credit) x 100 x qty in cash.
    Reserved cash cannot simultaneously buy stock.
  * Stock is bought only from unreserved cash.

An earlier version of the backtester allocated 100% of equity to stock and THEN
sold spreads against money already spent. That silent leverage inflated the
15-year CAGR by roughly 8 percentage points. This module exists so the same
mistake cannot be made twice, in either the backtest or live trading.
"""
from __future__ import annotations

from dataclasses import dataclass, field

CONTRACT_MULT = 100.0


class CapitalError(AssertionError):
    """Raised when an operation would spend money the account does not have."""


@dataclass
class Reservation:
    """Cash set aside to collateralise one defined-risk short position."""
    key: str
    amount: float
    note: str = ""


@dataclass
class Portfolio:
    cash: float
    shares: dict[str, float] = field(default_factory=dict)
    reservations: list[Reservation] = field(default_factory=list)

    # ------------------------------------------------------------------ views
    @property
    def reserved(self) -> float:
        return sum(r.amount for r in self.reservations)

    @property
    def free_cash(self) -> float:
        """Cash that is genuinely available. This is the number that matters."""
        return self.cash - self.reserved

    def stock_value(self, prices: dict[str, float]) -> float:
        return sum(q * prices.get(s, 0.0) for s, q in self.shares.items())

    def equity(self, prices: dict[str, float], option_liability: float = 0.0) -> float:
        return self.cash + self.stock_value(prices) - option_liability

    # ------------------------------------------------------------- invariants
    def assert_solvent(self, ctx: str = "") -> None:
        if self.cash < -1e-6:
            raise CapitalError(f"{ctx}: negative cash ${self.cash:,.2f}")
        if self.free_cash < -1e-6:
            raise CapitalError(
                f"{ctx}: reserved collateral ${self.reserved:,.2f} exceeds cash "
                f"${self.cash:,.2f} — capital would be used twice")

    # ---------------------------------------------------------------- actions
    def buy_stock(self, sym: str, qty: float, price: float,
                  cost_bps: float = 5.0) -> float:
        cost = qty * price * (1 + cost_bps / 10_000)
        if cost > self.free_cash + 1e-6:
            raise CapitalError(
                f"buy {qty:.4f} {sym} costs ${cost:,.2f} but free cash is "
                f"${self.free_cash:,.2f}")
        self.cash -= cost
        self.shares[sym] = self.shares.get(sym, 0.0) + qty
        self.assert_solvent(f"buy {sym}")
        return cost

    def sell_stock(self, sym: str, qty: float, price: float,
                   cost_bps: float = 5.0) -> float:
        have = self.shares.get(sym, 0.0)
        if qty > have + 1e-9:
            raise CapitalError(f"sell {qty} {sym} but only {have} held")
        proceeds = qty * price * (1 - cost_bps / 10_000)
        self.cash += proceeds
        rem = have - qty
        if rem <= 1e-9:
            self.shares.pop(sym, None)
        else:
            self.shares[sym] = rem
        return proceeds

    def open_short_spread(self, key: str, credit_total: float,
                          collateral: float, note: str = "") -> None:
        """Receive the credit, reserve the max loss. Refuses if unaffordable."""
        if collateral > self.free_cash + credit_total + 1e-6:
            raise CapitalError(
                f"{key}: collateral ${collateral:,.2f} exceeds free cash "
                f"${self.free_cash:,.2f} + credit ${credit_total:,.2f}")
        self.cash += credit_total
        self.reservations.append(Reservation(key, collateral, note))
        self.assert_solvent(f"open {key}")

    def close_short_spread(self, key: str, debit_total: float) -> None:
        self.cash -= debit_total
        self.reservations = [r for r in self.reservations if r.key != key]
        self.assert_solvent(f"close {key}")

    def max_contracts(self, per_contract_collateral: float,
                      per_contract_credit: float) -> int:
        """Largest position the free cash can actually collateralise."""
        if per_contract_collateral <= 0:
            return 0
        net = per_contract_collateral - per_contract_credit
        if net <= 0:
            net = per_contract_collateral
        return max(0, int(self.free_cash // net))
