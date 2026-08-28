#!/usr/bin/env python
"""Build a survivorship-bias-controlled universe from Alpaca.

The 39-name universe in the original backtest was hand-picked in 2026 and is the
single biggest weakness in those results. This builds a universe the honest way:

  * ACTIVE tradable US equities, AND
  * INACTIVE (delisted, bankrupt, acquired) names, which is the whole point.
    FRCB, SIVBQ and BBBYQ are in here. A universe without failures is a universe
    that cannot lose.

Liquidity screen is applied per symbol from its OWN history, not from today's
snapshot, so a name that was liquid in 2021 and died in 2023 stays in.

Alpaca's IEX daily history starts ~2020-07, so this is a ~6-year window. Shorter
than the 2005-2026 .pkl set, but far less biased. Both are reported.
"""
from __future__ import annotations

import json
import os
import statistics as st
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "broad"
START = "2020-08-01"
MIN_BARS = 400
MIN_MEDIAN_DOLLAR_VOL = 3_000_000


def sess():
    k, s = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")
    if not k or not s:
        sys.exit("ALPACA_API_KEY / ALPACA_SECRET_KEY not set")
    x = requests.Session()
    x.headers.update({"APCA-API-KEY-ID": k, "APCA-API-SECRET-KEY": s})
    return x


def candidates(s) -> list[str]:
    out: set[str] = set()
    for status in ("active", "inactive"):
        r = s.get("https://paper-api.alpaca.markets/v2/assets",
                  params={"status": status, "asset_class": "us_equity"}, timeout=120)
        r.raise_for_status()
        for a in r.json():
            sym = a["symbol"]
            if not a.get("tradable") and status == "active":
                continue
            if a.get("exchange") not in ("NASDAQ", "NYSE", "AMEX", "ARCA", "BATS"):
                continue
            if len(sym) > 5 or not sym.isalpha():
                continue
            out.add(sym)
        print(f"  {status}: running total {len(out)}")
    return sorted(out)


def fetch(s, syms: list[str]) -> dict[str, list]:
    out: dict[str, list] = {}
    page = None
    while True:
        p = {"symbols": ",".join(syms), "timeframe": "1Day", "start": START,
             "limit": 10000, "adjustment": "split", "feed": "iex", "sort": "asc"}
        if page:
            p["page_token"] = page
        for attempt in range(4):
            r = s.get("https://data.alpaca.markets/v2/stocks/bars", params=p, timeout=120)
            if r.status_code == 429:
                time.sleep(2 * (attempt + 1)); continue
            r.raise_for_status(); break
        else:
            return out
        j = r.json()
        for sym, bars in (j.get("bars") or {}).items():
            out.setdefault(sym, []).extend(bars)
        page = j.get("next_page_token")
        if not page:
            return out


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    OUT.mkdir(parents=True, exist_ok=True)
    s = sess()
    cands = candidates(s)
    print(f"{len(cands)} candidate symbols")
    kept = 0
    B = 150
    for i in range(0, len(cands), B):
        batch = cands[i:i + B]
        try:
            data = fetch(s, batch)
        except Exception as e:
            print(f"  batch {i}: {e}"); continue
        for sym, bars in data.items():
            if len(bars) < MIN_BARS:
                continue
            dv = [b["c"] * b["v"] for b in bars if b.get("v")]
            if not dv or st.median(dv) < MIN_MEDIAN_DOLLAR_VOL:
                continue
            rows = ["date,open,high,low,close,volume"]
            rows += [f"{b['t'][:10]},{b['o']},{b['h']},{b['l']},{b['c']},{b['v']}"
                     for b in bars]
            (OUT / f"{sym}.csv").write_text("\n".join(rows))
            kept += 1
        print(f"  {i+len(batch)}/{len(cands)} scanned, {kept} kept", flush=True)
    print(f"DONE: {kept} symbols in {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
