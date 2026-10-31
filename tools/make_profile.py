#!/usr/bin/env python3
"""Build every data-driven asset of the profile README from REAL GitHub data.

    python tools/make_profile.py --user YOUR_USERNAME            # writes assets/ + README.md
    python tools/make_profile.py --demo                           # layout test only -> preview/demo/

Data sources (no third-party services, nothing hot-linked):
  * contributions : https://github.com/users/<user>/contributions   (public HTML fragment)
  * languages     : GitHub REST API, repo language bytes (set GITHUB_TOKEN to avoid rate limits)

Outputs: contributions-log.png, stats.png, languages.png, grid.png, social-*.png,
snake.svg, and README.md.
"""
import argparse
import datetime as dt
import html
import json
import os
import random
import re
import sys
import urllib.request
from collections import deque

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))

# ---- theme (matches make_character.py / make_header.py) -----------------------
BG = (10, 13, 18)
WIN_BG = (13, 17, 23)
WIN_BAR = (22, 27, 34)
BORDER = (38, 45, 55)
CYAN = (34, 211, 238)
MUTED = (139, 148, 158)
TXT = (201, 209, 217)
RED, YEL, GRN = (255, 95, 86), (255, 189, 46), (39, 201, 63)
EMPTY = (27, 32, 41)
LEVELS = [EMPTY, (62, 70, 84), (84, 94, 114), (124, 58, 237), (167, 139, 250)]
FONTS = "/usr/share/fonts/truetype/liberation/"
S = 2                      # PNG render scale (displayed at 880px wide)
W = 880

LANG_COLORS = {
    "Python": "#3572A5", "HTML": "#e34c26", "TypeScript": "#3178c6", "JavaScript": "#f1e05a",
    "Shell": "#89e051", "Jupyter Notebook": "#DA5B0B", "CSS": "#563d7c", "Go Template": "#00ADD8",
    "C++": "#f34b7d", "C": "#555555", "Java": "#b07219", "PHP": "#4F5D95", "Go": "#00ADD8",
    "Rust": "#dea584", "Kotlin": "#A97BFF", "Dart": "#00B4AB", "SCSS": "#c6538c", "Vue": "#41b883",
    "Ruby": "#701516", "Swift": "#F05138", "C#": "#178600", "Dockerfile": "#384d54", "Makefile": "#427819",
}


def font(name, size):
    return ImageFont.truetype(FONTS + name, int(size * S))


def mono(size, bold=False):
    return font("LiberationMono-Bold.ttf" if bold else "LiberationMono-Regular.ttf", size)


def sans(size, bold=False):
    return font("LiberationSans-Bold.ttf" if bold else "LiberationSans-Regular.ttf", size)


def hex_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# ---- data ------------------------------------------------------------------------
def http(url, token=None):
    req = urllib.request.Request(url, headers={"User-Agent": "profile-readme-builder"})
    if token and "api.github.com" in url:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def parse_calendar(page):
    """-> {date: (count, level)} from a contributions HTML fragment."""
    cells = re.findall(r'data-date="(\d{4}-\d\d-\d\d)"[^>]*?id="([^"]+)"[^>]*?data-level="(\d)"', page)
    tips = {}
    for cid, n in re.findall(r'for="([^"]+)"[^>]*>\s*(?:(\d[\d,]*)|No) contributions?', page):
        tips[cid] = int(n.replace(",", "")) if n else 0
    out = {}
    for date, cid, lvl in cells:
        out[dt.date.fromisoformat(date)] = (tips.get(cid, 0), int(lvl))
    return out


def fetch_contributions(user, token=None):
    base = f"https://github.com/users/{user}/contributions"
    recent = parse_calendar(http(base))
    if not recent:
        sys.exit(f"No contribution data found for '{user}'. Check the username.")
    today = dt.date.today()
    start_year = 2008
    try:
        created = json.loads(http(f"https://api.github.com/users/{user}", token))["created_at"]
        start_year = int(created[:4])
    except Exception as e:                       # rate-limited: just probe every year
        print("  (API unavailable for account age, probing all years)", e)
    days = {}
    for y in range(start_year, today.year + 1):
        yr = parse_calendar(http(f"{base}?from={y}-01-01&to={y}-12-31"))
        for d, v in yr.items():
            if d.year == y and d <= today:
                days[d] = v[0]
    for d, v in recent.items():
        if d <= today:
            days[d] = v[0]
    return days, recent


def fetch_languages(user, token=None):
    repos = json.loads(http(f"https://api.github.com/users/{user}/repos?per_page=100&type=owner", token))
    total = {}
    for r in repos:
        if r.get("fork"):
            continue
        langs = json.loads(http(r["languages_url"], token))
        for k, v in langs.items():
            total[k] = total.get(k, 0) + v
    return total


def streaks(days, today):
    ds = sorted(d for d, c in days.items() if c > 0)
    longest, best = (0, None, None), None
    run_start = prev = None
    runs = []
    for d in ds:
        if prev is not None and (d - prev).days == 1:
            pass
        else:
            run_start = d
        prev = d
        if not runs or runs[-1][0] != run_start:
            runs.append([run_start, d])
        else:
            runs[-1][1] = d
    for a, b in runs:
        n = (b - a).days + 1
        if n > longest[0]:
            longest = (n, a, b)
    cur = (0, None, None)
    for a, b in runs:
        if (today - b).days <= 1:
            cur = ((b - a).days + 1, a, b)
    return cur, longest, (ds[0] if ds else None)


# ---- drawing helpers ------------------------------------------------------------------
def new_canvas(h):
    im = Image.new("RGB", (W * S, int(h * S)), BG)
    return im, ImageDraw.Draw(im)


def rr(d, box, r, fill=None, outline=None, width=1):
    d.rounded_rectangle([v * S for v in box], radius=r * S, fill=fill, outline=outline, width=int(width * S))


def text_c(d, cx, y, s, f, fill):
    d.text((cx * S - d.textlength(s, font=f) / 2, y * S), s, font=f, fill=fill)


def save_png(im, path):
    im.quantize(colors=96, method=Image.MEDIANCUT, dither=Image.NONE).save(path, optimize=True)
    print(f"  {os.path.relpath(path, ROOT)}: {im.width}x{im.height}, {os.path.getsize(path) / 1024:.0f} KB")


def window(d, box, title):
    x0, y0, x1, y1 = box
    rr(d, (x0, y0, x1, y1), 2, fill=WIN_BG, outline=BORDER)
    d.rectangle([(x0 + 1) * S, (y0 + 1) * S, (x1 - 1) * S, (y0 + 30) * S], fill=WIN_BAR)
    d.line([(x0 * S, (y0 + 30) * S), (x1 * S, (y0 + 30) * S)], fill=BORDER, width=S)
    for i, c in enumerate((RED, YEL, GRN)):
        cx, cy = x0 + 18 + i * 18, y0 + 15
        d.ellipse([(cx - 5) * S, (cy - 5) * S, (cx + 5) * S, (cy + 5) * S], fill=c)
    text_c(d, (x0 + x1) / 2, y0 + 8, title, mono(11), (110, 118, 129))


def weeks_grid(recent):
    """-> (cols, {(col,row): (count, level, date)}) with Sunday-first rows."""
    ds = sorted(recent)
    first = ds[0] - dt.timedelta(days=(ds[0].weekday() + 1) % 7)
    cells, ncol = {}, 0
    for d in ds:
        col = (d - first).days // 7
        row = (d.weekday() + 1) % 7
        cells[(col, row)] = (recent[d][0], recent[d][1], d)
        ncol = max(ncol, col + 1)
    return ncol, cells


def cell_color(level, is_head):
    return CYAN if is_head else LEVELS[level]


# ---- images ------------------------------------------------------------------------------
def img_contrib_log(recent, head_date, path):
    ncol, cells = weeks_grid(recent)
    h = 186
    im, d = new_canvas(h)
    window(d, (0.5, 0.5, W - 0.5, h - 0.5), "$ cat contributions.log")
    gx0, gy0, pitch, cs = 58, 68, 14.9, 11.5
    # month labels
    last_m = None
    last_x = -99
    for c in range(ncol):
        dd = next((cells[(c, r)][2] for r in range(7) if (c, r) in cells), None)
        if dd and dd.month != last_m:
            x = gx0 + c * pitch
            if x - last_x > 34 and c < ncol - 1:
                d.text((x * S, 44 * S), dd.strftime("%b"), font=mono(10.5), fill=(110, 118, 129))
                last_x = x
            last_m = dd.month
    for r, name in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        d.text((24 * S, (gy0 + r * pitch - 1) * S), name, font=mono(10.5), fill=(110, 118, 129))
    for (c, r), (n, lvl, date) in cells.items():
        x, y = gx0 + c * pitch, gy0 + r * pitch
        rr(d, (x, y, x + cs, y + cs), 2, fill=cell_color(lvl, date == head_date))
    save_png(im, path)


def img_grid(recent, head_date, path):
    ncol, cells = weeks_grid(recent)
    pitch, cs = 15.6, 12.4
    h = 7 * pitch + 28
    im, d = new_canvas(h)
    x0 = (W - ncol * pitch + (pitch - cs)) / 2
    for (c, r), (n, lvl, date) in cells.items():
        x, y = x0 + c * pitch, 14 + r * pitch
        rr(d, (x, y, x + cs, y + cs), 2, fill=cell_color(lvl, date == head_date))
    save_png(im, path)


def fmt_d(d, year=False):
    return d.strftime("%b ") + str(d.day) + (f", {d.year}" if year else "")


def img_stats(total, first, cur, longest, path):
    h = 150
    im, d = new_canvas(h)
    cols = [W / 6 + 20, W / 2, W * 5 / 6 - 20]
    for x in (W / 3 + 12, W * 2 / 3 - 12):
        d.line([(x * S, 30 * S), (x * S, 128 * S)], fill=(30, 140, 170), width=S)
    # total
    text_c(d, cols[0], 48, f"{total:,}", sans(26, True), (235, 239, 244))
    text_c(d, cols[0], 86, "Total Contributions", sans(12), TXT)
    if first:
        text_c(d, cols[0], 104, f"{fmt_d(first, True)} - Present", sans(10), (110, 118, 129))
    # current streak ring
    cx, cy, R = cols[1], 60, 28
    d.ellipse([(cx - R) * S, (cy - R) * S, (cx + R) * S, (cy + R) * S], outline=(139, 109, 245), width=3 * S)
    d.rectangle([(cx - 9) * S, (cy - R - 4) * S, (cx + 9) * S, (cy - R + 4) * S], fill=BG)   # gap for flame
    fl = [(cx, cy - R - 9), (cx + 5, cy - R - 2), (cx + 3, cy - R + 4), (cx - 3, cy - R + 4), (cx - 5, cy - R - 2)]
    d.polygon([(x * S, y * S) for x, y in fl], fill=(139, 109, 245))
    d.ellipse([(cx - 2) * S, (cy - R - 1) * S, (cx + 2) * S, (cy - R + 3) * S], fill=BG)
    text_c(d, cx, cy - 15, str(cur[0]), sans(26, True), (235, 239, 244))
    text_c(d, cx, 96, "Current Streak", sans(12, True), CYAN)
    if cur[1]:
        rng = fmt_d(cur[1]) if cur[1] == cur[2] else f"{fmt_d(cur[1])} - {fmt_d(cur[2])}"
        text_c(d, cx, 114, rng, sans(10), (110, 118, 129))
    # longest
    text_c(d, cols[2], 48, str(longest[0]), sans(26, True), (235, 239, 244))
    text_c(d, cols[2], 86, "Longest Streak", sans(12), TXT)
    if longest[1]:
        rng = fmt_d(longest[1]) if longest[1] == longest[2] else f"{fmt_d(longest[1])} - {fmt_d(longest[2])}"
        text_c(d, cols[2], 104, rng, sans(10), (110, 118, 129))
    save_png(im, path)


def img_languages(langs, path):
    total = sum(langs.values()) or 1
    top = sorted(langs.items(), key=lambda kv: -kv[1])[:8]
    h = 200
    im, d = new_canvas(h)
    bx0, bx1, by = 190, 690, 52
    text_c(d, (bx0 + bx1) / 2 - 130 + 0, 14, "", sans(1), CYAN)
    d.text((bx0 * S, 14 * S), "Most Used Languages", font=sans(18, True), fill=CYAN)
    # bar
    x = bx0
    bar = Image.new("RGB", ((bx1 - bx0) * S, 6 * S), EMPTY)
    bd = ImageDraw.Draw(bar)
    acc = 0.0
    for name, v in top:
        w = (bx1 - bx0) * S * v / total
        col = hex_rgb(LANG_COLORS.get(name, "#8b949e"))
        bd.rectangle([acc, 0, acc + w, 6 * S], fill=col)
        acc += w
    m = Image.new("L", bar.size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, bar.width, bar.height], radius=3 * S, fill=255)
    im.paste(bar, (bx0 * S, by * S), m)
    # legend: two columns
    for i, (name, v) in enumerate(top):
        col, row = divmod(i, 4)
        lx, ly = bx0 + col * 172, 78 + row * 28
        d.ellipse([lx * S, (ly + 3) * S, (lx + 8) * S, (ly + 11) * S], fill=hex_rgb(LANG_COLORS.get(name, "#8b949e")))
        d.text(((lx + 16) * S, ly * S), f"{name} {100 * v / total:.2f}%", font=sans(11.5), fill=TXT)
    save_png(im, path)


def icon(d, kind, x, y, col):
    """Small line icons drawn in a 16x16 box at (x,y)."""
    w = int(1.6 * S)
    if kind == "instagram":
        d.rounded_rectangle([x * S, y * S, (x + 16) * S, (y + 16) * S], radius=4.5 * S, outline=col, width=w)
        d.ellipse([(x + 4) * S, (y + 4) * S, (x + 12) * S, (y + 12) * S], outline=col, width=w)
        d.ellipse([(x + 11.5) * S, (y + 2.5) * S, (x + 13.5) * S, (y + 4.5) * S], fill=col)
    elif kind == "email":
        pts = [(x, y + 15), (x, y + 2), (x + 8, y + 10), (x + 16, y + 2), (x + 16, y + 15)]
        d.line([(a * S, b * S) for a, b in pts], fill=col, width=int(2.4 * S), joint="curve")
    elif kind == "portfolio":
        d.ellipse([x * S, y * S, (x + 16) * S, (y + 16) * S], outline=col, width=w)
        d.ellipse([(x + 4.5) * S, y * S, (x + 11.5) * S, (y + 16) * S], outline=col, width=w)
        d.line([(x * S, (y + 8) * S), ((x + 16) * S, (y + 8) * S)], fill=col, width=w)


def img_social(kind, label, path):
    f = mono(11.5, True)
    sp = 1.6
    tw = sum(ImageDraw.Draw(Image.new("RGB", (1, 1))).textlength(c, font=f) / S + sp for c in label)
    if kind == "linkedin":
        w, h = tw + 28, 28
        im = Image.new("RGB", (int(w * S), h * S), BG)
        d = ImageDraw.Draw(im)
        d.rectangle([0, 0, im.width, im.height], fill=(10, 102, 194))
        x = 14
    else:
        w, h = tw + 16 + 10 + 6, 28
        im = Image.new("RGB", (int(w * S), h * S), BG)
        d = ImageDraw.Draw(im)
        icon(d, kind, 3, 6, {"instagram": (167, 139, 250), "email": (16, 185, 129), "portfolio": CYAN}[kind])
        x = 3 + 16 + 10
    for c in label:
        d.text((x * S, 6.5 * S), c, font=f, fill=(235, 239, 244))
        x += d.textlength(c, font=f) / S + sp
    save_png(im, path)


# ---- snake -------------------------------------------------------------------------------
def snake_svg(recent, path, length=6, dt_s=0.075):
    ncol, cells = weeks_grid(recent)
    targets = {(c, r) for (c, r), v in cells.items() if v[0] > 0}
    inside = lambda c, r: 0 <= c < ncol and 0 <= r < 7
    start_row = min(targets, key=lambda t: t[0])[1] if targets else 3
    path_cells = [(-1, start_row)]

    def bfs(src, goal_set, blocked):
        q, prev = deque([src]), {src: None}
        while q:
            cur = q.popleft()
            if cur in goal_set and cur != src:
                out = []
                while cur != src:
                    out.append(cur); cur = prev[cur]
                return out[::-1]
            for dc, dr in ((1, 0), (0, 1), (0, -1), (-1, 0)):
                n = (cur[0] + dc, cur[1] + dr)
                if n in prev or n in blocked or not inside(*n):
                    continue
                prev[n] = cur
                q.append(n)
        return None

    remaining = set(targets)
    eaten_at = {}
    while remaining:
        head = path_cells[-1]
        body = set(path_cells[-(length):-1])
        leg = bfs(head, remaining, body) or bfs(head, remaining, set())
        if not leg:
            break
        for c in leg:
            path_cells.append(c)
            if c in remaining:
                remaining.discard(c)
                eaten_at[c] = len(path_cells) - 1
    n = len(path_cells) - 1
    T = (n + 6 + length + 3) * dt_s

    pitch, cs = 15, 12
    x0, y0 = (W - ncol * pitch) / 2 + 8, 24
    Hh = y0 + 7 * pitch + 22
    pos = lambda c, r: (x0 + c * pitch, y0 + r * pitch)
    pct = lambda step: step * dt_s / T * 100

    # keyframes at direction changes only (constant speed => linear interpolation is exact)
    key = []
    for i, c in enumerate(path_cells):
        if i in (0, n) or (path_cells[i][0] - path_cells[i - 1][0], path_cells[i][1] - path_cells[i - 1][1]) != \
                (path_cells[i + 1][0] - path_cells[i][0], path_cells[i + 1][1] - path_cells[i][1]):
            key.append(i)
    fade0, fade1 = pct(n + 2), pct(n + 6)
    kf = []
    for i in key:
        x, y = pos(*path_cells[i])
        op = "" if i < n else ""
        kf.append(f"{pct(i):.3f}%{{transform:translate({x:.1f}px,{y:.1f}px);opacity:1}}")
    xl, yl = pos(*path_cells[n])
    kf.append(f"{fade0:.3f}%{{transform:translate({xl:.1f}px,{yl:.1f}px);opacity:1}}")
    kf.append(f"{fade1:.3f}%{{transform:translate({xl:.1f}px,{yl:.1f}px);opacity:0}}")
    kf.append(f"100%{{transform:translate({xl:.1f}px,{yl:.1f}px);opacity:0}}")

    css = [f".s{{width:{cs}px;height:{cs}px;rx:3px;animation:mv {T:.2f}s linear infinite;animation-fill-mode:backwards}}",
           ".c{rx:2px}", "@keyframes mv{" + "".join(kf) + "}"]
    rects = []
    restore = pct(n + 6 + length + 1)
    ekeys = {}
    for (c, r), (cnt, lvl, date) in cells.items():
        x, y = pos(c, r)
        col = "#%02x%02x%02x" % LEVELS[lvl]
        if (c, r) in eaten_at:
            k = len(ekeys)
            p = pct(eaten_at[(c, r)])
            ekeys[(c, r)] = k
            css.append(f"@keyframes e{k}{{0%,{p:.3f}%{{fill:{col}}}{p + 0.02:.3f}%,{restore:.3f}%{{fill:#161b22}}"
                       f"{restore + 0.5:.3f}%,100%{{fill:{col}}}}}")
            css.append(f".e{k}{{animation:e{k} {T:.2f}s linear infinite}}")
            rects.append(f'<rect class="c e{k}" x="{x:.1f}" y="{y:.1f}" width="{cs}" height="{cs}" fill="{col}"/>')
        else:
            rects.append(f'<rect class="c" x="{x:.1f}" y="{y:.1f}" width="{cs}" height="{cs}" fill="{col}"/>')
    head_col, body = "#22d3ee", ["#a78bfa", "#9272f0", "#7c5ae6", "#6a48d6", "#5a3cc0", "#4b31a6"]
    segs = []
    for i in range(length):
        fill = head_col if i == 0 else body[min(i - 1, len(body) - 1)]
        segs.append(f'<rect class="s" fill="{fill}" style="animation-delay:{i * dt_s:.3f}s" x="0" y="0"/>')
    segs.reverse()                                   # head drawn last (on top)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{Hh:.0f}" viewBox="0 0 {W} {Hh:.0f}">'
           f'<style>{"".join(css)}</style>'
           f'<rect x="0.5" y="0.5" width="{W - 1}" height="{Hh - 1:.0f}" rx="3" fill="#0d1117" stroke="#262d37"/>'
           + "".join(rects) + "".join(segs) + "</svg>")
    with open(path, "w") as fh:
        fh.write(svg)
    print(f"  {os.path.relpath(path, ROOT)}: {W}x{Hh:.0f}, {len(svg) / 1024:.0f} KB, {n} steps, "
          f"{len(eaten_at)}/{len(targets)} cells eaten, loop {T:.0f}s")


# ---- README -------------------------------------------------------------------------------
def write_readme(path, links, assets_rel="assets", has_langs=True):
    def img(name, alt, extra=""):
        return f'<img src="{assets_rel}/{name}" width="{W}" alt="{alt}"{extra}>'

    soc = []
    for key, lab in (("linkedin", "LinkedIn"), ("instagram", "Instagram"), ("email", "Email"), ("portfolio", "Portfolio")):
        if links.get(key):
            h = html.escape(links[key], quote=True)
            soc.append(f'<a href="{h}"><img src="{assets_rel}/social-{key}.png" height="28" alt="{lab}"></a>')
    parts = [
        f'<p align="center">{img("header.gif", "Welcome to my terminal")}</p>',
        f'<p align="center">{img("contributions-log.png", "contributions.log")}</p>',
        f'<p align="center">{img("computer-character.gif", "Developer at a desk, drawn in animated dots, next to a neofetch panel")}</p>',
        f'<p align="center">{img("stats.png", "GitHub statistics: total contributions, current streak, longest streak")}</p>',
        *([f'<p align="center">{img("languages.png", "Most used languages")}</p>'] if has_langs else []),
        f'<p align="center">{img("grid.png", "Contribution grid")}</p>',
        '<p align="center">' + "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;".join(soc) + "</p>",
        f'<p align="center">{img("snake.svg", "Contribution snake")}</p>',
    ]
    with open(path, "w") as fh:
        fh.write("\n\n".join(parts) + "\n")


def load_links():
    with open(os.path.join(HERE, "profile.json")) as fh:
        p = json.load(fh)
    links = {}
    if p.get("linkedin"): links["linkedin"] = p["linkedin"]
    if p.get("instagram"): links["instagram"] = p["instagram"]
    if p.get("email"): links["email"] = "mailto:" + p["email"].replace("mailto:", "")
    if p.get("portfolio"): links["portfolio"] = p["portfolio"]
    return links


def demo_data():
    rnd = random.Random(4)
    today = dt.date.today()
    recent = {}
    d = today - dt.timedelta(days=364)
    while d <= today:
        n = 0 if rnd.random() < 0.8 else rnd.randint(1, 9)
        recent[d] = (n, 0 if n == 0 else 1 if n < 3 else 2 if n < 6 else 3 if n < 8 else 4)
        d += dt.timedelta(days=1)
    langs = {"Python": 4639, "HTML": 3096, "TypeScript": 1042, "JavaScript": 613, "Shell": 297,
             "Jupyter Notebook": 153, "CSS": 88, "Go Template": 72}
    return {d: v[0] for d, v in recent.items()}, recent, langs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user")
    ap.add_argument("--demo", action="store_true", help="synthetic data, writes to preview/demo only")
    a = ap.parse_args()
    token = os.environ.get("GITHUB_TOKEN")
    if a.demo:
        out = os.path.join(ROOT, "preview", "demo")
        days, recent, langs = demo_data()
    elif a.user:
        out = os.path.join(ROOT, "assets")
        print(f"Fetching real data for {a.user} ...")
        days, recent = fetch_contributions(a.user, token)
        try:
            langs = fetch_languages(a.user, token)
        except Exception as e:      # rate limit etc.: keep any existing languages.png, never invent numbers
            print(f"  !! language stats unavailable ({e}); set GITHUB_TOKEN and re-run")
            langs = None
    else:
        ap.error("pass --user NAME (or --demo for a layout test)")
    os.makedirs(out, exist_ok=True)
    today = dt.date.today()
    cur, longest, first = streaks(days, today)
    total = sum(days.values())
    head = cur[2] if cur[0] else None
    print(f"total={total} current={cur[0]} longest={longest[0]} languages={len(langs) if langs else 'n/a'}")
    img_contrib_log(recent, head, os.path.join(out, "contributions-log.png"))
    img_stats(total, first, cur, longest, os.path.join(out, "stats.png"))
    if langs:
        img_languages(langs, os.path.join(out, "languages.png"))
    img_grid(recent, head, os.path.join(out, "grid.png"))
    links = load_links()
    labels = {"linkedin": "LINKEDIN", "instagram": "INSTAGRAM", "email": "EMAIL", "portfolio": "PORTFOLIO"}
    for k in labels:
        if links.get(k) or a.demo:
            img_social(k, labels[k], os.path.join(out, f"social-{k}.png"))
    snake_svg(recent, os.path.join(out, "snake.svg"))
    if not a.demo:
        write_readme(os.path.join(ROOT, "README.md"), links,
                     has_langs=os.path.exists(os.path.join(out, "languages.png")))
        print("README.md written")


if __name__ == "__main__":
    main()
