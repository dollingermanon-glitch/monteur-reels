"""Animations en plus du skill reels-studio-skr.

vocal_gpt : un vocal en cours d'enregistrement dans la DA de ChatGPT
            (carte blanche, onde sonore qui défile, chrono, bouton stop) avec la
            transcription qui s'écrit en direct, mot par mot, calée sur la voix.

Dans edit.json :
  {"type": "vocal_gpt", "at": 50, "jusqu_a": 96, "cacher_sous_titres": true}
Les mots transcrits sont ceux du montage entre "at" et "jusqu_a" (fix compris).
"""
import math, os, random
from PIL import Image, ImageDraw, ImageFont

import fx

HERE = os.path.dirname(os.path.abspath(__file__))
INTER = os.path.join(HERE, "fonts", "Inter")

INK = (13, 13, 13, 255)          # texte ChatGPT
GREY = (93, 93, 93, 255)
LIGHT = (143, 143, 143, 255)
LINE = (229, 229, 229, 255)
WHITE = (255, 255, 255, 255)


def inter(size, weight):
    f = ImageFont.truetype(INTER, size)
    try:
        f.set_variation_by_axes([min(32, max(14, size // 2)), weight])   # [taille optique, graisse]
    except Exception:
        pass
    return f


class VocalGPT(fx.Anim):
    t_in, t_out = 0.3, 0.25
    Wc, PAD, LH, NL, ROW = 980, 40, 60, 3, 100

    def build(self):
        self.words = self.s.get("_words", [])
        self.font = inter(44, 450)
        self.small = inter(34, 500)
        self.Hc = self.PAD + self.NL * self.LH + 24 + self.ROW + self.PAD - 10
        self.box = (self.Wc + 40, self.Hc + 40)
        self.t0 = self.s["_start"]

    # ── texte ──
    def _lines(self, words):
        maxw = self.Wc - 2 * self.PAD
        lines, cur = [], []
        for w in words:
            test = " ".join(x[0] for x in cur + [w])
            if cur and self.font.getlength(test) > maxw:
                lines.append(cur); cur = [w]
            else:
                cur.append(w)
        if cur:
            lines.append(cur)
        return lines

    def _speaking(self, t):
        return any(ns - 0.02 <= t <= ne + 0.05 for ns, ne, _ in self.words)

    def frame(self, lt):
        t = self.t0 + lt
        img = Image.new("RGBA", (self.Wc, self.Hc), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, self.Wc - 1, self.Hc - 1], 48, fill=WHITE, outline=LINE, width=3)

        # transcription en direct (les 3 dernières lignes)
        shown = [(txt.replace("«", "").replace("»", "").strip(), ns) for ns, ne, txt in self.words if ns <= t]
        shown = [(s, ns) for s, ns in shown if s]
        if not shown:
            d.text((self.PAD, self.PAD), "Écoute…", font=self.font, fill=LIGHT)
        lines = self._lines(shown)[-self.NL:]
        for li, ln in enumerate(lines):
            x = self.PAD
            y = self.PAD + li * self.LH
            for k, (s, ns) in enumerate(ln):
                a = max(0.0, min(1.0, (t - ns) / 0.18))
                col = INK[:3] + (int(255 * a),)
                d.text((x, y), s, font=self.font, fill=col)
                x += self.font.getlength(s + " ")
            if li == len(lines) - 1 and int(t * 2.4) % 2 == 0:   # curseur
                d.rounded_rectangle([x - 4, y + 6, x, y + 52], 2, fill=INK)

        # barre du bas : +  onde  chrono  stop
        cy = self.Hc - self.PAD + 10 - self.ROW / 2
        d.line([(self.PAD, cy - self.ROW / 2 - 12), (self.Wc - self.PAD, cy - self.ROW / 2 - 12)], fill=LINE, width=2)
        px = self.PAD + 30
        d.ellipse([px - 30, cy - 30, px + 30, cy + 30], outline=LINE, width=3)
        d.line([(px - 13, cy), (px + 13, cy)], fill=GREY, width=5)
        d.line([(px, cy - 13), (px, cy + 13)], fill=GREY, width=5)

        sx = self.Wc - self.PAD - 44
        d.ellipse([sx - 44, cy - 44, sx + 44, cy + 44], fill=INK)
        d.rounded_rectangle([sx - 14, cy - 14, sx + 14, cy + 14], 5, fill=WHITE)
        el = max(0, int(lt))
        tm = f"{el // 60}:{el % 60:02d}"
        tw = self.small.getlength(tm)
        tx = sx - 44 - 28 - tw
        d.text((tx, cy - 22), tm, font=self.small, fill=GREY)

        x0, x1 = px + 30 + 34, tx - 30
        step, bw = 15, 7
        n = int((x1 - x0) // step)
        for k in range(n):
            tb = t - (n - 1 - k) * 0.06            # la barre la plus à droite = maintenant
            if tb < self.t0:
                h = 6
            else:
                r = random.Random(int(tb * 50))
                lvl = 1.0 if self._speaking(tb) else 0.12
                h = 6 + lvl * (14 + 46 * r.random()) * (0.75 + 0.25 * math.sin(tb * 13 + k))
            bx = x0 + k * step
            d.rounded_rectangle([bx, cy - h / 2, bx + bw, cy + h / 2], 4, fill=INK)

        out = Image.new("RGBA", self.box, (0, 0, 0, 0))
        sh = Image.new("RGBA", self.box, (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle([20, 28, 20 + self.Wc, 28 + self.Hc], 48, fill=(60, 40, 20, 70))
        from PIL import ImageFilter
        out.alpha_composite(sh.filter(ImageFilter.GaussianBlur(14)))
        out.alpha_composite(img, (20, 20))
        return out

    def draw(self, canvas, lt):
        self.pop(canvas, self.frame(lt), lt, rot=0, s0=0.85, back=1.4)



# ───────────────────────── aloe vera : avant / après ─────────────────────────
def _lerp(a, b, k):
    return tuple(int(x + (y - x) * k) for x, y in zip(a, b))


def _ease_back(x, s=1.9):
    x = max(0.0, min(1.0, x)) - 1
    return 1 + (s + 1) * x ** 3 + s * x ** 2


class Aloe(fx.Anim):
    """Un aloe vera flétri dans son pot ; une goutte tombe à « bascule » et il se redresse, tout vert.

    {"type": "aloe", "at": 184, "bascule": 195, "jusqu_a": 206}
    """
    t_in, t_out = 0.3, 0.25
    S = 460                                  # taille de la vignette
    LEAVES = [(-64, .78), (64, .8), (-47, .9), (47, .92), (-29, 1.0), (30, .98), (-12, 1.0), (13, 1.0), (0, .9)]
    SICK, SICK_TIP = (178, 146, 84), (122, 91, 56)
    OK, OK_HI = (104, 160, 98), (160, 204, 140)

    def build(self):
        self.box = (self.S + 40, self.S + 40)
        self.tb = self.s.get("_bascule", self.s["_start"] + self.s["_dur"] / 2) - self.s["_start"]
        b = self.b
        self.pills = {k: fx.card(fx.text_sprite(k, b.font("section", 40), b.fram, pad=2), b.rose, radius=30,
                                 pad=(30, 8), border=(b.blanc, 4), shadow=b.shadow) for k in ("Avant", "Après")}

    def _leaf(self, d, base, ang, ln, droop, wid, col, hi, sway, z):
        pts, n = [], 22
        x, y = base
        a0 = math.radians(ang + sway)
        sg = 1 if ang >= 0 else -1
        if ang == 0:
            sg = 1 if droop > 0 else 0
        step = ln / n
        cl = []
        for i in range(n + 1):
            u = i / n
            a = a0 + sg * math.radians(118) * droop * u ** 1.4
            cl.append((x, y, a, u))
            x += math.sin(a) * step; y -= math.cos(a) * step
        L, R = [], []
        for x, y, a, u in cl:
            w = wid * (1 - u) ** 0.85 + 1
            nx, ny = math.cos(a), math.sin(a)
            L.append((x - nx * w / 2, y - ny * w / 2)); R.append((x + nx * w / 2, y + ny * w / 2))
        d.polygon([(px * z, py * z) for px, py in L + R[::-1]], fill=col)
        mid = [(px * z, py * z) for px, py, _, u in cl if u < .85]
        d.line(mid, fill=hi, width=int(3 * z))
        # petites dents sur le bord
        for i in range(3, n - 2, 3):
            px, py = R[i] if i % 2 else L[i]
            d.ellipse([(px - 3) * z, (py - 3) * z, (px + 3) * z, (py + 3) * z], fill=hi)

    def frame(self, lt):
        b, S, z = self.b, self.S, 2
        img = Image.new("RGBA", (S * z, S * z), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse([10 * z, 10 * z, (S - 10) * z, (S - 10) * z], fill=b.creme, outline=b.doux, width=6 * z)

        tr = lt - self.tb                                # temps depuis la bascule
        h = 0.0 if tr < 0.05 else _ease_back((tr - 0.05) / 0.9)
        hc = max(0.0, min(1.0, h))
        cx, base_y = S / 2, S * 0.72
        # feuilles
        for k, (ang, lf) in enumerate(self.LEAVES):
            sway = math.sin(lt * (2.2 if h < .5 else 1.6) + k) * (1.5 + 2.5 * hc)
            droop = (0.95 if abs(ang) > 20 else 0.6) * (1 - hc)
            a = ang * (0.85 + 0.15 * h) * (1.25 - 0.25 * hc)
            ln = 235 * lf * (0.82 + 0.18 * h)
            wid = 58 * (0.75 + 0.25 * h)
            col = _lerp(self.SICK, self.OK, hc) + (255,)
            hi = _lerp(self.SICK_TIP, self.OK_HI, hc) + (255,)
            self._leaf(d, (cx + ang * 0.35, base_y), a, ln, droop, wid, col, hi, sway, z)
        # pot
        pc, rim, soil = (214, 160, 108, 255), (192, 138, 88, 255), (122, 91, 56, 255)
        top, bot = base_y - 8, S - 52
        d.polygon([((cx - 120) * z, top * z), ((cx + 120) * z, top * z), ((cx + 90) * z, bot * z), ((cx - 90) * z, bot * z)], fill=pc)
        d.rounded_rectangle([(cx - 135) * z, (top - 26) * z, (cx + 135) * z, (top + 14) * z], 14 * z, fill=rim)
        d.ellipse([(cx - 112) * z, (top - 20) * z, (cx + 112) * z, (top + 4) * z], fill=soil)
        # goutte d'eau qui tombe juste avant la bascule
        if -0.55 < tr < 0.05:
            k = (tr + 0.55) / 0.6
            gy = 40 + (top - 50) * k * k
            d.ellipse([(cx - 13) * z, (gy - 4) * z, (cx + 13) * z, (gy + 24) * z], fill=(150, 205, 235, 255))
            d.polygon([((cx - 11) * z, (gy + 4) * z), ((cx + 11) * z, (gy + 4) * z), (cx * z, (gy - 22) * z)], fill=(150, 205, 235, 255))
        if 0 <= tr < 0.6:
            r = 20 + 120 * tr
            d.ellipse([(cx - r) * z, (top - 10 - r * .25) * z, (cx + r) * z, (top - 10 + r * .25) * z],
                      outline=(150, 205, 235, int(255 * (1 - tr / .6))), width=4 * z)
        img = img.resize((S, S), Image.LANCZOS)

        out = Image.new("RGBA", self.box, (0, 0, 0, 0))
        out.alpha_composite(img, (20, 20))
        pill = self.pills["Après" if tr >= 0.15 else "Avant"]
        out.alpha_composite(pill, ((self.box[0] - pill.width) // 2, 4))
        return out

    def draw(self, canvas, lt):
        self.pop(canvas, self.frame(lt), lt, rot=0, s0=0.8, back=1.6)
        self.sparkles(canvas, lt, 170, n=7, seed=3, t0=self.tb + 0.2, life=1.2)


TYPES = {"vocal_gpt": VocalGPT, "aloe": Aloe}
