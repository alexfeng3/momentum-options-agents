from PIL import Image, ImageDraw, ImageFont, ImageFilter
import math, random

W, H = 1920, 1080
OUT = "/private/tmp/claude-501/-Users-alexfeng-project-workspace-alpaca-hedge-fund/53b445d4-c0e7-4975-9bb3-7b1742afbb9e/scratchpad/submission/cover_image/cover.png"

# ---- Palette ----
NAVY_TOP = (10, 14, 26)
NAVY_BOT = (19, 26, 46)
GREEN = (0, 255, 157)
GREEN_DIM = (0, 180, 112)
AMBER = (255, 176, 59)
WHITE = (240, 244, 250)
GREY = (150, 162, 186)

random.seed(7)

def lerp(a, b, t):
    return tuple(int(a[i] + (b[i]-a[i])*t) for i in range(3))

img = Image.new("RGB", (W, H), NAVY_TOP)
px = img.load()

# Diagonal gradient background (top-left dark -> bottom-right slightly lighter navy)
for y in range(H):
    t = y / H
    row_color = lerp(NAVY_TOP, NAVY_BOT, t)
    for x in range(0, W, 4):
        for dx in range(4):
            if x+dx < W:
                px[x+dx, y] = row_color

draw = ImageDraw.Draw(img, "RGBA")

# Subtle vignette / radial glow behind title area
glow = Image.new("RGBA", (W, H), (0,0,0,0))
gdraw = ImageDraw.Draw(glow)
cx, cy = int(W*0.5), int(H*0.42)
for r in range(700, 0, -10):
    alpha = int(18 * (1 - r/700))
    if alpha <= 0:
        continue
    gdraw.ellipse([cx-r, cy-r*0.55, cx+r, cy+r*0.55], fill=(0, 255, 157, alpha))
glow = glow.filter(ImageFilter.GaussianBlur(40))
img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
draw = ImageDraw.Draw(img, "RGBA")

# ---- Background chart motif (top-right corner, subtle) ----
def draw_chart_motif(draw, ox, oy, w, h, color, alpha=46):
    random.seed(3)
    n = 14
    pts = []
    val = 0.3
    for i in range(n):
        val += random.uniform(-0.08, 0.22)
        val = max(0.05, min(0.95, val))
        x = ox + w * i / (n-1)
        y = oy + h * (1 - val)
        pts.append((x, y))
    # fill area under line
    poly = pts + [(ox+w, oy+h), (ox, oy+h)]
    draw.polygon(poly, fill=color[:3] + (alpha//3,))
    draw.line(pts, fill=color[:3] + (alpha*3,), width=3, joint="curve")
    # candle ticks
    for i in range(0, n, 2):
        x, y = pts[i]
        draw.line([(x, y-14), (x, y+14)], fill=color[:3] + (alpha*2,), width=2)

draw_chart_motif(draw, W*0.62, H*0.10, W*0.34, H*0.30, GREEN, alpha=40)

# ---- Faint grid dots background texture (very subtle) ----
for gx in range(60, W, 60):
    for gy in range(60, H, 60):
        draw.ellipse([gx-1, gy-1, gx+1, gy+1], fill=(255,255,255,10))

# ---- Agent pipeline motif (bottom band) ----
labels = ["MARKET\nDATA", "STRATEGY", "AI\nJUDGE", "RISK", "EXECUTION", "POSITION"]
n_nodes = len(labels)
band_y = int(H*0.80)
margin_x = 220
usable_w = W - 2*margin_x
xs = [margin_x + usable_w * i / (n_nodes - 1) for i in range(n_nodes)]
node_r = 30

# connecting line
for i in range(n_nodes - 1):
    x1, x2 = xs[i], xs[i+1]
    draw.line([(x1+node_r, band_y), (x2-node_r, band_y)], fill=(0,255,157,90), width=3)
    # arrowhead
    ax, ay = x2-node_r, band_y
    draw.polygon([(ax, ay), (ax-14, ay-7), (ax-14, ay+7)], fill=(0,255,157,140))

try:
    font_node = ImageFont.truetype("/System/Library/Fonts/Avenir Next.ttc", 20, index=0)
except Exception:
    font_node = ImageFont.load_default()

for i, (x, label) in enumerate(zip(xs, labels)):
    is_ai = (label == "AI\nJUDGE")
    fill = (19, 26, 46, 255)
    outline = AMBER if is_ai else GREEN
    draw.ellipse([x-node_r, band_y-node_r, x+node_r, band_y+node_r], fill=fill, outline=outline+(255,), width=3)
    inner_r = 6
    draw.ellipse([x-inner_r, band_y-inner_r, x+inner_r, band_y+inner_r], fill=outline+(255,))
    # label below node
    lines = label.split("\n")
    ly = band_y + node_r + 16
    for line in lines:
        bbox = draw.textbbox((0,0), line, font=font_node)
        lw = bbox[2]-bbox[0]
        draw.text((x-lw/2, ly), line, font=font_node, fill=(200, 210, 226, 255))
        ly += 24

# ---- Badge (top-left) ----
badge_font = ImageFont.truetype("/System/Library/Fonts/Avenir Next.ttc", 24, index=1)
badge_text = "AGENTIC HACKATHON  •  Built on Alpaca"
bbox = draw.textbbox((0,0), badge_text, font=badge_font)
bw, bh = bbox[2]-bbox[0], bbox[3]-bbox[1]
pad_x, pad_y = 26, 14
bx, by = 110, 90
draw.rounded_rectangle([bx, by, bx+bw+2*pad_x, by+bh+2*pad_y+6], radius=28,
                        outline=(0,255,157,220), width=2, fill=(0,255,157,22))
draw.text((bx+pad_x, by+pad_y-2), badge_text, font=badge_font, fill=(190, 255, 225, 255))

# ---- Title ----
title_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Black.ttf", 108)
title_lines = ["MOMENTUM + OPTIONS", "AGENTS"]
ty = 300
for line in title_lines:
    bbox = draw.textbbox((0,0), line, font=title_font)
    tw = bbox[2]-bbox[0]
    tx = (W - tw) / 2
    # soft shadow
    draw.text((tx+4, ty+6), line, font=title_font, fill=(0,0,0,120))
    draw.text((tx, ty), line, font=title_font, fill=WHITE)
    ty += 118

# ---- Accent underline ----
underline_w = 340
uy = ty + 6
draw.rounded_rectangle([(W-underline_w)/2, uy, (W+underline_w)/2, uy+6], radius=3, fill=GREEN)

# ---- Tagline ----
tagline_font = ImageFont.truetype("/System/Library/Fonts/Avenir Next.ttc", 40, index=0)
tagline = "Five autonomous agents. One risk officer with veto power."
tagline2 = "Real fills on paper money."
for i, line in enumerate([tagline, tagline2]):
    bbox = draw.textbbox((0,0), line, font=tagline_font)
    tw = bbox[2]-bbox[0]
    tx = (W - tw) / 2
    draw.text((tx, uy + 40 + i*54), line, font=tagline_font, fill=GREY)

img.save(OUT, "PNG")
print("saved", OUT, img.size)
