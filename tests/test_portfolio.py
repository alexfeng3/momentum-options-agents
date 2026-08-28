"""Capital invariants. These are the tests that would have caught the 8pp
inflation from spending the same dollar twice."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from options_agents.portfolio import CapitalError, Portfolio


def test_cannot_spend_more_than_free_cash():
    pf = Portfolio(cash=1000.0)
    with pytest.raises(CapitalError, match="free cash"):
        pf.buy_stock("AAPL", 100, 50.0)          # $5,000 of stock on $1,000


def test_reserved_collateral_is_not_spendable():
    """THE regression test. Sell a spread, then try to spend the collateral."""
    pf = Portfolio(cash=10_000.0)
    pf.open_short_spread("X", credit_total=200.0, collateral=8_000.0)
    assert pf.cash == pytest.approx(10_200.0)
    assert pf.reserved == pytest.approx(8_000.0)
    assert pf.free_cash == pytest.approx(2_200.0)
    pf.buy_stock("AAPL", 20, 100.0)              # $2,000 — fits in free cash
    with pytest.raises(CapitalError):
        pf.buy_stock("MSFT", 50, 100.0)          # would dip into collateral


def test_closing_a_spread_releases_its_collateral():
    pf = Portfolio(cash=10_000.0)
    pf.open_short_spread("X", 200.0, 8_000.0)
    assert pf.free_cash == pytest.approx(2_200.0)
    pf.close_short_spread("X", debit_total=50.0)
    assert pf.reserved == 0.0
    assert pf.free_cash == pytest.approx(10_150.0)


def test_cannot_open_a_spread_it_cannot_collateralise():
    pf = Portfolio(cash=1_000.0)
    with pytest.raises(CapitalError, match="collateral"):
        pf.open_short_spread("X", credit_total=50.0, collateral=9_000.0)


def test_cannot_sell_shares_it_does_not_own():
    pf = Portfolio(cash=0.0, shares={"AAPL": 10})
    with pytest.raises(CapitalError, match="only"):
        pf.sell_stock("AAPL", 20, 100.0)


def test_round_trip_conserves_money_minus_costs():
    pf = Portfolio(cash=10_000.0)
    pf.buy_stock("AAPL", 50, 100.0, cost_bps=5)
    pf.sell_stock("AAPL", 50, 100.0, cost_bps=5)
    assert pf.cash < 10_000.0                     # costs were actually charged
    assert pf.cash == pytest.approx(10_000.0 - 2 * 5_000 * 5 / 10_000, abs=1e-6)


def test_max_contracts_respects_free_cash():
    pf = Portfolio(cash=10_000.0)
    pf.open_short_spread("X", 0.0, 9_000.0)
    assert pf.max_contracts(per_contract_collateral=500.0,
                            per_contract_credit=0.0) == 2      # $1,000 free
    assert pf.max_contracts(per_contract_collateral=5_000.0,
                            per_contract_credit=0.0) == 0


def test_equity_accounts_for_option_liability():
    pf = Portfolio(cash=10_000.0, shares={"AAPL": 10})
    eq = pf.equity({"AAPL": 100.0}, option_liability=500.0)
    assert eq == pytest.approx(10_000 + 1_000 - 500)


def test_solvency_assertion_fires_on_manual_corruption():
    pf = Portfolio(cash=100.0)
    pf.reservations.append(type(pf.reservations)and __import__(
        "options_agents.portfolio", fromlist=["Reservation"]).Reservation("z", 500.0))
    with pytest.raises(CapitalError, match="used twice"):
        pf.assert_solvent("test")
