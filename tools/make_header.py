#!/usr/bin/env python3
"""Generate assets/header.gif: dotted headline that dissolves into particles.

Same visual language as the dotted character: every phrase is built from small
individual dots (cyan). After a hold the dots drift apart and fade; the next phrase
reassembles from particles while the last ones are still dissolving. Plain GIF.
"""
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

PHRASES = [
    "WELCOME TO MY TERMINAL.",
    "HI, I'M SUBHASH.",
    "SOFTWARE DEVELOPER.",
    "FULL-STACK DEVELOPER.",
    "FRONTEND SPECIALIST.",
    "BACKEND DEVELOPER.",
    "ARTIFICIAL INTELLIGENCE ENTHUSIAST.",
    "AI APPLICATION BUILDER.",
]

W, H = 880, 130
SS = 3                       # supersample for crisp dots
PITCH = 3                    # dot grid pitch (px)
BG = (10, 13, 18)
CYAN = (34, 211, 238)
LIGHT = (150, 240, 255)
HOLD_MS = 2600
FRAME_MS = 40
N = 40                       # frames in a transition
OUT_FR = 28                  # frames a phrase takes to dissolve
IN_FR = 28                   # frames the next phrase takes to assemble
IN_START = N - IN_FR         # the next phrase starts forming while the old one dissolves
FONT = "assets/fonts/SpaceGrotesk.ttf"


def smooth(t):
    t = np.clip(t, 0, 1)
    return t * t * (3 - 2 * t)


class Phrase:
    def __init__(self, text, seed):
        rng = np.random.default_rng(seed)
        font = ImageFont.truetype(FONT, 56)
        font.set_variation_by_axes([800])
        m = Image.new("L", (W, H), 0)
        d = ImageDraw.Draw(m)
        tw = d.textlength(text, font=font)
        asc, desc = font.getmetrics()
        d.text(((W - tw) / 2, (H - (asc + desc)) / 2), text, font=font, fill=255)
        a = np.asarray(m, np.float32) / 255.0
        cw, ch = W // PITCH, H // PITCH
        cov = a[:ch * PITCH, :cw * PITCH].reshape(ch, PITCH, cw, PITCH).mean(axis=(1, 3))
        ys, xs = np.nonzero(cov > 0.3)
        self.x = (xs * PITCH + PITCH / 2).astype(np.float32)
        self.y = (ys * PITCH + PITCH / 2).astype(np.float32)
        c = cov[ys, xs]
        self.r = (0.75 + 0.75 * np.clip(c, 0, 1)).astype(np.float32)
        n = len(xs)
        t = rng.random(n)
        self.col = np.array([[CYAN[k] + (LIGHT[k] - CYAN[k]) * (0.55 * tt ** 3) for k in range(3)] for tt in t], np.float32)
        xn = (self.x - self.x.min()) / (np.ptp(self.x) + 1e-6)
        self.t_out = np.clip(0.6 * xn + 0.4 * rng.random(n), 0, 1)             # dissolve sweeps left -> right
        self.t_in = np.clip(0.6 * xn + 0.4 * rng.random(n), 0, 1)              # reassembles left -> right
        ang = rng.uniform(-math.pi * 0.9, math.pi * 0.1, n)                    # drift up / right
        mag = rng.uniform(18, 70, n)
        self.vx = np.cos(ang) * mag + 18
        self.vy = np.sin(ang) * mag - 8
        self.ph = rng.uniform(0, 2 * math.pi, n)
        self.wob = rng.uniform(2, 8, n)

    def state(self, p, order):
        """p: 0 assembled .. 1 fully dispersed."""
        q = smooth((p - order * 0.55) / 0.45)
        x = self.x + self.vx * q + np.sin(self.ph + q * 5) * self.wob * q
        y = self.y + self.vy * q + np.cos(self.ph + q * 4) * self.wob * q
        return x, y, self.r * (1 - 0.7 * q), 1 - q ** 1.4


def draw(layers):
    """-> RGBA frame: dots only, fully transparent elsewhere."""
    img = Image.new("RGB", (W * SS, H * SS), (0, 0, 0))
    cov = Image.new("L", (W * SS, H * SS), 0)
    d, dc = ImageDraw.Draw(img), ImageDraw.Draw(cov)
    for ph, p, order in layers:
        x, y, r, a = ph.state(p, order)
        for i in np.nonzero((a > 0.04) & (r > 0.2))[0]:
            col = tuple(int(ph.col[i][k] * a[i]) for k in range(3))     # fade by darkening, not alpha
            cx, cy, rr = x[i] * SS, y[i] * SS, r[i] * SS
            box = [cx - rr, cy - rr, cx + rr, cy + rr]
            d.ellipse(box, fill=col)
            dc.ellipse(box, fill=255)
    img = np.asarray(img.resize((W, H), Image.LANCZOS), np.float32)
    cov = np.asarray(cov.resize((W, H), Image.LANCZOS), np.float32)
    keep = cov >= 110
    rgb = np.clip(img * 255.0 / np.maximum(cov, 110)[:, :, None], 0, 255)
    out = np.zeros((H, W, 4), np.uint8)
    out[..., :3] = rgb.astype(np.uint8)
    out[..., 3] = np.where(keep, 255, 0)
    return Image.fromarray(out, "RGBA")


def main(out):
    ph = [Phrase(t, 11 + i) for i, t in enumerate(PHRASES)]
    n = len(ph)
    frames, durs = [], []
    for i in range(n):
        cur, nxt = ph[i], ph[(i + 1) % n]
        frames.append(draw([(cur, 0.0, cur.t_out)])); durs.append(HOLD_MS)
        for k in range(1, N):
            layers = []
            if k <= OUT_FR:
                layers.append((cur, k / OUT_FR, cur.t_out))
            if k >= IN_START:
                layers.append((nxt, 1 - (k - IN_START) / IN_FR, nxt.t_in))
            frames.append(draw(layers)); durs.append(FRAME_MS)

    TI = 63                                           # palette index reserved for transparency
    sample = frames[:: max(1, len(frames) // 24)] + frames[:: max(1, N + 1)]
    sheet = Image.new("RGB", (W, H * len(sample)))
    for j, fr in enumerate(sample):
        sheet.paste(fr.convert("RGB"), (0, j * H))
    pal = sheet.quantize(colors=TI, method=Image.MEDIANCUT, dither=Image.NONE)
    q = []
    for fr in frames:
        p = fr.convert("RGB").quantize(palette=pal, dither=Image.NONE)
        arr = np.asarray(p).copy()
        arr[np.asarray(fr)[..., 3] == 0] = TI
        p = Image.fromarray(arr, "P")
        p.putpalette(pal.getpalette()[:TI * 3] + [0, 0, 0])
        p.info["transparency"] = TI
        q.append(p)
    q[0].save(out, save_all=True, append_images=q[1:], duration=durs, loop=0, optimize=False,
              disposal=2, transparency=TI)
    print(f"{out}: {W}x{H}, {len(q)} frames, {os.path.getsize(out) / 1024:.0f} KB, loop {sum(durs) / 1000:.1f}s")


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "..", "assets", "header.gif"))
