"""One-page write-up: AI logic, risk gates, Alpaca infrastructure.

US Letter portrait — a document meant to be read, not a 16:9 slide. Same dark
navy / green visual system as the rest of the submission for consistency.
"""
from __future__ import annotations

from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

OUT = "/Users/alexfeng/project-workspace/alpaca-hedge-fund/submission/1_page_summary.pdf"

PW, PH = 612, 792  # US Letter, points

BG = HexColor("#0a1120")
PANEL = HexColor("#111827")
BORDER = HexColor("#1f2937")
TEXT = HexColor("#eef2f7")
DIM = HexColor("#9aa5b5")
GREEN = HexColor("#3ddc84")
AMBER = HexColor("#f5a623")

FONTS = "/System/Library/Fonts/Avenir Next.ttc"

pdfmetrics.registerFont(TTFont("Avenir", FONTS, subfontIndex=0))       # regular
pdfmetrics.registerFont(TTFont("Avenir-Bold", FONTS, subfontIndex=1))  # bold
pdfmetrics.registerFont(TTFont("Avenir-Italic", FONTS, subfontIndex=4))

c = canvas.Canvas(OUT, pagesize=(PW, PH))


def bg():
    c.setFillColor(BG)
    c.rect(0, 0, PW, PH, fill=1, stroke=0)


def wrap(text, font, size, max_w):
    words = text.split(" ")
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if pdfmetrics.stringWidth(trial, font, size) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def para(x, y, text, *, font="Avenir", size=8.3, leading=11.6, color=TEXT,
         max_w, bold_font="Avenir-Bold"):
    """Renders **bold** spans inline. Returns the y after the last line."""
    import re
    parts = re.split(r"(\*\*[^*]+\*\*)", text)
    tokens = []
    for p in parts:
        if p.startswith("**") and p.endswith("**"):
            tokens.append((p[2:-2], bold_font))
        elif p:
            for w in p.split(" "):
                if w:
                    tokens.append((w, font))

    lines, cur, cur_w = [], [], 0.0
    space_w = pdfmetrics.stringWidth(" ", font, size)
    for tok, tf in tokens:
        tw = pdfmetrics.stringWidth(tok, tf, size)
        add_w = tw + (space_w if cur else 0)
        if cur_w + add_w <= max_w:
            cur.append((tok, tf))
            cur_w += add_w
        else:
            lines.append(cur)
            cur, cur_w = [(tok, tf)], tw
    if cur:
        lines.append(cur)

    for line in lines:
        cx = x
        for tok, tf in line:
            c.setFont(tf, size)
            c.setFillColor(color)
            c.drawString(cx, y, tok)
            cx += pdfmetrics.stringWidth(tok, tf, size) + space_w
        y -= leading
    return y


def section_header(x, y, w, label, accent=GREEN):
    c.setFillColor(accent)
    c.rect(x, y - 3, 3, 13, fill=1, stroke=0)
    c.setFont("Avenir-Bold", 11.5)
    c.setFillColor(TEXT)
    c.drawString(x + 10, y, label)
    return y - 18


bg()

# ---- header band --------------------------------------------------------
c.setFillColor(GREEN)
c.rect(0, PH - 6, PW, 6, fill=1, stroke=0)

MX = 40
top = PH - 40
c.setFont("Avenir-Bold", 20)
c.setFillColor(TEXT)
c.drawString(MX, top, "Momentum + Options Agents")
c.setFont("Avenir-Italic", 9.5)
c.setFillColor(GREEN)
c.drawRightString(PW - MX, top + 2, "AGENTIC HACKATHON")
c.setFont("Avenir", 9)
c.setFillColor(DIM)
c.drawRightString(PW - MX, top - 12, "Alpaca Paper Trading")

top -= 22
c.setFont("Avenir", 9.3)
c.setFillColor(DIM)
top = para(MX, top, "One-page summary: AI logic, risk gates, and the Alpaca infrastructure implementation "
                     "behind an autonomous, six-agent momentum + options trading system.",
           size=9.3, leading=12.5, max_w=PW - 2 * MX)
top -= 6
c.setStrokeColor(BORDER)
c.setLineWidth(0.75)
c.line(MX, top, PW - MX, top)
top -= 20

COL_W = (PW - 2 * MX - 16) / 2
COL2_X = MX + COL_W + 16

# ============================================================ AI LOGIC (left, full first block)
y = section_header(MX, top, COL_W, "1 · AI / AGENT LOGIC")
y -= 2
y = para(MX, y, "A deterministic six-agent pipeline. An LLM can veto, but never generates or "
                "sizes a trade — kept out of the signal path so the strategy stays backtestable.",
         max_w=COL_W)
y -= 6

steps = [
    ("Market Data", "Scores every liquid stock on vol-adjusted momentum: "
                     "0.45×(12-1mo return) + 0.25×(3mo) + 0.20×trend + 0.10×(rel. strength vs SPY), "
                     "each divided by 60-day realised vol. Reads real SEC EDGAR XBRL filings for "
                     "post-earnings drift (SUE score + volume-confirmed gap must both agree)."),
    ("Strategy", "Rules only, no risk checks. Proposes: CORE (top-6 momentum, equal-weight, cash "
                 "if SPY < 200-day SMA), PEAD (5%/event on a confirmed earnings beat), SPREAD "
                 "(20-delta put credit spread on a name already held), SPREAD_EXIT (close at 50% "
                 "profit or ≤5 DTE, unconditionally)."),
    ("Judgment (AI, optional)", "Can flag a name as risky. Cannot invent or size a trade. "
                                 "Abstains without an API key — the deterministic pipeline runs unchanged."),
]
for name, desc in steps:
    c.setFont("Avenir-Bold", 8.6)
    c.setFillColor(GREEN)
    c.drawString(MX, y, name)
    y -= 10.5
    y = para(MX, y, desc, size=8.0, leading=10.8, max_w=COL_W, color=DIM)
    y -= 5

ai_bottom = y

# ============================================================ RISK GATES (right column, top)
y2 = section_header(COL2_X, top, COL_W, "2 · RISK GATES", accent=AMBER)
y2 -= 2
y2 = para(COL2_X, y2, "Every gate is a runtime check that **raises**, not a convention that could "
                      "silently drift.", max_w=COL_W)
y2 -= 6

gates = [
    ("4 paper-trading gates — all required", "PAPER_TRADING=true · paper API endpoint · account "
        "number prefix 'PA' · SHA-256 of the account number in a **tracked source allowlist** "
        "(not .env) — widening it is a reviewable code change."),
    ("Risk agent — hard veto authority", "Position limits (max 10, 20% per name), overlay risk "
        "budget (15% max collateral, 3% per spread), and the **single-pot capital rule**: "
        "`portfolio.py` asserts cash ≥ 0 and reserved collateral ≤ cash — money cannot be spent "
        "twice. An earlier accounting bug here inflated a 15-yr backtest CAGR by ~8pp before "
        "being caught."),
    ("Execution agent — the one-way valve", "The **only** component that can write to Alpaca. "
        "Handed an unapproved decision, it **raises** rather than submits — structural, not a "
        "convention an agent could talk itself out of."),
    ("Pinned by tests", "64 automated tests, including ones that specifically prove the capital "
        "invariants hold and that execution refuses an unapproved order."),
]
for name, desc in gates:
    c.setFont("Avenir-Bold", 8.6)
    c.setFillColor(AMBER)
    y2 = para(COL2_X, y2, f"**{name}**", size=8.6, leading=10.8, max_w=COL_W)
    y2 = para(COL2_X, y2, desc, size=8.0, leading=10.8, max_w=COL_W, color=DIM)
    y2 -= 5

# ============================================================ ALPACA INFRA (right column, continues below gates)
y2 -= 4
y2 = section_header(COL2_X, y2, COL_W, "3 · ALPACA INFRASTRUCTURE", accent=GREEN)
y2 -= 2

infra = [
    ("APIs", "Trading API (paper) for account/positions/orders; Market Data API for daily bars, "
             "quotes, and option chains (IEX feed)."),
    ("Order types", "Stock legs are simple market orders. Spreads are Alpaca's **multi-leg (mleg) "
                     "limit orders** — the defined-risk order class options strategies require — "
                     "priced from the resolved contracts' own live quotes, not the pricing model's."),
    ("Verification at runtime", "`broker.py::verify_paper()` calls Alpaca's account endpoint and "
                                 "checks the returned account number against the gates in §2 "
                                 "before a single order can be built."),
    ("Scheduling", "No daemon. A Hermes cron job runs `cli cycle --no-llm --execute` 3×/weekday "
                   "(9:45, 12:45, 3:45 ET) against the Alpaca paper endpoint; results post to "
                   "Discord. A closed market silently rejects every proposal — safe by default."),
]
for name, desc in infra:
    y2 = para(COL2_X, y2, f"**{name}**", size=8.6, leading=10.8, max_w=COL_W)
    y2 = para(COL2_X, y2, desc, size=8.0, leading=10.8, max_w=COL_W, color=DIM)
    y2 -= 5

# ============================================================ proof strip (bottom, full width)
bottom_y = min(ai_bottom, y2) - 4
strip_h = 40
strip_y = 58
c.setFillColor(PANEL)
c.roundRect(MX, strip_y, PW - 2 * MX, strip_h, 6, fill=1, stroke=1)
c.setStrokeColor(GREEN)
c.setFillColor(GREEN)
c.rect(MX, strip_y, 3, strip_h, fill=1, stroke=0)
c.setFont("Avenir-Bold", 8.8)
c.setFillColor(GREEN)
c.drawString(MX + 14, strip_y + strip_h - 14, "LIVE, NOT JUST BACKTESTED")
c.setFont("Avenir", 8.2)
c.setFillColor(TEXT)
para(MX + 14, strip_y + strip_h - 26,
     "Sept 3, 10:33am ET: the risk-gated, Alpaca-verified pipeline above sold a real TD 115/105 "
     "put credit spread on paper capital ($0.55/share credit, 2 contracts) — autonomously, on schedule.",
     size=8.2, leading=10.6, max_w=PW - 2 * MX - 28, color=TEXT)

# ---- footer ---------------------------------------------------------------
c.setFont("Avenir", 7.3)
c.setFillColor(DIM)
c.drawString(MX, 34, "github.com/alexfeng3/momentum-options-agents")
c.drawRightString(PW - MX, 34, "momentum-options-agents-alexfeng3s-projects.vercel.app")
c.setFillColor(GREEN)
c.rect(0, 0, PW, 4, fill=1, stroke=0)

c.showPage()
c.save()
print(f"Saved: {OUT}")
