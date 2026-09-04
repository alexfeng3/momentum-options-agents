#!/usr/bin/env python
from PIL import Image, ImageDraw, ImageFont
import os

W, H = 1920, 1080
BG = (12, 16, 24)
ACCENT = (64, 200, 160)
WHITE = (240, 242, 245)
GREY = (150, 160, 172)

FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
FONT_REG = "/System/Library/Fonts/HelveticaNeue.ttc"

OUT_DIR = os.path.dirname(os.path.abspath(__file__))


def font(path, size):
    return ImageFont.truetype(path, size)


def draw_centered(draw, text, y, fnt, fill, max_width=1700):
    # simple wrap
    words = text.split(" ")
    lines = []
    cur = ""
    for w in words:
        test = (cur + " " + w).strip()
        bbox = draw.textbbox((0, 0), test, font=fnt)
        if bbox[2] - bbox[0] > max_width and cur:
            lines.append(cur)
            cur = w
        else:
            cur = test
    if cur:
        lines.append(cur)
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=fnt)
        w_ = bbox[2] - bbox[0]
        h_ = bbox[3] - bbox[1]
        draw.text(((W - w_) / 2, y), line, font=fnt, fill=fill)
        y += h_ + 20
    return y


def base_slide():
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    # accent bar
    d.rectangle([0, 0, W, 10], fill=ACCENT)
    d.rectangle([0, H - 10, W, H], fill=ACCENT)
    return img, d


def save(img, name):
    path = os.path.join(OUT_DIR, name)
    img.save(path)
    print("saved", path)


def slide_title():
    img, d = base_slide()
    f_title = font(FONT_BOLD, 108)
    f_sub = font(FONT_REG, 46)
    draw_centered(d, "MOMENTUM + OPTIONS AGENTS", 400, f_title, WHITE)
    draw_centered(d, "Five autonomous agents. One risk officer with veto power.", 600, f_sub, ACCENT)
    save(img, "slide_01.png")


def slide_pipeline():
    img, d = base_slide()
    f_h = font(FONT_BOLD, 66)
    f_item = font(FONT_REG, 52)
    draw_centered(d, "THE PIPELINE", 130, f_h, ACCENT)
    stages = [
        "Market Data",
        "Strategy",
        "Judgment (AI)",
        "Risk (veto)",
        "Execution",
        "Position",
    ]
    y = 320
    line = "  →  ".join(stages)
    draw_centered(d, line, y, f_item, WHITE, max_width=1800)
    save(img, "slide_02.png")


def slide_strategy():
    img, d = base_slide()
    f_h = font(FONT_BOLD, 62)
    f_item = font(FONT_BOLD, 64)
    draw_centered(d, "THE STRATEGY", 140, f_h, ACCENT)
    y = 420
    for line, color in [
        ("80% momentum core", WHITE),
        ("5% earnings drift", WHITE),
        ("15% option spreads", WHITE),
    ]:
        y = draw_centered(d, line, y, f_item, color) + 20
    f_note = font(FONT_REG, 44)
    draw_centered(d, "One pot of capital — never spent twice", y + 40, f_note, GREY)
    save(img, "slide_03.png")


def slide_backtest():
    img, d = base_slide()
    f_h = font(FONT_BOLD, 62)
    f_big = font(FONT_BOLD, 90)
    f_item = font(FONT_BOLD, 58)
    draw_centered(d, "BACKTEST — TEST PERIOD 2022-2026", 140, f_h, ACCENT)
    y = 380
    y = draw_centered(d, "+1072% return", y, f_big, WHITE) + 20
    y = draw_centered(d, "Sharpe 1.88", y, f_item, WHITE) + 10
    y = draw_centered(d, "+64.5%/yr alpha", y, f_item, WHITE)
    save(img, "slide_04.png")


def slide_bias():
    img, d = base_slide()
    f_h = font(FONT_BOLD, 60)
    f_item = font(FONT_BOLD, 56)
    draw_centered(d, "BEING HONEST ABOUT BIAS", 160, f_h, ACCENT)
    y = 420
    draw_centered(
        d,
        "On a bias-free, 951-stock universe:",
        y,
        f_item,
        WHITE,
    )
    y += 140
    f_big = font(FONT_BOLD, 84)
    draw_centered(d, "~40% of the headline return", y, f_big, WHITE)
    y += 130
    draw_centered(d, "was universe selection", y, f_big, WHITE)
    save(img, "slide_05.png")


def slide_live():
    img, d = base_slide()
    f_h = font(FONT_BOLD, 56)
    f_item = font(FONT_BOLD, 62)
    f_big = font(FONT_BOLD, 78)
    draw_centered(d, "LIVE PROOF — NOT JUST A BACKTEST", 120, f_h, ACCENT)
    y = 360
    y = draw_centered(d, "Sept 3, 10:33am ET", y, f_big, WHITE) + 10
    y = draw_centered(d, "The put credit spread actually filled", y, f_item, WHITE) + 30
    f_note = font(FONT_REG, 50)
    draw_centered(d, "Real premium collected: $110 — no human in the loop", y, f_note, GREY)
    save(img, "slide_06.png")


def slide_safety():
    img, d = base_slide()
    f_h = font(FONT_BOLD, 62)
    f_item = font(FONT_BOLD, 60)
    draw_centered(d, "SAFETY", 140, f_h, ACCENT)
    y = 400
    for line in [
        "4 gates before any order",
        "Capital can't be spent twice",
        "64 automated tests",
    ]:
        y = draw_centered(d, line, y, f_item, WHITE) + 30
    save(img, "slide_07.png")


def slide_closing():
    img, d = base_slide()
    f_big = font(FONT_BOLD, 90)
    f_sub = font(FONT_REG, 50)
    y = 440
    y = draw_centered(d, "Five agents. One veto. Real fills.", y, f_big, WHITE) + 80
    draw_centered(d, "Agentic Hackathon", y, f_sub, ACCENT)
    save(img, "slide_08.png")


if __name__ == "__main__":
    slide_title()
    slide_pipeline()
    slide_strategy()
    slide_backtest()
    slide_bias()
    slide_live()
    slide_safety()
    slide_closing()
