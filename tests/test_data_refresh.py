"""Price-cache refresh, the staleness guard and the rebalance state, end to end.

Nothing here touches the network: the broker is a fake, and the CSV cache lives
in a temporary directory.
"""
from __future__ import annotations

import math
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from options_agents import orchestrator
from options_agents.agents.market_data import MarketDataAgent
from options_agents.eventlog import ET, EventLog
from options_agents.marketdata import HistoricalBook
from options_agents.refresh import HEADER, refresh_bars
from options_agents.strategy_config import LiveConfig


class NullLog:
    def __init__(self):
        self.events = []

    def emit(self, agent, event, payload=None, **kw):
        self.events.append((agent, event, payload))
        return {}


def _weekdays_ending(end: date, n: int) -> list[date]:
    out, d = [], end
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


def _closes(n: int, start: float = 50.0, drift: float = 0.2) -> list[float]:
    # a steady uptrend with a little deterministic noise: passes every screen
    return [round(start + drift * i + math.sin(i) * 0.3, 4) for i in range(n)]


def _write_csv(path: Path, days: list[date], closes: list[float],
               trailing_newline: bool = False) -> None:
    rows = [HEADER] + [f"{d},{c},{c},{c},{c},1000" for d, c in zip(days, closes)]
    path.write_text("\n".join(rows) + ("\n" if trailing_newline else ""))


def _cache(tmp_path: Path, end: date, symbols=("SPY", "AAA", "BBB"), n=300) -> Path:
    d = tmp_path / "broad"
    d.mkdir()
    days = _weekdays_ending(end, n)
    for s in symbols:
        _write_csv(d / f"{s}.csv", days, _closes(n))   # like the real files: no final \n
    return d


def _bar(day: date, close: float) -> dict:
    return {"t": f"{day.isoformat()}T04:00:00Z", "o": close, "h": close,
            "l": close, "c": close, "v": 5000}


class FakeBars:
    """get_stock_bars() stand-in. `recent` is served for any recent start date,
    `history` when the start is the full-history start."""

    def __init__(self, cfg, recent=None, history=None, error=None):
        self.cfg, self.recent, self.history = cfg, recent or {}, history or {}
        self.error, self.calls = error, []

    def get_stock_bars(self, symbols, start_iso, **kw):
        self.calls.append((list(symbols), start_iso))
        if self.error:
            raise RuntimeError(self.error)
        src = self.history if start_iso == self.cfg.history_start else self.recent
        return {s: list(src[s]) for s in symbols if s in src}


def _cfg(data_dir, **kw):
    return LiveConfig(universe=("AAA", "BBB"), data_dir=data_dir, **kw)


def _dates(path: Path) -> list[str]:
    return [ln.split(",")[0] for ln in path.read_text().splitlines()[1:] if ln]


# ------------------------------------------------------------------- refresh
def test_refresh_appends_finished_sessions_and_never_writes_today(tmp_path):
    last = date(2026, 9, 25)                      # a Friday
    d = _cache(tmp_path, last)
    cfg = _cfg(d)
    closes = _closes(300)
    today = date(2026, 9, 29)                     # Tuesday
    recent = {s: [_bar(last, closes[-1]),                    # overlap
                  _bar(date(2026, 9, 28), 111.0),            # Monday, finished
                  _bar(today, 112.0)]                        # partial: must not land
              for s in ("SPY", "AAA", "BBB")}
    res = refresh_bars(FakeBars(cfg, recent), ["SPY", "AAA", "BBB"], cfg, today)
    for s in ("SPY", "AAA", "BBB"):
        got = _dates(d / f"{s}.csv")
        assert got[-1] == "2026-09-28"
        assert "2026-09-29" not in got            # never today's bar
        assert len(got) == len(set(got)) == 301   # overlap not duplicated
    assert res["updated"] == 3 and res["bars_added"] == 3
    assert res["rewritten"] == [] and res["newest_bar"] == "2026-09-28"
    # and the book can read what was written (trailing newline handled)
    assert HistoricalBook(["SPY"], data_dir=d).newest_date("SPY") == date(2026, 9, 28)


def test_refresh_ignores_bars_dated_after_today_too(tmp_path):
    last = date(2026, 9, 25)
    d = _cache(tmp_path, last, symbols=("SPY",))
    cfg = _cfg(d)
    recent = {"SPY": [_bar(last, _closes(300)[-1]), _bar(date(2026, 9, 30), 1.0)]}
    res = refresh_bars(FakeBars(cfg, recent), ["SPY"], cfg, date(2026, 9, 29))
    assert res["bars_added"] == 0 and _dates(d / "SPY.csv")[-1] == "2026-09-25"


def test_symbol_with_no_new_bars_is_left_untouched(tmp_path):
    last = date(2026, 9, 25)
    d = _cache(tmp_path, last)
    cfg = _cfg(d)
    before = (d / "BBB.csv").read_bytes()
    recent = {"SPY": [_bar(date(2026, 9, 28), 111.0)]}       # BBB: nothing at all
    res = refresh_bars(FakeBars(cfg, recent), ["SPY", "AAA", "BBB"], cfg,
                       date(2026, 9, 29))
    assert (d / "BBB.csv").read_bytes() == before
    assert res["updated"] == 1


def test_a_split_mismatch_triggers_a_full_history_rewrite(tmp_path):
    last = date(2026, 9, 25)
    d = _cache(tmp_path, last)
    cfg = _cfg(d)
    days = _weekdays_ending(last, 300)
    cached_close = _closes(300)[-1]
    # AAA split 2:1: the fresh series is in new units and half the old price
    new_units = [_bar(x, round(c / 2, 4)) for x, c in zip(days, _closes(300))]
    new_units.append(_bar(date(2026, 9, 28), 55.0))
    fake = FakeBars(
        cfg,
        recent={"SPY": [_bar(last, cached_close), _bar(date(2026, 9, 28), 111.0)],
                "AAA": new_units[-2:],
                "BBB": [_bar(last, cached_close), _bar(date(2026, 9, 28), 111.0)]},
        history={"AAA": new_units})
    res = refresh_bars(fake, ["SPY", "AAA", "BBB"], cfg, date(2026, 9, 29))
    assert res["rewritten"] == ["AAA"]
    assert (d / "AAA.csv").read_text().splitlines()[0] == HEADER
    book = HistoricalBook(["AAA", "BBB"], data_dir=d)
    assert book.close("AAA", days[0]) == pytest.approx(_closes(300)[0] / 2)  # old bars re-based
    assert book.newest_date("AAA") == date(2026, 9, 28)
    assert book.close("BBB", days[0]) == pytest.approx(_closes(300)[0])      # BBB untouched
    assert (cfg.history_start) in [c[1] for c in fake.calls]


def test_a_small_price_difference_is_not_treated_as_a_split(tmp_path):
    last = date(2026, 9, 25)
    d = _cache(tmp_path, last, symbols=("SPY",))
    cfg = _cfg(d)
    c = _closes(300)[-1]
    recent = {"SPY": [_bar(last, c * 1.004), _bar(date(2026, 9, 28), 111.0)]}  # 0.4%
    res = refresh_bars(FakeBars(cfg, recent), ["SPY"], cfg, date(2026, 9, 29))
    assert res["rewritten"] == [] and res["bars_added"] == 1


def test_a_truncated_history_does_not_replace_a_good_one(tmp_path):
    last = date(2026, 9, 25)
    d = _cache(tmp_path, last, symbols=("SPY", "AAA"))
    cfg = _cfg(d)
    before = (d / "AAA.csv").read_bytes()
    fake = FakeBars(cfg, recent={"AAA": [_bar(last, 1.0)]},          # mismatch
                    history={"AAA": [_bar(last, 1.0)]})              # 1 bar only
    res = refresh_bars(fake, ["SPY", "AAA"], cfg, date(2026, 9, 29))
    assert res["rewrite_skipped"] == ["AAA"] and (d / "AAA.csv").read_bytes() == before


def test_api_failure_is_reported_and_leaves_the_cache_alone(tmp_path):
    last = date(2026, 9, 25)
    d = _cache(tmp_path, last)
    cfg = _cfg(d)
    before = {p.name: p.read_bytes() for p in d.glob("*.csv")}
    res = refresh_bars(FakeBars(cfg, error="boom"), ["SPY", "AAA", "BBB"], cfg,
                       date(2026, 9, 29))
    assert res["batch_errors"] and res["bars_added"] == 0
    assert {p.name: p.read_bytes() for p in d.glob("*.csv")} == before


# ----------------------------------------------------------- market data agent
class _ClockBroker:
    def get_clock(self):
        return {"is_open": True}


def _snapshot(d: Path, as_of: date):
    cfg = _cfg(d)
    log = NullLog()
    book = HistoricalBook(["SPY", "AAA", "BBB"], data_dir=d)
    return MarketDataAgent(_ClockBroker(), book, cfg, log).run(as_of), log


def test_fresh_cache_is_not_stale(tmp_path):
    d = _cache(tmp_path, date(2026, 9, 25))
    snap, _ = _snapshot(d, date(2026, 9, 28))     # Monday after a Friday bar
    assert snap.data_stale is False and snap.newest_bar == "2026-09-25"
    assert snap.ranked


def test_stale_cache_is_flagged_and_logged(tmp_path):
    d = _cache(tmp_path, date(2026, 8, 27))
    snap, log = _snapshot(d, date(2026, 9, 29))
    assert snap.data_stale is True and snap.newest_bar == "2026-08-27"
    assert any(e[1] == "data_stale" for e in log.events)


def test_the_threshold_is_five_calendar_days(tmp_path):
    d = _cache(tmp_path, date(2026, 9, 21))
    assert _snapshot(d, date(2026, 9, 26))[0].data_stale is False     # 5 days
    assert _snapshot(d, date(2026, 9, 27))[0].data_stale is True      # 6 days


def test_a_stale_cache_no_longer_looks_like_every_name_delisted(tmp_path):
    """The old test measured delisting against the wall clock, so a cache 33 days
    old scored zero candidates. Measured against the book's own newest date the
    names are still ranked; it is the staleness guard that stops the trading."""
    d = _cache(tmp_path, date(2026, 8, 27))
    snap, _ = _snapshot(d, date(2026, 9, 29))
    assert snap.ranked, "names must still be scored relative to the book's own date"
    assert snap.data_stale is True


def test_a_name_that_stopped_trading_is_still_treated_as_delisted(tmp_path):
    d = _cache(tmp_path, date(2026, 9, 25))
    days = _weekdays_ending(date(2026, 9, 25), 300)
    _write_csv(d / "BBB.csv", days[:250], _closes(250))               # ended 50 sessions ago
    snap, _ = _snapshot(d, date(2026, 9, 28))
    assert "BBB" not in snap.ranked and "AAA" in snap.ranked


# ------------------------------------------------------------- full cycle (fake)
NOW = datetime(2026, 9, 30, 9, 45, tzinfo=ET)


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


class _CycleBroker:
    base = "https://paper-api.alpaca.markets"
    verified = False

    def __init__(self, cfg, positions=(), market_open=True, recent=None, error=None):
        self.positions, self.market_open = list(positions), market_open
        self.bars = FakeBars(cfg, recent, error=error)

    def verify_paper(self):
        self.verified = True
        return {"account_number": "PA-TEST", "equity": "100000", "cash": "100000"}

    def get_account(self):
        return {"account_number": "PA-TEST", "equity": "100000", "cash": "100000",
                "buying_power": "100000", "long_market_value": "0"}

    def get_clock(self):
        return {"is_open": self.market_open}

    def get_positions(self):
        return self.positions

    def get_open_orders(self):
        return []

    def get_option_quotes(self, symbols):
        return {}

    def get_stock_bars(self, symbols, start_iso, **kw):
        return self.bars.get_stock_bars(symbols, start_iso)


def _holding(sym, value=10_000.0):
    return {"symbol": sym, "asset_class": "us_equity", "qty": "100",
            "avg_entry_price": "100", "current_price": "100",
            "market_value": str(value), "unrealized_pl": "0", "unrealized_plpc": "0"}


@pytest.fixture
def cycle(tmp_path, monkeypatch):
    """Runs orchestrator.run_cycle against a fake broker and a temp cache."""
    monkeypatch.setattr(orchestrator, "datetime", _FrozenDatetime)
    monkeypatch.setattr(orchestrator, "EventLog", lambda run_id, echo=True: EventLog(
        run_id, echo=False, log_dir=tmp_path / "logs"))
    # execution is not under test here, and must never reach a network
    monkeypatch.setattr(orchestrator.ExecutionAgent, "run",
                        lambda self, decisions, snap: [])

    def run(end: date, *, positions=(), dry_run=True, market_open=True,
            last_rebalance=None, error=None):
        cache = tmp_path / "broad"
        if cache.exists():
            for p in cache.glob("*"):
                p.unlink()
        else:
            cache.mkdir()
        days = _weekdays_ending(end, 300)
        for s in ("SPY", "AAA", "BBB"):
            _write_csv(cache / f"{s}.csv", days, _closes(300))
        cfg = LiveConfig(universe=("AAA", "BBB"), data_dir=cache, top_n=1,
                         core_weight=0.8,
                         rebalance_file=tmp_path / "state" / "rebalance.json")
        if last_rebalance:
            from options_agents.rebalance import save_last_rebalance
            save_last_rebalance(cfg.rebalance_file, last_rebalance)
        broker = _CycleBroker(cfg, positions, market_open, error=error)
        monkeypatch.setattr(orchestrator, "AlpacaBroker", lambda: broker)
        res = orchestrator.run_cycle(cfg, dry_run=dry_run, echo=False, use_llm=False)
        return res, cfg

    return run


def _stock_kinds(res):
    return [p["kind"] for p in res["proposals"]]


def test_cycle_with_a_stale_cache_and_a_dead_api_trades_nothing(cycle):
    """Refresh fails, the cache is 33 days old, the account holds a name that is
    not in the ranking. Old behaviour: sell it. Now: no stock trade at all."""
    res, cfg = cycle(date(2026, 8, 27), positions=[_holding("ZZZ")], error="api down",
                     dry_run=False)
    assert res["data_stale"] is True and res["newest_bar"] == "2026-08-27"
    assert res["proposals"] == [] and res["decisions"] == []
    assert not cfg.rebalance_file.exists(), "stale data must not record a rebalance"


def test_cycle_on_fresh_data_with_no_state_is_a_rebalance_and_buys(cycle):
    res, cfg = cycle(date(2026, 9, 29), dry_run=True)
    assert res["data_stale"] is False and res["is_rebalance"] is True
    assert _stock_kinds(res) == ["CORE"]
    assert res["next_rebalance"] is None            # not recorded yet


def test_dry_run_never_writes_the_rebalance_state(cycle):
    res, cfg = cycle(date(2026, 9, 29), dry_run=True)
    assert not cfg.rebalance_file.exists()


def test_closed_market_never_writes_the_rebalance_state(cycle):
    res, cfg = cycle(date(2026, 9, 29), dry_run=False, market_open=False)
    assert not cfg.rebalance_file.exists()


def test_live_cycle_with_the_market_open_records_the_rebalance(cycle):
    from options_agents.rebalance import load_last_rebalance
    res, cfg = cycle(date(2026, 9, 29), dry_run=False, market_open=True)
    assert load_last_rebalance(cfg.rebalance_file) == date(2026, 9, 30)
    assert res["next_rebalance"] == "2026-10-21"


def test_cycle_between_rebalances_leaves_a_stray_holding_alone(cycle):
    res, cfg = cycle(date(2026, 9, 29), positions=[_holding("ZZZ")],
                     last_rebalance=date(2026, 9, 20))
    assert res["is_rebalance"] is False
    assert res["proposals"] == []
    assert res["next_rebalance"] == "2026-10-11"


def test_cycle_on_rebalance_day_exits_the_stray_holding(cycle):
    res, cfg = cycle(date(2026, 9, 29), positions=[_holding("ZZZ")],
                     last_rebalance=date(2026, 9, 9))          # 21 days ago
    assert res["is_rebalance"] is True
    assert sorted(_stock_kinds(res)) == ["CORE", "EXIT"]
