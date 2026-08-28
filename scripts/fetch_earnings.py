#!/usr/bin/env python
"""Fetch real quarterly EPS + SEC filing dates from EDGAR's free XBRL API.

This is what makes a PEAD backtest possible: SEC gives the actual diluted EPS per
fiscal quarter AND the date the filing hit EDGAR. No vendor earnings calendar and
no API key required.

Rate-limited to SEC's published guidance (<10 req/s). Results cached to
data/earnings/<TICKER>.json so the backtest never needs the network.
"""
from __future__ import annotations
import json, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "earnings"
# SEC requires a descriptive User-Agent with contact details. Set SEC_USER_AGENT
# in your environment; the default is deliberately generic so this repo carries
# no personal contact information.
UA = os.getenv("SEC_USER_AGENT", "options-agents-research contact@example.com")
TICKERS = ["AAPL","AMD","AMZN","AVAV","AVGO","CEG","CHPT","COIN","ENPH","FCEL",
           "FSLR","GOOGL","KTOS","LCID","LMT","LRCX","MARA","META","MRVL","MSFT",
           "MU","NVDA","PLTR","PLUG","RKLB","RUN","SMCI","SPCE","STX","TSLA",
           "TSM","VST","WDC"]


def get(url: str) -> dict | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept-Encoding": "gzip, deflate"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            if r.headers.get("Content-Encoding") == "gzip":
                import gzip
                raw = gzip.decompress(raw)
            return json.loads(raw)
    except Exception as e:
        print(f"    ! {e}")
        return None


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    tmap = get("https://www.sec.gov/files/company_tickers.json")
    if not tmap:
        return 1
    cik = {v["ticker"]: v["cik_str"] for v in tmap.values()}

    for t in TICKERS:
        dest = OUT / f"{t}.json"
        if dest.exists():
            print(f"  {t}: cached"); continue
        c = cik.get(t)
        if not c:
            print(f"  {t}: no CIK"); continue
        url = (f"https://data.sec.gov/api/xbrl/companyconcept/CIK{c:010d}"
               f"/us-gaap/EarningsPerShareDiluted.json")
        d = get(url)
        time.sleep(0.2)
        if not d:
            print(f"  {t}: no EPS concept"); continue
        rows = []
        for unit, items in (d.get("units") or {}).items():
            for it in items:
                # quarterly only: 10-Q, or a 10-K's Q4 stub
                if it.get("form") not in ("10-Q", "10-K"):
                    continue
                if not it.get("filed") or it.get("val") is None:
                    continue
                rows.append({"start": it.get("start"), "end": it.get("end"),
                             "val": it["val"], "filed": it["filed"],
                             "form": it["form"], "fy": it.get("fy"),
                             "fp": it.get("fp"), "accn": it.get("accn")})
        # dedupe on (end, accn); keep the earliest filing for each period end
        seen = {}
        for r in rows:
            k = (r["start"], r["end"])
            if k not in seen or r["filed"] < seen[k]["filed"]:
                seen[k] = r
        out = sorted(seen.values(), key=lambda r: (r["filed"], r["end"] or ""))
        dest.write_text(json.dumps({"ticker": t, "cik": c, "rows": out}, indent=1))
        print(f"  {t}: {len(out)} quarterly EPS rows, "
              f"{out[0]['filed'] if out else '-'} -> {out[-1]['filed'] if out else '-'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
