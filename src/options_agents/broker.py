"""Alpaca REST wrapper with a hard paper-trading guard. The only module that
talks to Alpaca. Contains no strategy logic.

ACCOUNT SAFETY. Four gates must pass before any order:
  1. PAPER_TRADING=true in the environment.
  2. Base URL is Alpaca's paper endpoint.
  3. Account number starts 'PA'.
  4. SHA-256 of the account number is in ALLOWED_ACCOUNT_HASHES below.

Gate 4 stores a HASH, not the account number, so this repository can be public
without disclosing which account it trades. .env can narrow the allowlist but
never widen it — widening requires editing this file.
"""
from __future__ import annotations

import hashlib
import os
import time
from typing import Any

import requests

PAPER_BASE_URL = "https://paper-api.alpaca.markets"
DATA_BASE_URL = "https://data.alpaca.markets"

# SHA-256 of each account number this strategy may trade. Hashes, not values.
ALLOWED_ACCOUNT_HASHES = frozenset({
    "136bed16015d89eb85953e6ccf6b3153ab6e8bd5738572537df08c397d6958d5",
})


def account_hash(num: str) -> str:
    return hashlib.sha256(num.strip().encode()).hexdigest()


class NotPaperTradingError(RuntimeError):
    """Raised whenever anything could reach an account it must not."""


class AlpacaBroker:
    def __init__(self, feed: str = "iex", timeout: float = 20.0):
        self.key = os.getenv("ALPACA_API_KEY", "")
        self.secret = os.getenv("ALPACA_SECRET_KEY", "")
        if not self.key or not self.secret:
            raise RuntimeError("ALPACA_API_KEY / ALPACA_SECRET_KEY not set (see .env.example)")
        self.base = os.getenv("ALPACA_BASE_URL", PAPER_BASE_URL).rstrip("/")
        self.feed, self.timeout = feed, timeout
        self._verified = False
        self._s = requests.Session()
        self._s.headers.update({"APCA-API-KEY-ID": self.key,
                                "APCA-API-SECRET-KEY": self.secret,
                                "accept": "application/json"})

    # ------------------------------------------------------------------ guard
    def verify_paper(self) -> dict:
        if os.getenv("PAPER_TRADING", "").strip().lower() not in ("1", "true", "yes"):
            raise NotPaperTradingError("PAPER_TRADING is not true — refusing to trade.")
        if "paper-api.alpaca.markets" not in self.base:
            raise NotPaperTradingError(f"Not the paper endpoint: {self.base}")

        declared = os.getenv("ALPACA_ACCOUNT_NUMBER", "").strip()
        if not declared:
            raise NotPaperTradingError(
                "ALPACA_ACCOUNT_NUMBER is not set. This strategy refuses to trade an "
                "unnamed account.")
        if account_hash(declared) not in ALLOWED_ACCOUNT_HASHES:
            raise NotPaperTradingError(
                "ALPACA_ACCOUNT_NUMBER is not in the source allowlist. Editing .env "
                "cannot widen this — add the account's SHA-256 to "
                "ALLOWED_ACCOUNT_HASHES in broker.py if that is really intended.")

        acct = self.get_account()
        num = str(acct.get("account_number", ""))
        if not num.startswith("PA"):
            raise NotPaperTradingError(f"Account {num} is not a paper account.")
        if num != declared:
            raise NotPaperTradingError(
                f"ACCOUNT MISMATCH: credentials resolve to {num}, but "
                f"ALPACA_ACCOUNT_NUMBER declares a different account.")
        if account_hash(num) not in ALLOWED_ACCOUNT_HASHES:
            raise NotPaperTradingError("Resolved account is not in the source allowlist.")
        self._verified = True
        return acct

    @property
    def verified(self) -> bool:
        return self._verified

    # ------------------------------------------------------------------- http
    def _get(self, url: str, params: dict | None = None) -> Any:
        r = self._s.get(url, params=params, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    # ---------------------------------------------------------------- account
    def get_account(self) -> dict:
        return self._get(f"{self.base}/v2/account")

    def get_clock(self) -> dict:
        return self._get(f"{self.base}/v2/clock")

    def get_positions(self) -> list[dict]:
        return self._get(f"{self.base}/v2/positions")

    def get_open_orders(self) -> list[dict]:
        return self._get(f"{self.base}/v2/orders", {"status": "open", "limit": 500})

    def get_order(self, oid: str) -> dict:
        return self._get(f"{self.base}/v2/orders/{oid}")

    # ---------------------------------------------------------------- options
    def get_option_contracts(self, underlying: str, *, expiration_gte: str,
                             expiration_lte: str, option_type: str = "put",
                             strike_gte: float | None = None,
                             strike_lte: float | None = None,
                             limit: int = 1000) -> list[dict]:
        p = {"underlying_symbols": underlying, "status": "active",
             "expiration_date_gte": expiration_gte,
             "expiration_date_lte": expiration_lte,
             "type": option_type, "limit": limit}
        if strike_gte is not None:
            p["strike_price_gte"] = f"{strike_gte:.2f}"
        if strike_lte is not None:
            p["strike_price_lte"] = f"{strike_lte:.2f}"
        return self._get(f"{self.base}/v2/options/contracts", p).get("option_contracts", [])

    def get_option_quotes(self, symbols: list[str]) -> dict[str, dict]:
        if not symbols:
            return {}
        j = self._get(f"{DATA_BASE_URL}/v1beta1/options/quotes/latest",
                      {"symbols": ",".join(symbols)})
        return j.get("quotes") or {}

    def get_stock_bars(self, symbols: list[str], start_iso: str,
                       timeframe: str = "1Day", limit: int = 10000) -> dict:
        out: dict[str, list] = {}
        page = None
        while True:
            p = {"symbols": ",".join(symbols), "timeframe": timeframe,
                 "start": start_iso, "limit": limit, "adjustment": "split",
                 "feed": self.feed, "sort": "asc"}
            if page:
                p["page_token"] = page
            j = self._get(f"{DATA_BASE_URL}/v2/stocks/bars", p)
            for s, bars in (j.get("bars") or {}).items():
                out.setdefault(s, []).extend(bars)
            page = j.get("next_page_token")
            if not page:
                return out

    def get_latest_stock_quotes(self, symbols: list[str]) -> dict:
        return self._get(f"{DATA_BASE_URL}/v2/stocks/quotes/latest",
                         {"symbols": ",".join(symbols), "feed": self.feed}).get("quotes", {})

    # ----------------------------------------------------------------- orders
    def submit_equity_order(self, *, symbol: str, side: str, notional: float | None = None,
                            qty: float | None = None, client_order_id: str) -> dict:
        if not self._verified:
            raise NotPaperTradingError("verify_paper() has not passed.")
        body = {"symbol": symbol, "side": side, "type": "market",
                "time_in_force": "day", "order_class": "simple",
                "client_order_id": client_order_id}
        if notional is not None:
            body["notional"] = f"{notional:.2f}"
        else:
            body["qty"] = f"{qty:.9f}".rstrip("0").rstrip(".")
        return self._post("/v2/orders", body)

    def submit_spread_order(self, *, legs: list[dict], qty: int, limit_price: float,
                            client_order_id: str) -> dict:
        """Multi-leg defined-risk spread. Alpaca requires limit orders for mleg.

        `legs` entries: {"symbol", "side" ('buy'|'sell'), "ratio_qty",
        "position_intent"}. A credit spread is submitted with a NEGATIVE limit
        price on Alpaca's net-debit convention.
        """
        if not self._verified:
            raise NotPaperTradingError("verify_paper() has not passed.")
        for leg in legs:
            if "position_intent" not in leg:
                raise ValueError("every mleg leg needs a position_intent")
        body = {"order_class": "mleg", "qty": str(qty), "type": "limit",
                "time_in_force": "day", "limit_price": f"{limit_price:.2f}",
                "client_order_id": client_order_id, "legs": legs}
        return self._post("/v2/orders", body)

    def _post(self, path: str, body: dict) -> dict:
        r = self._s.post(f"{self.base}{path}", json=body, timeout=self.timeout)
        if r.status_code >= 400:
            raise RuntimeError(f"order rejected {r.status_code}: {r.text}")
        return r.json()

    def poll_fill(self, oid: str, seconds: float = 8.0) -> dict:
        end = time.time() + seconds
        o = self.get_order(oid)
        while time.time() < end:
            if o.get("status") in ("filled", "canceled", "rejected", "expired"):
                return o
            time.sleep(0.5)
            o = self.get_order(oid)
        return o
