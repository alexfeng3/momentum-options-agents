#!/usr/bin/env python
"""Hackathon slide deck generator: Momentum + Options Agents."""
import os
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ---------- fonts ----------
pdfmetrics.registerFont(TTFont("Avenir", "/System/Library/Fonts/Avenir Next.ttc", subfontIndex=0))
pdfmetrics.registerFont(TTFont("Avenir-Bold", "/System/Library/Fonts/Avenir Next.ttc", subfontIndex=1))
pdfmetrics.registerFont(TTFont("Avenir-Italic", "/System/Library/Fonts/Avenir Next.ttc", subfontIndex=4))
pdfmetrics.registerFont(TTFont("ArialBold", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"))

F_REG = "Avenir"
F_BOLD = "Avenir-Bold"
F_ITAL = "Avenir-Italic"

# ---------- palette ----------
BG = HexColor("#0a1120")
BG2 = HexColor("#0f1a2e")
PANEL = HexColor("#131f36")
PANEL2 = HexColor("#16233d")
ACCENT = HexColor("#3ddc84")       # electric green
ACCENT_DIM = HexColor("#1f7a4d")
AMBER = HexColor("#f5a623")
WHITE = HexColor("#f2f5fa")
GRAY = HexColor("#9aa8c0")
GRAY_DIM = HexColor("#5f6d85")
LINE = HexColor("#233355")
RED = HexColor("#ef5350")

PW, PH = 1280, 720
MARGIN = 64

OUT = os.path.join(os.path.dirname(__file__), "slides", "deck.pdf")
c = canvas.Canvas(OUT, pagesize=(PW, PH))

page_num = [0]

def bg(color=BG):
    c.setFillColor(color)
    c.rect(0, 0, PW, PH, fill=1, stroke=0)

def footer(label):
    page_num[0] += 1
    c.setFont(F_REG, 10)
    c.setFillColor(GRAY_DIM)
    c.drawString(MARGIN, 28, "MOMENTUM + OPTIONS AGENTS")
    c.drawRightString(PW - MARGIN, 28, f"{page_num[0]:02d} / 09")
    c.setFillColor(GRAY_DIM)
    c.drawCentredString(PW / 2, 28, label)

def header(kicker, title, title_size=30):
    c.setFont(F_BOLD, 12)
    c.setFillColor(ACCENT)
    c.drawString(MARGIN, PH - 66, kicker.upper())
    c.setFont(F_BOLD, title_size)
    c.setFillColor(WHITE)
    c.drawString(MARGIN, PH - 100, title)
    c.setStrokeColor(LINE)
    c.setLineWidth(1)
    c.line(MARGIN, PH - 118, PW - MARGIN, PH - 118)

def wrap_text(text, font, size, max_width):
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if pdfmetrics.stringWidth(test, font, size) <= max_width:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines

def draw_paragraph(x, y, text, font=F_REG, size=16, leading=24, max_width=600, color=GRAY, align="left"):
    lines = wrap_text(text, font, size, max_width)
    c.setFont(font, size)
    c.setFillColor(color)
    for i, ln in enumerate(lines):
        yy = y - i * leading
        if align == "left":
            c.drawString(x, yy, ln)
        elif align == "center":
            c.drawCentredString(x, yy, ln)
    return y - len(lines) * leading

def rounded_panel(x, y, w, h, color=PANEL, radius=10, stroke=None, stroke_w=1):
    c.setFillColor(color)
    if stroke:
        c.setStrokeColor(stroke)
        c.setLineWidth(stroke_w)
        c.roundRect(x, y, w, h, radius, fill=1, stroke=1)
    else:
        c.roundRect(x, y, w, h, radius, fill=1, stroke=0)

# =========================================================
# SLIDE 1 — Title
# =========================================================
bg()
# subtle accent glow bar
c.setFillColor(ACCENT)
c.rect(0, PH - 8, PW, 8, fill=1, stroke=0)

c.setFont(F_BOLD, 13)
c.setFillColor(ACCENT)
c.drawCentredString(PW / 2, PH - 200, "AGENTIC HACKATHON — ALPACA PAPER TRADING")

c.setFont(F_BOLD, 56)
c.setFillColor(WHITE)
c.drawCentredString(PW / 2, PH / 2 + 20, "Momentum + Options Agents")

c.setFont(F_REG, 20)
c.setFillColor(GRAY)
c.drawCentredString(PW / 2, PH / 2 - 30, "Five autonomous agents. One risk officer with veto power.")

# decorative small dots row
dot_y = PH / 2 - 100
n = 6
spacing = 46
start_x = PW / 2 - (n - 1) * spacing / 2
for i in range(n):
    col = ACCENT if i != 2 else AMBER
    c.setFillColor(col)
    c.circle(start_x + i * spacing, dot_y, 6, fill=1, stroke=0)

footer("Momentum + Options Agents")
c.showPage()

# =========================================================
# SLIDE 2 — The pitch / problem
# =========================================================
bg()
header("The Pitch", "Discipline doesn't scale by hand")

body_y = PH - 190
p1 = ("Momentum investing works — but running it with real discipline means position "
      "sizing, earnings-drift detection, options-overlay collateral math, risk vetoes, "
      "and exit timing, all done consistently, every single day.")
p2 = ("Most people can't hold six agents' worth of judgment in their head at once. "
      "This system runs it as a pipeline of five specialized agents (plus an optional "
      "sixth) — each with one narrow job, so no single component can do everything, "
      "and nothing gets forgotten.")

y = draw_paragraph(MARGIN, body_y, p1, size=19, leading=28, max_width=PW - 2 * MARGIN, color=WHITE)
y -= 30
draw_paragraph(MARGIN, y, p2, size=19, leading=28, max_width=PW - 2 * MARGIN, color=GRAY)

footer("The Pitch")
c.showPage()

# =========================================================
# SLIDE 3 — Architecture (the 6-agent pipeline)
# =========================================================
bg()
header("Architecture", "The six-agent pipeline", title_size=28)

agents = [
    ("1", "Market Data\nAgent", "Scores momentum, reads real\nSEC earnings filings", ACCENT, False),
    ("2", "Strategy\nAgent", "Proposes buys / trims / exits\n+ option spreads (rules only)", ACCENT, False),
    ("3", "Judgment\nAgent (AI)", "Can flag a name as risky.\nCannot invent or size a trade.\nOptional — abstains w/o API key", GRAY, True),
    ("4", "Risk Agent", "VETO AUTHORITY.\nPosition limits, per-name caps,\nsingle-pot capital rule", AMBER, False),
    ("5", "Execution\nAgent", "ONLY agent that talks to the\nbroker. Refuses unapproved\norders — raises, not submits", ACCENT, False),
    ("6", "Position\nAgent", "Reports P&L, exposure,\nreconciles the book", ACCENT, False),
]

n = len(agents)
top = PH - 160
box_w = 168
box_h = 190
gap = (PW - 2 * MARGIN - n * box_w) / (n - 1)
y0 = top - box_h

for i, (num, name, desc, color, optional) in enumerate(agents):
    x = MARGIN + i * (box_w + gap)
    # arrow to next box
    if i < n - 1:
        ax0 = x + box_w
        ax1 = x + box_w + gap
        ay = y0 + box_h / 2
        c.setStrokeColor(GRAY_DIM)
        c.setLineWidth(2)
        c.line(ax0 + 4, ay, ax1 - 8, ay)
        # arrowhead
        c.setFillColor(GRAY_DIM)
        c.line(ax1 - 8, ay, ax1 - 16, ay + 5)
        c.line(ax1 - 8, ay, ax1 - 16, ay - 5)

    stroke_color = AMBER if color == AMBER else (color if not optional else GRAY_DIM)
    rounded_panel(x, y0, box_w, box_h, color=PANEL2, radius=10, stroke=stroke_color, stroke_w=2)

    # number badge
    c.setFillColor(stroke_color)
    c.circle(x + 26, y0 + box_h - 26, 15, fill=1, stroke=0)
    c.setFont(F_BOLD, 14)
    c.setFillColor(BG)
    c.drawCentredString(x + 26, y0 + box_h - 31, num)

    if optional:
        c.setFont(F_ITAL, 9)
        c.setFillColor(GRAY_DIM)
        c.drawRightString(x + box_w - 10, y0 + box_h - 20, "OPTIONAL")

    # name
    c.setFont(F_BOLD, 13.5)
    c.setFillColor(WHITE)
    name_lines = name.split("\n")
    ny = y0 + box_h - 60
    for ln in name_lines:
        c.drawString(x + 14, ny, ln)
        ny -= 16

    # description
    c.setFont(F_REG, 9.5)
    c.setFillColor(GRAY)
    desc_lines = desc.split("\n")
    dy = ny - 10
    for ln in desc_lines:
        c.drawString(x + 14, dy, ln)
        dy -= 13.5

caption_y = y0 - 46
c.setFont(F_ITAL, 13.5)
c.setFillColor(ACCENT)
c.drawCentredString(PW / 2, caption_y, "“The one-way valve: only Execution can write to the broker, and it structurally cannot bypass Risk.”")

footer("Architecture")
c.showPage()

# =========================================================
# SLIDE 4 — The strategy
# =========================================================
bg()
header("The Strategy", "Three sleeves, one pot of capital")

sleeves = [
    ("MOMENTUM CORE", "80%", ACCENT,
     "Top 6 stocks by vol-adjusted momentum score (12m minus last month, "
     "3-month, trend, relative strength vs SPY). Equal-weighted, rebalanced "
     "periodically. Goes to 100% cash if SPY is below its 200-day moving average."),
    ("PEAD SLEEVE", "5% / event", AMBER,
     "Buys stocks the day after a confirmed earnings beat, using REAL SEC EDGAR "
     "filing data (not simulated) — measured two independent ways (SUE score + "
     "volume-confirmed price gap) that both must agree."),
    ("OPTIONS OVERLAY", "15% max collateral", ACCENT,
     "Sells 20-delta put credit spreads on stocks the other sleeves already own — "
     "collects premium on names it's already bullish on. Closes each spread at 50% "
     "of max profit, or unconditionally within 5 days of expiry to avoid assignment."),
]

top = PH - 155
card_h = 130
gap = 22
x = MARGIN
w = PW - 2 * MARGIN

for i, (name, pct, color, desc) in enumerate(sleeves):
    y = top - i * (card_h + gap) - card_h
    rounded_panel(x, y, w, card_h, color=PANEL, radius=10, stroke=LINE, stroke_w=1)
    # left accent bar
    c.setFillColor(color)
    c.roundRect(x, y, 6, card_h, 3, fill=1, stroke=0)

    c.setFont(F_BOLD, 16)
    c.setFillColor(WHITE)
    c.drawString(x + 30, y + card_h - 32, name)

    c.setFont(F_BOLD, 16)
    c.setFillColor(color)
    c.drawRightString(x + w - 24, y + card_h - 32, pct)

    draw_paragraph(x + 30, y + card_h - 58, desc, size=12.5, leading=18,
                   max_width=w - 60, color=GRAY)

footer("The Strategy")
c.showPage()

# =========================================================
# SLIDE 5 — Backtest results (table)
# =========================================================
bg()
header("Backtest Results", "Train / validate / test — never re-tuned")

cols = ["Period", "Return", "Win Rate", "Profit\nFactor", "Max\nDrawdown", "Ann.\nSharpe", "Alpha\n(ann)", "vs SPY"]
rows = [
    ["Train 2011–2018", "+360.1%", "95.2%", "2.12", "-15.3%", "0.95", "+12.0%", "+131.3%"],
    ["Validate 2019–2021", "+221.7%", "92.7%", "1.20", "-47.0%", "1.17", "+32.0%", "+99.7%"],
    ["Test 2022–2026", "+1072.1%", "94.3%", "2.47", "-30.6%", "1.88", "+64.5%", "+63.7%"],
]

table_top = PH - 165
table_x = MARGIN
table_w = PW - 2 * MARGIN
col_w0 = 190
rest_w = (table_w - col_w0) / (len(cols) - 1)
col_widths = [col_w0] + [rest_w] * (len(cols) - 1)

header_h = 46
row_h = 60

# header row
c.setFillColor(PANEL2)
c.roundRect(table_x, table_top - header_h, table_w, header_h, 8, fill=1, stroke=0)
cx = table_x
c.setFont(F_BOLD, 11.5)
c.setFillColor(GRAY)
for i, col in enumerate(cols):
    cw = col_widths[i]
    lines = col.split("\n")
    ty = table_top - header_h / 2 + (len(lines) - 1) * 6 + 2
    for ln in lines:
        if i == 0:
            c.drawString(cx + 18, ty, ln)
        else:
            c.drawCentredString(cx + cw / 2, ty, ln)
        ty -= 13
    cx += cw

y = table_top - header_h
for r_idx, row in enumerate(rows):
    row_color = PANEL if r_idx % 2 == 0 else BG2
    ry = y - row_h
    c.setFillColor(row_color)
    c.rect(table_x, ry, table_w, row_h, fill=1, stroke=0)
    cx = table_x
    for i, val in enumerate(row):
        cw = col_widths[i]
        if i == 0:
            c.setFont(F_BOLD, 13.5)
            c.setFillColor(WHITE)
            c.drawString(cx + 18, ry + row_h / 2 - 5, val)
        else:
            emphasize = i in (1, 6, 7)
            c.setFont(F_BOLD if emphasize else F_REG, 14 if emphasize else 13)
            c.setFillColor(ACCENT if emphasize else GRAY)
            c.drawCentredString(cx + cw / 2, ry + row_h / 2 - 5, val)
        cx += cw
    c.setStrokeColor(LINE)
    c.setLineWidth(0.75)
    c.line(table_x, ry, table_x + table_w, ry)
    y = ry

c.setStrokeColor(LINE)
c.setLineWidth(1)
c.rect(table_x, y, table_w, table_top - y, fill=0, stroke=1)

c.setFont(F_ITAL, 13)
c.setFillColor(GRAY)
c.drawCentredString(PW / 2, y - 40, "Test period was run once and never tuned on.")

footer("Backtest Results")
c.showPage()

# =========================================================
# SLIDE 6 — Honest about bias
# =========================================================
bg()
header("Intellectual Honesty", "How much of that return is universe selection?", title_size=25)

sub = ("On a mechanically-screened 951-stock universe (survivorship-bias-free, includes "
       "delisted/bankrupt names) vs. the hand-picked 39-name universe behind the headline "
       "numbers, 2021–2026:")
y = draw_paragraph(MARGIN, PH - 165, sub, size=14.5, leading=20, max_width=PW - 2 * MARGIN, color=GRAY)

# three stat cards
stats = [
    ("SPY (baseline)", "+70.7%", "Sharpe 0.60", GRAY),
    ("951-name universe", "+329.2%", "Sharpe 0.93 · alpha +28.7%/yr", ACCENT),
    ("Hand-picked 39 names", "+249.1%", "Basis for Slide 5 headline", AMBER),
]
card_w = (PW - 2 * MARGIN - 2 * 24) / 3
card_h = 130
cy = y - 40 - card_h
for i, (label, val, sub_label, color) in enumerate(stats):
    cx = MARGIN + i * (card_w + 24)
    rounded_panel(cx, cy, card_w, card_h, color=PANEL, radius=10, stroke=LINE)
    c.setFont(F_REG, 12.5)
    c.setFillColor(GRAY)
    c.drawCentredString(cx + card_w / 2, cy + card_h - 30, label)
    c.setFont(F_BOLD, 30)
    c.setFillColor(color)
    c.drawCentredString(cx + card_w / 2, cy + card_h - 72, val)
    c.setFont(F_REG, 10.5)
    c.setFillColor(GRAY_DIM)
    c.drawCentredString(cx + card_w / 2, cy + 22, sub_label)

# headline banner
banner_y = cy - 74
rounded_panel(MARGIN, banner_y, PW - 2 * MARGIN, 56, color=PANEL2, radius=10, stroke=AMBER, stroke_w=1.5)
c.setFont(F_BOLD, 14.5)
c.setFillColor(AMBER)
c.drawCentredString(PW / 2, banner_y + 32, "~40% of the headline backtest return was universe selection, not the strategy.")
c.setFont(F_REG, 12.5)
c.setFillColor(WHITE)
c.drawCentredString(PW / 2, banner_y + 13, "Expect ~+29%/yr alpha going forward — not the hand-picked number.")

footer("Intellectual Honesty")
c.showPage()

# =========================================================
# SLIDE 7 — Live proof (highlight slide)
# =========================================================
bg()
# amber glow strip to mark this as the highlight slide
c.setFillColor(AMBER)
c.rect(0, PH - 8, PW, 8, fill=1, stroke=0)

c.setFont(F_BOLD, 12)
c.setFillColor(AMBER)
c.drawString(MARGIN, PH - 60, "LIVE PROOF — THIS ACTUALLY HAPPENED")
c.setFont(F_BOLD, 27)
c.setFillColor(WHITE)
c.drawString(MARGIN, PH - 94, "From broken fills to a real credit spread, in 6 days")
c.setStrokeColor(LINE)
c.line(MARGIN, PH - 112, PW - MARGIN, PH - 112)

events = [
    ("Aug 28", GRAY, "Momentum core deployed live on Alpaca paper trading — bought 6 stocks (CNC, JAZZ, TD, UTHR, VLO, WBD) equal-weight. Clean fill."),
    ("Aug 28", RED, "3 option spread orders (WBD, JAZZ, TD) submitted — ALL THREE expired unfilled. Root cause: limit price calculated from a Black-Scholes model's own strikes/expiry, not Alpaca's real listed contracts — every order asked for more credit than the spread could pay."),
    ("Sep 2–3", AMBER, "Diagnosed & fixed 4 independent defects (mispriced limit vs. real contracts; overlay could fire only once per rebalance; expiry search window too narrow; duplicate-order check broken for multi-leg orders). Also found: agents could OPEN a spread but had no path to CLOSE one. Built a leg-pairing module that reconstructs an open spread from the broker's own position data."),
    ("Sep 3, 10:33am ET", ACCENT, "THE TD 115/105 PUT CREDIT SPREAD FILLED — sold 115 put @ $0.95, bought 105 put @ $0.40, net credit $0.55/share ($110 total) on 2 contracts. Real premium collected."),
    ("Sep 3, later", ACCENT, "12:45pm & 3:45pm scheduled cycles both correctly recognized the open position, did NOT duplicate it, and correctly left it alone — the full open→hold→close lifecycle running unattended on real fills, not a backtest."),
]

top = PH - 145
line_x = MARGIN + 110
c.setStrokeColor(LINE)
c.setLineWidth(2)
c.line(line_x, top + 6, line_x, 96)

y = top
for date, color, text in events:
    c.setFont(F_BOLD, 11.5)
    c.setFillColor(color)
    c.drawString(MARGIN, y - 4, date)

    c.setFillColor(color)
    c.circle(line_x, y - 6, 5, fill=1, stroke=0)

    lines = wrap_text(text, F_REG, 11.5, PW - MARGIN - (line_x + 26))
    ty = y
    c.setFont(F_REG, 11.5)
    c.setFillColor(WHITE if color != GRAY else GRAY)
    for ln in lines:
        c.drawString(line_x + 26, ty - 4, ln)
        ty -= 15.5
    y = ty - 12

c.setFont(F_ITAL, 12.5)
c.setFillColor(AMBER)
c.drawCentredString(PW / 2, 60, "“This is the exact failure the system is fixed against, working live, autonomously, without a human in the loop.”")

footer("Live Proof")
c.showPage()

# =========================================================
# SLIDE 8 — Safety design
# =========================================================
bg()
header("Safety Design", "Four layers between a proposal and a fill")

items = [
    ("Paper trading only, structurally", "4 independent gates must ALL pass before any order reaches the broker: env flag, paper API endpoint, account number prefix, and a SHA-256 hash of the account number checked against a tracked allowlist in source code — not just a .env file, so widening access requires a reviewable code change."),
    ("Capital cannot be double-spent", "Enforced by runtime assertions, not just logic that could silently drift. An earlier bug where this wasn't enforced inflated a 15-year backtest CAGR by ~8 percentage points before being caught and fixed."),
    ("64 automated tests", "Including tests that pin the capital invariants, and tests that specifically prove the Execution Agent raises an exception (refuses) if handed an unapproved order."),
    ("Silent-safe on a schedule", "Runs 3x per weekday with zero human intervention required — but any run that finds nothing to do is safe by default: if the market is closed, every proposal is automatically rejected."),
]

top = PH - 155
card_h = 106
gap = 18
w = PW - 2 * MARGIN
for i, (title, desc) in enumerate(items):
    y = top - i * (card_h + gap) - card_h
    rounded_panel(MARGIN, y, w, card_h, color=PANEL, radius=10, stroke=LINE)
    c.setFillColor(ACCENT)
    c.roundRect(MARGIN, y, 6, card_h, 3, fill=1, stroke=0)
    c.setFont(F_BOLD, 14.5)
    c.setFillColor(WHITE)
    c.drawString(MARGIN + 28, y + card_h - 30, title)
    draw_paragraph(MARGIN + 28, y + card_h - 54, desc, size=11.5, leading=16,
                   max_width=w - 56, color=GRAY)

footer("Safety Design")
c.showPage()

# =========================================================
# SLIDE 9 — What's next / closing
# =========================================================
bg()
header("What's Next", "Extending what already works")

next_items = [
    "Extend the PEAD sleeve's live coverage beyond the current names.",
    "Tighten the options overlay's fill rate further.",
    "Consider adding more sleeves to the pipeline.",
]
y = PH - 190
c.setFont(F_REG, 16)
for item in next_items:
    c.setFillColor(ACCENT)
    c.circle(MARGIN + 6, y - 5, 4, fill=1, stroke=0)
    c.setFillColor(WHITE)
    c.setFont(F_REG, 16)
    c.drawString(MARGIN + 24, y - 10, item)
    y -= 40

# closing tagline banner
banner_y = 150
rounded_panel(MARGIN, banner_y, PW - 2 * MARGIN, 130, color=PANEL2, radius=14, stroke=ACCENT, stroke_w=2)
c.setFont(F_BOLD, 34)
c.setFillColor(ACCENT)
c.drawCentredString(PW / 2, banner_y + 78, "Five agents. One veto. Real fills.")
c.setFont(F_REG, 14)
c.setFillColor(GRAY)
c.drawCentredString(PW / 2, banner_y + 38, "Momentum + Options Agents — Agentic Hackathon, Alpaca Paper Trading")

footer("What's Next")
c.showPage()

c.save()
print(f"Saved: {OUT}")
print(f"Pages: {page_num[0]}")
