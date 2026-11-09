#!/usr/bin/env python3
"""Reel « zones » — format « tes yeux vont ici / et non pas ici ».

Mécanique reprise de la référence « exemple broke » (zones qui montrent où va / ne va pas
chaque élément, étiquettes, mot qui pop, cadre « zone interdite »), mais 100 % à la charte SKR :
sous-titres Poppins Bold blanc qui s'écrivent en direct (sans mot surligné), titres Fredoka
capitales jaune délavé, texte secondaire manuscrit blanc (Sriracha), pastilles jaune soutenu
au texte caramel, zones « non » crème hachurées caramel. Pas de noir, pas de rose, pas d'emoji.

Usage : python3 reel_zones.py <workdir> [--photos]
Lit  <workdir>/norm.mp4, transcript.json, zones.json
Écrit <workdir>/export_zones/reel_final_HD.mp4 (ou photos.jpg)
"""
import json, math, os, re, subprocess, sys
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
SFX = os.path.join(HERE, "sfx")
SKILL_FONTS = "/root/.claude/skills/synced/a912f5e8-72e4-453c-95d0-156ee1c40b84_0b225c18-fd08-473a-800f-f09213d96fdf/reels-studio-skr/fonts"
W, H, FPS = 1080, 1920, 30

WHITE = (255, 255, 255, 255)
TITRE = (252, 238, 201, 255)       # jaune délavé
ACCENT = (242, 210, 127, 255)      # jaune soutenu
CREME = (255, 250, 240, 255)
CARAMEL = (122, 91, 56, 255)
OUI = (242, 210, 127)              # zone « ici » : jaune soutenu
NON = (255, 250, 240)              # zone « pas ici » : crème hachurée caramel
SHADOW = (70, 45, 25)


@lru_cache(maxsize=None)
def font(name, size):
    return ImageFont.truetype(os.path.join(SKILL_FONTS, name), int(size))


def ease_out(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def ease_back(x, k=1.7):
    x = max(0.0, min(1.0, x)) - 1
    return 1 + (k + 1) * x ** 3 + k * x ** 2


def shadowed(layer, blur=8, off=(0, 4), alpha=150):
    pad = blur * 3
    big = Image.new("RGBA", (layer.width + 2 * pad, layer.height + 2 * pad), (0, 0, 0, 0))
    a = layer.getchannel("A").point(lambda v: v * alpha // 255)
    sh = Image.new("RGBA", layer.size, SHADOW + (255,)); sh.putalpha(a)
    big.paste(sh, (pad + off[0], pad + off[1]), sh)
    big = big.filter(ImageFilter.GaussianBlur(blur))
    big.alpha_composite(layer, (pad, pad))
    return big


def put(c, spr, cx, cy, scale=1.0, alpha=1.0):
    if scale <= 0.01 or alpha <= 0.01:
        return
    if abs(scale - 1) > 0.005:
        spr = spr.resize((max(1, int(spr.width * scale)), max(1, int(spr.height * scale))), Image.BICUBIC)
    if alpha < 0.999:
        spr = spr.copy(); spr.putalpha(spr.getchannel("A").point(lambda v: int(v * alpha)))
    c.alpha_composite(spr, (int(cx - spr.width / 2), int(cy - spr.height / 2)))


# ───────────────────── icônes ─────────────────────
@lru_cache(maxsize=None)
def badge(ok, size=86):
    s = 4
    img = Image.new("RGBA", (size * s, size * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((0, 0, size * s - 1, size * s - 1), fill=ACCENT if ok else CREME)
    col = CARAMEL
    lw = int(size * s * 0.11)
    if ok:
        pts = [(0.27, 0.53), (0.44, 0.69), (0.74, 0.34)]
        d.line([(x * size * s, y * size * s) for x, y in pts], fill=col, width=lw, joint="curve")
    else:
        for a, b in (((0.31, 0.31), (0.69, 0.69)), ((0.69, 0.31), (0.31, 0.69))):
            d.line([(a[0] * size * s, a[1] * size * s), (b[0] * size * s, b[1] * size * s)], fill=col, width=lw)
    return shadowed(img.resize((size, size), Image.LANCZOS), 6, (0, 3), 110)


@lru_cache(maxsize=None)
def label_spr(text, size=58, color=TITRE):
    f = font("Fredoka-Bold.ttf", size)
    bb = f.getbbox(text)
    img = Image.new("RGBA", (bb[2] + 20, bb[3] + 20), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((10 - bb[0], 10), text, font=f, fill=color)
    return shadowed(img, 11, (0, 4), 170)


@lru_cache(maxsize=None)
def hand_spr(text, size=56, color=WHITE):
    f = font("Sriracha-Regular.ttf", size)
    bb = f.getbbox(text)
    img = Image.new("RGBA", (bb[2] + 30, bb[3] + 30), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((15 - bb[0], 12), text, font=f, fill=color)
    return shadowed(img, 10, (0, 3), 200)


@lru_cache(maxsize=None)
def ig_tile(size=170):
    """Logo Instagram monochrome à la charte : tuile jaune soutenu, appareil caramel."""
    k = 4; S = size * k
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, S - 1, S - 1), int(S * 0.24), fill=ACCENT)
    lw = int(S * 0.075)
    d.rounded_rectangle((S * .2, S * .2, S * .8, S * .8), int(S * .17), outline=CARAMEL, width=lw)
    d.ellipse((S * .355, S * .355, S * .645, S * .645), outline=CARAMEL, width=lw)
    d.ellipse((S * .64, S * .29, S * .72, S * .37), fill=CARAMEL)
    return shadowed(img.resize((size, size), Image.LANCZOS), 12, (0, 6), 110)


@lru_cache(maxsize=None)
def pill_spr(text, size=60, bg=ACCENT, fg=CARAMEL):
    f = font("Fredoka-Bold.ttf", size)
    bb = f.getbbox(text)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    pw, ph = tw + 2 * int(size * 0.7), th + 2 * int(size * 0.45)
    img = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, pw - 1, ph - 1), ph // 2, fill=bg)
    d.text(((pw - tw) / 2 - bb[0], (ph - th) / 2 - bb[1]), text, font=f, fill=fg)
    return shadowed(img, 10, (0, 5), 120)


# ───────────────────── éléments ─────────────────────
class Zone:
    """Rectangle / bande / rond / cadre translucide qui montre l'endroit."""

    def __init__(self, s):
        self.s = s
        self.ok = s.get("ok", True)
        self.t0, self.t1 = s["t0"], s["t1"]

    def draw(self, c, t):
        s = self.s
        a_in = ease_out((t - self.t0) / 0.18)
        a_out = min(1, max(0, (self.t1 - t) / 0.15))
        a = a_in * a_out
        if a <= 0:
            return
        col = OUI if self.ok else NON
        alpha = int(s.get("alpha", 0.72 if self.ok else 0.6) * 255 * a)
        x0, y0, x1, y1 = [v * (W if k % 2 == 0 else H) for k, v in enumerate(s["box"])]
        lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(lay)
        shape = s.get("forme", "rect")
        # légère entrée : le bloc s'étire depuis son centre
        k = 0.82 + 0.18 * ease_back((t - self.t0) / 0.22)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        hw, hh = (x1 - x0) / 2 * k, (y1 - y0) / 2 * k
        if shape == "rond":
            d.ellipse((cx - hw, cy - hh, cx + hw, cy + hh), fill=col + (alpha,))
        elif shape == "cadre":
            ep = s.get("epaisseur", 70)
            d.rectangle((0, 0, W, H), fill=col + (alpha,))
            d.rounded_rectangle((x0 + ep, y0 + ep, x1 - ep, y1 - ep * 3.2), 28, fill=(0, 0, 0, 0))
        else:
            d.rounded_rectangle((cx - hw, cy - hh, cx + hw, cy + hh), s.get("rayon", 22), fill=col + (alpha,))
        if not self.ok:
            # hachures caramel douces, limitées à la forme
            mask = lay.getchannel("A").point(lambda v: 255 if v > 0 else 0)
            hat = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            hd = ImageDraw.Draw(hat)
            for x in range(-H, W, 46):
                hd.line([(x, H), (x + H, 0)], fill=CARAMEL[:3] + (int(120 * a),), width=9)
            lay.alpha_composite(Image.composite(hat, Image.new("RGBA", (W, H), (0, 0, 0, 0)), mask))
        c.alpha_composite(lay)
        # pastille check / croix
        if s.get("icone", True):
            bx, by = s.get("icone_pos", (x1 - 10, y0 + 10) if shape != "cadre" else (W / 2, H * 0.935))
            bx = bx * W if bx <= 1 else bx
            by = by * H if by <= 1 else by
            put(c, badge(self.ok), bx, by, ease_back((t - self.t0 - 0.06) / 0.25), a_out)
        if s.get("label"):
            lx, ly = s.get("label_pos", ((x0 + x1) / 2 / W, (y1 + 50) / H))
            put(c, label_spr(s["label"], s.get("label_taille", 58)), lx * W, ly * H,
                0.9 + 0.1 * ease_out((t - self.t0) / 0.2), a)


class Pop:
    """Gros mot qui pop (comme le « Ai » de la référence)."""

    def __init__(self, s):
        self.s, self.t0, self.t1 = s, s["t0"], s["t1"]

    def draw(self, c, t):
        s = self.s
        a_out = min(1, max(0, (self.t1 - t) / 0.15))
        sc = ease_back((t - self.t0) / 0.28, 2.2)
        if s.get("pastille"):
            spr = pill_spr(s["text"], s.get("taille", 60))
        else:
            spr = label_spr(s["text"], s.get("taille", 150), TITRE)
        put(c, spr, s["x"] * W, s["y"] * H, sc, a_out)


class CTA(Pop):
    def draw(self, c, t):
        s = self.s
        a_out = min(1, max(0, (self.t1 - t) / 0.15))
        sc = ease_back((t - self.t0) / 0.3, 2.0)
        # petit « clic » : la pastille s'enfonce puis passe en « Abonnée »
        clic = s["t0"] + s.get("clic", 0.9)
        txt = s["text"] if t < clic else s.get("apres", s["text"])
        if clic - 0.08 <= t < clic + 0.08:
            sc *= 0.92
        bg = ACCENT if t < clic else CREME
        put(c, pill_spr(txt, s.get("taille", 64), bg, CARAMEL), s["x"] * W, s["y"] * H, sc, a_out)


class Titre(Pop):
    """Accroche : capitales arrondies jaune délavé + ligne manuscrite blanche."""

    def __init__(self, s):
        super().__init__(s)
        f = font("Fredoka-Bold.ttf", s.get("taille", 104))
        words, lines, cur = s["text"].upper().split(), [], ""
        for w in words:
            if cur and f.getlength(cur + " " + w) > 960:
                lines.append(cur); cur = w
            else:
                cur = (cur + " " + w).strip()
        lines.append(cur)
        self.lines = [label_spr(l, s.get("taille", 104)) for l in lines]
        self.sub = hand_spr(s["sub"], s.get("taille_sub", 60)) if s.get("sub") else None

    def draw(self, c, t):
        s = self.s
        a_out = min(1, max(0, (self.t1 - t) / 0.2))
        y = s["y"] * H
        for k, spr in enumerate(self.lines):
            x = (t - self.t0 - 0.12 * k) / 0.3
            if x > 0:
                put(c, spr, W / 2, y + spr.height / 2, 1.25 - 0.25 * ease_out(x), min(1, x * 1.6) * a_out)
            y += spr.height - 34
        if self.sub:
            x = (t - self.t0 - 0.12 * len(self.lines) - 0.1) / 0.35
            if x > 0:
                put(c, self.sub, W / 2, y + self.sub.height / 2 + 4, 1, ease_out(x) * a_out)


class LogoIG(Pop):
    def draw(self, c, t):
        s = self.s
        a_out = min(1, max(0, (self.t1 - t) / 0.15))
        sc = ease_back((t - self.t0) / 0.3, 2.0)
        put(c, ig_tile(s.get("taille", 170)), s["x"] * W, s["y"] * H, sc, a_out)
        if s.get("label"):
            x = (t - self.t0 - 0.15) / 0.3
            put(c, hand_spr(s["label"], 52), s["x"] * W, s["y"] * H + s.get("taille", 170) * 0.5 + 40,
                1, ease_out(x) * a_out)


TYPES = {"zone": Zone, "pop": Pop, "cta": CTA, "titre": Titre, "logo_ig": LogoIG}


# ───────────────────── sous-titres : charte SKR, le texte s'écrit en direct ─────────────────────
class Captions:
    def __init__(self, words, y, size=62, max_mots=3, max_car=20, fixes=None):
        self.y, self.size = y, size
        fixes = fixes or {}
        ws = []
        for w in words:
            txt = fixes.get(str(w["i"]), w["text"])
            if txt:
                ws.append(dict(w, text=txt))
        chunks, cur = [], []
        for w in ws:
            cand = " ".join(x["text"] for x in cur + [w])
            if cur and (w["text"].lower().strip(",.") in ("et", "mais", "ou") or len(cur) >= max_mots
                        or len(cand) > max_car or w["start"] - cur[-1]["end"] > 0.6):
                chunks.append(cur); cur = []
            cur.append(w)
            if re.search(r"[.!?,]$", w["text"]):
                chunks.append(cur); cur = []
        if cur:
            chunks.append(cur)
        self.chunks = []
        f = font("Poppins-Bold.ttf", size)
        for k, ch in enumerate(chunks):
            text = " ".join(w["text"] for w in ch)
            text = text[0].upper() + text[1:] if k == 0 or re.search(r"[.!?]$", chunks[k - 1][-1]["text"]) else text
            nxt = chunks[k + 1][0]["start"] if k + 1 < len(chunks) else ch[-1]["end"] + 1.0
            self.chunks.append({"words": ch, "text": text, "w": f.getlength(text),
                                "t0": ch[0]["start"] - 0.04, "t1": min(nxt - 0.02, ch[-1]["end"] + 0.9)})

    @lru_cache(maxsize=1024)
    def sprite(self, k, n):
        ch = self.chunks[k]
        f = font("Poppins-Bold.ttf", self.size)
        bw = int(ch["w"]) + 40
        img = Image.new("RGBA", (bw, int(self.size * 1.5)), (0, 0, 0, 0))
        ImageDraw.Draw(img).text((20, 8), ch["text"][:n], font=f, fill=WHITE)
        return shadowed(img, 9, (0, 4), 150)

    def draw(self, c, t, y=None):
        for k, ch in enumerate(self.chunks):
            if ch["t0"] <= t < ch["t1"]:
                n, pos = 0, 0
                for w in ch["words"]:
                    L = len(w["text"]) + 1
                    if t >= w["end"]:
                        n = pos + L
                    elif t >= w["start"] - 0.04:
                        n = pos + max(1, int(L * (t - w["start"] + 0.04) / max(0.08, w["end"] - w["start"])))
                    pos += L
                spr = self.sprite(k, min(n, len(ch["text"])))
                put(c, spr, W / 2, (y or self.y) * H)
                return


# ───────────────────── montage ─────────────────────
def sh(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True)
    if r.returncode:
        sys.exit(r.stderr.decode()[-2000:])


def main():
    wd = sys.argv[1]
    cfg = json.load(open(os.path.join(wd, "zones.json")))
    tr = json.load(open(os.path.join(wd, "transcript.json")))
    norm = os.path.join(wd, "norm.mp4")
    segs = cfg["plans"]                      # [[début, fin, zoom], …] en secondes source
    offs, acc = [], 0.0
    for a, b, *_ in segs:
        nf = int(round((b - a) * FPS))
        offs.append((a, b, acc)); acc += nf / FPS
    total = acc

    def M(x):
        """temps source → temps du montage"""
        for a, b, o in offs:
            if x < a:
                return o
            if x <= b:
                return o + x - a
        return total

    # éléments + sous-titres en temps montage
    els = []
    for s in cfg["elements"]:
        s = dict(s); s["t0"], s["t1"] = M(s["t0"]), M(s["t1"])
        els.append(TYPES[s["type"]](s))
    words = []
    for w in tr["words"]:
        if any(a - 0.05 <= w["start"] <= b for a, b, *_ in segs) and not w.get("filler"):
            words.append(dict(w, start=M(w["start"]), end=M(min(w["end"], [b for a, b, *_ in segs if a - 0.05 <= w["start"] <= b][0]))))
    caps = Captions(words, cfg.get("sous_titres_y", 0.6), fixes=cfg.get("fix", {}))
    caps_y = cfg.get("sous_titres_y_pendant", [])   # [[t0, t1, y]] source

    def compose(t):
        full = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        for e in els:
            if e.t0 <= t < e.t1 and isinstance(e, Zone):
                e.draw(full, t)
        y = None
        for a, b, yy in caps_y:
            if M(a) <= t < M(b):
                y = yy
        hide = any(M(a) <= t < M(b) for a, b in cfg.get("cacher_sous_titres", []))
        if not hide:
            caps.draw(full, t, y)
        for e in els:
            if e.t0 <= t < e.t1 and not isinstance(e, Zone):
                e.draw(full, t)
        return full

    out = os.path.join(wd, "export_zones"); os.makedirs(out, exist_ok=True)
    cut = os.path.join(wd, "montage_zones.mp4")
    if not os.path.exists(cut) or "--recut" in sys.argv:
        fy = 0.3
        ins, fc = [], []
        for k, (a, b, *z) in enumerate(segs):
            z = z[0] if z else 1.0
            nf = int(round((b - a) * FPS)); d = nf / FPS
            cw, ch = int(W / z) // 2 * 2, int(H / z) // 2 * 2
            ins.append(f'-ss {a:.3f} -t {d + 0.2:.3f} -i "{norm}"')
            fc.append(f"[{k}:v]trim=end_frame={nf},setpts=PTS-STARTPTS,crop={cw}:{ch}:{(W - cw) // 2}:{int((H - ch) * fy)},"
                      f"scale={W}:{H}:flags=lanczos,setsar=1,fps={FPS}[v{k}];"
                      f"[{k}:a]atrim=end={d:.4f},asetpts=PTS-STARTPTS,afade=t=in:d=0.01,"
                      f"afade=t=out:st={max(0, d - 0.02):.4f}:d=0.02,apad=whole_dur={d:.4f}[a{k}];")
        f = "".join(fc) + "".join(f"[v{k}][a{k}]" for k in range(len(segs))) + f"concat=n={len(segs)}:v=1:a=1[v][a]"
        sh(f'ffmpeg -y -loglevel error {" ".join(ins)} -filter_complex "{f}" -map "[v]" -map "[a]" '
           f'-c:v libx264 -preset veryfast -crf 12 -c:a aac -b:a 256k -ar 48000 "{cut}"')
        print(f"→ montage coupé : {total:.1f}s, {len(segs)} plans", flush=True)

    if "--photos" in sys.argv:
        marks = cfg.get("photos") or [e.t0 + 0.4 for e in els]
        tiles = []
        for t in marks:
            t = M(t) if cfg.get("photos") else t
            p = os.path.join(wd, "_f.png")
            sh(f'ffmpeg -y -loglevel error -ss {t:.3f} -i "{cut}" -frames:v 1 "{p}"')
            bg = Image.open(p).convert("RGBA"); bg.alpha_composite(compose(t))
            tiles.append(bg.convert("RGB").resize((270, 480)))
        cols = 6
        sheet = Image.new("RGB", (270 * cols, 480 * ((len(tiles) + cols - 1) // cols)), "white")
        for i, tl in enumerate(tiles):
            sheet.paste(tl, ((i % cols) * 270, (i // cols) * 480))
        sheet.save(os.path.join(out, "photos.jpg"), quality=88)
        print("✓ photos", len(tiles)); return

    # sons
    events = []
    for e in els:
        if isinstance(e, Zone):
            events.append((e.t0, "pop", 0.35))
        elif isinstance(e, CTA):
            events += [(e.t0, "pop", 0.4), (e.t0 + e.s.get("clic", 0.9), "click1", 0.6)]
        else:
            events.append((e.t0 - 0.05, "woosh", 0.35))
    events = [x for x in events if 0 <= x[0] < total]
    sfx_in = " ".join(f'-i "{os.path.join(SFX, n + ".mp3")}"' for _, n, _ in events)
    mix = ["[0:a]volume=1.0[a0]"]
    for k, (t, n, v) in enumerate(events):
        ms = int(t * 1000)
        mix.append(f"[{k + 2}:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={v},adelay={ms}|{ms}[s{k}]")
    fc = "[0:v][1:v]overlay=0:0:format=auto,format=yuv420p[v];" + ";".join(mix) + ";[a0]" + \
         "".join(f"[s{k}]" for k in range(len(events))) + \
         f"amix=inputs={len(events) + 1}:normalize=0:duration=first,alimiter=limit=0.95[a]"
    final = os.path.join(out, "reel_final_HD.mp4")
    cmd = (f'ffmpeg -y -loglevel error -i "{cut}" -f rawvideo -pix_fmt rgba -s {W}x{H} -r {FPS} -i - {sfx_in} '
           f'-filter_complex "{fc}" -map "[v]" -map "[a]" -c:v libx264 -preset slow -crf 16 -profile:v high '
           f'-c:a aac -b:a 256k -movflags +faststart "{final}"')
    p = subprocess.Popen(cmd, shell=True, stdin=subprocess.PIPE)
    for fr in range(int(round(total * FPS))):
        p.stdin.write(compose(fr / FPS).tobytes())
    p.stdin.close(); p.wait()
    print(f"✓ {final} · {total:.1f}s · {len(els)} éléments · {len(events)} sons")


if __name__ == "__main__":
    main()
