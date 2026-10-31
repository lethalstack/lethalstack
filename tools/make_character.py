#!/usr/bin/env python3
"""Generate assets/computer-character.gif.

The whole two-panel identity section is rendered as one GIF so alignment is exact on
GitHub: left = `portrait.txt` window with an animated dotted programmer-at-a-desk,
right = `neofetch` window (static) built from tools/profile.json.

The character is drawn as a tone/part map, sampled into a halftone dot grid, then
dispersed into particles and reassembled in a seamless loop.
"""
import json
import re
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
W = 880
H = 470
BG = (10, 13, 18)
WIN_BG = (13, 17, 23)
WIN_BAR = (22, 27, 34)
BORDER = (38, 45, 55)
CYAN = (34, 211, 238)
MUTED = (139, 148, 158)
TXT = (201, 209, 217)
MONO = "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf"
MONO_B = "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf"

# ---- layout -------------------------------------------------------------
LEFT = (0, 0, 396, H)                # outer left panel
RIGHT = (396, 0, W, H)
BAR_H = 30
PITCH = 3                            # dot grid pitch (px)
SS = 3                               # supersample for dot drawing
FPS_MS = 50
HOLD_MS = 2400
EMPTY_MS = 500
STEPS = 34                           # frames for disperse / reform

PALETTE = {                          # part -> (dark, light) dot colours
    "person": ((98, 70, 220), (167, 139, 250)),
    "skin":   ((120, 98, 235), (196, 181, 253)),
    "chair":  ((52, 98, 200), (96, 150, 245)),
    "desk":   ((60, 82, 130), (110, 138, 196)),
    "screen": ((14, 130, 160), (34, 211, 238)),
    "frame":  ((40, 110, 190), (86, 160, 240)),
    "floor":  ((40, 50, 72), (70, 84, 112)),
    "misc":   ((84, 70, 190), (150, 130, 240)),
}


# ---- scene ---------------------------------------------------------------
# An original anime-styled programmer: sharp profile, spiky hair, hoodie, headphones,
# cel-shaded with cyan rim light from the monitor. Drawn as a label map, shaded per
# part, then sampled into a halftone dot grid (dot size = tone).
import cv2

LABELS = ["none", "skin", "hair", "hoodie", "pants", "shoe", "chair", "desk", "frame",
          "screen", "misc", "line", "eye", "floor"]
PALETTE = {
    "skin":   ((112, 92, 214), (214, 202, 255)),
    "hair":   ((58, 46, 150), (136, 116, 245)),
    "hoodie": ((74, 52, 190), (150, 120, 248)),
    "pants":  ((40, 48, 140), (84, 96, 214)),
    "shoe":   ((44, 40, 110), (96, 88, 200)),
    "chair":  ((36, 72, 176), (84, 138, 240)),
    "desk":   ((52, 68, 116), (112, 136, 192)),
    "frame":  ((38, 96, 180), (90, 164, 244)),
    "screen": ((14, 130, 160), (34, 211, 238)),
    "misc":   ((90, 74, 200), (172, 156, 250)),
    "line":   ((190, 176, 255), (236, 230, 255)),
    "eye":    ((150, 232, 255), (225, 250, 255)),
    "floor":  ((34, 44, 66), (64, 78, 108)),
}
BASE_TONE = {"skin": 0.47, "hair": 0.48, "hoodie": 0.58, "pants": 0.42, "shoe": 0.4, "chair": 0.55,
             "desk": 0.55, "frame": 0.6, "screen": 0.9, "misc": 0.6, "line": 1.0, "eye": 1.0, "floor": 0.4}
RIM = (34, 211, 238)
BAYER = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], np.float32) / 15.0
R = 4                                  # label pixels per panel pixel


def build_labels(cw, ch):
    Wc, Hc = cw * PITCH * R, ch * PITCH * R
    lab = np.zeros((Hc, Wc), np.uint8)

    def fin(draw_fn, name, key):
        m = Image.new("L", (Wc, Hc), 0)
        draw_fn(ImageDraw.Draw(m))
        m = np.asarray(m) > 127
        if key:
            k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(key * R * 2 + 1),) * 2)
            lab[cv2.dilate(m.astype(np.uint8), k) > 0] = 0
        lab[m] = LABELS.index(name)

    P = lambda p: (p[0] * R, p[1] * R)

    def line(name, p0, p1, w, key=0):
        def f(d):
            d.line([P(p0), P(p1)], fill=255, width=max(1, int(w * R)))
            r = w * R / 2
            for (x, y) in (p0, p1):
                d.ellipse([x * R - r, y * R - r, x * R + r, y * R + r], fill=255)
        fin(f, name, key)

    def poly(name, pts, key=0):
        fin(lambda d: d.polygon([P(p) for p in pts], fill=255), name, key)

    def ell(name, cx, cy, rx, ry, key=0):
        fin(lambda d: d.ellipse([(cx - rx) * R, (cy - ry) * R, (cx + rx) * R, (cy + ry) * R], fill=255), name, key)

    def rect(name, x0, y0, x1, y1, r=0, key=0):
        if r:
            fin(lambda d: d.rounded_rectangle([x0 * R, y0 * R, x1 * R, y1 * R], radius=r * R, fill=255), name, key)
        else:
            fin(lambda d: d.rectangle([x0 * R, y0 * R, x1 * R, y1 * R], fill=255), name, key)

    def poly_line(name, pts, w, key=0):
        for p0, p1 in zip(pts, pts[1:]):
            line(name, p0, p1, w, key)

    kl = 1.3
    # floor + chair
    line("floor", (14, 406), (380, 406), 1.6)
    line("chair", (112, 326), (112, 392), 7)
    line("chair", (56, 398), (170, 398), 6)
    for wx in (54, 112, 172):
        ell("chair", wx, 405, 6, 6)
    rect("chair", 44, 138, 78, 296, r=15)                       # tall gaming backrest
    ell("chair", 62, 146, 17, 12)                               # headrest
    rect("chair", 56, 306, 168, 326, r=8, key=kl)               # seat
    line("chair", (100, 284), (160, 284), 7, key=kl)            # armrest
    rect("chair", 126, 286, 136, 308)
    # desk, PC tower, monitor
    rect("desk", 360, 304, 374, 406)
    rect("desk", 208, 304, 220, 406)
    rect("frame", 296, 322, 346, 406, r=4)                       # PC tower
    line("screen", (304, 332), (338, 332), 2.4)                 # tower LED strip
    rect("desk", 196, 290, 392, 304, r=3, key=kl)               # desk top
    rect("frame", 308, 244, 320, 284)                           # neck
    rect("frame", 290, 281, 338, 290, r=3)                      # stand base
    rect("frame", 252, 108, 376, 246, r=6, key=kl)              # bezel
    rect("screen", 259, 115, 369, 239, r=2)                     # screen
    rect("frame", 222, 279, 292, 290, r=2, key=1)               # keyboard
    ell("frame", 352, 286, 8, 4)                                # mouse
    rect("misc", 366, 266, 384, 290, r=3, key=1)                # mug
    line("misc", (384, 271), (390, 278), 3)
    # legs
    line("pants", (88, 308), (206, 302), 30, key=kl)
    line("pants", (206, 302), (214, 396), 24, key=kl)
    poly("shoe", [(196, 388), (244, 388), (256, 396), (256, 406), (194, 406)], key=kl)
    # torso / hoodie
    poly("hoodie", [(56, 308), (64, 214), (82, 176), (118, 166), (148, 180), (160, 214), (154, 262), (152, 308)], key=kl)
    ell("hoodie", 98, 178, 24, 15, key=0)                        # hood bunched at the neck
    # neck, head (head group is scaled 1.25x about the neck for anime proportions)
    HS = 1.25
    hp = lambda p: (148 + (p[0] - 148) * HS, 166 + (p[1] - 166) * HS)
    hline = lambda n, p0, p1, w, key=0: line(n, hp(p0), hp(p1), w * HS, key)
    hpoly = lambda n, pts, key=0: poly(n, [hp(p) for p in pts], key)
    hell = lambda n, cx, cy, rx, ry, key=0: ell(n, *hp((cx, cy)), rx * HS, ry * HS, key)
    line("skin", (134, 192), (148, 152), 23, key=kl)
    hpoly("skin", [(138, 100), (166, 92), (188, 100), (192, 114), (190, 122), (200, 133), (193, 137), (194, 144),
                   (191, 149), (195, 154), (186, 163), (172, 168), (152, 161), (140, 142), (134, 118)], key=kl)
    hell("skin", 147, 128, 6, 9)                                 # ear
    # hair: mass + spikes + fringe
    hpoly("hair", [(128, 130), (122, 104), (130, 84), (150, 70), (178, 72), (196, 88), (198, 100), (186, 98),
                   (178, 108), (170, 100), (160, 110), (150, 100), (142, 114), (142, 132), (136, 150)], key=kl)
    hpoly("hair", [(134, 90), (100, 74), (124, 98)])
    hpoly("hair", [(128, 106), (94, 100), (124, 118)])
    hpoly("hair", [(140, 78), (120, 52), (152, 72)])
    hpoly("hair", [(160, 72), (162, 46), (180, 74)])
    hpoly("hair", [(176, 96), (196, 108), (182, 113)])
    hpoly("hair", [(164, 100), (178, 118), (168, 114)])
    # eye + brow
    hpoly("eye", [(173, 114), (195, 108), (189, 124), (178, 122)])
    hell("none", 188, 116, 2.0, 3.0)                             # pupil gap
    hline("hair", (168, 103), (197, 105), 3.6)                   # brow
    hline("line", (176, 115), (193, 111), 1.2)                   # upper lash line
    # headphones (cup + band)
    hell("misc", 146, 131, 11, 13, key=kl)
    hell("none", 146, 131, 5, 7)
    hline("misc", (146, 119), (152, 84), 4)
    hline("misc", (152, 84), (130, 78), 4)
    # arm: sleeve + forearm + hand
    line("hoodie", (112, 208), (150, 268), 23, key=kl)
    line("hoodie", (150, 268), (226, 277), 18, key=kl)
    ell("skin", 238, 277, 11, 8, key=kl)
    # line art + folds
    hline("line", (186, 120), (198, 132), 1.4)                   # nose bridge
    hline("line", (188, 146), (195, 147), 1.4)                   # mouth
    hline("line", (150, 160), (186, 164), 1.2)                   # jaw
    line("line", (140, 198), (143, 236), 1.8)                    # drawstrings
    line("line", (150, 200), (153, 228), 1.8)
    for s0, s1 in (((82, 262), (136, 270)), ((122, 228), (138, 244)), ((70, 232), (96, 250)),
                   ((60, 160), (60, 278)), ((158, 262), (190, 272)), ((86, 214), (112, 226)),
                   ((100, 290), (140, 296)), ((176, 290), (186, 300)), ((120, 250), (146, 258))):
        line("none", s0, s1, 1.5)                                # fold / seam gaps
    for s0, s1 in (((150, 82), (132, 98)), ((162, 82), (150, 104)), ((172, 86), (160, 108)),
                   ((140, 92), (122, 106)), ((156, 76), (146, 92)), ((132, 100), (112, 108))):
        hline("none", s0, s1, 1.3)                               # hair strand gaps
    return lab


def shade(lab):
    """Per-pixel cel-shaded tone + rim-light amount (monitor light comes from the right)."""
    Hc, Wc = lab.shape
    tone = np.zeros((Hc, Wc), np.float32)
    rim = np.zeros((Hc, Wc), np.float32)
    sig = 2.4 * R
    xs = (np.arange(Wc, dtype=np.float32) / Wc)[None, :]
    ys = (np.arange(Hc, dtype=np.float32) / Hc)[:, None]
    for i, name in enumerate(LABELS):
        if name == "none":
            continue
        m = (lab == i).astype(np.float32)
        if not m.any():
            continue
        b = cv2.GaussianBlur(m, (0, 0), sig)
        gx = np.gradient(b, axis=1) * sig * 2.5
        gy = np.gradient(b, axis=0) * sig * 2.5
        lit = np.clip(-gx * 0.85 - gy * 0.3, 0, 1)
        dark = np.clip(gx * 0.9 + gy * 0.2, 0, 1)
        t = BASE_TONE[name] * (0.72 + 0.5 * xs) * (1.12 - 0.42 * ys) * (1 - 0.35 * dark) + 0.34 * lit
        sel = lab == i
        tone[sel] = t[sel]
        rim[sel] = np.clip((lit[sel] - 0.28) / 0.5, 0, 1)
    # cel-shading: 4 flat bands
    bands = np.digitize(tone, [0.30, 0.45, 0.62, 0.80])
    tone_q = np.array([0.26, 0.42, 0.62, 0.82, 1.0], np.float32)[bands]
    return tone_q, rim


def sample_dots(cw, ch):
    lab = build_labels(cw, ch)
    tone, rim = shade(lab)
    b = PITCH * R
    cover = (lab != 0).reshape(ch, b, cw, b).mean(axis=(1, 3))
    counts = np.stack([(lab == i).reshape(ch, b, cw, b).mean(axis=(1, 3)) for i in range(len(LABELS))])
    counts[0] = 0
    part = counts.argmax(axis=0)
    mask = (lab != 0).astype(np.float32)
    denom = np.maximum(mask.reshape(ch, b, cw, b).sum(axis=(1, 3)), 1)
    tcell = (tone * mask).reshape(ch, b, cw, b).sum(axis=(1, 3)) / denom
    rcell = (rim * mask).reshape(ch, b, cw, b).sum(axis=(1, 3)) / denom
    rng = np.random.default_rng(7)
    sx0, sy0, sx1, sy1 = 259, 115, 369, 239            # screen box (panel px)
    dots = []
    for cy in range(ch):
        for cx in range(cw):
            c = cover[cy, cx]
            if c < 0.34:
                continue
            nm = LABELS[part[cy, cx]]
            px, py = cx * PITCH + PITCH / 2, cy * PITCH + PITCH / 2
            if nm == "screen" and sx0 < px < sx1 and sy0 < py < sy1:
                row = int((py - sy0) // PITCH)
                if row % 3 == 2:
                    continue
                r_i = row // 3
                ln = 0.25 + ((r_i * 37) % 7) / 7.0 * 0.62
                ind = 0.0 if r_i % 3 else 0.1
                xr = (px - sx0) / (sx1 - sx0)
                if not (0.05 + ind <= xr <= 0.05 + ind + ln):
                    continue
                pal = [(34, 211, 238), (167, 139, 250), (96, 165, 250), (226, 240, 255)]
                col = pal[(int(xr * 40) // 5 + r_i) % 4]
                dots.append((px, py, 1.25, col))
                continue
            dark, light = PALETTE[nm]
            t = float(np.clip(tcell[cy, cx] + 0.16 * (BAYER[cy % 4, cx % 4] - 0.47), 0.15, 1.0))
            col = [dark[i] + (light[i] - dark[i]) * t for i in range(3)]
            rm = float(rcell[cy, cx]) * (1.0 if nm in ("hair", "skin", "hoodie", "pants", "shoe", "chair", "misc") else 0.35)
            col = tuple(int(col[i] + (RIM[i] - col[i]) * rm * 0.85) for i in range(3))
            r = (0.42 + 0.78 * t) * min(1.0, 0.65 + c)
            if nm in ("line", "eye"):
                r = 1.15
            if nm == "floor":
                r = 0.9
            dots.append((px, py, min(r, 1.25), col))
    # soft cyan light spill around the monitor (sparse, tiny dots)
    for cy in range(ch):
        for cx in range(cw):
            if cover[cy, cx] >= 0.34:
                continue
            px, py = cx * PITCH + PITCH / 2, cy * PITCH + PITCH / 2
            dx = max(252 - px, 0, px - 376)
            dy = max(108 - py, 0, py - 246)
            dd = math.hypot(dx, dy)
            if 0 < dd < 40 and rng.random() < 0.30 * (1 - dd / 40) ** 1.7:
                f = 1 - dd / 40
                dots.append((px, py, 0.55 + 0.4 * f, tuple(int(c * (0.35 + 0.65 * f)) for c in RIM)))
    return dots


# ---- animation ------------------------------------------------------------
def smooth(t):
    t = np.clip(t, 0, 1)
    return t * t * (3 - 2 * t)


class Particles:
    def __init__(self, dots, seed=3):
        rng = np.random.default_rng(seed)
        n = len(dots)
        self.x = np.array([d[0] for d in dots], np.float32)
        self.y = np.array([d[1] for d in dots], np.float32)
        self.r = np.array([d[2] for d in dots], np.float32)
        self.col = np.array([d[3] for d in dots], np.uint8)
        self.n = n
        xn = (self.x - self.x.min()) / (np.ptp(self.x) + 1e-6)
        yn = (self.y - self.y.min()) / (np.ptp(self.y) + 1e-6)
        # disperse order: sweeps left->right with noise; reform order: bottom->top with noise
        self.t_out = np.clip(0.55 * xn + 0.45 * rng.random(n), 0, 1)
        self.t_in = np.clip(0.55 * (1 - yn) + 0.45 * rng.random(n), 0, 1)
        ang = rng.uniform(-math.pi * 0.85, math.pi * 0.15, n)   # drift up/right
        mag = rng.uniform(20, 90, n)
        self.vx = np.cos(ang) * mag + 25
        self.vy = np.sin(ang) * mag - 10
        self.ph = rng.uniform(0, 2 * math.pi, n)
        self.wob = rng.uniform(3, 9, n)

    def state(self, p, t_order):
        """p in 0..1: 0 = assembled, 1 = fully dispersed. Returns x, y, r, alpha."""
        q = smooth((p - t_order * 0.55) / 0.45)
        x = self.x + self.vx * q + np.sin(self.ph + q * 5) * self.wob * q
        y = self.y + self.vy * q + np.cos(self.ph + q * 4) * self.wob * q
        r = self.r * (1 - 0.75 * q)
        a = 1 - q ** 1.4
        return x, y, r, a


def draw_dots(base, box, x, y, r, a, col):
    """Draw particles into `base` (RGB image), clipped to `box`, supersampled."""
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    layer = Image.new("RGB", (bw * SS, bh * SS), WIN_BG)
    d = ImageDraw.Draw(layer)
    order = np.argsort(-a)           # faint ones first
    for i in order[::-1]:
        if a[i] < 0.04 or r[i] < 0.25:
            continue
        c = tuple(int(WIN_BG[k] + (col[i][k] - WIN_BG[k]) * a[i]) for k in range(3))
        cx, cy, rr = x[i] * SS, y[i] * SS, r[i] * SS
        if cx < -rr or cy < -rr or cx > bw * SS + rr or cy > bh * SS + rr:
            continue
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=c)
    layer = layer.resize((bw, bh), Image.LANCZOS)
    out = base.copy()
    out.paste(layer, (x0, y0))
    return out


# ---- static chrome ---------------------------------------------------------
def window(d, box, title, fill=WIN_BG):
    x0, y0, x1, y1 = box
    d.rectangle([x0, y0, x1, y1], fill=fill, outline=BORDER)
    d.rectangle([x0 + 1, y0 + 1, x1 - 1, y0 + BAR_H], fill=WIN_BAR)
    d.line([(x0, y0 + BAR_H), (x1, y0 + BAR_H)], fill=BORDER)
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        cx = x0 + 18 + i * 18
        d.ellipse([cx - 5, y0 + BAR_H / 2 - 5, cx + 5, y0 + BAR_H / 2 + 5], fill=c)
    f = ImageFont.truetype(MONO, 11)
    tw = d.textlength(title, font=f)
    d.text(((x0 + x1) / 2 - tw / 2, y0 + BAR_H / 2 - 7), title, font=f, fill=(110, 118, 129))


def neofetch(d, box, cfg):
    x0, y0, x1, y1 = box
    f = ImageFont.truetype(MONO, 12)
    fb = ImageFont.truetype(MONO_B, 13)
    px = x0 + 22
    y = y0 + BAR_H + 24
    d.text((px, y), cfg["handle"], font=fb, fill=(139, 125, 255)); y += 8
    d.line([(px, y + 14), (px + 150, y + 14)], fill=BORDER); y += 28
    LH = 18

    def row(label, value):
        nonlocal y
        d.text((px, y), label + ":", font=f, fill=CYAN)
        d.text((px + 100, y), value, font=f, fill=MUTED)
        y += LH

    for group in cfg["groups"]:
        rows = [(k, v) for k, v in group if v]
        if not rows:
            continue
        for k, v in rows:
            row(k, v)
        y += 12
    # palette strip
    sw = ["#a78bfa", "#7c3aed", "#22d3ee", "#0891b2", "#10b981", "#059669", "#f97316", "#ef4444"]
    for i, c in enumerate(sw):
        d.rectangle([px + i * 22, y, px + i * 22 + 17, y + 17], fill=c)


def load_profile():
    path = os.path.join(HERE, "profile.json")
    with open(path) as fh:
        p = json.load(fh)
    def g(k):
        v = p.get(k) or ""
        if k in ("email", "linkedin", "instagram", "portfolio"):
            v = re.sub(r"^(mailto:|https?://)(www\.)?", "", v).rstrip("/")
        return v
    groups = [
        [("Name", g("name")), ("Role", g("role")), ("Origin", g("origin")), ("Education", g("education")), ("Status", g("status"))],
        [("Languages", g("languages")), ("Frontend", g("frontend")), ("Backend", g("backend")),
         ("Database", g("database")), ("Cloud", g("cloud")), ("AI", g("ai_ml"))],
        (p.get("projects") if isinstance(p.get("projects"), list) else [("Projects", g("projects"))]) +
        [("Email", g("email")), ("LinkedIn", g("linkedin")),
         ("Instagram", g("instagram")), ("Portfolio", g("portfolio"))],
    ]
    return {"handle": p.get("handle_line") or "subhash@github", "groups": groups}


def main(out):
    cfg = load_profile()
    base = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(base)
    window(d, (0, 0, LEFT[2] - 1, H - 1), "portrait.txt")
    window(d, (RIGHT[0], 0, W - 1, H - 1), "$ neofetch")
    neofetch(d, (RIGHT[0], 0, W - 1, H - 1), cfg)

    box = (1, BAR_H + 1, LEFT[2] - 1, H - 1)          # animated region
    bw, bh = box[2] - box[0], box[3] - box[1]
    cw, ch = bw // PITCH, bh // PITCH
    dots = sample_dots(cw, ch)
    ps = Particles(dots)
    print(f"{len(dots)} dots on a {cw}x{ch} grid")

    seq, dur = [], []
    seq.append(draw_dots(base, box, *ps.state(0, ps.t_out), ps.col)); dur.append(HOLD_MS)
    for k in range(1, STEPS):
        seq.append(draw_dots(base, box, *ps.state(k / STEPS, ps.t_out), ps.col)); dur.append(FPS_MS)
    seq.append(draw_dots(base, box, *ps.state(1.0, ps.t_out), ps.col)); dur.append(EMPTY_MS)
    for k in range(STEPS - 1, 0, -1):
        seq.append(draw_dots(base, box, *ps.state(k / STEPS, ps.t_in), ps.col)); dur.append(FPS_MS)

    sample = [seq[0]] * 3 + seq[:: max(1, len(seq) // 14)]
    sheet = Image.new("RGB", (W, H * len(sample)))
    for j, fr in enumerate(sample):
        sheet.paste(fr, (0, j * H))
    pal = sheet.quantize(colors=255, method=Image.MEDIANCUT, dither=Image.NONE)
    q = [fr.quantize(palette=pal, dither=Image.NONE) for fr in seq]
    q[0].save(out, save_all=True, append_images=q[1:], duration=dur, loop=0, optimize=False, disposal=1)
    print(f"{out}: {W}x{H}, {len(q)} frames, {os.path.getsize(out) / 1024:.0f} KB")
    return seq


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "assets", "computer-character.gif"))
