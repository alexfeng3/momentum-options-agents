"""Agent 1 — Market Data Agent.

Fetches daily bars from Alpaca, computes point-in-time momentum scores, realised
volatility and IV estimates, and surfaces recent SEC earnings events. Returns
structured data only; makes no trading decisions.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta

from ..earnings import build_events
from ..selection import Score, rank, realised_vol
from ..volatility import iv_rank


@dataclass
class NameSnapshot:
    symbol: str
    last_price: float | None
    momentum_score: float | None
    mom_12_1: float | None
    mom_3m: float | None
    trend: float | None
    realised_vol: float | None
    iv_estimate: float | None
    iv_rank: float | None
    bars: int
    recent_earnings: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MarketSnapshot:
    as_of: str
    market_open: bool
    spy_above_sma200: bool
    spy_price: float | None
    names: dict[str, NameSnapshot] = field(default_factory=dict)
    ranked: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["names"] = {k: v.to_dict() if hasattr(v, "to_dict") else v
                      for k, v in self.names.items()}
        return d


class MarketDataAgent:
    name = "marketdata"

    def __init__(self, broker, book, cfg, log):
        self.broker, self.book, self.cfg, self.log = broker, book, cfg, log

    def run(self, as_of: date, top_n: int = 20) -> MarketSnapshot:
        cfg = self.cfg
        try:
            clock = self.broker.get_clock()
            is_open = bool(clock.get("is_open"))
        except Exception as e:
            self.log.emit(self.name, "clock_failed", {"error": str(e)})
            is_open = False

        spy = self.book.closes_until("SPY", as_of, 300)
        spy_ok = len(spy) >= 200 and spy[-1] > sum(spy[-200:]) / 200

        cands: dict[str, list[float]] = {}
        for s in cfg.universe:
            if self.book.is_delisted(s, as_of):
                continue
            c = self.book.closes_until(s, as_of, 300)
            if len(c) >= 260 and c[-1] >= cfg.min_price:
                rv = realised_vol(c, 60)
                if cfg.max_vol and (rv is None or rv > cfg.max_vol):
                    continue
                cands[s] = c

        scored: list[Score] = rank(cands, spy, top_n=max(top_n, cfg.top_n))
        names: dict[str, NameSnapshot] = {}
        ivh: dict[str, list[float]] = {}
        for sc in scored:
            c = cands[sc.symbol]
            rv = realised_vol(c, 60)
            iv = max(0.10, rv * cfg.iv_premium) if rv else None
            hist = []
            for k in range(60, 0, -1):
                if len(c) > k + 60:
                    h = realised_vol(c[:-k], 60)
                    if h:
                        hist.append(h * cfg.iv_premium)
            ivh[sc.symbol] = hist
            ev = None
            try:
                evs = [e for e in build_events(sc.symbol, self.book)
                       if e.announce_date and
                       as_of - timedelta(days=cfg.pead_window) <= e.announce_date <= as_of]
                if evs:
                    e = evs[-1]
                    ev = {"announce_date": e.announce_date.isoformat(),
                          "days_since": (as_of - e.announce_date).days,
                          "eps": e.eps, "sue": e.sue, "yoy_growth": e.yoy_growth,
                          "gap_pct": e.gap_pct, "vol_ratio": e.vol_ratio}
            except Exception:
                ev = None
            names[sc.symbol] = NameSnapshot(
                symbol=sc.symbol, last_price=c[-1], momentum_score=sc.total,
                mom_12_1=sc.mom_12_1, mom_3m=sc.mom_3m, trend=sc.trend,
                realised_vol=rv, iv_estimate=iv,
                iv_rank=iv_rank(hist, iv) if (hist and iv) else None,
                bars=len(c), recent_earnings=ev)

        snap = MarketSnapshot(
            as_of=as_of.isoformat(), market_open=is_open,
            spy_above_sma200=spy_ok, spy_price=spy[-1] if spy else None,
            names=names, ranked=[s.symbol for s in scored])
        self.log.emit(self.name, "snapshot", {
            "as_of": snap.as_of, "market_open": is_open,
            "spy_above_sma200": spy_ok, "universe_size": len(cfg.universe),
            "candidates_scored": len(scored),
            "top": [{"symbol": s.symbol,
                     "score": round(s.total, 4),
                     "mom_12_1": round(s.mom_12_1, 4),
                     "vol": round(s.vol, 4)} for s in scored[:10]]})
        return snap
