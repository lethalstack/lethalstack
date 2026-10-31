#!/usr/bin/env python3
"""Generate assets/header.gif: a looping 3D paper-flip text sequence.

Each phrase sits on a thin dark "paper" panel. After a hold it rotates around its
horizontal axis (perspective projected, eased, with shading); the next phrase,
pre-rotated on the back of the panel, swings in. Output is a plain GIF so it
renders on GitHub without any CSS/JS.
"""
import math
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

PHRASES = [
    "WELCOME TO MY TERMINAL",
    "HI, I'M SUBHASH.",
    "SOFTWARE ENGINEER",
    "FULL-STACK DEVELOPER",
    "WEB DEVELOPER",
    "LIFELONG LEARNER",
]

W, H = 880, 150            # final GIF size
SS = 2                     # supersampling factor
CARD_W, CARD_H = 820, 104  # panel size (final px)
BG = (10, 13, 18)
CARD = (15, 20, 27)
CARD_EDGE = (44, 52, 63)
CYAN = (34, 211, 238)
HOLD_MS = 2800
FLIP_FRAMES = 26
FRAME_MS = 40
FONT = "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf"
FOCAL = 1100.0             # perspective distance (final px)


def ease_in_out(t):
    # smootherstep: zero velocity at both ends, gentle through the middle
    return t * t * t * (t * (6 * t - 15) + 10)


def face(text, font):
    """Front face of one panel as an RGB array at supersampled size."""
    w, h = CARD_W * SS, CARD_H * SS
    im = Image.new("RGB", (w, h), CARD)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=6 * SS, outline=CARD_EDGE, width=SS)
    # faint inner top highlight, like the lip of a paper sheet
    d.line([(8 * SS, 2 * SS), (w - 8 * SS, 2 * SS)], fill=(24, 31, 40), width=SS)
    tw = d.textlength(text, font=font)
    asc, desc = font.getmetrics()
    x = (w - tw) / 2
    y = (h - (asc + desc)) / 2 + SS
    # soft cyan bloom under the glyphs (subtle, not a glow orb)
    bloom = Image.new("RGB", (w, h), (0, 0, 0))
    ImageDraw.Draw(bloom).text((x, y), text, font=font, fill=(6, 40, 48))
    from PIL import ImageFilter
    bloom = bloom.filter(ImageFilter.GaussianBlur(6 * SS))
    im = Image.fromarray(np.clip(np.asarray(im, dtype=np.int16) + np.asarray(bloom, dtype=np.int16), 0, 255).astype(np.uint8))
    ImageDraw.Draw(im).text((x, y), text, font=font, fill=CYAN)
    return im


def homography(src, dst):
    """3x3 matrix mapping src quad -> dst quad (4 points each)."""
    A, b = [], []
    for (x, y), (u, v) in zip(src, dst):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y]); b.append(u)
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y]); b.append(v)
    h = np.linalg.solve(np.array(A, float), np.array(b, float))
    return np.append(h, 1).reshape(3, 3)


def render(face_img, theta):
    """Canvas with the panel rotated by theta (radians) about its horizontal axis."""
    cw, ch = W * SS, H * SS
    canvas = Image.new("RGB", (cw, ch), BG)
    s, c = math.sin(theta), math.cos(theta)
    if abs(c) < 0.012:      # edge-on: draw a thin bright paper edge
        y = ch / 2
        ImageDraw.Draw(canvas).line([(cw / 2 - CARD_W * SS / 2, y), (cw / 2 + CARD_W * SS / 2, y)], fill=(70, 82, 96), width=SS)
        return canvas.resize((W, H), Image.LANCZOS)

    w, h = face_img.size
    # shading: the half rotating away darkens, the half rotating toward lightens a touch
    gy = np.linspace(-1, 1, h)[:, None]
    shade = 1.0 - 0.55 * abs(s) ** 1.3 + 0.18 * s * (-gy) * abs(s)
    arr = np.asarray(face_img, dtype=np.float32) * shade[:, :, None]
    shaded = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))

    corners_src = [(0, 0), (w, 0), (w, h), (0, h)]
    dst = []
    f = FOCAL * SS
    for (x, y) in corners_src:
        px, py = x - w / 2, y - h / 2
        z = py * s                      # depth: positive = toward the viewer
        k = f / (f - z)
        dst.append((cw / 2 + px * k, ch / 2 + py * c * k))
    # PIL wants dst->src coefficients
    Hm = homography(dst, corners_src)
    coeffs = (Hm[0, 0], Hm[0, 1], Hm[0, 2], Hm[1, 0], Hm[1, 1], Hm[1, 2], Hm[2, 0], Hm[2, 1])
    warped = shaded.transform((cw, ch), Image.PERSPECTIVE, coeffs, Image.BICUBIC)
    mask = Image.new("L", (w, h), 255).transform((cw, ch), Image.PERSPECTIVE, coeffs, Image.BILINEAR)

    # contact shadow beneath the panel while it tilts
    if abs(s) > 0.05:
        sh = Image.new("L", (cw, ch), 0)
        ImageDraw.Draw(sh).rectangle([cw / 2 - w / 2 + 20 * SS, ch / 2 + dst[2][1] - ch / 2 - 2 * SS,
                                      cw / 2 + w / 2 - 20 * SS, ch / 2 + dst[2][1] - ch / 2 + 10 * SS], fill=int(60 * abs(s)))
        from PIL import ImageFilter
        sh = sh.filter(ImageFilter.GaussianBlur(8 * SS))
        canvas = Image.composite(Image.new("RGB", (cw, ch), (0, 0, 0)), canvas, sh)
    canvas.paste(warped, (0, 0), mask)
    return canvas.resize((W, H), Image.LANCZOS)


def main(out):
    font = ImageFont.truetype(FONT, 46 * SS)
    faces = [face(t, font) for t in PHRASES]
    frames, durations = [], []
    n = len(faces)
    for i in range(n):
        cur, nxt = faces[i], faces[(i + 1) % n]
        frames.append(render(cur, 0.0)); durations.append(HOLD_MS)
        for k in range(1, FLIP_FRAMES):
            p = ease_in_out(k / FLIP_FRAMES) * math.pi     # 0..180 degrees
            if p < math.pi / 2:
                fr = render(cur, p)
            else:
                fr = render(nxt, p - math.pi)              # back face, pre-rotated
            frames.append(fr); durations.append(FRAME_MS)

    # one shared palette from a spread of frames keeps colours stable across the loop
    sample = frames[:: max(1, len(frames) // 24)]
    sheet = Image.new("RGB", (W, H * len(sample)))
    for j, fr in enumerate(sample):
        sheet.paste(fr, (0, j * H))
    pal = sheet.quantize(colors=128, method=Image.MEDIANCUT, dither=Image.NONE)
    q = [fr.quantize(palette=pal, dither=Image.NONE) for fr in frames]
    q[0].save(out, save_all=True, append_images=q[1:], duration=durations, loop=0,
              optimize=False, disposal=1)
    print(f"{out}: {W}x{H}, {len(q)} frames, {os.path.getsize(out) / 1024:.0f} KB, "
          f"loop {sum(durations) / 1000:.1f}s")


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "..", "assets", "header.gif"))
