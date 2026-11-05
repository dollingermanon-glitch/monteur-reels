#!/usr/bin/env python3
"""Motion v1 — reel 100 % animé (sans face caméra) à la charte SKR.

Usage : python3 motion_v1.py <workdir> [--apercu] [--voix chemin.m4a]

Lit  <workdir>/motion.json   (scènes + sous-titres, avec leurs temps)
     <workdir>/assets/       (vignettes de reels)
Écrit <workdir>/<nom>_motion.mp4   (+ apercu.jpg avec --apercu)

Sans --voix : la vidéo sort avec les bruitages seuls, calée sur un timing estimé.
Avec --voix : la voix off est mixée sous les bruitages (recaler motion.json avant).
"""
import json, math, os, subprocess, sys
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
FD = os.path.join(HERE, "fonts")
SFX = os.path.join(HERE, "sfx")
W, H, FPS = 1080, 1920, 30

CREAM = (250, 245, 233, 255)
INK = (30, 27, 24, 255)
GREY = (120, 113, 104, 255)
LINE = (226, 219, 203, 255)
YELLOW = (246, 228, 170, 255)     # jaune beurre de la charte
OCRE = (204, 138, 32, 255)        # accent lisible sur fond crème
WHITE = (255, 255, 255, 255)
CARD = (255, 253, 248, 255)

FONTS = {
    "sans": ("Inter", 800), "black": ("Inter", 900), "semi": ("Inter", 600), "reg": ("Inter", 450),
    "serif": ("PlayfairDisplay", 400), "serif_i": ("PlayfairDisplay-Italic", 450),
    "mono": ("Inter", 500),
}


@lru_cache(maxsize=None)
def font(kind, size):
    name, wght = FONTS[kind]
    f = ImageFont.truetype(os.path.join(FD, name), int(size))
    axes = f.get_variation_axes() if wght else []
    if axes:
        f.set_variation_by_axes([wght if a["name"] in (b"Weight", "Weight") else a["default"] for a in axes])
    return f


# ───────────────────── utilitaires ─────────────────────
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease_out(x):
    x = clamp(x); return 1 - (1 - x) ** 3


def ease_back(x, k=1.7):
    x = clamp(x); return 1 + (k + 1) * (x - 1) ** 3 + k * (x - 1) ** 2


def shadowed(layer, blur=24, off=(0, 14), alpha=46):
    pad = blur * 3
    big = Image.new("RGBA", (layer.width + 2 * pad, layer.height + 2 * pad), (0, 0, 0, 0))
    a = layer.getchannel("A").point(lambda v: v * alpha // 255)
    sh = Image.new("RGBA", layer.size, (60, 40, 10, 255)); sh.putalpha(a)
    big.paste(sh, (pad + off[0], pad + off[1]), sh)
    big = big.filter(ImageFilter.GaussianBlur(blur))
    big.alpha_composite(layer, (pad, pad))
    return big


def put(c, spr, cx, cy, scale=1.0, alpha=1.0, anchor="c"):
    if alpha <= 0.01 or scale <= 0.01:
        return
    s = spr
    if abs(scale - 1) > 0.005:
        s = s.resize((max(1, int(s.width * scale)), max(1, int(s.height * scale))), Image.BICUBIC)
    if alpha < 0.99:
        s = s.copy(); s.putalpha(s.getchannel("A").point(lambda v: int(v * alpha)))
    x = cx - s.width / 2 if anchor == "c" else cx
    c.alpha_composite(s, (int(x), int(cy - s.height / 2)))


@lru_cache(maxsize=4096)
def txt(text, kind, size, color=INK):
    f = font(kind, size)
    asc, desc = f.getmetrics()
    w = int(f.getlength(text)) + 30
    img = Image.new("RGBA", (max(w, 4), asc + desc + 20), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((15, 10), text, font=f, fill=color)
    return img


@lru_cache(maxsize=1024)
def rich(segs, size):
    """segs : tuple de (texte, police, couleur) posés sur la même ligne de base."""
    sprs = [txt(t, k, size, col) for t, k, col in segs]
    asc = max(font(k, size).getmetrics()[0] for _, k, _ in segs)
    hh = max(s.height for s in sprs) + 10
    img = Image.new("RGBA", (sum(s.width - 30 for s in sprs) + 30, hh), (0, 0, 0, 0))
    x = 0
    for s, (_, k, _) in zip(sprs, segs):
        dy = asc - font(k, size).getmetrics()[0]
        img.alpha_composite(s, (x, dy)); x += s.width - 30
    return img


def rrect(size, r, fill, outline=None, width=2):
    img = Image.new("RGBA", (int(size[0]), int(size[1])), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle((0, 0, img.width - 1, img.height - 1), r, fill=fill,
                                          outline=outline, width=width)
    return img


def asterisk(size, color=OCRE, rays=10):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img); c = size / 2
    for k in range(rays):
        a = k * math.pi * 2 / rays + 0.15
        r = c * (0.95 if k % 2 == 0 else 0.8)
        d.line((c, c, c + r * math.cos(a), c + r * math.sin(a)), fill=color, width=max(3, size // 11))
    d.ellipse((c - size * .09, c - size * .09, c + size * .09, c + size * .09), fill=color)
    return img


def ig_icon(size):
    g = Image.new("RGBA", (size, size))
    stops = [(254, 218, 117), (250, 126, 30), (214, 41, 118), (150, 47, 191), (79, 91, 213)]
    px = g.load()
    for y in range(size):
        for x in range(size):
            k = clamp((x * 0.4 + (size - y) * 0.6) / size) * (len(stops) - 1)
            i = min(int(k), len(stops) - 2); f = k - i
            px[x, y] = tuple(int(stops[i][j] * (1 - f) + stops[i + 1][j] * f) for j in range(3)) + (255,)
    m = Image.new("L", (size, size)); ImageDraw.Draw(m).rounded_rectangle((0, 0, size - 1, size - 1), size // 4.2, fill=255)
    g.putalpha(m)
    d = ImageDraw.Draw(g); s = size; lw = max(3, s // 14)
    d.rounded_rectangle((s * .2, s * .2, s * .8, s * .8), s * .18, outline=WHITE, width=lw)
    d.ellipse((s * .35, s * .35, s * .65, s * .65), outline=WHITE, width=lw)
    d.ellipse((s * .66, s * .27, s * .73, s * .34), fill=WHITE)
    return g


def make_bg():
    yy = np.linspace(0, 1, H)[:, None]; xx = np.linspace(0, 1, W)[None, :]
    base = np.array(CREAM[:3], float)
    glow = np.array([252, 232, 176], float)
    d1 = np.exp(-(((xx - 0.85) / 0.55) ** 2 + ((yy - 0.08) / 0.35) ** 2))
    d2 = np.exp(-(((xx - 0.1) / 0.5) ** 2 + ((yy - 0.95) / 0.3) ** 2)) * 0.6
    k = np.clip(d1 + d2, 0, 1)[..., None] * 0.55
    rgb = base * (1 - k) + glow * k
    a = np.full((H, W, 1), 255.0)
    return Image.fromarray(np.dstack([rgb, a]).astype(np.uint8), "RGBA")


# ───────────────────── briques visuelles ─────────────────────
@lru_cache(maxsize=None)
def window(w, h, title="Claude"):
    win = rrect((w, h), 34, CARD, outline=LINE)
    d = ImageDraw.Draw(win)
    for k, col in enumerate([(255, 95, 87), (254, 188, 46), (40, 200, 64)]):
        d.ellipse((30 + k * 30, 28, 48 + k * 30, 46), fill=col)
    t = txt(title, "semi", 26, GREY)
    win.alpha_composite(t, (w // 2 - t.width // 2, 16))
    d.line((0, 74, w, 74), fill=LINE, width=2)
    return win


def input_bar(w, text, cursor=False, send_on=False, placeholder="Écris à Claude…"):
    bar = rrect((w, 110), 26, (247, 243, 234, 255), outline=LINE)
    if text:
        t = txt(text + ("|" if cursor else ""), "reg", 34, INK)
    else:
        t = txt(placeholder, "reg", 34, GREY)
    bar.alpha_composite(t, (14, 55 - t.height // 2))
    btn = rrect((64, 64), 16, OCRE if send_on else LINE)
    ImageDraw.Draw(btn).polygon([(32, 16), (48, 34), (38, 34), (38, 48), (26, 48), (26, 34), (16, 34)], fill=WHITE)
    bar.alpha_composite(btn, (w - 86, 23))
    return bar


@lru_cache(maxsize=None)
def chip(text, fill=YELLOW, col=INK, size=30, kind="semi"):
    t = txt(text, kind, size, col)
    c = rrect((t.width + 18, t.height + 4), (t.height + 4) // 2, fill)
    c.alpha_composite(t, (9, 2))
    return c


@lru_cache(maxsize=None)
def thumb(path, w):
    im = Image.open(path).convert("RGBA")
    im = im.resize((w, int(im.height * w / im.width)), Image.LANCZOS)
    m = Image.new("L", im.size); ImageDraw.Draw(m).rounded_rectangle((0, 0, im.width - 1, im.height - 1), 22, fill=255)
    im.putalpha(m)
    return shadowed(im, blur=18, off=(0, 10), alpha=60)


# ───────────────────── scènes ─────────────────────
class Scene:
    def __init__(self, s, t0, t1, wd):
        self.s, self.t0, self.t1, self.wd = s, t0, t1, wd
        self.sfx = []

    def appear(self, t, at=0.0, d=0.35):
        return ease_out((t - self.t0 - at) / d)


def header(c, t, sc, n, segs, total_steps=7):
    """Barre de progression 7 segments + « Étape N » + titre."""
    x0, x1, y = 70, W - 70, 170
    gap = 14; sw = (x1 - x0 - gap * (total_steps - 1)) / total_steps
    d = ImageDraw.Draw(c)
    for k in range(total_steps):
        xa = x0 + k * (sw + gap)
        d.rounded_rectangle((xa, y, xa + sw, y + 8), 4, fill=LINE)
        if k < n - 1:
            d.rounded_rectangle((xa, y, xa + sw, y + 8), 4, fill=OCRE)
        elif k == n - 1:
            p = ease_out((t - sc.t0) / 0.5)
            d.rounded_rectangle((xa, y, xa + max(8, sw * p), y + 8), 4, fill=OCRE)
    a = sc.appear(t, 0, 0.3)
    put(c, txt(f"Étape {n}", "semi", 34, OCRE), x0 - 15, 238, alpha=a, anchor="l")
    ttl = rich(segs, 96)
    put(c, ttl, x0 - 15, 330 + (1 - a) * 30, scale=min(1.0, 960 / ttl.width), alpha=a, anchor="l")


class Hook(Scene):
    def __init__(self, *a):
        super().__init__(*a)
        self.sfx = [(self.t0 + 0.05, "pop", 0.5), (self.t0 + 0.55, "woosh", 0.35), (self.t0 + 2.6, "pop", 0.4)]
        self.sfx += [(self.t0 + 3.0 + k * 0.22, "click1", 0.25) for k in range(7)]

    def draw(self, c, t):
        r = t - self.t0
        up = ease_out((r - 2.4) / 0.5) * 120
        a1 = ease_out(r / 0.3)
        put(c, txt("Je ne monte plus", "sans", 80, INK), W / 2, 640 - up + (1 - a1) * 30, alpha=a1)
        # surligneur jaune derrière « aucun »
        s2 = ease_back((r - 0.45) / 0.45)
        hl = ease_out((r - 0.7) / 0.4)
        if hl > 0:
            ImageDraw.Draw(c).rounded_rectangle((W / 2 - 250, 760 - up, W / 2 - 250 + 500 * hl, 880 - up), 18, fill=YELLOW)
        put(c, txt("aucun", "serif_i", 190, OCRE), W / 2, 790 - up, scale=0.6 + 0.4 * s2, alpha=clamp(s2 * 1.5))
        a3 = ease_out((r - 1.0) / 0.3)
        put(c, txt("de mes reels.", "serif", 92, INK), W / 2, 960 - up + (1 - a3) * 30, alpha=a3)
        a4 = ease_out((r - 2.6) / 0.35)
        put(c, rich((("C'est ", "semi", INK), ("Claude", "semi", OCRE), (" qui le fait.", "semi", INK)), 56),
            W / 2, 1020 + (1 - a4) * 30, alpha=a4)
        # 7 segments qui se remplissent
        if r > 2.9:
            x0, x1, y = 170, W - 170, 1150
            gap = 14; sw = (x1 - x0 - gap * 6) / 7
            d = ImageDraw.Draw(c)
            for k in range(7):
                p = ease_out((r - 3.0 - k * 0.22) / 0.2)
                xa = x0 + k * (sw + gap)
                d.rounded_rectangle((xa, y, xa + sw, y + 16), 8, fill=LINE)
                if p > 0:
                    d.rounded_rectangle((xa, y, xa + max(16, sw * p), y + 16), 8, fill=OCRE)
            a5 = ease_out((r - 3.0) / 0.3)
            put(c, rich((("7", "black", OCRE), (" étapes.", "serif", INK)), 84), W / 2, 1270, alpha=a5)


class Ouvre(Scene):
    def __init__(self, *a):
        super().__init__(*a); self.sfx = [(self.t0 + 0.05, "woosh", 0.4), (self.t0 + 0.35, "pop", 0.4)]

    def draw(self, c, t):
        header(c, t, self, 1, (("Ouvre ", "serif", INK), ("Claude", "serif_i", OCRE)))
        s = ease_back((t - self.t0 - 0.2) / 0.45)
        win = window(860, 620).copy()
        put(win, asterisk(90), 430, 230, scale=0.8 + 0.2 * math.sin((t - self.t0) * 3) ** 2)
        put(win, txt("On monte quoi aujourd'hui ?", "semi", 42, INK), 430, 340)
        win.alpha_composite(input_bar(800, ""), (30, 470))
        put(c, shadowed(win), W / 2, 930, scale=0.85 + 0.15 * s, alpha=clamp(s * 1.4))


class Charte(Scene):
    ROWS = [("Couleurs", "jaune beurre + crème"), ("Polices", "Inter + Playfair"),
            ("Sous-titres", "effet frappe"), ("Rythme", "coupes serrées"), ("Règle", "jamais sur mon visage")]

    def __init__(self, *a):
        super().__init__(*a)
        self.step = min(0.9, (self.t1 - self.t0 - 1.6) / len(self.ROWS))
        self.sfx = [(self.t0 + 0.2, "pop", 0.45)] + [(self.t0 + 0.9 + k * self.step, "click2", 0.35) for k in range(len(self.ROWS))]

    def draw(self, c, t):
        header(c, t, self, 2, (("Ta ", "serif", INK), ("charte", "serif_i", OCRE)))
        r = t - self.t0
        s = ease_back((r - 0.15) / 0.45)
        card = rrect((860, 840), 34, CARD, outline=LINE)
        top = rrect((860, 170), 34, YELLOW)
        ImageDraw.Draw(top).rectangle((0, 120, 860, 170), fill=YELLOW)
        card.alpha_composite(top, (0, 0))
        card.alpha_composite(txt("MON GUIDE DE STYLE", "semi", 26, GREY), (44, 26))
        card.alpha_composite(txt("Ma charte", "serif_i", 80, INK), (40, 52))
        for k, (a, b) in enumerate(self.ROWS):
            p = ease_out((r - 0.9 - k * self.step) / 0.3)
            if p <= 0:
                continue
            y = 215 + k * 92
            row = Image.new("RGBA", (800, 80), (0, 0, 0, 0))
            dd = ImageDraw.Draw(row)
            dd.rounded_rectangle((0, 18, 44, 62), 12, fill=OCRE)
            dd.line((10, 40, 19, 50, 35, 29), fill=WHITE, width=6)
            row.alpha_composite(rich(((a + " : ", "semi", INK), (b, "reg", GREY)), 38), (52, 6))
            put(card, row, 40 + (1 - p) * 40, y + 40, alpha=p, anchor="l")
        # pastilles de couleur
        pz = ease_back((r - 0.9 - len(self.ROWS) * self.step) / 0.4)
        if pz > 0:
            for k, col in enumerate([YELLOW, CREAM, OCRE, INK]):
                dot = Image.new("RGBA", (84, 84)); ImageDraw.Draw(dot).ellipse((2, 2, 81, 81), fill=col, outline=LINE, width=3)
                put(card, dot, 90 + k * 110, 760, scale=pz)
        put(c, shadowed(card), W / 2, 920, scale=0.85 + 0.15 * s, alpha=clamp(s * 1.4))


class Skill(Scene):
    LINES = [("---", GREY), ("name: montage-reels", OCRE), ("description: monte mes reels", OCRE), ("---", GREY),
             ("1. Lis ma charte", INK), ("2. Coupe les blancs et les « euh »", INK),
             ("3. Sous-titre à ma charte", INK), ("4. Exporte en 9:16", INK)]

    def __init__(self, *a):
        super().__init__(*a)
        self.n = sum(len(l) for l, _ in self.LINES)
        self.dur = max(1.0, self.t1 - self.t0 - 0.9)
        self.sfx = [(self.t0 + 0.1, "pop", 0.4), (self.t0 + 0.5, "typing1", 0.35, min(self.dur, 3.5))]

    def draw(self, c, t):
        header(c, t, self, 3, (("Ton ", "serif", INK), ("skill", "serif_i", OCRE), (" de montage", "serif", INK)))
        r = t - self.t0
        s = ease_back((r - 0.1) / 0.45)
        win = window(860, 760, "SKILL.md").copy()
        win.alpha_composite(chip("installé", (232, 245, 233, 255), (46, 140, 70, 255), 24), (700, 18))
        typed = int(self.n * clamp((r - 0.5) / self.dur))
        y = 110
        for line, col in self.LINES:
            if typed <= 0:
                break
            part = line[:typed]; typed -= len(line)
            cur = typed < 0 and int(r * 3) % 2 == 0
            win.alpha_composite(txt(part + ("|" if cur else ""), "mono", 36, col), (36, y)); y += 74
        put(c, shadowed(win), W / 2, 930, scale=0.85 + 0.15 * s, alpha=clamp(s * 1.4))


class Matiere(Scene):
    def __init__(self, *a):
        super().__init__(*a)
        self.th = [os.path.join(self.wd, "assets", f"thumb{k}.jpg") for k in range(1, 7)]
        self.sfx = [(self.t0 + 0.15 + k * 0.18, "pop", 0.3) for k in range(6)] + [(self.t0 + 1.6, "click1", 0.3)]

    def draw(self, c, t):
        header(c, t, self, 4, (("Ta ", "serif", INK), ("matière", "serif_i", OCRE)))
        r = t - self.t0
        for k, p in enumerate(self.th):
            s = ease_back((r - 0.15 - k * 0.18) / 0.4)
            if s <= 0:
                continue
            cx = W / 2 + (k % 3 - 1) * 280; cy = 650 + (k // 3) * 440
            put(c, thumb(p, 245), cx, cy, scale=0.6 + 0.4 * s, alpha=clamp(s * 1.5))
        for k, lab in enumerate(["+ rushs", "+ photos", "+ sons"]):
            s = ease_back((r - 1.6 - k * 0.15) / 0.35)
            put(c, chip(lab, YELLOW, INK, 40), W / 2 + (k - 1) * 260, 1345, scale=0.6 + 0.4 * s, alpha=clamp(s * 1.5))


class Upload(Scene):
    FILES = ["rushs.mp4", "ma-charte.pdf", "SKILL.md"]

    def __init__(self, *a):
        super().__init__(*a)
        self.sfx = [(self.t0 + 0.2 + k * 0.3, "woosh", 0.3) for k in range(3)] + [(self.t0 + 1.3, "notif1", 0.3)]

    def draw(self, c, t):
        header(c, t, self, 5, (("Balance ", "serif", INK), ("tout", "serif_i", OCRE)))
        r = t - self.t0
        win = window(860, 620).copy()
        put(win, asterisk(90), 430, 210)
        put(win, txt("On monte quoi aujourd'hui ?", "semi", 42, INK), 430, 310)
        win.alpha_composite(input_bar(800, ""), (30, 470))
        s = ease_back(r / 0.4)
        put(c, shadowed(win), W / 2, 930, scale=0.9 + 0.1 * s, alpha=clamp(s * 1.4))
        # fichiers qui volent du bas vers la zone de saisie
        for k, f in enumerate(self.FILES):
            p = ease_out((r - 0.2 - k * 0.3) / 0.5)
            if p <= 0:
                continue
            tx = 160 + [0, 250, 540][k]; ty = 1065
            x = W / 2 + (k - 1) * 250 + (tx - (W / 2 + (k - 1) * 250)) * p
            y = 1500 + (ty - 1500) * p
            put(c, chip(f, (240, 234, 220, 255), INK, 28), x, y, anchor="l", alpha=clamp(p * 2))


class Demande(Scene):
    MSG = "Monte-moi ça en suivant ma charte"

    def __init__(self, *a):
        super().__init__(*a)
        self.dur = max(1.0, min(2.2, self.t1 - self.t0 - 1.0))
        self.sfx = [(self.t0 + 0.3, "typing2", 0.35, self.dur), (self.t0 + 0.4 + self.dur, "button", 0.5)]

    def draw(self, c, t):
        header(c, t, self, 6, (("Demande-lui de ", "serif", INK), ("monter", "serif_i", OCRE)))
        r = t - self.t0
        win = window(860, 620).copy()
        n = int(len(self.MSG) * clamp((r - 0.3) / self.dur))
        sent = r > 0.4 + self.dur
        if sent:
            bub = chip(self.MSG, YELLOW, INK, 34, "reg")
            put(win, bub, 830 - bub.width, 200, anchor="l", alpha=ease_out((r - 0.4 - self.dur) / 0.25))
            if r > 0.9 + self.dur:
                put(win, asterisk(60), 80, 330, scale=0.85 + 0.15 * math.sin(r * 6))
                put(win, txt("Je m'en occupe…", "reg", 34, GREY), 120, 330, anchor="l")
        win.alpha_composite(chip("skill : montage-reels", (253, 236, 214, 255), OCRE, 24), (40, 418))
        win.alpha_composite(input_bar(800, "" if sent else self.MSG[:n], cursor=not sent and n > 0,
                                      send_on=n == len(self.MSG) and not sent), (30, 470))
        s = ease_back(r / 0.4)
        put(c, shadowed(win), W / 2, 930, scale=0.9 + 0.1 * s, alpha=clamp(s * 1.4))


class Attends(Scene):
    def __init__(self, *a):
        super().__init__(*a)
        self.dur = max(1.5, self.t1 - self.t0 - 0.8)
        self.sfx = [(self.t0 + 0.2, "timer", 0.3, self.dur), (self.t0 + 0.2 + self.dur, "notif2", 0.45)]

    def draw(self, c, t):
        header(c, t, self, 7, (("Attends le ", "serif", INK), ("résultat", "serif_i", OCRE)))
        r = t - self.t0
        p = ease_out((r - 0.2) / self.dur)
        R = 260; cx, cy = W / 2, 930
        d = ImageDraw.Draw(c)
        d.ellipse((cx - R, cy - R, cx + R, cy + R), outline=LINE, width=26)
        if p > 0:
            d.arc((cx - R, cy - R, cx + R, cy + R), -90, -90 + 360 * p, fill=OCRE, width=26)
        put(c, txt("environ", "reg", 36, GREY), cx, cy - 120)
        put(c, txt(str(int(round(30 * p))), "serif", 200, INK), cx, cy - 5)
        put(c, txt("minutes", "semi", 40, INK), cx, cy + 125)


class Retouche(Scene):
    def __init__(self, *a):
        super().__init__(*a)
        self.sfx = [(self.t0 + 0.3, "pop", 0.4), (self.t0 + 1.2, "notif1", 0.35)]

    def draw(self, c, t):
        r = t - self.t0
        a = ease_out(r / 0.3)
        put(c, rich((("Une retouche ? ", "serif", INK), ("Redemande.", "serif_i", OCRE)), 74), W / 2, 420 + (1 - a) * 30, alpha=a)
        win = window(860, 560).copy()
        b1 = chip("Coupe plus serré au début", YELLOW, INK, 34, "reg")
        put(win, b1, 830 - b1.width, 180, anchor="l", alpha=ease_out((r - 0.3) / 0.25))
        if r > 1.2:
            b2 = chip("C'est fait. Nouvelle version prête ✓", (240, 236, 226, 255), INK, 34, "reg")
            put(win, b2, 30, 300, anchor="l", alpha=ease_out((r - 1.2) / 0.25))
        win.alpha_composite(input_bar(800, ""), (30, 420))
        s = ease_back(r / 0.4)
        put(c, shadowed(win), W / 2, 930, scale=0.9 + 0.1 * s, alpha=clamp(s * 1.4))


class Payoff(Scene):
    def __init__(self, *a):
        super().__init__(*a); self.sfx = [(self.t0 + 0.05, "woosh", 0.4), (self.t0 + 1.1, "pop", 0.45)]

    def draw(self, c, t):
        r = t - self.t0
        a1 = ease_out(r / 0.3)
        put(c, txt("Ce temps-là,", "serif", 96, INK), W / 2, 700 + (1 - a1) * 30, alpha=a1)
        a2 = ease_out((r - 0.5) / 0.3)
        put(c, txt("je le passe sur ce qui fait", "semi", 52, INK), W / 2, 830 + (1 - a2) * 30, alpha=a2)
        hl = ease_out((r - 1.1) / 0.35)
        if hl > 0:
            ImageDraw.Draw(c).rounded_rectangle((W / 2 - 440, 915, W / 2 - 440 + 880 * hl, 1050), 22, fill=YELLOW)
        s = ease_back((r - 1.0) / 0.45)
        put(c, txt("vraiment vendre.", "serif_i", 112, OCRE), W / 2, 975, scale=0.6 + 0.4 * s, alpha=clamp(s * 1.5))


class CTA(Scene):
    WORD = "MONTAGE"

    def __init__(self, *a):
        super().__init__(*a)
        self.sfx = [(self.t0 + 0.05, "woosh", 0.4), (self.t0 + 0.4, "pop", 0.55), (self.t0 + 1.4, "typing1", 0.3, 0.9),
                    (self.t0 + 2.5, "button", 0.45)]

    def draw(self, c, t):
        r = t - self.t0
        a = ease_out(r / 0.3)
        put(c, txt("Commente", "serif", 110, INK), W / 2, 560 + (1 - a) * 30, alpha=a)
        s = ease_back((r - 0.35) / 0.45)
        pill = rrect((640, 190), 40, OCRE)
        put(pill, txt(self.WORD, "black", 118, WHITE), 320, 95)
        pill = shadowed(pill)
        put(c, pill, W / 2, 750, scale=(0.6 + 0.4 * s) * (1 + 0.03 * math.sin(r * 5) * (r > 1)), alpha=clamp(s * 1.5))
        a2 = ease_out((r - 0.8) / 0.3)
        for k, lab in enumerate(["Ma charte", "Le skill"]):
            put(c, chip(lab, YELLOW, INK, 38), W / 2 + (k - 0.5) * 290, 930, alpha=a2)
        put(c, txt("et je te les envoie en DM", "reg", 40, GREY), W / 2, 1015, alpha=a2)
        # barre de commentaire Insta
        a3 = ease_out((r - 1.2) / 0.3)
        if a3 > 0:
            n = int(len(self.WORD) * clamp((r - 1.4) / 0.9))
            bar = rrect((780, 110), 55, WHITE, outline=LINE)
            bar.alpha_composite(ig_icon(70), (22, 20))
            tt = txt((self.WORD[:n] or "Ajoute un commentaire…") + ("|" if 0 < n < len(self.WORD) else ""), "reg" if not n else "semi", 36, INK if n else GREY)
            bar.alpha_composite(tt, (110, 55 - tt.height // 2))
            pub = txt("Publier", "semi", 34, (0, 149, 246, 255) if r > 2.4 else (170, 205, 240, 255))
            bar.alpha_composite(pub, (650, 55 - pub.height // 2))
            put(c, shadowed(bar, alpha=30), W / 2, 1200 + (1 - a3) * 40, alpha=a3)


TYPES = {"hook": Hook, "ouvre": Ouvre, "charte": Charte, "skill": Skill, "matiere": Matiere, "upload": Upload,
         "demande": Demande, "attends": Attends, "retouche": Retouche, "payoff": Payoff, "cta": CTA}


# ───────────────────── sous-titres ─────────────────────
class Captions:
    """Sous-titres de la voix off, mot-clé entre *étoiles* en ocre. Apparition par blocs."""

    def __init__(self, caps):
        self.caps = caps

    def draw(self, c, t):
        for t0, t1, text in self.caps:
            if t0 <= t < t1:
                segs = []
                for k, part in enumerate(text.split("*")):
                    if part:
                        segs.append((part, "sans", OCRE if k % 2 else INK))
                spr = rich(tuple(segs), 50)
                a = ease_out((t - t0) / 0.12)
                put(c, spr, W / 2, 1480 + (1 - a) * 12, scale=0.94 + 0.06 * ease_back((t - t0) / 0.2), alpha=a)
                return


def build(wd):
    mj = json.load(open(os.path.join(wd, "motion.json")))
    sc = mj["scenes"]
    total = mj["duree"]
    scenes = []
    for k, s in enumerate(sc):
        t1 = sc[k + 1]["t"] if k + 1 < len(sc) else total
        scenes.append(TYPES[s["type"]](s, s["t"], t1, wd))
    caps = []
    for s in sc:
        caps += [tuple(x) for x in s.get("sous_titres", [])]
    return mj, scenes, Captions(caps), total


def main():
    wd = sys.argv[1]
    mj, scenes, caps, total = build(wd)
    bg = make_bg()

    def compose(t):
        c = bg.copy()
        for s in scenes:
            if s.t0 <= t < s.t1:
                s.draw(c, t)
        caps.draw(c, t)
        return c

    if "--apercu" in sys.argv:
        tiles = []
        for s in scenes:
            for f in (0.45, 0.92):
                tiles.append(compose(s.t0 + (s.t1 - s.t0) * f).convert("RGB").resize((270, 480), Image.LANCZOS))
        cols = 6
        sheet = Image.new("RGB", (270 * cols, 480 * ((len(tiles) + cols - 1) // cols)), "white")
        for i, tl in enumerate(tiles):
            sheet.paste(tl, ((i % cols) * 270, (i // cols) * 480))
        sheet.save(os.path.join(wd, "apercu.jpg"), quality=88)
        print("✓ aperçu", len(tiles)); return

    voix = sys.argv[sys.argv.index("--voix") + 1] if "--voix" in sys.argv else None
    events = sorted(tuple(x) + (None,) * (4 - len(x)) for s in scenes for x in s.sfx if 0 <= x[0] < total)
    ins = f'-f lavfi -t {total} -i anullsrc=r=48000:cl=stereo' if not voix else f'-i "{voix}"'
    ins += " " + " ".join(f'-i "{os.path.join(SFX, n + ".mp3")}"' for _, n, _, _ in events)
    vol_sfx = 1.0 if not voix else 0.6
    mix = [f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,apad=whole_dur={total}[a0]"]
    for k, (t, n, v, du) in enumerate(events):
        ms = int(max(0, t) * 1000)
        trm = f"atrim=0:{du},afade=t=out:st={max(0, du - 0.1)}:d=0.1," if du else ""
        mix.append(f"[{k + 2}:a]{trm}aformat=sample_rates=48000:channel_layouts=stereo,volume={v * vol_sfx},adelay={ms}|{ms}[s{k}]")
    fc = ";".join(mix) + ";[a0]" + "".join(f"[s{k}]" for k in range(len(events))) + \
        f"amix=inputs={len(events) + 1}:normalize=0:duration=first,alimiter=limit=0.95[a]"
    out = os.path.join(wd, mj["nom"] + "_motion.mp4")
    cmd = (f'ffmpeg -y -loglevel error -f rawvideo -pix_fmt rgba -s {W}x{H} -r {FPS} -i - {ins} '
           f'-filter_complex "{fc}" -map 0:v -map "[a]" -t {total} -c:v libx264 -preset medium -crf 16 -pix_fmt yuv420p '
           f'-c:a aac -b:a 192k -movflags +faststart "{out}"')
    p = subprocess.Popen(cmd, shell=True, stdin=subprocess.PIPE)
    for fr in range(int(round(total * FPS))):
        t = fr / FPS
        p.stdin.write(compose(t).tobytes())
        if fr % (FPS * 10) == 0:
            print(f"→ {t:.0f}/{total:.0f}s", flush=True)
    p.stdin.close(); p.wait()
    print(f"✓ {out} · {len(events)} sons · {len(scenes)} scènes")


if __name__ == "__main__":
    main()
