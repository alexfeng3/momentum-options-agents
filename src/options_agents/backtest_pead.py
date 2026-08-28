"""PEAD backtest on real SEC earnings events, with an optional options overlay.

Post-Earnings Announcement Drift: a volume-confirmed positive earnings surprise is
followed by continued drift for weeks, as institutions reposition. Bernard & Thomas
(1989). Here the surprise is measured two ways and both must agree:

  * FUNDAMENTAL — SUE from real SEC diluted EPS (seasonal random walk).
  * MARKET — the volume-confirmed announcement gap.

No look-ahead: entry is the day AFTER the detected announcement, and the
announcement is located using only bars up to the SEC filing date.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .earnings import build_events
from .pricing import price, strike_for_delta
from .selection import realised_vol

MULT = 100.0


@dataclass
class PeadConfig:
    universe: tuple[str, ...] = ()
    sue_min: float = 0.5
    gap_min: float = 0.01
    vol_ratio_min: float = 1.3
    hold_days: int = 40
    max_positions: int = 8
    stop_pct: float = -0.15
    market_filter: bool = True
    starting_equity: float = 100_000.0
    # options overlay: sell a put credit spread on each PEAD name
    overlay: bool = True
    short_delta: float = 0.20
    width_pct: float = 0.10
    dte: int = 30
    risk_per_trade: float = 0.03
    max_risk: float = 0.15
    profit_target: float = 0.50
    iv_premium: float = 1.10
    slippage: float = 0.05

    def replace(self, **kw):
        from dataclasses import replace as _r
        return _r(self, **kw)


@dataclass
class PeadTrade:
    symbol: str
    entry_date: date
    exit_date: date
    entry_px: float
    exit_px: float
    shares: float
    pnl: float
    return_on_premium: float
    reason: str
    sue: float
    gap: float
    kind: str = "stock"


@dataclass
class _Pos:
    sym: str; entry: date; px: float; shares: float; expiry: date
    sue: float; gap: float


@dataclass
class _Spread:
    sym: str; ks: float; kl: float; exp: date; n: int
    credit: float; width: float; opened: date; sue: float; gap: float
    collateral: float = 0.0      # cash reserved; cannot also be invested


class PeadBacktest:
    def __init__(self, cfg: PeadConfig, book):
        self.cfg, self.book = cfg, book
        self.cash = cfg.starting_equity
        self.pos: list[_Pos] = []
        self.spreads: list[_Spread] = []
        self.trades: list[PeadTrade] = []
        self.curve: list[tuple[date, float]] = []
        self.events: dict[date, list] = {}

    def _load_events(self):
        for sym in self.cfg.universe:
            for e in build_events(sym, self.book):
                if not e.announce_date or e.sue is None or e.gap_pct is None:
                    continue
                self.events.setdefault(e.announce_date, []).append(e)

    def _iv(self, sym, d):
        rv = realised_vol(self.book.closes_until(sym, d, 90), 60)
        return max(0.10, rv * self.cfg.iv_premium) if rv else None

    def _spread_cost(self, sp, d):
        spot = self.book.close(sp.sym, d)
        if spot is None:
            return 0.0
        dte = (sp.exp - d).days
        if dte <= 0:
            return max(0.0, sp.ks - spot) - max(0.0, sp.kl - spot)
        iv = self._iv(sp.sym, d)
        if iv is None:
            return 0.0
        r = self.book.risk_free(d); T = dte / 365.0
        return price(spot, sp.ks, T, r, iv, "put") - price(spot, sp.kl, T, r, iv, "put")

    @property
    def reserved(self) -> float:
        return sum(s.collateral for s in self.spreads)

    @property
    def free_cash(self) -> float:
        return self.cash - self.reserved

    def _assert_solvent(self, d):
        if self.cash < -1e-6:
            raise AssertionError(f"{d}: negative cash ${self.cash:,.2f}")
        if self.free_cash < -1e-6:
            raise AssertionError(
                f"{d}: spread collateral ${self.reserved:,.2f} exceeds cash "
                f"${self.cash:,.2f} — capital used twice")

    def equity_at(self, d):
        v = self.cash
        v += sum(p.shares * (self.book.close(p.sym, d) or p.px) for p in self.pos)
        v -= sum(max(0.0, min(self._spread_cost(s, d), s.width)) * MULT * s.n
                 for s in self.spreads)
        return v

    def run(self, start: date, end: date) -> dict:
        cfg = self.cfg
        self._load_events()
        days = [d for d in self.book.days if start <= d <= end]
        prev = None
        for d in days:
            if prev is not None:
                self.cash += max(0.0, self.free_cash) * self.book.risk_free(d) * \
                    ((d - prev).days / 365.0)
            prev = d
            self._manage(d)
            self._enter(d)
            self._assert_solvent(d)
            self.curve.append((d, self.equity_at(d)))
        for p in list(self.pos):
            self._close(p, days[-1], "END")
        for s in list(self.spreads):
            self._close_spread(s, days[-1], "END")
        return {"equity_curve": self.curve, "trades": self.trades}

    def _manage(self, d):
        for p in list(self.pos):
            spot = self.book.close(p.sym, d)
            if spot is None:
                continue
            if d >= p.expiry:
                self._close(p, d, "TIME")
            elif spot / p.px - 1 <= self.cfg.stop_pct:
                self._close(p, d, "STOP")
        for s in list(self.spreads):
            c = self._spread_cost(s, d)
            if (s.exp - d).days <= 0 or (s.credit > 0 and
                                         (s.credit - c) / s.credit >= self.cfg.profit_target):
                self._close_spread(s, d, "SPREAD")

    def _close(self, p, d, reason):
        spot = self.book.close(p.sym, d) or p.px
        proceeds = p.shares * spot
        self.cash += proceeds
        cost = p.shares * p.px
        self.pos.remove(p)
        self.trades.append(PeadTrade(p.sym, p.entry, d, p.px, spot, p.shares,
                                     proceeds - cost,
                                     (proceeds / cost - 1) if cost else 0.0,
                                     reason, p.sue, p.gap, "stock"))

    def _close_spread(self, s, d, reason):
        c = max(0.0, min(self._spread_cost(s, d), s.width)) * (1 + self.cfg.slippage)
        pay = c * MULT * s.n
        self.cash -= pay
        self.spreads.remove(s)
        credit = s.credit * MULT * s.n
        self.trades.append(PeadTrade(s.sym, s.opened, d, s.credit, c, s.n,
                                     credit - pay,
                                     (credit - pay) / max(1e-9, (s.width - s.credit) * MULT * s.n),
                                     reason, s.sue, s.gap, "spread"))

    def _enter(self, d):
        cfg = self.cfg
        yday = [dd for dd in self.book.days if dd < d]
        if not yday:
            return
        evs = self.events.get(yday[-1], [])
        if not evs:
            return
        if cfg.market_filter:
            b = self.book.closes_until("SPY", d, 200)
            if len(b) < 200 or b[-1] <= sum(b) / len(b):
                return
        eq = self.equity_at(d)
        for e in evs:
            if len(self.pos) >= cfg.max_positions:
                break
            if any(p.sym == e.symbol for p in self.pos):
                continue
            if e.sue < cfg.sue_min or e.gap_pct < cfg.gap_min:
                continue
            if (e.vol_ratio or 0) < cfg.vol_ratio_min:
                continue
            spot = self.book.close(e.symbol, d)
            if spot is None or spot < 5:
                continue
            # Only unreserved cash may buy stock, and we must leave room for the
            # spread we are about to sell against this name.
            headroom = eq * cfg.max_risk if cfg.overlay else 0.0
            alloc = min(eq / cfg.max_positions, max(0.0, self.free_cash - headroom))
            if alloc <= 0:
                continue
            sh = alloc / spot
            if sh <= 0:
                continue
            self.cash -= sh * spot
            self.pos.append(_Pos(e.symbol, d, spot, sh,
                                 d + timedelta(days=cfg.hold_days),
                                 e.sue, e.gap_pct))
            if cfg.overlay:
                self._sell_spread(e, d, spot, eq)

    def _sell_spread(self, e, d, spot, eq):
        cfg = self.cfg
        if any(s.sym == e.symbol for s in self.spreads):
            return
        iv = self._iv(e.symbol, d)
        if iv is None:
            return
        T = cfg.dte / 365.0; r = self.book.risk_free(d)
        ks = round(strike_for_delta(spot, T, r, iv, cfg.short_delta, "put"), 2)
        w = max(1.0, round(spot * cfg.width_pct, 2)); kl = ks - w
        if kl <= 0:
            return
        cr = (price(spot, ks, T, r, iv, "put")
              - price(spot, kl, T, r, iv, "put")) * (1 - cfg.slippage)
        if cr <= 0.02:
            return
        risk = (w - cr) * MULT
        deployed = sum(s.collateral for s in self.spreads)
        n = int((eq * cfg.risk_per_trade) // risk)
        if n < 1:
            return
        if deployed + n * risk > eq * cfg.max_risk:
            n = int((eq * cfg.max_risk - deployed) // risk)
        # HARD CONSTRAINT: collateral must fit in unreserved cash, net of credit.
        n = min(n, int((self.free_cash + cr * MULT * n) // risk) if risk else 0)
        if n < 1:
            return
        self.cash += cr * MULT * n
        self.spreads.append(_Spread(e.symbol, ks, kl, d + timedelta(days=cfg.dte),
                                    n, cr, w, d, e.sue, e.gap_pct,
                                    collateral=risk * n))
