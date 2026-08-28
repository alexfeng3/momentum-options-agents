"""Directional backtester: momentum-selected long call options.

Thesis: selection provides the direction, options provide the leverage. Buying
calls on the strongest-momentum names converts a stock edge into a convex one,
with max loss capped at the premium paid.

Single-name implied vol is MODELLED, because no option chain history exists here:
    IV = realised_vol(60d) x iv_premium
Single-name options normally trade 5-25% above trailing realised vol. The default
1.15 is charged on the way IN and on the way OUT, so the strategy never gets to
buy cheap and sell rich through a modelling artifact.

BENCHMARKS. SPY is reported, but the honest benchmark is EQUAL-WEIGHT BUY-AND-HOLD
OF THE SAME UNIVERSE. The 42 names were chosen with hindsight in 2026; any
long-only strategy on them will beat SPY on universe luck alone. Only the margin
over the equal-weight basket is attributable to selection and options.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta

from .marketdata import HistoricalBook
from .pricing import greeks, price, strike_for_delta
from .selection import rank, realised_vol

CONTRACT_MULT = 100.0


@dataclass
class DirectionalConfig:
    universe: tuple[str, ...] = ()
    benchmark: str = "SPY"
    top_n: int = 4
    rebalance_days: int = 21          # monthly
    target_delta: float = 0.60        # 0.5 = balanced, 0.8 = stock replacement
    dte: int = 60
    exit_dte: int = 14                # roll before gamma/theta cliff
    profit_target: float = 1.00       # +100% on premium
    stop_loss: float = -0.50          # -50% on premium
    premium_pct: float = 0.04         # used only when target_notional is None
    # Size by DELTA NOTIONAL, not premium. Premium-based sizing silently produces
    # ~1x exposure while still paying theta, which is strictly worse than holding
    # the shares. target_notional=1.5 means the option book carries 1.5x the
    # account's equity in delta-equivalent stock exposure.
    target_notional: float | None = None
    max_premium_pct: float = 0.35     # hard cap on premium at risk per position
    max_positions: int = 4
    iv_premium: float = 1.15          # IV / realised vol
    slippage_pct: float = 0.03        # single-name option spreads
    fee_per_contract: float = 0.05
    require_uptrend: bool = True
    market_filter: bool = True        # only hold when SPY > its own SMA200
    starting_equity: float = 100_000.0
    min_price: float = 5.0

    def replace(self, **kw):
        from dataclasses import replace as _r
        return _r(self, **kw)


@dataclass
class LongCall:
    symbol: str
    strike: float
    expiry: date
    entry_date: date
    contracts: int
    entry_price: float        # per contract, per share
    entry_spot: float
    entry_iv: float
    premium_paid: float       # total dollars


@dataclass
class DirTrade:
    symbol: str
    entry_date: date
    exit_date: date
    entry_spot: float
    exit_spot: float
    premium_paid: float
    proceeds: float
    pnl: float
    return_on_premium: float
    reason: str
    held_days: int


class DirectionalBacktest:
    def __init__(self, cfg: DirectionalConfig, book: HistoricalBook):
        self.cfg, self.book = cfg, book
        self.cash = cfg.starting_equity
        self.open: list[LongCall] = []
        self.trades: list[DirTrade] = []
        self.curve: list[tuple[date, float]] = []
        self.rejects: dict[str, int] = {}

    # ------------------------------------------------------------------ util
    def _iv(self, sym: str, d: date) -> float | None:
        closes = self.book.closes_until(sym, d, 90)
        rv = realised_vol(closes, 60)
        if rv is None or rv <= 0:
            return None
        return max(0.08, rv * self.cfg.iv_premium)

    def _opt_value(self, lc: LongCall, spot: float, d: date) -> float:
        dte = (lc.expiry - d).days
        if dte <= 0:
            return max(0.0, spot - lc.strike)
        iv = self._iv(lc.symbol, d) or lc.entry_iv
        r = self.book.risk_free(d)
        return price(spot, lc.strike, dte / 365.0, r, iv, "call")

    def _mtm(self, d: date) -> float:
        tot = 0.0
        for lc in self.open:
            spot = self.book.close(lc.symbol, d)
            if spot is None:
                tot += lc.premium_paid       # stale: carry at cost
                continue
            tot += self._opt_value(lc, spot, d) * CONTRACT_MULT * lc.contracts
        return tot

    def equity_at(self, d: date) -> float:
        return self.cash + self._mtm(d)

    def _reject(self, k: str) -> None:
        self.rejects[k] = self.rejects.get(k, 0) + 1

    # ------------------------------------------------------------------- run
    def run(self, start: date, end: date) -> dict:
        cfg = self.cfg
        days = [d for d in self.book.days if start <= d <= end]
        last_rebal: date | None = None
        prev = None
        for d in days:
            # interest on idle cash
            if prev is not None:
                idle = max(0.0, self.cash)
                self.cash += idle * self.book.risk_free(d) * ((d - prev).days / 365.0)
            prev = d

            self._manage(d)
            if last_rebal is None or (d - last_rebal).days >= cfg.rebalance_days:
                if self._market_ok(d):
                    self._rebalance(d)
                last_rebal = d
            self.curve.append((d, self.equity_at(d)))

        for lc in list(self.open):
            self._close(lc, days[-1], "END_OF_TEST")
        return {"equity_curve": self.curve, "trades": self.trades,
                "rejects": self.rejects}

    def _market_ok(self, d: date) -> bool:
        if not self.cfg.market_filter:
            return True
        b = self.book.closes_until(self.cfg.benchmark, d, 200)
        if len(b) < 200:
            return False
        return b[-1] > sum(b) / len(b)

    # ------------------------------------------------------------- lifecycle
    def _manage(self, d: date) -> None:
        cfg = self.cfg
        for lc in list(self.open):
            spot = self.book.close(lc.symbol, d)
            if spot is None:
                continue
            dte = (lc.expiry - d).days
            val = self._opt_value(lc, spot, d)
            ret = (val / lc.entry_price - 1.0) if lc.entry_price > 0 else -1.0
            if dte <= 0:
                self._close(lc, d, "EXPIRY")
            elif ret >= cfg.profit_target:
                self._close(lc, d, "PROFIT_TARGET")
            elif ret <= cfg.stop_loss:
                self._close(lc, d, "STOP")
            elif dte <= cfg.exit_dte:
                self._close(lc, d, "ROLL_DTE")

    def _close(self, lc: LongCall, d: date, reason: str) -> None:
        spot = self.book.close(lc.symbol, d) or lc.entry_spot
        val = self._opt_value(lc, spot, d)
        val *= (1.0 - self.cfg.slippage_pct)          # sell into the bid
        proceeds = max(0.0, val) * CONTRACT_MULT * lc.contracts
        proceeds -= self.cfg.fee_per_contract * lc.contracts
        self.cash += proceeds
        self.open.remove(lc)
        self.trades.append(DirTrade(
            symbol=lc.symbol, entry_date=lc.entry_date, exit_date=d,
            entry_spot=lc.entry_spot, exit_spot=spot,
            premium_paid=lc.premium_paid, proceeds=proceeds,
            pnl=proceeds - lc.premium_paid,
            return_on_premium=(proceeds / lc.premium_paid - 1.0) if lc.premium_paid else 0.0,
            reason=reason, held_days=(d - lc.entry_date).days))

    def _rebalance(self, d: date) -> None:
        cfg = self.cfg
        if len(self.open) >= cfg.max_positions:
            return
        held = {lc.symbol for lc in self.open}
        cands: dict[str, list[float]] = {}
        for sym in cfg.universe:
            if sym in held:
                continue
            closes = self.book.closes_until(sym, d, 300)
            if len(closes) < 260 or closes[-1] < cfg.min_price:
                continue
            cands[sym] = closes
        if not cands:
            self._reject("no_candidates"); return
        bench = self.book.closes_until(cfg.benchmark, d, 300)
        picks = rank(cands, bench, cfg.top_n, require_uptrend=cfg.require_uptrend)
        if not picks:
            self._reject("no_ranked"); return

        equity = self.equity_at(d)
        for sc in picks:
            if len(self.open) >= cfg.max_positions:
                break
            spot = self.book.close(sc.symbol, d)
            iv = self._iv(sc.symbol, d)
            if spot is None or iv is None:
                self._reject("no_iv"); continue
            expiry = d + timedelta(days=cfg.dte)
            T = cfg.dte / 365.0
            r = self.book.risk_free(d)
            k = round(strike_for_delta(spot, T, r, iv, cfg.target_delta, "call"), 2)
            px = price(spot, k, T, r, iv, "call") * (1.0 + cfg.slippage_pct)
            if px <= 0.05:
                self._reject("no_premium"); continue
            if cfg.target_notional is not None:
                g = greeks(spot, k, T, r, iv, "call")
                delta = max(0.05, abs(g.delta))
                # contracts such that delta x 100 x spot x n = per-name notional
                per_name_notional = equity * cfg.target_notional / cfg.max_positions
                n = int(per_name_notional // (delta * CONTRACT_MULT * spot))
                # never let premium at risk exceed the cap
                cap = int((equity * cfg.max_premium_pct) // (px * CONTRACT_MULT))
                n = min(n, cap)
            else:
                budget = equity * cfg.premium_pct
                n = int(budget // (px * CONTRACT_MULT))
            if n < 1:
                self._reject("too_small"); continue
            cost = px * CONTRACT_MULT * n + cfg.fee_per_contract * n
            if cost > self.cash:
                self._reject("no_cash"); continue
            self.cash -= cost
            self.open.append(LongCall(
                symbol=sc.symbol, strike=k, expiry=expiry, entry_date=d,
                contracts=n, entry_price=px, entry_spot=spot, entry_iv=iv,
                premium_paid=cost))


def equal_weight_universe(book: HistoricalBook, universe: list[str],
                          start: date, end: date, equity: float,
                          rebalance_days: int = 63) -> list[tuple[date, float]]:
    """Equal-weight, periodically rebalanced buy-and-hold of the same names.

    This is the benchmark that controls for a hindsight-chosen universe.
    A name is included only from the date it actually has price history.
    """
    days = [d for d in book.days if start <= d <= end]
    if not days:
        return []
    curve = []
    holdings: dict[str, float] = {}
    val = equity
    last = None
    for d in days:
        if holdings:
            # last traded price, not zero: delisted names are usually
            # acquisitions that paid out, and zeroing them understates the
            # benchmark that every strategy is measured against.
            val = sum(q * (book.last_price(s, d) or 0) for s, q in holdings.items())
            val += holdings.get("__cash__", 0.0)
        if last is None or (d - last).days >= rebalance_days:
            live = [s for s in universe if book.close(s, d)]
            if live:
                per = val / len(live)
                holdings = {s: per / book.close(s, d) for s in live}
            last = d
        curve.append((d, val))
    return curve
