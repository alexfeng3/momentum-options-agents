#!/usr/bin/env python
"""Add known delisted / bankrupt / acquired names to the broad universe.

Alpaca's /v2/assets inactive list is ~85% OTC shells and omits most notable
failures (FRCB, SIVBQ, BBBYQ are absent), but the DATA api still serves their
bars. So the failures have to be requested by name.

This list is CURATED, which is itself a bias: it favours *memorable* failures.
That is the conservative direction — memorable failures were large and liquid,
exactly the names a momentum screen could have bought. It does not fully repair
survivorship bias, and docs/UNIVERSE.md says so.
"""
from __future__ import annotations

import os
import statistics as st
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "broad"

# Bankruptcies, failed SPACs/EV names, meme collapses, bank failures, buyouts.
FAILURES = """
FRCB SIVBQ SBNY BBBYQ WEWKQ PTON WISH RIDE NKLA GOEV ARVL FFIE MULN SOLO
XELA CVNA AMC EXPR PRTY YELLQ RAD TUP BIG PARA LUMN VFC NCLH CCL AAL
XOG ANDV NUAN CONE ZNGA CERN PLAN TWTR ATVI VMW SGEN HZNP ABMD FISV XLNX
MXIM ALXN CXO WLTW TIF MYL AGN CELG RTN ETFC WORK FIT PBCT PS TCF
ZM DOCU ROKU PINS SNAP CHWY BYND SPCE OPEN SKLZ CLOV WKHS BLNK QS HYLN
LAZR VLDR MVIS GEVO SPWR RUN NOVA ENVX AMRS PLL LILM JOBY ACHR EVGO
ZI COUP AVLR PING SUMO API MNTV CDAY SAIL ZEN MIME PFPT
""".split()

MIN_BARS, MIN_DV = 200, 1_000_000


def main() -> int:
    load_dotenv(ROOT / ".env")
    k, s = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")
    if not k or not s:
        sys.exit("credentials not set")
    ses = requests.Session()
    ses.headers.update({"APCA-API-KEY-ID": k, "APCA-API-SECRET-KEY": s})
    OUT.mkdir(parents=True, exist_ok=True)

    todo = [x for x in dict.fromkeys(FAILURES) if not (OUT / f"{x}.csv").exists()]
    print(f"{len(todo)} names to probe ({len(FAILURES)-len(todo)} already present)")
    added = dead = 0
    for i in range(0, len(todo), 50):
        batch = todo[i:i + 50]
        got: dict[str, list] = {}
        page = None
        while True:
            p = {"symbols": ",".join(batch), "timeframe": "1Day",
                 "start": "2020-08-01", "limit": 10000, "adjustment": "split",
                 "feed": "iex", "sort": "asc"}
            if page:
                p["page_token"] = page
            r = ses.get("https://data.alpaca.markets/v2/stocks/bars", params=p, timeout=120)
            if r.status_code != 200:
                break
            j = r.json()
            for sym, bars in (j.get("bars") or {}).items():
                got.setdefault(sym, []).extend(bars)
            page = j.get("next_page_token")
            if not page:
                break
        for sym, bars in got.items():
            if len(bars) < MIN_BARS:
                continue
            dv = [b["c"] * b["v"] for b in bars if b.get("v")]
            if not dv or st.median(dv) < MIN_DV:
                continue
            rows = ["date,open,high,low,close,volume"]
            rows += [f"{b['t'][:10]},{b['o']},{b['h']},{b['l']},{b['c']},{b['v']}"
                     for b in bars]
            (OUT / f"{sym}.csv").write_text("\n".join(rows))
            added += 1
            if bars[-1]["t"][:10] < "2026-06-01":
                dead += 1
    print(f"added {added} names, {dead} of them stopped trading before 2026-06")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
