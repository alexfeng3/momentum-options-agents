"""Agent 4 — Execution Agent.

Submits ONLY risk-approved orders to Alpaca paper trading. Stock legs are simple
market orders; option spreads are multi-leg (mleg) limit orders, which is what
Alpaca requires for defined-risk structures.

Contains no strategy logic and no risk logic. If handed an unapproved decision it
RAISES rather than submitting — the veto is structural.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

from ..broker import NotPaperTradingError
from ..eventlog import ET


@dataclass
class OrderResult:
    symbol: str
    kind: str
    side: str
    qty: float | None
    contracts: int | None
    order_id: str | None
    client_order_id: str
    status: str
    submitted_at: str
    filled_qty: float = 0.0
    filled_avg_price: float | None = None
    legs: list[dict] | None = None
    dry_run: bool = False
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class ExecutionAgent:
    name = "execution"

    def __init__(self, broker, cfg, log, dry_run: bool = True):
        self.broker, self.cfg, self.log, self.dry_run = broker, cfg, log, dry_run

    def run(self, decisions, snap) -> list[OrderResult]:
        approved = [d for d in decisions if d.approved]
        if not approved:
            self.log.emit(self.name, "nothing_to_execute",
                          {"decisions_seen": len(decisions)})
            return []
        # A multi-leg parent order comes back from Alpaca with a NULL `symbol`, so
        # keying this check on it silently let a second spread stack on a name
        # that already had one working. The client order id carries the symbol:
        # <prefix>-<kind>-<SYMBOL>-<epoch_ms>.
        open_syms: set[str] = set()
        try:
            for o in self.broker.get_open_orders():
                coid = str(o.get("client_order_id") or "")
                if not coid.startswith(self.cfg.coid_prefix):
                    continue
                if o.get("symbol"):
                    open_syms.add(o["symbol"])
                parts = coid.split("-")
                if len(parts) >= 4:
                    open_syms.add(parts[2])
        except Exception as e:
            self.log.emit(self.name, "open_order_check_failed", {"error": str(e)})
            open_syms = set()

        out = []
        # exits first so their capital is available to the entries
        order = {"SPREAD_EXIT": 0, "EXIT": 0, "TRIM": 0}
        for d in sorted(approved, key=lambda x: order.get(x.kind, 1)):
            out.append(self._submit(d, snap, open_syms))
        return out

    def _submit(self, d, snap, open_syms) -> OrderResult:
        if not d.approved:
            raise RuntimeError(f"Execution refused: {d.symbol} is {d.action}.")
        now = datetime.now(ET)
        coid = f"{self.cfg.coid_prefix}-{d.kind.lower()}-{d.symbol}-{int(time.time()*1000)}"

        if d.symbol in open_syms:
            r = OrderResult(d.symbol, d.kind, "-", d.qty, d.contracts, None, coid,
                            "skipped_duplicate", now.isoformat(),
                            error="an open strategy order already exists")
            self.log.emit(self.name, "order_skipped", r.to_dict())
            return r

        if d.kind == "SPREAD":
            return self._submit_spread(d, snap, coid, now)
        if d.kind == "SPREAD_EXIT":
            return self._submit_spread_exit(d, coid, now)
        return self._submit_stock(d, coid, now)

    # ------------------------------------------------------------------ stock
    def _submit_stock(self, d, coid, now) -> OrderResult:
        side = "sell" if d.kind == "EXIT" else "buy"
        req = {"symbol": d.symbol, "side": side, "qty": d.qty,
               "notional": d.notional, "client_order_id": coid,
               "dry_run": self.dry_run}
        self.log.emit(self.name, "order_request", req)
        if self.dry_run:
            print(f"  [DRY-RUN] {side.upper():<4} {d.symbol:<6} "
                  f"{d.qty:.4f} sh  ({d.kind})")
            r = OrderResult(d.symbol, d.kind, side, d.qty, None, None, coid,
                            "dry_run", now.isoformat(), dry_run=True)
            self.log.emit(self.name, "order_response", r.to_dict())
            return r
        if not self.broker.verified:
            raise NotPaperTradingError("paper mode not verified at submit time")
        try:
            o = self.broker.submit_equity_order(symbol=d.symbol, side=side,
                                                qty=d.qty, client_order_id=coid)
        except Exception as e:
            r = OrderResult(d.symbol, d.kind, side, d.qty, None, None, coid,
                            "error", now.isoformat(), error=str(e))
            self.log.emit(self.name, "order_error", r.to_dict())
            return r
        o = self.broker.poll_fill(o["id"], self.cfg.fill_poll_seconds)
        r = OrderResult(d.symbol, d.kind, side, d.qty, None, o["id"],
                        o["client_order_id"], o["status"], o["submitted_at"],
                        float(o.get("filled_qty") or 0),
                        float(o["filled_avg_price"]) if o.get("filled_avg_price") else None)
        self.log.emit(self.name, "order_response", r.to_dict())
        return r

    # ----------------------------------------------------------------- spread
    def _submit_spread(self, d, snap, coid, now) -> OrderResult:
        st = getattr(d, "structure", None) or self._structure_from(snap, d.symbol)
        if not st:
            r = OrderResult(d.symbol, d.kind, "sell_to_open", None, d.contracts,
                            None, coid, "error", now.isoformat(),
                            error="no structure available")
            self.log.emit(self.name, "order_error", r.to_dict())
            return r

        def fail(msg):
            r = OrderResult(d.symbol, d.kind, "sell_to_open", None, d.contracts,
                            None, coid, "error", now.isoformat(), error=msg)
            self.log.emit(self.name, "order_error", r.to_dict())
            return r

        try:
            legs, resolved = self._resolve_contracts(st)
        except Exception as e:
            return fail(f"contract lookup failed: {e}")

        credit, pricing = self._limit_credit(legs, resolved, st)
        if credit <= 0.01:
            return fail(f"no credit available on the resolved {resolved['width']:.0f}-wide "
                        f"spread ({pricing['source']}) — refusing to sell it for nothing")

        # Max loss is set by the RESOLVED strikes, not the modelled ones. The risk
        # agent reserved collateral against the model, so a resolved spread that
        # is WIDER risks more than was actually set aside. Cut the size to fit the
        # reservation rather than quietly exceeding it.
        contracts = int(d.contracts or 0)
        per_reserved = (d.collateral or 0.0) / max(1, contracts)
        per_real = (resolved["width"] * (1 + self.cfg.slippage) - credit) * 100
        if per_real > per_reserved + 1e-6:
            contracts = int((d.collateral or 0.0) // per_real)
            if contracts < 1:
                return fail(
                    f"resolved {resolved['short_strike']}/{resolved['long_strike']} "
                    f"spread risks ${per_real:,.2f} per contract against "
                    f"${per_reserved:,.2f} reserved — the listed strikes are wider "
                    f"than the modelled {st['width']:.2f} and will not fit")
            self.log.emit(self.name, "spread_resized", {
                "symbol": d.symbol, "from": d.contracts, "to": contracts,
                "per_contract_risk": round(per_real, 2),
                "per_contract_reserved": round(per_reserved, 2)})

        # Alpaca mleg uses a net-debit convention, so a credit is a NEGATIVE limit.
        limit = -abs(credit)
        req = {"symbol": d.symbol, "contracts": contracts, "legs": legs,
               "limit_price": round(limit, 2), "client_order_id": coid,
               "dry_run": self.dry_run, "structure": st, "resolved": resolved,
               "pricing": pricing}
        self.log.emit(self.name, "order_request", req)

        if self.dry_run:
            print(f"  [DRY-RUN] SELL {d.symbol:<6} put spread "
                  f"{resolved['long_strike']:g}/{resolved['short_strike']:g} "
                  f"exp {resolved['expiry']} x{contracts} @ net credit "
                  f"{abs(limit):.2f} ({pricing['source']})  "
                  f"max loss ${per_real*contracts:,.0f}")
            r = OrderResult(d.symbol, d.kind, "sell_to_open", None, contracts,
                            None, coid, "dry_run", now.isoformat(),
                            legs=legs, dry_run=True)
            self.log.emit(self.name, "order_response", r.to_dict())
            return r

        if not self.broker.verified:
            raise NotPaperTradingError("paper mode not verified at submit time")
        try:
            o = self.broker.submit_spread_order(legs=legs, qty=contracts,
                                                limit_price=limit,
                                                client_order_id=coid)
        except Exception as e:
            r = OrderResult(d.symbol, d.kind, "sell_to_open", None, contracts,
                            None, coid, "error", now.isoformat(), legs=legs,
                            error=str(e))
            self.log.emit(self.name, "order_error", r.to_dict())
            return r
        o = self.broker.poll_fill(o["id"], self.cfg.fill_poll_seconds)
        r = OrderResult(d.symbol, d.kind, "sell_to_open", None, contracts,
                        o["id"], o["client_order_id"], o["status"],
                        o["submitted_at"], float(o.get("filled_qty") or 0),
                        None, legs=legs)
        self.log.emit(self.name, "order_response", r.to_dict())
        return r

    # ------------------------------------------------------------ spread exit
    def _submit_spread_exit(self, d, coid, now) -> OrderResult:
        """Buy the spread back. The legs are already known — they came from the
        broker's own positions — so there is no contract lookup, only pricing."""
        st = getattr(d, "structure", None) or {}
        legs = [
            {"symbol": st.get("short_symbol"), "ratio_qty": "1", "side": "buy",
             "position_intent": "buy_to_close"},
            {"symbol": st.get("long_symbol"), "ratio_qty": "1", "side": "sell",
             "position_intent": "sell_to_close"},
        ]

        def fail(msg):
            r = OrderResult(d.symbol, d.kind, "buy_to_close", None, d.contracts,
                            None, coid, "error", now.isoformat(), legs=legs,
                            error=msg)
            self.log.emit(self.name, "order_error", r.to_dict())
            return r

        if not all(l["symbol"] for l in legs):
            return fail("spread exit is missing a leg symbol")

        q = st.get("pricing") or {}
        mid, natural = q.get("mid_debit"), q.get("natural_debit")
        if q.get("two_sided") and mid is not None and natural is not None:
            # Closing PAYS a debit, so conceding means paying MORE. Same knob,
            # mirrored: limit_cross of the mid->natural distance.
            debit = mid + self.cfg.limit_cross * (natural - mid)
            source = "quotes"
        elif natural and natural > 0:
            # Not two-sided, but we can still see what crossing costs. Near expiry
            # getting out matters more than getting the last cent.
            debit, source = natural, "natural_only"
        else:
            return fail("no usable market to price the close against")

        debit = max(0.01, round(debit, 2))
        req = {"symbol": d.symbol, "contracts": d.contracts, "legs": legs,
               "limit_price": debit, "client_order_id": coid,
               "dry_run": self.dry_run, "structure": st, "pricing_source": source}
        self.log.emit(self.name, "order_request", req)

        if self.dry_run:
            kept = (st.get("entry_credit", 0) - debit) * 100 * (d.contracts or 0)
            print(f"  [DRY-RUN] CLOSE {d.symbol:<6} put spread "
                  f"{st.get('long_strike')}/{st.get('short_strike')} "
                  f"x{d.contracts} @ net debit {debit:.2f} ({source})  "
                  f"keeps ${kept:,.0f} of the credit")
            r = OrderResult(d.symbol, d.kind, "buy_to_close", None, d.contracts,
                            None, coid, "dry_run", now.isoformat(), legs=legs,
                            dry_run=True)
            self.log.emit(self.name, "order_response", r.to_dict())
            return r

        if not self.broker.verified:
            raise NotPaperTradingError("paper mode not verified at submit time")
        try:
            o = self.broker.submit_spread_order(legs=legs, qty=d.contracts,
                                                limit_price=debit,
                                                client_order_id=coid)
        except Exception as e:
            return fail(str(e))
        o = self.broker.poll_fill(o["id"], self.cfg.fill_poll_seconds)
        r = OrderResult(d.symbol, d.kind, "buy_to_close", None, d.contracts,
                        o["id"], o["client_order_id"], o["status"],
                        o["submitted_at"], float(o.get("filled_qty") or 0),
                        None, legs=legs)
        self.log.emit(self.name, "order_response", r.to_dict())
        return r

    def _structure_from(self, snap, sym):
        return None

    def _limit_credit(self, legs, resolved, st) -> tuple[float, dict]:
        """Price the limit off the contracts ACTUALLY being sold.

        `est_credit` is a Black-Scholes estimate at the MODEL's strikes and at
        exactly `dte` days. `_resolve_contracts` then snaps to real listed
        contracts — a different expiry and different strikes. On 2026-08-28 every
        resolved spread was narrower than the one priced (WBD 2.89 -> 2.00, TD
        12.11 -> 10.00, JAZZ 25.00 -> 20.00), so every order asked for more credit
        than the structure could pay and all three expired unfilled. Ask the
        market what the real spread is worth; fall back to the model only when
        the chain is not quoting two-sided.
        """
        short_sym, long_sym = legs[0]["symbol"], legs[1]["symbol"]
        meta: dict = {"short": short_sym, "long": long_sym}
        try:
            q = self.broker.get_option_quotes([short_sym, long_sym])
        except Exception as e:
            q, meta["quote_error"] = {}, str(e)
        sq, lq = q.get(short_sym) or {}, q.get(long_sym) or {}
        sb, sa = float(sq.get("bp") or 0), float(sq.get("ap") or 0)
        lb, la = float(lq.get("bp") or 0), float(lq.get("ap") or 0)

        two_sided = sb > 0 and sa > 0 and lb > 0 and la > 0
        mid = (sb + sa) / 2 - (lb + la) / 2         # credit at the mids
        natural = sb - la                           # credit crossing both legs

        # If crossing both legs does not yield a CREDIT, there is no market here
        # worth anchoring to and the mid is fiction. Outside trading hours the
        # closing quotes are junk (WBD's 27 put showed 0.06 x 2.37), and a tight
        # short leg against a blown-out long one passes any per-leg width test
        # while still being untradeable — UTHR quoted a 6.98 mid whose natural
        # was -0.15. Requiring a positive natural catches both, and guarantees
        # every limit we send sits between two prices that pay us.
        if two_sided and natural > 0:
            # limit_cross is how far to concede from the mid toward the natural:
            # 0.0 asks the mid and rarely fills, 1.0 is immediately marketable.
            credit = mid - self.cfg.limit_cross * (mid - natural)
            meta.update(source="quotes", short_bid=sb, short_ask=sa,
                        long_bid=lb, long_ask=la, mid_credit=round(mid, 2),
                        natural_credit=round(natural, 2))
        else:
            # No usable market. Scale the model credit to the RESOLVED width so we
            # at least stop asking a wider spread's credit for a narrower one, and
            # never ask MORE than the model thought it was worth. No further
            # discount: `est_credit` already carries cfg.slippage, and
            # `limit_cross` measures a distance to a natural price we do not have.
            scale = (resolved["width"] / st["width"]) if st.get("width") else 1.0
            credit = abs(st["est_credit"]) * min(1.0, scale)
            meta.update(source="model_fallback", width_scale=round(scale, 3),
                        model_credit=st.get("est_credit"),
                        short_bid=sb, short_ask=sa, long_bid=lb, long_ask=la,
                        mid_credit=round(mid, 2), natural_credit=round(natural, 2),
                        why=("crossing the quoted market yields no credit "
                             f"(natural {natural:+.2f}) — too wide to trust"
                             if two_sided else "no two-sided market"))
        meta["limit_credit"] = round(credit, 2)
        return round(credit, 2), meta

    def _resolve_contracts(self, st) -> tuple[list[dict], dict]:
        """Map model strikes onto real listed OCC contracts.

        Returns the mleg legs AND what they actually resolved to, because the
        listed strikes and expiry drive both the credit and the max loss and are
        not the ones the model priced.
        """
        target = date.fromisoformat(st["expiry_target"])
        # A +/-10 day window straddles the gap between monthly expiries, so any
        # name without weeklies resolves NOTHING whenever the target lands
        # mid-month. On 2026-09-03 that silently killed JAZZ, TD and UTHR: the
        # only listed expiries were 09-18 and 10-16, both outside the window.
        # Monthlies are ~30 days apart, so a 46-day window always contains one.
        lo = (target - timedelta(days=14)).isoformat()
        hi = (target + timedelta(days=32)).isoformat()
        contracts = self.broker.get_option_contracts(
            st["underlying"], expiration_gte=lo, expiration_lte=hi,
            option_type="put",
            strike_gte=st["long_strike"] * 0.85,
            strike_lte=st["short_strike"] * 1.15)
        if not contracts:
            raise RuntimeError("no listed put contracts in the target window")
        # one expiry: the one closest to target with the most strikes
        by_exp: dict[str, list] = {}
        for c in contracts:
            by_exp.setdefault(c["expiration_date"], []).append(c)
        exp = min(by_exp, key=lambda e: (abs((date.fromisoformat(e) - target).days),
                                         -len(by_exp[e])))
        chain = sorted(by_exp[exp], key=lambda c: float(c["strike_price"]))
        short = min(chain, key=lambda c: abs(float(c["strike_price"]) - st["short_strike"]))
        long_ = min(chain, key=lambda c: abs(float(c["strike_price"]) - st["long_strike"]))
        if short["symbol"] == long_["symbol"]:
            raise RuntimeError("short and long legs resolved to the same contract")
        if float(long_["strike_price"]) >= float(short["strike_price"]):
            raise RuntimeError("long strike is not below the short strike — not a credit spread")
        ks, kl = float(short["strike_price"]), float(long_["strike_price"])
        legs = [
            {"symbol": short["symbol"], "ratio_qty": "1", "side": "sell",
             "position_intent": "sell_to_open"},
            {"symbol": long_["symbol"], "ratio_qty": "1", "side": "buy",
             "position_intent": "buy_to_open"},
        ]
        return legs, {"short_strike": ks, "long_strike": kl, "width": ks - kl,
                      "expiry": exp, "modelled_width": st.get("width"),
                      "modelled_expiry": st.get("expiry_target")}
