"""Historical data loading for the backtester. CSV in, plain dicts out."""
from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data" / "underlying"


def load_series(symbol: str, data_dir: Path | None = None) -> dict[date, dict[str, float]]:
    f = (data_dir or DATA) / f"{symbol}.csv"
    if not f.exists():
        raise FileNotFoundError(f"{f} — run scripts/fetch_data.py")
    out: dict[date, dict[str, float]] = {}
    with f.open() as fh:
        for row in csv.DictReader(fh):
            d = datetime.fromisoformat(row["date"].split()[0]).date()
            try:
                rec = {k: float(row[k]) for k in ("open", "high", "low", "close")}
                # volume matters: the earnings-announcement detector requires a
                # volume-confirmed gap, and silently reads 0 if it is missing.
                try:
                    rec["volume"] = float(row.get("volume") or 0.0)
                except (TypeError, ValueError):
                    rec["volume"] = 0.0
                out[d] = rec
            except (ValueError, KeyError):
                continue
    return out


class HistoricalBook:
    """All series needed by the backtest, aligned on the trading calendar."""

    def __init__(self, underlyings: list[str], data_dir: Path | None = None):
        self.px = {}
        for s in underlyings:
            try:
                self.px[s] = load_series(s, data_dir)
            except FileNotFoundError:
                if data_dir is None:
                    raise
        self.vol, self.rate = {}, {}
        for s in ("_VIX", "_VXN", "_VIX9D", "_VIX3M"):
            try:
                self.vol[s] = load_series(s)
            except FileNotFoundError:
                pass
        try:
            self.rate = load_series("_IRX")
        except FileNotFoundError:
            self.rate = {}
        # trading days = the union across underlyings, sorted
        days: set[date] = set()
        for s in self.px:
            days |= set(self.px[s])
        self.days = sorted(days)

    def close(self, sym: str, d: date) -> float | None:
        r = self.px.get(sym, {}).get(d)
        return r["close"] if r else None

    def last_price(self, sym: str, d: date) -> float | None:
        """Most recent close at or before d.

        Required for delisting. A held name whose series ends must be liquidated
        at its LAST TRADED PRICE, not marked to zero: most series that end are
        acquisitions (ATVI, VMW, XLNX, TWTR) which paid out at a premium.
        Marking those to zero manufactures total losses and produced a fake
        -91% drawdown. True bankruptcies end near zero anyway, so this handles
        both cases correctly.
        """
        rec = self.px.get(sym)
        if not rec:
            return None
        r = rec.get(d)
        if r:
            return r["close"]
        prior = [x for x in rec if x <= d]
        return rec[max(prior)]["close"] if prior else None

    def is_delisted(self, sym: str, d: date, stale_days: int = 15) -> bool:
        """True only if the series went quiet well before `d`.

        A tolerance is essential: the newest bar is normally the PREVIOUS session,
        so a naive `max(rec) < d` marks the entire universe delisted and silently
        scores zero candidates.
        """
        rec = self.px.get(sym)
        if not rec:
            return True
        return (d - max(rec)).days > stale_days

    def vol_close(self, idx: str, d: date) -> float | None:
        r = self.vol.get(idx, {}).get(d)
        return r["close"] if r else None

    def risk_free(self, d: date) -> float:
        """13-week T-bill as a decimal. Falls back to the last known value."""
        r = self.rate.get(d)
        if r:
            return max(0.0, r["close"] / 100.0)
        prior = [dd for dd in self.rate if dd <= d]
        if not prior:
            return 0.02
        return max(0.0, self.rate[max(prior)]["close"] / 100.0)

    def closes_until(self, sym: str, d: date, n: int) -> list[float]:
        ds = [dd for dd in self.px[sym] if dd <= d][-n:]
        return [self.px[sym][dd]["close"] for dd in sorted(ds)]
