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


# ------------------------------------------------------------------- overlay
# The 2026-08-28 failure: three put spreads were submitted, none filled, and the
# overlay never tried again. Two independent defects caused it, one per test.

def test_overlay_proposes_on_a_held_name_with_no_new_core_buy():
    """THE regression. The overlay used to key off new CORE/PEAD proposals, but a
    position already at target weight emits none — so it got exactly one attempt,
    on the cycle that built the book, and could never retry an unfilled spread."""
    from options_agents.agents.strategy import StrategyAgent
    cfg = LiveConfig(universe=("AAA",), top_n=1, core_weight=0.8,
                     overlay_enabled=True, iv_rank_min=20.0)
    snap = _snap(["AAA"], {"AAA": 100.0})
    props = StrategyAgent(cfg, NullLog()).run(
        snap, {"AAA": 800.0}, _Book(), date(2026, 8, 28),
        held_value={"AAA": 80_000.0}, equity=100_000.0)
    assert [p for p in props if p.kind == "CORE"] == [], "already at target"
    assert [p for p in props if p.kind == "SPREAD"], \
        "overlay must still propose on a name the model is long"


def test_overlay_does_not_stack_a_second_spread_on_the_same_name():
    from options_agents.agents.strategy import StrategyAgent
    cfg = LiveConfig(universe=("AAA",), top_n=1, core_weight=0.8,
                     overlay_enabled=True)
    snap = _snap(["AAA"], {"AAA": 100.0})
    props = StrategyAgent(cfg, NullLog()).run(
        snap, {"AAA": 800.0}, _Book(), date(2026, 8, 28),
        held_value={"AAA": 80_000.0}, equity=100_000.0,
        held_options={"AAA"})
    assert [p for p in props if p.kind == "SPREAD"] == []


def test_overlay_does_not_write_a_spread_on_a_name_being_exited():
    from options_agents.agents.strategy import StrategyAgent
    cfg = LiveConfig(universe=("AAA", "BBB"), top_n=1, core_weight=0.8,
                     overlay_enabled=True)
    snap = _snap(["AAA"], {"AAA": 100.0})
    props = StrategyAgent(cfg, NullLog()).run(
        snap, {"BBB": 100.0}, _Book(), date(2026, 8, 28),
        held_value={"BBB": 10_000.0}, equity=100_000.0)
    assert any(p.kind == "EXIT" and p.symbol == "BBB" for p in props)
    assert not any(p.kind == "SPREAD" and p.symbol == "BBB" for p in props)


class _OptBroker:
    """Chain that lists 95/85 strikes when the model asked for 96.20/84.09."""
    verified = True

    def __init__(self, quotes=None, strikes=(95.0, 85.0)):
        self.quotes, self.strikes = quotes or {}, strikes

    def get_open_orders(self):
        return []

    def get_option_contracts(self, underlying, **kw):
        return [{"symbol": f"AAA261016P{int(k*1000):08d}",
                 "strike_price": str(k), "expiration_date": "2026-10-16"}
                for k in self.strikes]

    def get_option_quotes(self, symbols):
        return {s: self.quotes[s] for s in symbols if s in self.quotes}


def _spread_decision(contracts=1, collateral=900.0, width=12.11):
    st = {"underlying": "AAA", "short_strike": 96.20, "long_strike": 84.09,
          "width": width, "est_credit": 2.50, "max_loss_per_contract": 900.0,
          "expiry_target": "2026-10-16", "dte": 30, "spot": 100.0, "iv": 0.3,
          "iv_rank": 50}
    d = Decision("AAA", "SPREAD", "APPROVE", "overlay", contracts=contracts,
                 collateral=collateral)
    d.structure = st
    return d


def test_spread_limit_is_priced_from_the_real_quotes_not_black_scholes():
    """The model priced a 12.11-wide spread; the chain only lists a 10-wide one.
    Asking the wider spread's credit is why all three orders expired unfilled."""
    q = {"AAA261016P00095000": {"bp": 3.00, "ap": 3.40},
         "AAA261016P00085000": {"bp": 1.00, "ap": 1.20}}
    ex = ExecutionAgent(_OptBroker(q), LiveConfig(limit_cross=0.5), NullLog(),
                        dry_run=True)
    legs, resolved = ex._resolve_contracts(_spread_decision().structure)
    credit, meta = ex._limit_credit(legs, resolved, _spread_decision().structure)
    assert resolved["width"] == 10.0            # not the modelled 12.11
    assert meta["source"] == "quotes"
    # mid credit 3.20 - 1.10 = 2.10; natural 3.00 - 1.20 = 1.80; halfway = 1.95
    assert credit == pytest.approx(1.95, abs=0.01)
    assert credit < abs(_spread_decision().structure["est_credit"])


def test_spread_limit_falls_back_to_a_width_scaled_model_credit():
    """No two-sided market. The fallback must still correct for the fact that the
    resolved spread is narrower than the one Black-Scholes priced."""
    ex = ExecutionAgent(_OptBroker({}), LiveConfig(limit_cross=0.5), NullLog(),
                        dry_run=True)
    st = _spread_decision().structure
    legs, resolved = ex._resolve_contracts(st)
    credit, meta = ex._limit_credit(legs, resolved, st)
    assert meta["source"] == "model_fallback"
    # 2.50 scaled by 10.00/12.11 — est_credit already carries cfg.slippage
    assert credit == pytest.approx(2.50 * 10.0 / 12.11, abs=0.01)


def test_spread_is_resized_when_the_listed_strikes_risk_more_than_reserved():
    """Risk reserved collateral against the MODEL's width. A wider listed spread
    must be cut to fit the reservation, never silently exceed it."""
    q = {"AAA261016P00095000": {"bp": 3.00, "ap": 3.40},
         "AAA261016P00075000": {"bp": 1.00, "ap": 1.20}}
    ex = ExecutionAgent(_OptBroker(q, strikes=(95.0, 75.0)),
                        LiveConfig(limit_cross=0.5), NullLog(), dry_run=True)
    d = _spread_decision(contracts=2, collateral=1_800.0)
    from datetime import datetime
    r = ex._submit_spread(d, None, "moqa-spread-AAA-1", datetime.now())
    # a 20-wide spread risks ~$1,900/contract against $900 reserved per contract
    assert r.status == "error" and "will not fit" in r.error


def test_duplicate_check_sees_a_multi_leg_order_with_a_null_symbol():
    """Alpaca returns `symbol: null` on an mleg parent, so the old check let a
    second spread stack on a name that already had one working."""
    class B(_OptBroker):
        def get_open_orders(self):
            return [{"symbol": None, "client_order_id": "moqa-spread-AAA-123"}]
    ex = ExecutionAgent(B(), CFG, NullLog(), dry_run=True)
    out = ex.run([_spread_decision()], None)
    assert out[0].status == "skipped_duplicate"


def test_expiry_window_finds_a_monthly_when_the_name_has_no_weeklies():
    """A +/-10 day window straddles the gap between monthlies, so a name without
    weeklies resolved nothing whenever the target landed mid-month."""
    class Monthlies(_OptBroker):
        seen = {}

        def get_option_contracts(self, underlying, **kw):
            Monthlies.seen = kw
            out = []
            for exp in ("2026-09-18", "2026-10-16"):   # monthlies only
                if not (kw["expiration_gte"] <= exp <= kw["expiration_lte"]):
                    continue
                out += [{"symbol": f"AAA{exp[2:4]}{exp[5:7]}{exp[8:10]}P{int(k*1000):08d}",
                         "strike_price": str(k), "expiration_date": exp}
                        for k in (95.0, 85.0)]
            return out

    ex = ExecutionAgent(Monthlies(), CFG, NullLog(), dry_run=True)
    st = _spread_decision().structure          # targets 2026-10-16
    legs, resolved = ex._resolve_contracts(st)
    assert resolved["expiry"] == "2026-10-16"

    st = dict(st, expiry_target="2026-10-03")  # mid-month: the old window failed
    legs, resolved = ex._resolve_contracts(st)
    assert resolved["expiry"] in ("2026-09-18", "2026-10-16")


def test_a_quote_too_wide_to_trust_falls_back_to_the_model():
    """Closing quotes are junk — WBD's 27 put showed 0.06 x 2.37. Pricing off the
    mid of that invents a credit nobody will pay."""
    q = {"AAA261016P00095000": {"bp": 0.06, "ap": 2.37},
         "AAA261016P00085000": {"bp": 0.03, "ap": 0.13}}
    ex = ExecutionAgent(_OptBroker(q), LiveConfig(limit_cross=0.5), NullLog(),
                        dry_run=True)
    st = _spread_decision().structure
    legs, resolved = ex._resolve_contracts(st)
    credit, meta = ex._limit_credit(legs, resolved, st)
    assert meta["source"] == "model_fallback"
    assert "no credit" in meta["why"] and meta["natural_credit"] < 0


# -------------------------------------------------------------- spread exits
# Before 2026-09-03 the live agents could OPEN a spread and never close one:
# the 50%-profit rule existed only in the backtesters, so every live spread ran
# to expiry and the system traded a different strategy from the tearsheet's.

def _open_spread(entry_credit=0.45, expiry="2026-09-25", mid=0.17,
                 two_sided=True, contracts=11):
    from options_agents.spreads import OpenSpread
    from datetime import date as _d
    sp = OpenSpread(underlying="AAA", expiry=_d.fromisoformat(expiry), right="P",
                    short_symbol="AAA260925P00027000",
                    long_symbol="AAA260925P00025000",
                    short_strike=27.0, long_strike=25.0, contracts=contracts,
                    entry_credit=entry_credit)
    sp.pricing = {"two_sided": two_sided, "mid_debit": mid,
                  "natural_debit": mid + 0.08}
    return sp


def _exits(cfg, spreads, as_of=date(2026, 9, 3)):
    from options_agents.agents.strategy import StrategyAgent
    return StrategyAgent(cfg, NullLog())._spread_exits(spreads, as_of)


def test_spread_is_bought_back_at_the_profit_target():
    # sold at 0.45, buyable at 0.17 -> 62% of the credit earned, target is 50%
    out = _exits(LiveConfig(profit_target=0.50), [_open_spread(mid=0.17)])
    assert len(out) == 1 and out[0].kind == "SPREAD_EXIT"
    assert "Profit target" in out[0].reason
    assert out[0].structure["contracts"] == 11


def test_spread_is_left_alone_before_the_profit_target():
    # buyable at 0.30 -> only 33% earned
    assert _exits(LiveConfig(profit_target=0.50), [_open_spread(mid=0.30)]) == []


def test_spread_is_closed_near_expiry_whatever_the_profit():
    """A short put left open into expiry gets exercised against the account
    rather than closed on our terms."""
    out = _exits(LiveConfig(profit_target=0.50, close_dte=5),
                 [_open_spread(mid=0.44, expiry="2026-09-05")])
    assert len(out) == 1 and "to expiry" in out[0].reason


def test_profit_target_is_not_taken_off_an_untradeable_quote():
    assert _exits(LiveConfig(), [_open_spread(mid=0.01, two_sided=False)]) == []


def test_spread_exit_is_approved_even_with_no_cash_and_at_every_limit():
    from options_agents.agents.strategy import StrategyAgent
    p = _exits(LiveConfig(), [_open_spread()])[0]
    d = RiskAgent(LiveConfig(max_positions=0), NullLog()).run(
        [p], Portfolio(cash=0.0), PRICES, 100_000,
        paper_verified=True, market_open=True)[0]
    assert d.approved and d.contracts == 11


def test_spread_exit_still_obeys_the_paper_gate():
    p = _exits(LiveConfig(), [_open_spread()])[0]
    d = risk().run([p], Portfolio(cash=0.0), PRICES, 100_000,
                   paper_verified=False, market_open=True)[0]
    assert not d.approved and "not verified" in d.reason


def test_closing_order_is_buy_to_close_at_a_positive_debit():
    """Alpaca's mleg convention is net-debit: opening a credit spread sends a
    negative limit, closing it sends a positive one."""
    from datetime import datetime
    p = _exits(LiveConfig(), [_open_spread(mid=0.17)])[0]
    d = Decision("AAA", "SPREAD_EXIT", "APPROVE", "close", contracts=11)
    d.structure = p.structure
    captured = {}

    class Log(NullLog):
        def emit(self, agent, event, payload):
            if event == "order_request":
                captured.update(payload)
            return {}

    ex = ExecutionAgent(_OptBroker(), LiveConfig(limit_cross=0.5), Log(),
                        dry_run=True)
    r = ex._submit_spread_exit(d, "moqa-spread_exit-AAA-1", datetime.now())
    assert r.status == "dry_run"
    assert captured["limit_price"] > 0
    assert [l["position_intent"] for l in captured["legs"]] == \
        ["buy_to_close", "sell_to_close"]
    # mid 0.17, natural 0.25, half way = 0.21
    assert captured["limit_price"] == pytest.approx(0.21, abs=0.01)


def test_overlay_does_not_reopen_a_spread_it_is_closing_this_cycle():
    from options_agents.agents.strategy import StrategyAgent
    cfg = LiveConfig(universe=("AAA",), top_n=1, core_weight=0.8,
                     overlay_enabled=True)
    snap = _snap(["AAA"], {"AAA": 100.0})
    props = StrategyAgent(cfg, NullLog()).run(
        snap, {"AAA": 800.0}, _Book(), date(2026, 9, 3),
        held_value={"AAA": 80_000.0}, equity=100_000.0,
        open_spreads=[_open_spread(mid=0.17)])
    assert any(p.kind == "SPREAD_EXIT" for p in props)
    assert not any(p.kind == "SPREAD" for p in props)


# ---------------------------------------------- rebalance calendar and stale data
# 2026-09-14: the price cache went stale, every name looked delisted, the ranking
# came back empty and the strategy agent sold the whole account as "no longer in
# the top-N". The backtest only trades once every 21 days; the live agents were
# trading every cycle. Both are pinned here.

def _run_strategy(cfg, held, held_value, *, ranked=("AAA",), rebalance=True,
                  stale=False, spy_ok=True, open_spreads=None, snap=None,
                  as_of=date(2026, 9, 30)):
    from options_agents.agents.strategy import StrategyAgent
    px = {s: 100.0 for s in set(ranked) | set(held)}
    snap = snap or _snap(list(ranked), px)
    snap.data_stale, snap.spy_above_sma200 = stale, spy_ok
    return StrategyAgent(cfg, NullLog()).run(
        snap, held, _Book(), as_of, held_value=held_value, equity=100_000.0,
        open_spreads=open_spreads, rebalance=rebalance)


def _kinds(props):
    return sorted(p.kind for p in props)


def test_stale_data_proposes_no_stock_trades_and_liquidates_nothing():
    """THE 2026-09-14 regression: held names must survive a stale cache."""
    cfg = LiveConfig(universe=("AAA", "BBB"), top_n=1, core_weight=0.8)
    props = _run_strategy(cfg, {"BBB": 100.0}, {"BBB": 10_000.0}, stale=True)
    assert props == [], "stale data: no buys, no exits, no trims"


def test_stale_data_also_blocks_the_regime_exit():
    cfg = LiveConfig(universe=("AAA", "BBB"), top_n=1)
    props = _run_strategy(cfg, {"BBB": 100.0}, {"BBB": 10_000.0}, stale=True,
                          spy_ok=False)
    assert props == []


def test_stale_data_still_closes_an_open_spread():
    """Spread exits are priced from live option quotes and only reduce risk."""
    cfg = LiveConfig(universe=("AAA", "BBB"), top_n=1)
    props = _run_strategy(cfg, {"BBB": 100.0}, {"BBB": 10_000.0}, stale=True,
                          open_spreads=[_open_spread(mid=0.17)],
                          as_of=date(2026, 9, 3))
    assert _kinds(props) == ["SPREAD_EXIT"]


def test_between_rebalances_nothing_is_exited_bought_or_trimmed():
    """BBB has left the top 1 and AAA is unowned, but it is not rebalance day."""
    cfg = LiveConfig(universe=("AAA", "BBB"), top_n=1, core_weight=0.8)
    props = _run_strategy(cfg, {"BBB": 100.0}, {"BBB": 10_000.0}, rebalance=False)
    assert props == []


def test_between_rebalances_the_regime_check_does_not_sell_either():
    cfg = LiveConfig(universe=("AAA", "BBB"), top_n=1)
    props = _run_strategy(cfg, {"BBB": 100.0}, {"BBB": 10_000.0},
                          rebalance=False, spy_ok=False)
    assert props == []


def test_between_rebalances_an_overweight_position_is_not_trimmed():
    cfg = LiveConfig(universe=("AAA",), top_n=1, core_weight=0.5)
    props = _run_strategy(cfg, {"AAA": 900.0}, {"AAA": 90_000.0}, rebalance=False)
    assert props == []


def test_between_rebalances_a_spread_is_still_closed():
    cfg = LiveConfig(universe=("AAA",), top_n=1)
    props = _run_strategy(cfg, {}, {}, rebalance=False, ranked=("AAA",),
                          open_spreads=[_open_spread(mid=0.17)],
                          as_of=date(2026, 9, 3))
    assert _kinds(props) == ["SPREAD_EXIT"]


def test_rebalance_day_exits_the_dropped_name_and_buys_the_new_one():
    cfg = LiveConfig(universe=("AAA", "BBB"), top_n=1, core_weight=0.8)
    props = _run_strategy(cfg, {"BBB": 100.0}, {"BBB": 10_000.0}, rebalance=True)
    assert [(p.kind, p.symbol) for p in props] == [("CORE", "AAA"), ("EXIT", "BBB")]


def test_rebalance_day_in_a_bear_market_exits_everything():
    cfg = LiveConfig(universe=("AAA", "BBB"), top_n=1)
    props = _run_strategy(cfg, {"BBB": 100.0}, {"BBB": 10_000.0},
                          rebalance=True, spy_ok=False)
    assert [(p.kind, p.symbol) for p in props] == [("EXIT", "BBB")]


def test_flat_account_with_no_recorded_rebalance_buys_the_top_six():
    """Today's situation: cash only, no state file. Buys top 6 at 80% / 6."""
    ranked = ["A1", "A2", "A3", "A4", "A5", "A6", "A7"]
    cfg = LiveConfig(universe=tuple(ranked), top_n=6, core_weight=0.80)
    from options_agents.rebalance import is_rebalance_cycle
    assert is_rebalance_cycle(date(2026, 9, 30), None, cfg.rebalance_days)
    props = _run_strategy(cfg, {}, {}, ranked=ranked, rebalance=True)
    assert _kinds(props) == ["CORE"] * 6
    assert {p.symbol for p in props} == set(ranked[:6])
    assert all(p.target_weight == pytest.approx(0.80 / 6) for p in props)


def test_second_cycle_on_rebalance_day_does_not_rebuy_what_filled():
    """as_of == last_rebalance is still a rebalance cycle (so a partial fill can
    be completed), and the 25% band is what stops it buying the book twice."""
    from options_agents.rebalance import is_rebalance_cycle
    day = date(2026, 9, 30)
    assert is_rebalance_cycle(day, day, 21)
    cfg = LiveConfig(universe=("AAA",), top_n=1, core_weight=0.8)
    props = _run_strategy(cfg, {"AAA": 800.0}, {"AAA": 80_000.0}, rebalance=True)
    assert props == []


def test_rebalance_calendar():
    from options_agents.rebalance import is_rebalance_cycle, next_rebalance_date
    last = date(2026, 9, 1)
    assert is_rebalance_cycle(date(2026, 9, 1), last, 21)         # same day
    assert not is_rebalance_cycle(date(2026, 9, 2), last, 21)
    assert not is_rebalance_cycle(date(2026, 9, 21), last, 21)    # 20 days
    assert is_rebalance_cycle(date(2026, 9, 22), last, 21)        # 21 days
    assert is_rebalance_cycle(date(2026, 9, 30), None, 21)        # never recorded
    assert next_rebalance_date(last, 21) == date(2026, 9, 22)
    assert next_rebalance_date(None, 21) is None


def test_rebalance_state_round_trips_and_survives_a_bad_file(tmp_path):
    from options_agents.rebalance import load_last_rebalance, save_last_rebalance
    f = tmp_path / "state" / "rebalance.json"
    assert load_last_rebalance(f) is None                          # no file
    save_last_rebalance(f, date(2026, 9, 30))
    assert load_last_rebalance(f) == date(2026, 9, 30)
    f.write_text("not json")
    assert load_last_rebalance(f) is None                          # unreadable


# --------------------------------------------- overlay and PEAD switched off
def _pead_snap():
    snap = _snap(["AAA", "BBB"], {"AAA": 100.0, "BBB": 100.0})
    snap.names["BBB"].recent_earnings = {"days_since": 1, "sue": 2.0,
                                         "gap_pct": 0.05, "vol_ratio": 3.0}
    return snap


def test_overlay_and_pead_are_off_by_default(monkeypatch):
    cfg = LiveConfig()
    assert cfg.overlay_enabled is False and cfg.pead_enabled is False
    monkeypatch.delenv("OVERLAY_ENABLED", raising=False)
    monkeypatch.delenv("PEAD_ENABLED", raising=False)
    cfg = LiveConfig.from_env(("AAA",))
    assert cfg.overlay_enabled is False and cfg.pead_enabled is False


def test_no_spread_or_pead_proposals_with_the_defaults():
    cfg = LiveConfig(universe=("AAA", "BBB"), top_n=1, core_weight=0.8)
    props = _run_strategy(cfg, {"AAA": 800.0}, {"AAA": 80_000.0}, snap=_pead_snap())
    assert not any(p.kind in ("SPREAD", "PEAD") for p in props)


def test_pead_proposals_return_only_when_enabled():
    """Guards the test above: this snapshot does qualify for PEAD."""
    cfg = LiveConfig(universe=("AAA", "BBB"), top_n=1, core_weight=0.8,
                     pead_enabled=True)
    props = _run_strategy(cfg, {"AAA": 800.0}, {"AAA": 80_000.0}, snap=_pead_snap())
    assert any(p.kind == "PEAD" and p.symbol == "BBB" for p in props)


def test_spread_exit_still_proposed_with_the_overlay_off():
    cfg = LiveConfig(universe=("AAA",), top_n=1)
    assert cfg.overlay_enabled is False
    props = _run_strategy(cfg, {"AAA": 800.0}, {"AAA": 80_000.0},
                          open_spreads=[_open_spread(mid=0.17)],
                          as_of=date(2026, 9, 3))
    assert [p.kind for p in props if p.kind.startswith("SPREAD")] == ["SPREAD_EXIT"]
