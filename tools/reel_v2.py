#!/usr/bin/env python3
"""Reel v2 — habillage d'après les références Instagram de Manon.

Usage : python3 reel_v2.py <workdir> [--photos]
Lit  work/transcript.json, work/edit.json (coupes), work/style.json (habillage),
     work/montage_sans_texte.mp4 (montage coupé/zoomé déjà rendu)
Écrit work/export_v2/reel_final_HD.mp4 (+ photos.jpg en mode --photos)
"""
import json, math, os, re, subprocess, sys
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import render_hd as rh  # plan de coupe (mêmes coupes que le montage déjà rendu)

W, H, FPS = 1080, 1920, 30
FD = os.path.join(ROOT, "fonts")
SFX = os.path.join(ROOT, "sfx")

WHITE = (255, 255, 255, 255)
YELLOW = (246, 228, 170, 255)      # jaune beurre pastel (doux)
CREAM = (251, 243, 194, 255)      # crème « $85,000 »
HAND_Y = (250, 238, 200, 255)
INK = (22, 22, 22, 255)
GREY_TXT = (110, 110, 110, 255)
GREEN = (46, 170, 82, 255)
RED = (226, 72, 64, 255)


# ───────────────────── typo ─────────────────────
FONTS = {
    "sans": ("Inter", 800), "black": ("Inter", 900), "semi": ("Inter", 600), "reg": ("Inter", 450),
    "serif_i": ("PlayfairDisplay-Italic", 500), "serif": ("PlayfairDisplay", 400),
    "script": ("KaushanScript-Regular.ttf", None), "hand": ("ArchitectsDaughter-Regular.ttf", None),
    "hand_b": ("GloriaHallelujah.ttf", None),
}


@lru_cache(maxsize=None)
def font(kind, size):
    name, wght = FONTS[kind]
    f = ImageFont.truetype(os.path.join(FD, name), int(size))
    if wght:
        axes = f.get_variation_axes()
        f.set_variation_by_axes([wght if a["name"] in (b"Weight", "Weight") else a["default"] for a in axes]
                                if len(axes) > 1 else [wght])
    return f


def shadowed(layer, blur=10, off=(0, 4), alpha=120):
    """Ajoute une ombre portée douce sous un calque RGBA."""
    pad = blur * 3
    big = Image.new("RGBA", (layer.width + 2 * pad, layer.height + 2 * pad), (0, 0, 0, 0))
    a = layer.getchannel("A").point(lambda v: v * alpha // 255)
    sh = Image.new("RGBA", layer.size, (0, 0, 0, 255)); sh.putalpha(a)
    big.paste(sh, (pad + off[0], pad + off[1]), sh)
    big = big.filter(ImageFilter.GaussianBlur(blur))
    big.alpha_composite(layer, (pad, pad))
    return big


@lru_cache(maxsize=4096)
def text_spr(text, kind, size, color=WHITE, shadow=True, spacing=0):
    f = font(kind, size)
    if spacing:
        ws = [f.getbbox(c)[2] - f.getbbox(c)[0] if c != " " else size * 0.3 for c in text]
        w = int(sum(ws) + spacing * len(text)) + 20
    else:
        b = f.getbbox(text); w = b[2] - min(0, b[0]) + 20
    asc, desc = f.getmetrics()
    img = Image.new("RGBA", (max(w, 4), asc + desc + 30), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if spacing:
        x = 10
        for c, cw in zip(text, ws):
            d.text((x, 12), c, font=f, fill=color); x += cw + spacing
    else:
        d.text((10, 12), text, font=f, fill=color)
    img = img.crop(img.getbbox() or (0, 0, 4, 4))
    return shadowed(img, blur=max(6, size // 9), off=(0, max(2, size // 25)), alpha=150) if shadow else img


def put(canvas, spr, cx, cy, scale=1.0, alpha=1.0, rot=0.0):
    if alpha <= 0.01 or scale <= 0.01:
        return
    s = spr
    if abs(scale - 1) > 0.01:
        s = s.resize((max(1, int(s.width * scale)), max(1, int(s.height * scale))), Image.BILINEAR)
    if rot:
        s = s.rotate(rot, resample=Image.BICUBIC, expand=True)
    if alpha < 0.99:
        s = s.copy(); s.putalpha(s.getchannel("A").point(lambda v: int(v * alpha)))
    canvas.alpha_composite(s, (int(cx - s.width / 2), int(cy - s.height / 2)))


def ease_out(x):
    x = min(max(x, 0), 1); return 1 - (1 - x) ** 3


def ease_back(x, k=1.9):
    x = min(max(x, 0), 1); return 1 + (k + 1) * (x - 1) ** 3 + k * (x - 1) ** 2


def rrect(size, r, fill, outline=None):
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle((0, 0, size[0] - 1, size[1] - 1), r, fill=fill, outline=outline)
    return img


def wrap(text, f, maxw):
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if cur and f.getlength(t) > maxw:
            lines.append(cur); cur = w
        else:
            cur = t
    if cur:
        lines.append(cur)
    return lines


# ───────────────────── éléments ─────────────────────
class El:
    hides_caps = False

    def __init__(self, s, T):
        self.s, self.T = s, T
        self.t0 = T(s["at"])
        self.t1 = T(s["fin"], end=True) if "fin" in s else self.t0 + s.get("dur", 2.0)
        self.sfx = []

    def life(self, t):
        """(apparition 0→1, disparition 1→0)"""
        return min(1, (t - self.t0) / 0.35), min(1, max(0, (self.t1 - t) / 0.22))


class Kinetic(El):
    """Empilement de mots qui tombent au rythme de la voix (WHERE / IS / MY / EXPERTISE / worth more)."""
    hides_caps = True

    def __init__(self, s, T):
        super().__init__(s, T)
        self.lines = []
        for ln in s["lignes"]:
            st = ln.get("style", "sans")
            kind, color, up = {"sans": ("black", WHITE, True), "sans_y": ("black", YELLOW, True),
                               "serif_y": ("serif_i", YELLOW, False), "serif": ("serif_i", WHITE, False),
                               "script": ("script", WHITE, False), "cream": ("black", CREAM, True),
                               "big_serif": ("serif", CREAM, False)}[st]
            size = ln.get("taille", {"serif_y": 128, "serif": 118, "script": 120, "big_serif": 200}.get(st, 112))
            txt = ln["text"].upper() if up else ln["text"]
            spr = text_spr(txt, kind, size, color)
            if spr.width > 1000:
                spr = text_spr(txt, kind, int(size * 1000 / spr.width), color)
            self.lines.append((spr, T(ln["at"]) if "at" in ln else self.t0))
        self.head = text_spr(s["entete"], "hand", 64, WHITE, spacing=3) if s.get("entete") else None
        gap = s.get("gap", -18)
        tot = sum(sp.height + gap for sp, _ in self.lines) + (self.head.height + 6 if self.head else 0)
        self.y = s.get("y", 0.75) * H - tot / 2
        self.sfx = [(self.t0, "woosh", 0.35)] + [(ta, "pop", 0.22) for _, ta in self.lines[1:]]
        if s.get("simple"):
            self.lines = [(sp, self.t0) for sp, _ in self.lines]

    def draw(self, c, t):
        _, out = self.life(t)
        y = self.y
        if self.head:
            a = ease_out((t - self.t0) / 0.3)
            put(c, self.head, W / 2, y + self.head.height / 2, alpha=a * out)
            y += self.head.height + 6
        for spr, ta in self.lines:
            if self.s.get("simple"):
                put(c, spr, W / 2, y + spr.height / 2, alpha=ease_out((t - self.t0) / 0.4) * out)
                y += spr.height + self.s.get("gap", -18)
                continue
            x = (t - ta) / 0.22
            if x >= 0:
                sc = 1.35 - 0.35 * ease_out(x)
                put(c, spr, W / 2, y + spr.height / 2, scale=sc, alpha=min(1, x * 1.6) * out)
            y += spr.height + self.s.get("gap", -18)


class Chapter(El):
    """Fondu orangé plein écran + « Step #1: » + ligne manuscrite."""
    hides_caps = True

    def __init__(self, s, T):
        super().__init__(s, T)
        self.a = text_spr(s["text"], "sans", 96, WHITE)
        self.b = text_spr(s["sub"], "script", 92, WHITE) if s.get("sub") else None
        self.sfx = [(self.t0 - 0.15, "woosh", 0.5)]

    def draw(self, c, t):
        inn, out = self.life(t)
        y = H * 0.57
        put(c, self.a, W / 2, y, scale=0.9 + 0.1 * ease_back(inn), alpha=inn * out)
        if self.b:
            x = ease_out((t - self.t0 - 0.25) / 0.35)
            put(c, self.b, W / 2, y + 110, alpha=x * out, scale=0.95 + 0.05 * x)


class DarkCard(El):
    """Carte noire, chiffre jaune + légende blanche ($500 coaching call)."""

    def __init__(self, s, T):
        super().__init__(s, T)
        v = text_spr(s["valeur"], "black", 128, YELLOW, shadow=False)
        if v.width > 760:
            v = text_spr(s["valeur"], "black", int(128 * 760 / v.width), YELLOW, shadow=False)
        l = text_spr(s["label"], "semi", 44, WHITE, shadow=False)
        cw, ch = max(v.width, l.width) + 120, v.height + l.height + 90
        card = rrect((cw, ch), 34, (12, 12, 12, 240))
        card.alpha_composite(v, ((cw - v.width) // 2, 38))
        card.alpha_composite(l, ((cw - l.width) // 2, 38 + v.height + 18))
        self.card = shadowed(card, 18, (0, 10), 110)
        self.y = s.get("y", 0.79) * H
        self.sfx = [(self.t0, s.get("son", "pop"), 0.55)]

    def draw(self, c, t):
        inn, out = self.life(t)
        put(c, self.card, W / 2, self.y + 60 * (1 - ease_out(inn)), scale=0.75 + 0.25 * ease_back(inn), alpha=min(1, inn * 2) * out)


class ResultCard(El):
    """Carte blanche + pastille + gros chiffre + courbe qui se trace (first 24 hours of launch)."""

    def __init__(self, s, T):
        super().__init__(s, T)
        self.cw, self.ch = 900, 270
        base = rrect((self.cw, self.ch), 40, (255, 255, 255, 250))
        d = ImageDraw.Draw(base)
        col = GREEN if s.get("sens", "up") == "up" else RED
        self.col = col
        d.ellipse((40, 52, 62, 74), fill=col)
        lab = text_spr(s["label"], "semi", 36, (60, 60, 60, 255), shadow=False)
        base.alpha_composite(lab, (76, 44))
        val = text_spr(s["valeur"], "black", 104, INK, shadow=False)
        base.alpha_composite(val, (38, 112))
        self.base = base
        pts = s.get("points", [0.1, 0.18, 0.3, 0.38, 0.55, 0.7, 0.92] if col == GREEN else [0.95, 0.9, 0.55, 0.3, 0.18, 0.12, 0.1])
        x0, x1, y0, y1 = 560, 860, 225, 60
        self.pts = [(x0 + (x1 - x0) * k / (len(pts) - 1), y0 + (y1 - y0) * p) for k, p in enumerate(pts)]
        self.y = s.get("y", 0.8) * H
        self.sfx = [(self.t0, s.get("son", "notif2"), 0.5)]

    def draw(self, c, t):
        inn, out = self.life(t)
        img = self.base.copy()
        d = ImageDraw.Draw(img)
        prog = ease_out((t - self.t0 - 0.3) / 1.2)
        n = len(self.pts) - 1
        upto = prog * n
        pts = self.pts[:int(upto) + 1]
        if int(upto) < n:
            a, b = self.pts[int(upto)], self.pts[int(upto) + 1]
            f = upto - int(upto)
            pts = pts + [(a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)]
        if len(pts) > 1:
            fill = [(pts[0][0], 230)] + pts + [(pts[-1][0], 230)]
            ov = Image.new("RGBA", img.size, (0, 0, 0, 0))
            ImageDraw.Draw(ov).polygon(fill, fill=self.col[:3] + (40,))
            img.alpha_composite(ov)
            d.line(pts, fill=self.col, width=7, joint="curve")
            ex, ey = pts[-1]
            d.ellipse((ex - 11, ey - 11, ex + 11, ey + 11), fill=self.col)
        spr = shadowed(img, 18, (0, 10), 100)
        put(c, spr, W / 2, self.y + 80 * (1 - ease_out(inn)), alpha=min(1, inn * 2) * out)


class DMStack(El):
    """Titre manuscrit + cartes blanches empilées avec bulles grises (straight from my DMs...)."""

    def __init__(self, s, T):
        super().__init__(s, T)
        self.head = text_spr(s["entete"], "hand", 58, HAND_Y, spacing=2)
        dots = [(232, 205, 120, 255), (150, 180, 150, 255), (214, 140, 100, 255)]
        f = font("reg", 40)
        self.cards = []
        for k, m in enumerate(s["messages"]):
            lines = wrap(m["text"], f, 640)
            bh = 40 + 52 * len(lines)
            cw, ch = 860, bh + 60
            card = rrect((cw, ch), 30, (255, 255, 255, 255))
            d = ImageDraw.Draw(card)
            d.rounded_rectangle((80, 30, 80 + max(f.getlength(l) for l in lines) + 56, 30 + bh), 30, fill=(236, 236, 236, 255))
            for j, l in enumerate(lines):
                d.text((108, 50 + 52 * j), l, font=f, fill=INK)
            d.ellipse((26, ch - 66, 60, ch - 32), fill=dots[k % 3])
            self.cards.append((shadowed(card, 16, (0, 8), 90), T(m["at"]) if "at" in m else self.t0 + 0.4 + 0.5 * k,
                               (-1.5, 1.2, -0.6)[k % 3], (-20, 26, -6)[k % 3]))
        self.y = s.get("y", 0.6) * H
        self.sfx = [(ta, "notif1", 0.45) for _, ta, _, _ in self.cards]

    def draw(self, c, t):
        _, out = self.life(t)
        y = self.y
        a = ease_out((t - self.t0) / 0.3)
        put(c, self.head, W / 2, y, alpha=a * out)
        y += self.head.height / 2 + 10
        for spr, ta, rot, dx in self.cards:
            x = (t - ta) / 0.35
            if x >= 0:
                put(c, spr, W / 2 + dx, y + spr.height / 2 - 14 + 50 * (1 - ease_out(x)), scale=0.9 + 0.1 * ease_back(x),
                    alpha=min(1, x * 2) * out, rot=rot)
            y += spr.height - 40


def ig_icon(size):
    """Logo Instagram dessiné (dégradé + appareil photo blanc)."""
    g = Image.new("RGBA", (size, size))
    px = g.load()
    stops = [(254, 218, 117), (250, 126, 30), (214, 41, 118), (150, 47, 191), (79, 91, 213)]
    for y in range(size):
        for x in range(size):
            p = min(0.999, max(0, ((size - y) * 0.75 + x * 0.25) / size * 1.0))
            p = 1 - p
            k = p * (len(stops) - 1); i = int(k); f = k - i
            a, b = stops[i], stops[min(i + 1, len(stops) - 1)]
            px[x, y] = tuple(int(a[j] + (b[j] - a[j]) * f) for j in range(3)) + (255,)
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, size - 1, size - 1), size // 4.2, fill=255)
    g.putalpha(m)
    d = ImageDraw.Draw(g)
    s = size
    d.rounded_rectangle((s * .2, s * .2, s * .8, s * .8), s * .17, outline="white", width=max(3, s // 14))
    d.ellipse((s * .36, s * .36, s * .64, s * .64), outline="white", width=max(3, s // 14))
    d.ellipse((s * .66, s * .28, s * .72, s * .34), fill="white")
    return shadowed(g, 14, (0, 8), 90)


def heart_icon(size, color=WHITE, fill=True):
    img = Image.new("RGBA", (size * 4, size * 4), (0, 0, 0, 0))
    d = ImageDraw.Draw(img); s = size * 4
    pts = [(s / 2 + s * 0.48 * (16 * math.sin(a) ** 3) / 17, s * 0.45 - s * 0.48 * (13 * math.cos(a) - 5 * math.cos(2 * a) - 2 * math.cos(3 * a) - math.cos(4 * a)) / 17)
           for a in [i / 60 * 2 * math.pi for i in range(61)]]
    if fill:
        d.polygon(pts, fill=color)
    else:
        d.line(pts, fill=color, width=s // 12, joint="curve")
    return img.resize((size, size), Image.LANCZOS)


class Phone(El):
    """Écran de Reel qui pop (insert « How to break a man's ego »), avec badge ✓/✗."""
    hides_caps = True

    def __init__(self, s, T, frame):
        super().__init__(s, T)
        pw, ph = 500, 890
        scr = frame.resize((pw, int(pw * H / W)), Image.LANCZOS).crop((0, 0, pw, ph)).convert("RGBA")
        dark = Image.new("RGBA", scr.size, (0, 0, 0, 70)); scr.alpha_composite(dark)
        d = ImageDraw.Draw(scr)
        f = font("sans", 38)
        lines = wrap(s["text"], f, 400)
        y = ph * 0.5 - len(lines) * 24
        for l in lines:
            tw = f.getlength(l)
            sp = text_spr(l, "sans", 38, WHITE)
            scr.alpha_composite(sp, (int((pw - sp.width) / 2), int(y))); y += 50
        # colonne d'icônes à droite + pseudo
        for k in range(4):
            cy = ph * 0.56 + k * 78
            if k == 0:
                scr.alpha_composite(heart_icon(40, WHITE, fill=False), (pw - 64, int(cy)))
            else:
                d.ellipse((pw - 62, cy + 2, pw - 26, cy + 38), outline="white", width=4)
        d.ellipse((24, ph - 112, 74, ph - 62), fill=(230, 210, 190, 255))
        d.text((88, ph - 106), s.get("compte", "socialskindlyroad"), font=font("semi", 28), fill="white")
        d.rounded_rectangle((88 + font("semi", 28).getlength(s.get("compte", "socialskindlyroad")) + 18, ph - 108,
                             88 + font("semi", 28).getlength(s.get("compte", "socialskindlyroad")) + 130, ph - 66), 12, outline="white", width=3)
        d.text((88 + font("semi", 28).getlength(s.get("compte", "socialskindlyroad")) + 34, ph - 104), "Suivre", font=font("semi", 26), fill="white")
        d.line((32, 40, 18, 54, 32, 68), fill="white", width=5)
        m = Image.new("L", scr.size, 0)
        ImageDraw.Draw(m).rounded_rectangle((0, 0, pw - 1, ph - 1), 26, fill=255)
        scr.putalpha(m)
        self.phone = shadowed(scr, 24, (0, 14), 140)
        ok = s.get("verdict") == "ok"
        bd = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
        dd = ImageDraw.Draw(bd)
        dd.ellipse((0, 0, 119, 119), fill=GREEN if ok else RED)
        if ok:
            dd.line((30, 62, 52, 84, 92, 38), fill="white", width=13, joint="curve")
        else:
            dd.line((36, 36, 84, 84), fill="white", width=13); dd.line((84, 36, 36, 84), fill="white", width=13)
        self.badge = shadowed(bd, 10, (0, 5), 120)
        self.lab = text_spr(s["etiquette"], "hand_b", 66, WHITE) if s.get("etiquette") else None
        self.sfx = [(self.t0, "woosh", 0.45), (self.t0 + s.get("badge_at", 1.2), "notif2" if ok else "pop", 0.5)]

    def draw(self, c, t):
        inn, out = self.life(t)
        cy = H * 0.745 + 700 * (1 - ease_back(min(1, (t - self.t0) / 0.45), 1.2))
        put(c, self.phone, W / 2, cy, alpha=out)
        x = (t - self.t0 - self.s.get("badge_at", 1.2)) / 0.3
        if x >= 0:
            put(c, self.badge, W / 2 + 230, cy - 410, scale=0.4 + 0.6 * ease_back(x), alpha=min(1, x * 2) * out)
        if self.lab:
            put(c, self.lab, W / 2 - 160, cy - 470, alpha=ease_out((t - self.t0 - 0.3) / 0.3) * out, rot=6)


class Sheet(El):
    """Menu d'appli sombre translucide + doigt qui tape « Supprimer »."""

    def __init__(self, s, T):
        super().__init__(s, T)
        self.opts = s["options"]
        self.tap = T(s["tap_at"]) if "tap_at" in s else self.t0 + 1.0
        self.sfx = [(self.t0, "woosh", 0.3), (self.tap, "click2", 0.8)]
        self.y = s.get("y", 0.79) * H

    def draw(self, c, t):
        inn, out = self.life(t)
        rw, rh_ = 760, 104
        img = rrect((rw, rh_ * len(self.opts) + 20), 34, (38, 38, 40, 225))
        d = ImageDraw.Draw(img)
        for k, o in enumerate(self.opts):
            y = 10 + k * rh_
            red = o == self.s["actif"]
            if red and t >= self.tap:
                d.rounded_rectangle((10, y + 4, rw - 10, y + rh_ - 4), 22, fill=(80, 80, 84, 255))
            if k:
                d.line((40, y, rw - 40, y), fill=(70, 70, 74, 255), width=2)
            f = font("semi", 42)
            d.text((rw / 2 - f.getlength(o) / 2, y + 26), o, font=f, fill=RED if red else (240, 240, 240, 255))
        spr = shadowed(img, 20, (0, 10), 120)
        sc = 1.0
        if self.tap <= t < self.tap + 0.25:
            sc = 1 - 0.04 * math.sin((t - self.tap) / 0.25 * math.pi)
        put(c, spr, W / 2, self.y + 60 * (1 - ease_out(inn)), scale=sc, alpha=min(1, inn * 2) * out)
        # doigt (cercle de tap)
        k = self.opts.index(self.s["actif"])
        ty = self.y - spr.height / 2 + 30 + 10 + k * rh_ + rh_ / 2 + 10
        x = (t - (self.tap - 0.45)) / 0.45
        if 0 <= x and t < self.tap + 0.6:
            r = 46 if t < self.tap else 46 + 60 * (t - self.tap) / 0.6
            a = 0.85 if t < self.tap else 0.85 * (1 - (t - self.tap) / 0.6)
            ring = Image.new("RGBA", (260, 260), (0, 0, 0, 0))
            ImageDraw.Draw(ring).ellipse((130 - r, 130 - r, 130 + r, 130 + r), fill=(255, 255, 255, int(110 * a)),
                                         outline=(255, 255, 255, int(255 * a)), width=5)
            put(c, ring, W / 2 + 140 + 120 * (1 - ease_out(x)), ty + 80 * (1 - ease_out(x)))


class CommentCTA(El):
    """Logo Instagram → barre de commentaire où « 101 » se tape, puis « Publier » tapé."""

    def __init__(self, s, T):
        super().__init__(s, T)
        self.ig = ig_icon(170)
        self.arrow = text_spr("→", "sans", 90, WHITE)
        self.word = s.get("mot", "101")
        self.t_type = self.t0 + 0.7
        self.t_send = self.t_type + 0.25 * len(self.word) + 0.4
        self.sfx = [(self.t0, "woosh", 0.35)] + [(self.t_type, "typing1", 0.5, 0.25 * len(self.word) + 0.1), (self.t_send, "click1", 0.7), (self.t_send + 0.15, "notif2", 0.4)]
        self.y = s.get("y", 0.76) * H

    def draw(self, c, t):
        inn, out = self.life(t)
        a = min(1, inn * 2) * out
        put(c, self.ig, W / 2 - 250, self.y, scale=0.5 + 0.5 * ease_back(inn), alpha=a)
        xa = ease_out((t - self.t0 - 0.25) / 0.3)
        put(c, self.arrow, W / 2 - 90 + 30 * xa, self.y, alpha=xa * out)
        n = max(0, min(len(self.word), int((t - self.t_type) / 0.25) + 1)) if t >= self.t_type else 0
        bar = rrect((440, 120), 60, (255, 255, 255, 250))
        d = ImageDraw.Draw(bar)
        typed = self.word[:n]
        f = font("semi", 46)
        if typed:
            d.text((40, 30), typed, font=f, fill=INK)
        else:
            d.text((40, 34), "Commenter…", font=font("reg", 38), fill=(150, 150, 150, 255))
        if typed and (t * 2) % 1 < 0.6 and t < self.t_send:
            cx = 40 + f.getlength(typed) + 6
            d.rectangle((cx, 32, cx + 4, 88), fill=(0, 149, 246, 255))
        sent = t >= self.t_send
        pf = font("sans", 36)
        d.text((300, 40), "Publier", font=pf, fill=(0, 149, 246, 255) if typed else (170, 205, 240, 255))
        sc = 1 - 0.05 * math.sin(min(1, (t - self.t_send) / 0.25) * math.pi) if sent else 1
        xb = ease_out((t - self.t0 - 0.4) / 0.35)
        put(c, shadowed(bar, 16, (0, 8), 100), W / 2 + 190, self.y, scale=sc * (0.8 + 0.2 * xb), alpha=xb * out)
        if sent:
            x = (t - self.t_send) / 0.5
            put(c, heart_icon(110, (237, 73, 86, 255)), W / 2 + 330, self.y - 90 - 60 * ease_out(x),
                scale=0.4 + 0.8 * ease_back(min(1, x)), alpha=max(0, 1 - max(0, x - 1.2)) * out)


class Note(El):
    """Annotation manuscrite + flèche dessinée (LAUNCH UPDATE!! ↘)."""

    def __init__(self, s, T):
        super().__init__(s, T)
        self.txt = [text_spr(l, "hand_b", 60, WHITE, spacing=1) for l in s["text"].split("\n")]
        self.x, self.y = s.get("x", 0.25) * W, s.get("y", 0.2) * H
        self.dir = s.get("fleche", "bas_droite")
        self.sfx = [(self.t0, "pop", 0.3)]

    def draw(self, c, t):
        inn, out = self.life(t)
        y = self.y
        for k, sp in enumerate(self.txt):
            a = ease_out((t - self.t0 - 0.12 * k) / 0.3)
            put(c, sp, self.x, y, alpha=a * out, rot=8)
            y += sp.height - 6
        p = ease_out((t - self.t0 - 0.35) / 0.6)
        if p > 0:
            ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            d = ImageDraw.Draw(ov)
            sx, sy = self.x - 20, y + 10
            sgn = 1 if self.dir == "bas_droite" else -1
            pts = []
            for i in range(41):
                u = i / 40 * p
                px_ = sx + sgn * 150 * u ** 1.6
                py_ = sy + 170 * math.sin(u * math.pi / 2)
                pts.append((px_, py_))
            d.line(pts, fill=(255, 255, 255, int(255 * out)), width=7, joint="curve")
            if p > 0.95:
                (ax, ay), (ex, ey) = pts[-3], pts[-1]
                ang = math.atan2(ey - ay, ex - ax)
                for da in (2.6, -2.6):
                    d.line((ex, ey, ex + 34 * math.cos(ang + da), ey + 34 * math.sin(ang + da)), fill=(255, 255, 255, int(255 * out)), width=7)
            c.alpha_composite(ov)


TYPES = {"kinetic": Kinetic, "chapitre": Chapter, "carte_noire": DarkCard, "resultat": ResultCard,
         "dm": DMStack, "telephone": Phone, "menu": Sheet, "commentaire": CommentCTA, "note": Note}


# ───────────────────── sous-titres : phrase entière, frappe manuscrite + curseur ─────────────────────
class Captions:
    def __init__(self, kept, style, T):
        self.y = style.get("sous_titres_y", 0.6) * H
        serif_at = set(style.get("phrases_serif", []))
        words = [w for w in kept if w["text"].strip()]
        sents, cur = [], []
        for w in words:
            cur.append(w)
            if re.search(r"[.!?…]$", w["text"]):
                sents.append(cur); cur = []
        if cur:
            sents.append(cur)
        GOOD = {"mais", "qui", "que", "qu'il", "qu'elle", "pour", "et", "c'est", "dans", "si", "sinon,", "quand", "elle", "tu", "de", "à"}

        def split(ws):
            txt = " ".join(x["text"] for x in ws)
            if len(txt) <= 50 or len(ws) < 4:
                return [ws]
            best, bs = None, 1e9
            tot = len(txt)
            pos = 0
            for k in range(1, len(ws)):
                pos += len(ws[k - 1]["text"]) + 1
                score = abs(pos - tot / 2)
                if re.search(r"[,:;]$", ws[k - 1]["text"]):
                    score -= 14
                elif ws[k]["text"].lower() in GOOD:
                    score -= 7
                if ws[k]["ns"] - ws[k - 1]["ne"] > 0.12:
                    score -= 6
                if score < bs:
                    bs, best = score, k
            return split(ws[:best]) + split(ws[best:])
        chunks = [c for snt in sents for c in split(snt)]
        self.chunks = []
        for k, ch in enumerate(chunks):
            serif = any(w["i"] in serif_at for w in ch)
            kind, size = ("serif_i", 74) if serif else ("script", 70)
            f = font(kind, size)
            text = " ".join(w["text"] for w in ch)
            lines = wrap(text, f, 960)
            nxt = chunks[k + 1][0]["ns"] if k + 1 < len(chunks) else ch[-1]["ne"] + 0.8
            self.chunks.append({"words": ch, "text": text, "lines": lines, "kind": kind, "size": size,
                                "t0": ch[0]["ns"], "t1": min(nxt, ch[-1]["ne"] + 0.7)})

    @lru_cache(maxsize=256)
    def sprite(self, k, n, cursor):
        ch = self.chunks[k]
        f = font(ch["kind"], ch["size"])
        lh = int(ch["size"] * 1.22)
        bw = int(max(f.getlength(l) for l in ch["lines"])) + 60
        img = Image.new("RGBA", (bw + 40, lh * len(ch["lines"]) + 40), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        left, rem, last = 20, n, (20, 20)
        for j, l in enumerate(ch["lines"]):
            part = l[:rem]; rem -= len(part) + 1
            y = 14 + j * lh
            off = (bw - f.getlength(l)) / 2 if ch["kind"] == "serif_i" else 0
            if part:
                d.text((left + off, y), part, font=f, fill=WHITE)
            last = (left + off + f.getlength(part), y)
            if rem < 0:
                break
        if cursor:
            x, y = last
            d.rectangle((x + 8, y + ch["size"] * 0.12, x + 8 + ch["size"] * 0.42, y + ch["size"] * 1.05), fill=WHITE)
        return shadowed(img, 9, (0, 3), 170)

    def draw(self, c, t, hidden):
        for k, ch in enumerate(self.chunks):
            if ch["t0"] - 0.05 <= t < ch["t1"]:
                if hidden(ch["t0"], ch["t1"], t):
                    return
                # nombre de caractères visibles calé sur la voix
                n, pos = 0, 0
                for w in ch["words"]:
                    L = len(w["text"]) + 1
                    if t >= w["ne"]:
                        n = pos + L
                    elif t >= w["ns"]:
                        n = pos + int(L * (t - w["ns"]) / max(0.08, w["ne"] - w["ns"]))
                    pos += L
                n = min(n, len(ch["text"]))
                typing = n < len(ch["text"])
                cursor = typing or ((t - ch["t0"]) * 2.2) % 1 < 0.55
                spr = self.sprite(k, n, cursor and t < ch["t1"] - 0.1)
                put(c, spr, W / 2, self.y + spr.height / 2 - 40)
                return


# ───────────────────── fondu orangé (Step #1) ─────────────────────
def make_wash():
    import numpy as np
    yy = np.linspace(0, 1, H)[:, None]; xx = np.linspace(0, 1, W)[None, :]
    k = np.clip(0.55 * yy + 0.45 * (1 - xx) * 0.6 + 0.1, 0, 1)[..., None]
    top, bot = np.array([255, 214, 120]), np.array([243, 132, 64])
    rgb = (top * (1 - k) + bot * k).astype(np.uint8)
    return rgb


def main():
    wd = sys.argv[1]
    photos = "--photos" in sys.argv
    tr = json.load(open(os.path.join(wd, "transcript.json")))
    ed = json.load(open(os.path.join(wd, "edit.json")))
    st = json.load(open(os.path.join(wd, "style.json")))
    segs, kept, by_i, total = rh.plan(tr, ed)

    def T(x, end=False):
        if isinstance(x, str):
            return float(x.rstrip("s"))
        if x in by_i:
            return by_i[x]["ne" if end else "ns"]
        nxt = [w for i, w in sorted(by_i.items()) if i >= x]
        return nxt[0]["ns"] if nxt else total

    cut = os.path.join(wd, "montage_sans_texte.mp4")

    def frame_at(t):
        p = os.path.join(wd, f"_f{t:.2f}.png")
        subprocess.run(f'ffmpeg -y -loglevel error -ss {t:.3f} -i "{cut}" -frames:v 1 "{p}"', shell=True, check=True)
        return Image.open(p).convert("RGB")

    els = []
    for s in st["elements"]:
        if s["type"] == "telephone":
            els.append(Phone(s, T, frame_at(float(s.get("image_t", 2.0)))))
        else:
            els.append(TYPES[s["type"]](s, T))
    for k, (e, s_) in enumerate(zip(els, st["elements"])):
        if s_.get("hold"):
            nxt = [x.t0 for x in els[k + 1:]]
            e.t1 = max(e.t1, (nxt[0] if nxt else total) - 0.02)
    caps = Captions(kept, st, T)
    washes = sorted([e.t0 for e in els if isinstance(e, Chapter)] + [T(x) for x in st.get("fondus", [])])
    import numpy as np
    wash_rgb = make_wash()

    def wash_alpha(t):
        for w0 in washes:
            x = (t - (w0 - 0.45)) / 0.7
            if 0 <= x <= 1:
                return (math.sin(x * math.pi) ** 0.9) * 0.62
        return 0

    def hidden(a, b, t):
        return any(e.hides_caps and e.t0 - 0.05 <= t < e.t1 for e in els)

    def compose(t):
        full = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        wa = wash_alpha(t)
        if wa > 0:
            full = Image.fromarray(np.dstack([wash_rgb, np.full((H, W, 1), int(wa * 255), np.uint8)]), "RGBA")
        caps.draw(full, t, hidden)
        for e in els:
            if e.t0 <= t < e.t1:
                e.draw(full, t)
        return full

    out = os.path.join(wd, "export_v2")
    os.makedirs(out, exist_ok=True)
    if photos:
        tiles = []
        for e in els:
            t = min(e.t1 - 0.1, e.t0 + max(1.0, (e.t1 - e.t0) * 0.75))
            bg = frame_at(t).convert("RGBA")
            bg.alpha_composite(compose(t))
            tiles.append(bg.convert("RGB").resize((270, 480)))
        for t in st.get("photos_sous_titres", []):
            bg = frame_at(t).convert("RGBA"); bg.alpha_composite(compose(t)); tiles.append(bg.convert("RGB").resize((270, 480)))
        cols = 6
        sheet = Image.new("RGB", (270 * cols, 480 * ((len(tiles) + cols - 1) // cols)), "black")
        for i, tl in enumerate(tiles):
            sheet.paste(tl, ((i % cols) * 270, (i // cols) * 480))
        sheet.save(os.path.join(out, "photos.jpg"), quality=88)
        print("✓ photos", len(tiles))
        return

    # sons : liste d'événements
    events = [tuple(x) + (None,) * (4 - len(x)) for e in els for x in e.sfx if 0 <= x[0] < total]
    events += [(w - 0.3, "woosh", 0.45, None) for w in [T(x) for x in st.get("fondus", [])]]
    if st.get("sons", True) is False:
        events = []
    events.sort()
    sfx_in = " ".join(f'-i "{os.path.join(SFX, n + ".mp3")}"' for _, n, _, _ in events)
    fc = "[0:v][1:v]overlay=0:0:format=auto,format=yuv420p[v];"
    mix = ["[0:a]volume=1.0[a0]"]
    for k, (t, n, v, du) in enumerate(events):
        ms = int(max(0, t) * 1000)
        tr_ = f"atrim=0:{du},afade=t=out:st={max(0, du - 0.08)}:d=0.08," if du else ""
        mix.append(f"[{k + 2}:a]{tr_}aformat=sample_rates=48000:channel_layouts=stereo,volume={v},adelay={ms}|{ms}[s{k}]")
    fc += ";".join(mix) + ";" + "[a0]" + "".join(f"[s{k}]" for k in range(len(events))) + \
          f"amix=inputs={len(events) + 1}:normalize=0:duration=first,alimiter=limit=0.95[a]"
    final = os.path.join(out, "reel_final_HD.mp4")
    cmd = (f'ffmpeg -y -loglevel error -i "{cut}" -f rawvideo -pix_fmt rgba -s {W}x{H} -r {FPS} -i - {sfx_in} '
           f'-filter_complex "{fc}" -map "[v]" -map "[a]" -c:v libx264 -preset slow -crf 14 -profile:v high '
           f'-c:a aac -b:a 256k -movflags +faststart "{final}"')
    p = subprocess.Popen(cmd, shell=True, stdin=subprocess.PIPE)
    nfr = int(round(total * FPS))
    for fr in range(nfr):
        t = fr / FPS
        p.stdin.write(compose(t).tobytes())
        if fr % (FPS * 10) == 0:
            print(f"→ {t:.0f}/{total:.0f}s", flush=True)
    p.stdin.close(); p.wait()
    print(f"✓ {final} · {len(events)} sons · {len(els)} éléments")


if __name__ == "__main__":
    main()
