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


TYPES = {"vocal_gpt": VocalGPT}
