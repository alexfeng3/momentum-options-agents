"""Pairing broker option legs back into spreads, and pricing the exit."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from options_agents.spreads import OpenSpread, debit_to_close, pair_spreads, parse_occ


def _leg(sym, qty, entry):
    return {"asset_class": "us_option", "symbol": sym, "qty": str(qty),
            "avg_entry_price": str(entry)}


def test_parse_occ_splits_a_multi_character_root():
    assert parse_occ("JAZZ260918P00230000") == ("JAZZ", date(2026, 9, 18), "P", 230.0)
    assert parse_occ("WBD260925P00027000") == ("WBD", date(2026, 9, 25), "P", 27.0)


def test_parse_occ_rejects_junk():
    assert parse_occ("AAPL") is None
    assert parse_occ("WBD260945P00027000") is None      # month 45


def test_pairs_a_short_put_spread_and_recovers_the_entry_credit():
    sps = pair_spreads([_leg("WBD260925P00027000", -11, 0.75),
                        _leg("WBD260925P00025000", 11, 0.30),
                        {"asset_class": "us_equity", "symbol": "WBD", "qty": "462"}])
    assert len(sps) == 1
    sp = sps[0]
    assert (sp.short_strike, sp.long_strike, sp.width) == (27.0, 25.0, 2.0)
    assert sp.entry_credit == 0.45 and sp.contracts == 11
    assert sp.dte(date(2026, 9, 15)) == 10


def test_an_unpaired_short_leg_is_ignored_not_guessed_at():
    """A naked short is not something this strategy creates. Inventing a spread
    around an unpaired leg would misstate the risk."""
    assert pair_spreads([_leg("WBD260925P00027000", -11, 0.75)]) == []


def test_a_credit_wider_than_the_spread_is_refused():
    """A credit spread always takes in less than its width. If it does not,
    avg_entry_price is not in the units assumed and acting on it would misprice
    the exit."""
    assert pair_spreads([_leg("WBD260925P00027000", -11, 75.0),
                         _leg("WBD260925P00025000", 11, 30.0)]) == []


def test_legs_pair_to_the_nearest_protective_strike():
    sps = pair_spreads([_leg("WBD260925P00027000", -5, 0.75),
                        _leg("WBD260925P00025000", 5, 0.30),
                        _leg("WBD260925P00020000", 5, 0.10)])
    assert len(sps) == 1 and sps[0].long_strike == 25.0


def _sp(**kw):
    base = dict(underlying="WBD", expiry=date(2026, 9, 25), right="P",
                short_symbol="S", long_symbol="L", short_strike=27.0,
                long_strike=25.0, contracts=11, entry_credit=0.45)
    base.update(kw)
    return OpenSpread(**base)


def test_debit_to_close_uses_short_minus_long():
    sp = _sp(quotes={"S": {"bp": 0.20, "ap": 0.30}, "L": {"bp": 0.05, "ap": 0.11}})
    q = debit_to_close(sp)
    assert q["two_sided"] is True
    assert q["mid_debit"] == 0.17          # 0.25 - 0.08
    assert q["natural_debit"] == 0.25      # pay 0.30 ask, hit 0.05 bid


def test_debit_to_close_flags_a_one_sided_market():
    sp = _sp(quotes={"S": {"bp": 0.20, "ap": 0.30}, "L": {"bp": 0, "ap": 0.11}})
    assert debit_to_close(sp)["two_sided"] is False
