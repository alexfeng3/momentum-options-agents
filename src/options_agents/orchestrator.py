"""Runs one full cycle: data -> strategy -> judgment -> risk -> execution -> analysis."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from pathlib import Path

from . import llm
from .agents.execution import ExecutionAgent
from .agents.market_data import MarketDataAgent
from .agents.position import PositionAgent
from .agents.risk import RiskAgent
from .agents.strategy import StrategyAgent
from .broker import AlpacaBroker
from .eventlog import ET, EventLog
from .marketdata import HistoricalBook
from .portfolio import Portfolio
from .strategy_config import LiveConfig


def load_universe(cfg: LiveConfig) -> list[str]:
    return sorted(p.stem for p in Path(cfg.data_dir).glob("*.csv")
                  if not p.stem.startswith("_"))


def run_cycle(cfg: LiveConfig, dry_run: bool = True, echo: bool = True,
              use_llm: bool = True) -> dict:
    run_id = uuid.uuid4().hex[:12]
    log = EventLog(run_id, echo=echo)
    now = datetime.now(ET)
    as_of = now.date()

    log.emit("orchestrator", "cycle_start", {
        "run_id": run_id, "dry_run": dry_run, "mode": "paper",
        "universe_size": len(cfg.universe), "top_n": cfg.top_n,
        "overlay_enabled": cfg.overlay_enabled, "now_et": now.isoformat()})

    broker = AlpacaBroker()
    acct = broker.verify_paper()                       # 4 gates, or abort
    log.emit("orchestrator", "paper_verified",
             {"account_number": acct["account_number"], "base_url": broker.base})

    book = HistoricalBook(list(cfg.universe) + ["SPY"], data_dir=Path(cfg.data_dir))

    # 1. Market Data Agent
    snap = MarketDataAgent(broker, book, cfg, log).run(as_of)

    # current holdings, strategy-scoped by asset class
    positions = broker.get_positions()
    held = {p["symbol"]: float(p["qty"]) for p in positions
            if p.get("asset_class") != "us_option"}
    prices = {s: n.last_price for s, n in snap.names.items() if n.last_price}
    for p in positions:
        if p.get("current_price"):
            prices.setdefault(p["symbol"], float(p["current_price"]))

    equity = float(acct["equity"])
    pf = Portfolio(cash=float(acct["cash"]), shares=dict(held))

    # 2. Strategy Agent
    held_value = {p["symbol"]: float(p["market_value"]) for p in positions
                  if p.get("asset_class") != "us_option"}
    proposals = StrategyAgent(cfg, log).run(snap, held, book, as_of,
                                            held_value=held_value, equity=equity)

    # 3. Judgment Agent (LLM) — veto only, abstains without a key
    review = None
    if use_llm:
        cands = [{"symbol": p.symbol, "kind": p.kind, "reason": p.reason,
                  "signals": p.signals}
                 for p in proposals if p.kind in ("CORE", "PEAD")]
        review = llm.review(cands, {
            "as_of": as_of.isoformat(),
            "spy_above_sma200": snap.spy_above_sma200,
            "spy_price": snap.spy_price,
            "market_open": snap.market_open})
        log.emit("judgment", "review", {
            "available": review.available, "error": review.error,
            "regime": review.regime, "regime_note": review.regime_note,
            "judgments": {k: {"verdict": v.verdict, "confidence": v.confidence,
                              "reason": v.reason}
                          for k, v in review.judgments.items()}})

    # 4. Risk Oversight Agent — veto authority
    decisions = RiskAgent(cfg, log).run(
        proposals, pf, prices, equity,
        paper_verified=broker.verified, market_open=snap.market_open,
        llm_review=review, as_of=as_of)

    # attach structures so execution can resolve real contracts
    by_key = {(p.symbol, p.kind): p for p in proposals}
    for d in decisions:
        p = by_key.get((d.symbol, d.kind))
        if p is not None and p.structure:
            d.structure = p.structure

    # 5. Execution Agent — approved only
    orders = ExecutionAgent(broker, cfg, log, dry_run=dry_run).run(decisions, snap)

    # 6. Position Analysis Agent
    summary = PositionAgent(broker, cfg, log).run(snap, as_of)

    result = {"run_id": run_id, "dry_run": dry_run, "as_of": as_of.isoformat(),
              "market_open": snap.market_open,
              "spy_above_sma200": snap.spy_above_sma200,
              "snapshot": snap.to_dict(),
              "llm": {"available": bool(review and review.available),
                      "regime": review.regime if review else None,
                      "note": review.regime_note if review else None,
                      "error": review.error if review else None},
              "proposals": [p.to_dict() for p in proposals],
              "decisions": [d.to_dict() for d in decisions],
              "orders": [o.to_dict() for o in orders],
              "summary": summary, "log_file": str(log.path)}
    log.emit("orchestrator", "cycle_end", {
        "proposals": len(proposals),
        "approved": sum(1 for d in decisions if d.approved),
        "rejected": sum(1 for d in decisions if not d.approved),
        "orders_submitted": sum(1 for o in orders
                                if o.status not in ("dry_run", "error", "skipped_duplicate"))})
    return result
