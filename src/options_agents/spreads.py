"""Pairing broker option legs back into the spreads the strategy opened.

Alpaca reports each leg of a multi-leg position separately, so the spread the
strategy sold has to be reconstructed from two rows before it can be managed.
This module is pure: it takes position dicts and returns structures. No network,
no config, no orders — so the exit rules that depend on it stay testable.

Everything here is quoted in **premium per share**, the same units as
`est_credit` and Alpaca's `avg_entry_price`. Multiply by 100 for dollars.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


def parse_occ(symbol: str) -> tuple[str, date, str, float] | None:
    """`WBD260925P00027000` -> ("WBD", 2026-09-25, "P", 27.0).

    The trailing 15 characters are fixed width (6 date + 1 right + 8 strike), so
    the underlying is whatever precedes them.
    """
    if len(symbol) <= 15:
        return None
    root, tail = symbol[:-15], symbol[-15:]
    try:
        expiry = date(2000 + int(tail[0:2]), int(tail[2:4]), int(tail[4:6]))
        right = tail[6].upper()
        strike = int(tail[7:]) / 1000.0
    except (ValueError, IndexError):
        return None
    if right not in ("C", "P") or not root:
        return None
    return root, expiry, right, strike


@dataclass
class OpenSpread:
    underlying: str
    expiry: date
    right: str
    short_symbol: str
    long_symbol: str
    short_strike: float
    long_strike: float
    contracts: int
    entry_credit: float          # premium per share received when opened
    width: float = 0.0
    quotes: dict = field(default_factory=dict)
    pricing: dict = field(default_factory=dict)   # filled by debit_to_close()

    def __post_init__(self):
        if not self.width:
            self.width = abs(self.short_strike - self.long_strike)

    def dte(self, as_of: date) -> int:
        return (self.expiry - as_of).days

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items()}
        d["expiry"] = self.expiry.isoformat()
        return d


def pair_spreads(positions: list[dict]) -> list[OpenSpread]:
    """Reconstruct short vertical spreads from individual option legs.

    Legs are matched on (underlying, expiry, right): one short row against one
    long row. A leg that cannot be paired is ignored rather than guessed at — a
    naked short option is not something this strategy creates, and inventing a
    spread around an unpaired leg would misstate the risk.
    """
    groups: dict[tuple, dict[str, list]] = {}
    for p in positions:
        if p.get("asset_class") != "us_option":
            continue
        parsed = parse_occ(p.get("symbol", ""))
        if not parsed:
            continue
        root, expiry, right, strike = parsed
        try:
            qty = float(p["qty"])
            entry = abs(float(p["avg_entry_price"]))
        except (KeyError, TypeError, ValueError):
            continue
        if qty == 0:
            continue
        side = "short" if qty < 0 else "long"
        groups.setdefault((root, expiry, right), {}).setdefault(side, []).append(
            {"symbol": p["symbol"], "strike": strike, "qty": abs(qty), "entry": entry})

    out: list[OpenSpread] = []
    for (root, expiry, right), sides in groups.items():
        shorts = sorted(sides.get("short", []), key=lambda x: x["strike"])
        longs = sorted(sides.get("long", []), key=lambda x: x["strike"])
        for s in shorts:
            if not longs:
                break
            # A put spread is protected by the strike BELOW it, a call spread by
            # the one above. Take the nearest such leg.
            if right == "P":
                cands = [l for l in longs if l["strike"] < s["strike"]]
                partner = max(cands, key=lambda x: x["strike"]) if cands else None
            else:
                cands = [l for l in longs if l["strike"] > s["strike"]]
                partner = min(cands, key=lambda x: x["strike"]) if cands else None
            if partner is None:
                continue
            longs.remove(partner)
            credit = s["entry"] - partner["entry"]
            width = abs(s["strike"] - partner["strike"])
            # A credit spread always takes in less than its width. If it did not,
            # avg_entry_price is not in the units assumed and acting on it would
            # misprice the exit — skip rather than trade on a bad parse.
            if not (0 < credit < width):
                continue
            out.append(OpenSpread(
                underlying=root, expiry=expiry, right=right,
                short_symbol=s["symbol"], long_symbol=partner["symbol"],
                short_strike=s["strike"], long_strike=partner["strike"],
                contracts=int(min(s["qty"], partner["qty"])),
                entry_credit=round(credit, 4), width=width))
    return out


def debit_to_close(sp: OpenSpread) -> dict:
    """What it costs to buy the spread back, from its legs' current quotes.

    Closing a short vertical means buying back the short leg and selling the
    long one, so the debit is `short − long`. `natural` is what crossing both
    markets costs right now; `mid` is fair value and is what the profit test
    uses — measuring profit off the price you would be forced to pay makes a
    winner look like a loser whenever the market is wide.
    """
    s = sp.quotes.get(sp.short_symbol) or {}
    l = sp.quotes.get(sp.long_symbol) or {}
    sb, sa = float(s.get("bp") or 0), float(s.get("ap") or 0)
    lb, la = float(l.get("bp") or 0), float(l.get("ap") or 0)
    two_sided = sb > 0 and sa > 0 and lb > 0 and la > 0
    mid = (sb + sa) / 2 - (lb + la) / 2
    natural = sa - lb                      # pay the short's ask, hit the long's bid
    return {"two_sided": two_sided, "mid_debit": round(mid, 4),
            "natural_debit": round(natural, 4),
            "short_bid": sb, "short_ask": sa, "long_bid": lb, "long_ask": la}
