"""Agent-boundary tests: the risk agent's veto must be structural."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from options_agents.agents.execution import ExecutionAgent
from options_agents.agents.risk import Decision, RiskAgent
from options_agents.agents.strategy import Proposal
from options_agents.portfolio import Portfolio
from options_agents.strategy_config import LiveConfig


class NullLog:
    def emit(self, *a, **k):
        return {}


CFG = LiveConfig(universe=("AAA", "BBB", "CCC"))
PRICES = {"AAA": 100.0, "BBB": 50.0, "CCC": 25.0}


def core(sym, w=0.2):
    return Proposal(sym, "CORE", "BUY", w, "momentum", {})


def risk():
    return RiskAgent(CFG, NullLog())


def test_everything_is_rejected_when_paper_is_unverified():
    d = risk().run([core("AAA")], Portfolio(cash=100_000), PRICES, 100_000,
                   paper_verified=False, market_open=True)[0]
    assert d.action == "REJECT" and "not verified" in d.reason


def test_everything_is_rejected_when_market_is_closed():
    d = risk().run([core("AAA")], Portfolio(cash=100_000), PRICES, 100_000,
                   paper_verified=True, market_open=False)[0]
    assert d.action == "REJECT" and "closed" in d.reason


def test_llm_veto_blocks_a_trade():
    from options_agents.llm import Judgment, LLMReview
    rev = LLMReview(available=True,
                    judgments={"AAA": Judgment("AAA", "veto", 0.9, "accounting probe")})
    d = risk().run([core("AAA")], Portfolio(cash=100_000), PRICES, 100_000,
                   paper_verified=True, market_open=True, llm_review=rev)[0]
    assert d.action == "REJECT" and "veto" in d.reason.lower()


def test_llm_abstention_does_not_block():
    from options_agents.llm import LLMReview
    rev = LLMReview(available=False, error="no key")
    d = risk().run([core("AAA")], Portfolio(cash=100_000), PRICES, 100_000,
                   paper_verified=True, market_open=True, llm_review=rev)[0]
    assert d.approved


def test_two_proposals_cannot_spend_the_same_cash():
    """Capital is simulated as approvals accrue, so the second must shrink.

    max_position_pct is lifted to 1.0 here on purpose: with the default 20% cap
    the per-position limit binds first and the cash constraint is never exercised,
    which makes the test pass without testing anything.
    """
    cfg = LiveConfig(universe=("AAA", "BBB"), max_position_pct=1.0, cash_floor=0.0)
    pf = Portfolio(cash=10_000.0)
    ds = RiskAgent(cfg, NullLog()).run(
        [core("AAA", 0.8), core("BBB", 0.8)], pf, PRICES, 10_000,
        paper_verified=True, market_open=True)
    spent = sum((d.notional or 0) for d in ds if d.approved)
    assert spent <= 10_000.0 + 1e-6, f"spent ${spent} of $10,000"
    assert any(d.action == "REDUCE" or not d.approved for d in ds), \
        "second proposal should have been reduced or rejected"


def test_position_limit_is_enforced():
    cfg = LiveConfig(universe=("AAA", "BBB", "CCC"), max_positions=1)
    ds = RiskAgent(cfg, NullLog()).run(
        [core("AAA", 0.1), core("BBB", 0.1)], Portfolio(cash=100_000), PRICES,
        100_000, paper_verified=True, market_open=True)
    assert sum(1 for d in ds if d.approved) == 1
    assert any("position limit" in d.reason for d in ds if not d.approved)


def test_spread_is_rejected_when_collateral_is_unaffordable():
    st = {"underlying": "AAA", "short_strike": 95, "long_strike": 85, "width": 10,
          "est_credit": 1.0, "max_loss_per_contract": 900.0,
          "expiry_target": "2026-10-16", "dte": 30, "spot": 100, "iv": 0.3,
          "iv_rank": 50}
    p = Proposal("AAA", "SPREAD", "SELL_TO_OPEN", None, "overlay", {}, st)
    pf = Portfolio(cash=200.0)
    d = risk().run([p], pf, PRICES, 100_000, paper_verified=True,
                   market_open=True)[0]
    assert d.action == "REJECT" and "collateralise" in d.reason


def test_execution_refuses_an_unapproved_decision():
    ex = ExecutionAgent(broker=None, cfg=CFG, log=NullLog(), dry_run=True)
    bad = Decision("AAA", "CORE", "REJECT", "vetoed")
    with pytest.raises(RuntimeError, match="Execution refused"):
        ex._submit(bad, None, set())


def test_exits_are_approved_even_at_limits():
    pf = Portfolio(cash=0.0, shares={"AAA": 10})
    p = Proposal("AAA", "EXIT", "SELL", 0.0, "dropped out", {})
    d = risk().run([p], pf, PRICES, 1_000, paper_verified=True,
                   market_open=True)[0]
    assert d.approved and d.qty == 10


# ------------------------------------------------------------------ rebalance
def _snap(ranked, prices):
    from options_agents.agents.market_data import MarketSnapshot, NameSnapshot
    names = {s: NameSnapshot(symbol=s, last_price=prices[s], momentum_score=1.0,
                             mom_12_1=0.5, mom_3m=0.1, trend=1.0, realised_vol=0.3,
                             iv_estimate=0.33, iv_rank=50.0, bars=300)
             for s in ranked}
    return MarketSnapshot(as_of="2026-08-28", market_open=True,
                          spy_above_sma200=True, spy_price=600.0,
                          names=names, ranked=list(ranked))


class _Book:
    def risk_free(self, d):
        return 0.04


def test_position_already_at_target_is_left_alone():
    """The bug this pins: without netting, every cycle re-buys the whole book."""
    from options_agents.agents.strategy import StrategyAgent
    cfg = LiveConfig(universe=("AAA",), top_n=1, core_weight=0.8,
                     overlay_enabled=False)
    snap = _snap(["AAA"], {"AAA": 100.0})
    props = StrategyAgent(cfg, NullLog()).run(
        snap, {"AAA": 800.0}, _Book(), date(2026, 8, 28),
        held_value={"AAA": 80_000.0}, equity=100_000.0)
    assert [p for p in props if p.kind == "CORE"] == []


def test_underweight_position_buys_only_the_gap():
    from options_agents.agents.strategy import StrategyAgent
    cfg = LiveConfig(universe=("AAA",), top_n=1, core_weight=0.8,
                     overlay_enabled=False)
    snap = _snap(["AAA"], {"AAA": 100.0})
    props = StrategyAgent(cfg, NullLog()).run(
        snap, {"AAA": 100.0}, _Book(), date(2026, 8, 28),
        held_value={"AAA": 10_000.0}, equity=100_000.0)
    core = [p for p in props if p.kind == "CORE"]
    assert len(core) == 1
    # target 80k, holding 10k -> buy the 70k gap, not the full 80k
    assert core[0].target_weight == pytest.approx(0.70, abs=1e-9)


def test_overweight_position_is_trimmed():
    from options_agents.agents.strategy import StrategyAgent
    cfg = LiveConfig(universe=("AAA",), top_n=1, core_weight=0.5,
                     overlay_enabled=False)
    snap = _snap(["AAA"], {"AAA": 100.0})
    props = StrategyAgent(cfg, NullLog()).run(
        snap, {"AAA": 900.0}, _Book(), date(2026, 8, 28),
        held_value={"AAA": 90_000.0}, equity=100_000.0)
    assert any(p.kind == "TRIM" for p in props)


def test_risk_off_regime_exits_everything():
    from options_agents.agents.strategy import StrategyAgent
    cfg = LiveConfig(universe=("AAA",), top_n=1)
    snap = _snap(["AAA"], {"AAA": 100.0})
    snap.spy_above_sma200 = False
    props = StrategyAgent(cfg, NullLog()).run(
        snap, {"AAA": 100.0}, _Book(), date(2026, 8, 28),
        held_value={"AAA": 10_000.0}, equity=100_000.0)
    assert props and all(p.kind == "EXIT" for p in props)


def test_trim_sells_only_the_excess_not_the_whole_position():
    """A TRIM that liquidates the position would be bought straight back next
    cycle, paying costs both ways."""
    from options_agents.agents.strategy import Proposal as P
    pf = Portfolio(cash=10_000.0, shares={"AAA": 900.0})
    p = P("AAA", "TRIM", "SELL", 0.5, "trim to target", {})
    d = risk().run([p], pf, {"AAA": 100.0}, 100_000,
                   paper_verified=True, market_open=True)[0]
    assert d.approved
    assert d.qty == pytest.approx(400.0)      # 900 held, 500 target -> sell 400
    assert d.qty < 900.0


def test_trim_below_min_ticket_is_left_alone():
    from options_agents.agents.strategy import Proposal as P
    pf = Portfolio(cash=0.0, shares={"AAA": 501.0})
    p = P("AAA", "TRIM", "SELL", 0.5, "trim", {})
    d = risk().run([p], pf, {"AAA": 100.0}, 100_000,
                   paper_verified=True, market_open=True)[0]
    assert not d.approved and "minimum ticket" in d.reason


def test_exit_still_sells_everything():
    from options_agents.agents.strategy import Proposal as P
    pf = Portfolio(cash=0.0, shares={"AAA": 900.0})
    d = risk().run([P("AAA", "EXIT", "SELL", 0.0, "dropped out", {})], pf,
                   {"AAA": 100.0}, 100_000, paper_verified=True,
                   market_open=True)[0]
    assert d.approved and d.qty == 900.0
