"""Pricing and volatility model tests. Silent sign errors here look like great
backtests — an earlier version of this engine reported a 100% win rate."""
from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from options_agents.pricing import greeks, price, strike_for_delta
from options_agents.selection import rank, realised_vol, score_symbol
from options_agents.volatility import VolSurface, iv_rank


def test_put_call_parity():
    S, K, T, r, s = 100, 100, 0.25, 0.04, 0.20
    c, p = price(S, K, T, r, s, "call"), price(S, K, T, r, s, "put")
    assert c - p == pytest.approx(S - K * math.exp(-r * T), abs=1e-9)


def test_value_is_monotone_in_vol_and_time():
    assert (price(100, 100, .25, .04, .10, "call")
            < price(100, 100, .25, .04, .40, "call"))
    assert (price(100, 100, .10, .04, .20, "call")
            < price(100, 100, 1.0, .04, .20, "call"))


def test_zero_dte_is_intrinsic():
    assert price(110, 100, 0, .04, .2, "call") == pytest.approx(10)
    assert price(90, 100, 0, .04, .2, "put") == pytest.approx(10)
    assert price(90, 100, 0, .04, .2, "call") == pytest.approx(0)


def test_strike_for_delta_round_trips_both_ways():
    for kind in ("put", "call"):
        for target in (0.10, 0.20, 0.35):
            k = strike_for_delta(500, 30 / 365, .05, .30, target, kind)
            got = abs(greeks(500, k, 30 / 365, .05, .30, kind).delta)
            assert got == pytest.approx(target, abs=1e-3), f"{kind} {target}"


def test_put_delta_is_negative_call_delta_positive():
    assert greeks(100, 100, .25, .04, .2, "put").delta < 0
    assert greeks(100, 100, .25, .04, .2, "call").delta > 0


def test_skew_makes_downside_puts_richer():
    s = VolSurface(atm_30d=0.20, slope_9d=0.92, slope_3m=1.05)
    assert s.iv(500, 450, 30) > s.iv(500, 500, 30) > s.iv(500, 550, 30)


def test_term_structure_inverts_under_stress():
    calm = VolSurface(atm_30d=0.14, slope_9d=0.85, slope_3m=1.08)
    assert calm.iv(500, 500, 5) < calm.iv(500, 500, 30)
    stress = VolSurface(atm_30d=0.45, slope_9d=1.25, slope_3m=0.92)
    assert stress.iv(500, 500, 5) > stress.iv(500, 500, 30)


def test_iv_rank_bounds_and_warmup():
    hist = [0.10 + 0.001 * i for i in range(300)]
    assert iv_rank(hist, 0.05) == 0.0
    assert iv_rank(hist, 9.9) == 100.0
    assert iv_rank(hist[:10], 0.2) is None


def test_realised_vol_of_flat_series_is_zero():
    assert realised_vol([100.0] * 30, 20) == pytest.approx(0.0)


# ---------------------------------------------------------------- selection
def _series(start, growth, n=300):
    return [start * (1 + growth) ** i for i in range(n)]


def test_momentum_score_needs_a_year_of_history():
    assert score_symbol("X", _series(100, 0.001, 100)) is None
    assert score_symbol("X", _series(100, 0.001, 300)) is not None


def test_stronger_trend_scores_higher():
    fast = score_symbol("F", _series(100, 0.002))
    slow = score_symbol("S", _series(100, 0.0002))
    assert fast.total > slow.total


def test_ranking_excludes_downtrends_when_required():
    up = _series(100, 0.002)
    down = list(reversed(_series(100, 0.002)))
    picks = rank({"UP": up, "DOWN": down}, None, top_n=5, require_uptrend=True)
    assert [p.symbol for p in picks] == ["UP"]


def test_momentum_skips_the_most_recent_month():
    """12-1 momentum must ignore the last ~21 sessions (short-term reversal)."""
    base = _series(100, 0.002)
    spiked = base[:-21] + [base[-22] * 3] * 21     # huge recent spike
    a = score_symbol("A", base)
    b = score_symbol("B", spiked)
    assert b.mom_12_1 == pytest.approx(a.mom_12_1, rel=1e-9)
