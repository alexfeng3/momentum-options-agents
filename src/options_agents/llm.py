"""LLM judgment layer (Claude), with graceful degradation.

The deterministic pipeline is the strategy. The LLM is a REVIEWER with veto and
de-ranking power over candidates the rules already selected, plus a narrator that
explains each trade in plain English. It can never invent a trade, size one, or
override a risk decision.

That boundary is deliberate. An LLM in the trade-generation path cannot be
backtested honestly over 15 years, and results would vary run to run. A veto-only
reviewer keeps the backtest meaningful while still using judgment where judgment
genuinely helps: reading news and context that price data does not contain.

With no ANTHROPIC_API_KEY the layer ABSTAINS — every candidate passes through
untouched and the run continues. It never blocks trading, and never silently
pretends to have an opinion.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")
MAX_TOKENS = 2000


@dataclass
class Judgment:
    symbol: str
    verdict: str            # "pass" | "caution" | "veto"
    confidence: float       # 0..1
    reason: str
    available: bool = True

    @property
    def vetoed(self) -> bool:
        return self.verdict == "veto"


@dataclass
class LLMReview:
    judgments: dict[str, Judgment] = field(default_factory=dict)
    regime: str = "unknown"
    regime_note: str = ""
    available: bool = False
    error: str | None = None


SYSTEM = """You are the Judgment Agent in a systematic options trading system.

A deterministic momentum + PEAD model has ALREADY selected these candidates. Your \
job is to review them for things price data cannot see: known accounting scandals, \
imminent binary events, takeover situations where the price is pinned, delisting \
risk, or a broken business the momentum score cannot know about.

You have VETO power only. You cannot add candidates, change position sizes, or \
overrule risk limits. Default to "pass" — the model has an edge and you should \
only override it when you have a specific, concrete concern. Vetoing everything \
is as wrong as vetoing nothing.

Return ONLY valid JSON, no prose:
{"regime": "risk_on|neutral|risk_off",
 "regime_note": "<one sentence>",
 "judgments": [{"symbol": "X", "verdict": "pass|caution|veto",
                "confidence": 0.0-1.0, "reason": "<one sentence>"}]}"""


def available() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def review(candidates: list[dict], market_context: dict,
           timeout: float = 45.0) -> LLMReview:
    """Ask Claude to review model-selected candidates. Abstains without a key."""
    if not candidates:
        return LLMReview(available=False, error="no candidates")
    if not available():
        return LLMReview(available=False,
                         error="ANTHROPIC_API_KEY not set — judgment layer abstained")
    try:
        import anthropic
    except ImportError:
        return LLMReview(available=False, error="anthropic package not installed")

    payload = {"market": market_context, "candidates": candidates}
    try:
        client = anthropic.Anthropic(timeout=timeout)
        msg = client.messages.create(
            model=MODEL, max_tokens=MAX_TOKENS, system=SYSTEM,
            messages=[{"role": "user", "content": json.dumps(payload, default=str)}])
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        data = _extract_json(text)
        out = LLMReview(available=True, regime=data.get("regime", "unknown"),
                        regime_note=data.get("regime_note", ""))
        for j in data.get("judgments", []):
            sym = j.get("symbol")
            if not sym:
                continue
            v = j.get("verdict", "pass")
            if v not in ("pass", "caution", "veto"):
                v = "pass"
            out.judgments[sym] = Judgment(sym, v, float(j.get("confidence", 0.5)),
                                          str(j.get("reason", ""))[:300])
        return out
    except Exception as e:                       # never let the LLM break a run
        return LLMReview(available=False, error=f"{type(e).__name__}: {e}")


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j < 0:
        raise ValueError("no JSON object in model response")
    return json.loads(text[i:j + 1])


def explain(trade: dict, timeout: float = 30.0) -> str:
    """One-sentence plain-English rationale. Falls back to a deterministic string."""
    fallback = (f"{trade.get('action','TRADE')} {trade.get('symbol','?')}: "
                f"{trade.get('reason','model signal')}")
    if not available():
        return fallback
    try:
        import anthropic
        client = anthropic.Anthropic(timeout=timeout)
        m = client.messages.create(
            model=MODEL, max_tokens=200,
            system="Explain this systematic trade in ONE plain-English sentence "
                   "for a trading journal. No preamble, no hedging, no advice.",
            messages=[{"role": "user", "content": json.dumps(trade, default=str)}])
        return "".join(b.text for b in m.content
                       if getattr(b, "type", "") == "text").strip() or fallback
    except Exception:
        return fallback
