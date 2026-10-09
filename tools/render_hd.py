#!/usr/bin/env python3
"""Étapes 2 à 5 — Montage, sous-titres, animations, export CapCut.

Usage : python3 render.py <workdir> [--rapide]

Lit  <workdir>/transcript.json  (étape 1)
     <workdir>/edit.json        (le plan de montage écrit par Claude — voir SKILL.md)
Écrit <workdir>/export/ :
     reel_final.mp4                 tout incrusté, prêt à poster
     montage_sans_texte.mp4         rythme coupé, sans texte
     capcut/1_clips/clip_001.mp4…   les plans coupés, à glisser dans l'ordre
     capcut/2_animations/*.mov      chaque animation (fond transparent), nom = timecode
     capcut/3_sous-titres.srt       sous-titres éditables (import CapCut)
     capcut/4_sous-titres_style.mov sous-titres animés à ta charte (fond transparent)
     capcut/GUIDE.txt               où placer chaque élément
     Reel_CapCut.zip                tout le dossier capcut/ zippé
     apercu.jpg                     planche de vignettes pour contrôle
"""
import json, os, re, shutil, subprocess, sys
from PIL import Image
sys.path.insert(0, '/root/.claude/skills/synced/a912f5e8-72e4-453c-95d0-156ee1c40b84_0b225c18-fd08-473a-800f-f09213d96fdf/reels-studio-skr/scripts')
import fx
import face

W, H, FPS = fx.W, fx.H, 30
WORKDIR = '.'
RYTHME = {  # marge gardée avant / après chaque mot (s)
    "max": (0.03, 0.05), "soutenu": (0.05, 0.08), "naturel": (0.09, 0.16), "lent": (0.15, 0.75)}


def sh(cmd, inp=None):
    r = subprocess.run(cmd, shell=True, capture_output=True)
    if r.returncode:
        sys.exit(f"Erreur ffmpeg :\n{r.stderr.decode()[-2500:]}")


def tc(t):
    return f"{int(t // 60):02d}m{t % 60:05.2f}s"


def srt_tc(t):
    ms = int(round(t * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


# ───────────────────── plan de coupe ─────────────────────
def plan(tr, ed):
    words = [dict(w) for w in tr["words"]]
    for k, v in ed.get("fix", {}).items():
        words[int(k)]["text"] = v
    # mots non reconnus par la transcription : on garde l'audio du trou et on ajoute le texte
    for k, v in ed.get("ajouts", {}).items():
        k = int(k)
        words[k]["text"] = (words[k]["text"] + " " + v).strip()
        if k + 1 < len(words):
            words[k]["end"] = words[k + 1]["start"]
    dropped = set()
    for a, b in ed.get("drop", []):
        dropped.update(range(a, b + 1))
    if not ed.get("garder_euh", False):
        dropped.update(w["i"] for w in words if w["filler"])
    for i in ed.get("restore", []):
        dropped.discard(i)
    keys = set(ed.get("highlight", []))
    pb, pa = RYTHME.get(ed.get("rythme", "max"), RYTHME["max"])
    kept = [w for w in words if w["i"] not in dropped]
    for w in kept:
        w["key"] = w["i"] in keys

    # intervalles gardés : chaque mot + marges, sans jamais mordre sur un mot supprimé
    ivs = []
    for w in kept:
        lo, hi = w["start"] - pb, w["end"] + pa
        if w["i"] > 0 and words[w["i"] - 1]["i"] in dropped:
            lo = max(lo, (words[w["i"] - 1]["end"] + w["start"]) / 2)
        if w["i"] + 1 < len(words) and words[w["i"] + 1]["i"] in dropped:
            hi = min(hi, (words[w["i"] + 1]["start"] + w["end"]) / 2)
        ivs.append([max(0, lo), min(tr["duration"], hi), w])
    segs = []
    for lo, hi, w in ivs:
        if segs and lo <= segs[-1]["e"] + 0.02 and w["i"] - segs[-1]["last"] == 1 or \
                segs and lo <= segs[-1]["e"]:
            segs[-1]["e"] = max(segs[-1]["e"], hi); segs[-1]["last"] = w["i"]; segs[-1]["words"].append(w)
        else:
            segs.append({"s": lo, "e": hi, "last": w["i"], "words": [w]})
    # calage sur les images (évite tout décalage son/image)
    for s in segs:
        s["s"] = round(s["s"] * FPS) / FPS
        s["e"] = max(s["s"] + 2 / FPS, round(s["e"] * FPS) / FPS)
    # nouvelle timeline
    t = 0.0
    for s in segs:
        s["ns"] = t; t += s["e"] - s["s"]
    total = t

    def remap(x, seg):
        return seg["ns"] + min(max(x - seg["s"], 0), seg["e"] - seg["s"])

    by_i = {}
    for s in segs:
        for w in s["words"]:
            w["ns"], w["ne"] = remap(w["start"], s), remap(w["end"], s)
            by_i[w["i"]] = w
    return segs, kept, by_i, total


def zooms(segs, ed, brand):
    mode = ed.get("zoom", "alterne")
    punch = set(ed.get("zoom_punch", []))
    za, zp = brand.zoom["alterne"], brand.zoom["punch"]
    out = []
    for k, s in enumerate(segs):
        z = 1.0
        if mode == "alterne" and k % 2 == 1:
            z = za
        if any(w["i"] in punch for w in s["words"]):
            z = zp
        out.append(z)
    return out


# ───────────────────── sous-titres ─────────────────────
def chunk_words(kept, brand, ed):
    simple = brand.cap.get("style") == "simple"
    if simple:   # blocs de 2 lignes max, coupés de préférence en fin de phrase
        mc = brand.cap.get("caracteres_par_ligne", 28) * brand.cap.get("lignes", 2)
        mx = 99
    else:
        mx, mc = ed.get("max_mots", brand.cap["max_mots"]), brand.cap["max_caracteres"]
    emo = {int(k): v for k, v in ed.get("emojis", {}).items()} if fx.EMOJIS_ON else {}
    chunks, cur = [], []
    for w in [w for w in kept if w["text"].strip()]:
        text = w["text"]
        n = len(" ".join(x["text"] for x in cur + [w]))
        if cur and (len(cur) >= mx or n > mc or w["ns"] - cur[-1]["ne"] > 0.45):
            chunks.append(cur); cur = []
        cur.append(w)
        if re.search(r"[.!?]$", text) or (re.search(r"[,;:]$", text) and (not simple or n > mc * 0.55)):
            chunks.append(cur); cur = []
    if cur:
        chunks.append(cur)
    out = []
    for c in chunks:
        ws = [{"text": re.sub(r"[.,;:]$", "", w["text"]) + (" " + emo[w["i"]] if w["i"] in emo else ""),
               "start": w["ns"], "end": w["ne"], "key": w["key"]} for w in c]
        out.append({"words": ws, "start": c[0]["ns"], "end": c[-1]["ne"] + 0.25, "i0": c[0]["i"]})
    for a, b in zip(out, out[1:]):
        a["end"] = min(a["end"], b["start"]) if b["start"] - a["end"] < 0.3 else a["end"]
        a["end"] = min(a["end"], b["start"])
    hide = ed.get("cacher_sous_titres", [])
    return [c for c in out if not any(a <= c["i0"] <= b for a, b in hide)]


# ───────────────────── animations ─────────────────────
def build_anims(ed, by_i, total, brand, layout):
    def at(x, default=0.0):
        if x is None:
            return default
        if isinstance(x, (int,)) and x in by_i:
            return by_i[x]["ns"]
        if isinstance(x, int):  # mot supprimé → mot gardé suivant
            nxt = [w for i, w in sorted(by_i.items()) if i >= x]
            return nxt[0]["ns"] if nxt else total
        return float(str(x).rstrip("s"))
    anims = []
    for k, spec in enumerate(ed.get("animations", [])):
        spec = dict(spec)
        spec["_start"] = at(spec.get("at"))
        if "jusqu_a" in spec:
            j = spec["jusqu_a"]
            spec["_dur"] = (by_i[j]["ne"] if j in by_i else at(j)) - spec["_start"] + 0.15
        else:
            spec["_dur"] = float(spec.get("dur", 1.6))
        spec["_dur"] = max(0.6, min(spec["_dur"], total - spec["_start"]))
        for it in spec.get("items", []):
            it["_t"] = at(it.get("at"), spec["_start"] + 0.3)
        for fo in spec.get("focus", []):
            fo["_t"] = at(fo.get("at"), spec["_start"] + 0.5)
        if spec.get("image"):
            spec["_path"] = spec["image"] if os.path.isabs(spec["image"]) else os.path.join(WORKDIR, spec["image"])
        if spec["type"] == "emoji" and not fx.EMOJIS_ON:
            continue   # emojis désactivés par la charte
        cls = fx.TYPES.get(spec["type"])
        if not cls:
            print(f"⚠ type d'animation inconnu : {spec['type']} (ignoré)")
            continue
        a = cls(spec, brand, layout)
        a.idx = k + 1
        anims.append(a)
    return anims


# ───────────────────── rendu ─────────────────────
LIMITE_MO = 28          # le chat refuse les fichiers > 30 Mo : chaque livrable reste dessous
VERT = (0, 255, 0, 255)  # fond vert pour l'incrustation CapCut


def budget_kbps(total, mo=LIMITE_MO, audio=160):
    return int(max(1200, min(8000, mo * 8000 / max(total, 1) - audio)))


def open_pipe(out, mode, size=(W, H), kbps=None):
    if mode == "prores":   # transparence réelle (CapCut ordi, Premiere, Final Cut)
        enc = "-c:v prores_ks -profile:v 4444 -pix_fmt yuva444p10le -vendor apl0 -qscale:v 11"
    else:                  # fond vert, léger, lisible partout (CapCut mobile compris)
        rate = f"-maxrate {kbps}k -bufsize {2 * kbps}k" if kbps else ""
        enc = f"-c:v libx264 -preset veryfast -crf 20 {rate} -pix_fmt yuv420p"
    return subprocess.Popen(
        f'ffmpeg -y -loglevel error -f rawvideo -pix_fmt rgba -s {size[0]}x{size[1]} -r {FPS} -i - {enc} "{out}"',
        shell=True, stdin=subprocess.PIPE)


def pack(files, base, outdir):
    """Range les fichiers dans des zips de moins de LIMITE_MO (découpe en parties si besoin)."""
    groups, cur, size = [], [], 0
    for f in files:
        s = os.path.getsize(f)
        if cur and size + s > LIMITE_MO * 1e6:
            groups.append(cur); cur, size = [], 0
        cur.append(f); size += s
    if cur:
        groups.append(cur)
    out = []
    import zipfile
    for k, g in enumerate(groups):
        name = f"{base}.zip" if len(groups) == 1 else f"{base}_partie{k + 1}.zip"
        p = os.path.join(outdir, name)
        with zipfile.ZipFile(p, "w", zipfile.ZIP_STORED) as z:
            for f in g:
                z.write(f, os.path.relpath(f, os.path.dirname(os.path.dirname(f))))
        out.append(p)
    return out


def photos(wd, tr, ed, brand):
    """Aperçu express (~20 s) : une image par animation, sans encoder la vidéo."""
    norm = os.path.join(wd, "norm.mp4")
    segs, kept, by_i, total = plan(tr, ed)
    zs = zooms(segs, ed, brand)
    fy = brand.zoom["centre_visage_y"]
    zone = face.zone(norm, zs, fy)
    layout = fx.Layout(brand, zone, ed.get("sous_titres_y"))
    print("Placement : " + (layout.describe() if zone else "aucun visage détecté"))
    chunks = chunk_words(kept, brand, ed)
    caps = fx.Captions(brand, chunks, layout)
    anims = build_anims(ed, by_i, total, brand, layout)
    tiles = []
    for a in anims:
        t = a.start + min(1.3, a.dur * 0.7)
        k = max(i for i, s in enumerate(segs) if s["ns"] <= t)
        s, z = segs[k], zs[k]
        src = s["s"] + (t - s["ns"])
        cw, ch = int(W / z) // 2 * 2, int(H / z) // 2 * 2
        tmp = os.path.join(wd, "_photo.png")
        sh(f'ffmpeg -y -loglevel error -ss {src:.3f} -i "{norm}" -frames:v 1 -vf '
           f'"crop={cw}:{ch}:{(W - cw) // 2}:{int((H - ch) * fy)},scale={W}:{H}" "{tmp}"')
        img = Image.open(tmp).convert("RGBA")
        caps.draw(img, t)
        a.draw(img, t - a.start)
        if zone:
            from PIL import ImageDraw
            ImageDraw.Draw(img).rectangle(zone, outline=(0, 200, 255, 255), width=6)
        tiles.append(img.convert("RGB").resize((270, 480)))
    sheet = Image.new("RGB", (270 * min(6, len(tiles)), 480 * ((len(tiles) + 5) // 6)), "black")
    for i, tl in enumerate(tiles):
        sheet.paste(tl, ((i % 6) * 270, (i // 6) * 480))
    out = os.path.join(wd, "photos.jpg")
    sheet.save(out, quality=88)
    print(f"✓ {out} (cadre bleu = zone visage protégée)")


def main():
    global WORKDIR
    wd = sys.argv[1]
    WORKDIR = wd
    quick = "--rapide" in sys.argv
    if "--photos" in sys.argv:
        return photos(wd, json.load(open(os.path.join(wd, "transcript.json"))),
                      json.load(open(os.path.join(wd, "edit.json"))), fx.Brand())
    prores = "--prores" in sys.argv
    tr = json.load(open(os.path.join(wd, "transcript.json")))
    ed = json.load(open(os.path.join(wd, "edit.json")))
    brand = fx.Brand()
    norm = os.path.join(wd, "norm.mp4")
    ex = os.path.join(wd, "export")
    cc = os.path.join(ex, "capcut")
    hq = os.path.join(wd, "plans_hq")
    for d in (ex, hq):
        shutil.rmtree(d, ignore_errors=True)
    for d in ("1_plans", "2_animations", "3_sous-titres"):
        os.makedirs(os.path.join(cc, d), exist_ok=True)
    os.makedirs(hq)

    segs, kept, by_i, total = plan(tr, ed)
    zs = zooms(segs, ed, brand)
    fy = brand.zoom["centre_visage_y"]
    kb = budget_kbps(total)
    print(f"→ {len(segs)} plans · {tr['duration']:.1f}s → {total:.1f}s", flush=True)

    # 1) plans coupés : version HD interne + version légère pour CapCut
    clips, durs = [], []
    for k, (s, z) in enumerate(zip(segs, zs)):
        nf = int(round((s["e"] - s["s"]) * FPS))
        d = nf / FPS
        durs.append(d)
        cw, ch = int(W / z) // 2 * 2, int(H / z) // 2 * 2
        vf = f"crop={cw}:{ch}:{(W - cw) // 2}:{int((H - ch) * fy)},scale={W}:{H}:flags=lanczos,setsar=1"
        fo = max(0, d - 0.012)
        af = f"afade=t=in:d=0.008,afade=t=out:st={fo:.3f}:d=0.012,atrim=end={d:.5f},apad=whole_dur={d:.5f}"
        out = os.path.join(hq, f"plan_{k + 1:03d}.mp4")
        sh(f'ffmpeg -y -loglevel error -ss {s["s"]:.4f} -i "{norm}" -vf "{vf}" -frames:v {nf} -af "{af}" -t {d:.5f} '
           f'-c:v libx264 -preset veryfast -crf 12 -r {FPS} -c:a aac -b:a 192k -ar 48000 "{out}"')
        clips.append(out)
        if not quick:
            light = os.path.join(cc, "1_plans", f"plan_{k + 1:03d}.mp4")
            vq = "-c:v copy" if prores else f"-c:v libx264 -preset veryfast -crf 21 -maxrate {kb}k -bufsize {2 * kb}k"
            sh(f'ffmpeg -y -loglevel error -i "{out}" {vq} -c:a aac -b:a 160k "{light}"')
    print("→ Plans coupés", flush=True)

    # 2) montage complet sans texte (concat ré-encodé = calage exact)
    cut = os.path.join(wd, "montage_sans_texte.mp4")
    ins = " ".join(f'-i "{c}"' for c in clips)
    fc = "".join(f"[{k}:a]atrim=end={d:.5f},apad=whole_dur={d:.5f},asetpts=PTS-STARTPTS[a{k}];"
                 for k, d in enumerate(durs))
    fc += "".join(f"[{k}:v][a{k}]" for k in range(len(clips))) + f"concat=n={len(clips)}:v=1:a=1[v][a]"
    with open(os.path.join(wd, "concat.sh"), "w") as f:
        f.write(f'ffmpeg -y -loglevel error {ins} -filter_complex "{fc}" -map "[v]" -map "[a]" '
                f'-c:v libx264 -preset veryfast -crf 12 -c:a aac -b:a 256k "{cut}"')
    sh(f'sh "{os.path.join(wd, "concat.sh")}"')
    if "--cut-only" in sys.argv:
        print(f"✓ montage {total:.1f}s, {len(segs)} plans"); return

    # 3) sous-titres + animations (version incrustée + version fond vert sans ombres)
    zone = face.zone(norm, zs, fy)
    layout = fx.Layout(brand, zone, ed.get("sous_titres_y"))
    print("→ Placement : " + (layout.describe() if zone else "aucun visage détecté, placement par défaut"), flush=True)
    chunks = chunk_words(kept, brand, ed)
    caps = fx.Captions(brand, chunks, layout)
    anims = build_anims(ed, by_i, total, brand, layout)
    fx.SHADOWS = False
    g_caps = fx.Captions(brand, chunks, layout)
    g_anims = build_anims(ed, by_i, total, brand, layout)
    fx.SHADOWS = True
    hide_during = [(a.start, a.end) for a in anims if a.s.get("cacher_sous_titres")]

    def _t(x):
        return by_i[x]["ns"] if x in by_i else min([w["ns"] for i, w in by_i.items() if i >= x] or [total])
    washes = sorted(set([_t(x) for x in ed.get("transitions", [])] +
                        [a.start for a in anims if a.s["type"] == "section"]))
    wash_img = Image.new("RGBA", (W, H))
    import numpy as _np
    yy = _np.linspace(0, 1, H)[:, None, None]
    top, bot = _np.array([255, 196, 92]), _np.array([252, 238, 201])
    col = (top * (1 - yy) + bot * yy) * _np.ones((1, W, 1))
    wash_rgb = col.astype(_np.uint8)
    WD = 0.5
    def wash(img, t):
        for w0 in washes:
            x = (t - (w0 - WD / 2)) / WD
            if 0 <= x <= 1:
                a = (1 - abs(2 * x - 1)) ** 0.8 * 0.62
                arr = _np.dstack([wash_rgb, _np.full((H, W, 1), int(a * 255), _np.uint8)])
                return Image.alpha_composite(Image.fromarray(arr, "RGBA"), img)
        return img
    nfr = int(round(total * FPS))
    final = os.path.join(ex, "reel_final.mp4")
    p_final = subprocess.Popen(
        f'ffmpeg -y -loglevel error -i "{cut}" -f rawvideo -pix_fmt rgba -s {W}x{H} -r {FPS} -i - '
        f'-filter_complex "[0:v][1:v]overlay=0:0:format=auto,format=yuv420p[v]" -map "[v]" -map 0:a '
        f'-c:v libx264 -preset slow -crf 14 -profile:v high -level 4.2 -c:a aac -b:a 256k '
        f'-movflags +faststart "{final}"', shell=True, stdin=subprocess.PIPE)
    mode = "prores" if prores else "vert"
    ext = "mov" if prores else "mp4"
    p_caps = None if quick else open_pipe(os.path.join(cc, "3_sous-titres", f"sous-titres_charte.{ext}"), mode, kbps=kb)
    p_anims = {}
    blank = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bg = blank if prores else Image.new("RGBA", (W, H), VERT)
    for fr in range(nfr):
        t = fr / FPS
        show_caps = not any(a <= t < b for a, b in hide_during)
        full = blank.copy()
        if show_caps:
            caps.draw(full, t)
        for a in anims:
            if a.start <= t < a.end:
                a.draw(full, t - a.start)
        full = wash(full, t)
        p_final.stdin.write(full.tobytes())
        if not quick:
            fx.SHADOWS = prores
            if p_caps:
                lay = bg.copy()
                if show_caps:
                    g_caps.draw(lay, t) if not prores else caps.draw(lay, t)
                p_caps.stdin.write(lay.tobytes())
            for a, ga in zip(anims, g_anims):
                if a.start <= t < a.end:
                    if a.idx not in p_anims:
                        a.file = f"anim_{a.idx:02d}_a_{tc(a.start)}_{a.s['type']}.{ext}"
                        p_anims[a.idx] = open_pipe(os.path.join(cc, "2_animations", a.file), mode)
                    lay = bg.copy()
                    (a if prores else ga).draw(lay, t - a.start)
                    p_anims[a.idx].stdin.write(lay.tobytes())
                elif a.idx in p_anims and t >= a.end:
                    p_anims.pop(a.idx).stdin.close()
            fx.SHADOWS = True
        if fr % (FPS * 10) == 0:
            print(f"→ Rendu {t:.0f}/{total:.0f}s", flush=True)
    for p in [p_final, p_caps] + list(p_anims.values()):
        if p:
            p.stdin.close(); p.wait()

    # 4) SRT éditable
    srt = os.path.join(cc, "3_sous-titres", "sous-titres_modifiables.srt")
    with open(srt, "w") as f:
        for k, c in enumerate(chunks):
            f.write(f"{k + 1}\n{srt_tc(c['start'])} --> {srt_tc(c['end'])}\n"
                    f"{' '.join(w['text'] for w in c['words'])}\n\n")

    # 5) guide
    guide = os.path.join(cc, "3_sous-titres", "GUIDE_CAPCUT.txt")
    vert = "" if prores else (
        "   Elles sont sur fond vert : sélectionne le clip > Découper/Retirer l'arrière-plan >\n"
        "   Incrustation (Chroma key) > pipette sur le vert > Intensité ~20-30. Le vert disparaît.\n")
    with open(guide, "w") as f:
        f.write("MONTAGE CAPCUT — mode d'emploi\n\n"
                "1. PLANS : importe tout 1_plans, sélectionne les plans dans l'ordre (001, 002…)\n"
                "   et ajoute-les d'un coup sur la timeline : ton rythme est reconstitué.\n"
                "2. SOUS-TITRES, au choix :\n"
                "   a) Texte > Sous-titres > importer sous-titres_modifiables.srt (modifiables dans CapCut)\n"
                f"   b) ou ajoute sous-titres_charte.{ext} en superposition à 00:00 (ta charte, animée)\n"
                "3. ANIMATIONS : ajoute chaque fichier de 2_animations en superposition,\n"
                "   au timecode indiqué ci-dessous (il est aussi dans le nom du fichier).\n" + vert + "\n")
        for a in anims:
            f.write(f"  {tc(a.start)}  →  {getattr(a, 'file', a.s['type'])}   "
                    f"({a.s.get('text', a.s.get('title', ''))})\n")
        f.write(f"\nDurée totale : {tc(total)}\n")

    # 6) planche de contrôle
    marks = [0.4] + [a.start + 0.5 for a in anims][:9] + [total - 0.6]
    marks = sorted(set(round(m, 2) for m in marks if m < total))[:12]
    sh(f'ffmpeg -y -loglevel error ' + " ".join(f'-ss {m} -i "{final}"' for m in marks) +
       ' -filter_complex "' + "".join(f"[{k}:v]trim=end_frame=1,scale=270:480[t{k}];" for k in range(len(marks))) +
       "".join(f"[t{k}]" for k in range(len(marks))) +
       f'xstack=inputs={len(marks)}:layout=' + "|".join(f"{(k % 6) * 270}_{(k // 6) * 480}" for k in range(len(marks))) +
       f':fill=black[o]" -map "[o]" -frames:v 1 "{os.path.join(ex, "apercu.jpg")}"')

    # 7) zips < 30 Mo, prêts à envoyer
    zips = []
    if not quick:
        ls = lambda d: sorted(os.path.join(cc, d, f) for f in os.listdir(os.path.join(cc, d)))
        zips += pack(ls("1_plans"), "CapCut_1_plans", ex)
        zips += pack(ls("3_sous-titres") + ls("2_animations"), "CapCut_2_textes_animations", ex)
    json.dump({"duree_avant": tr["duration"], "duree_apres": round(total, 2), "plans": len(segs),
               "animations": [{"t": round(a.start, 2), "type": a.s["type"]} for a in anims],
               "sous_titres": len(chunks),
               "a_envoyer": [final] + zips},
              open(os.path.join(ex, "resume.json"), "w"), ensure_ascii=False, indent=1)
    print(f"✓ Terminé : {tr['duration']:.1f}s → {total:.1f}s, {len(segs)} plans, {len(anims)} animations")
    for f in [final] + zips:
        print(f"   {os.path.getsize(f) / 1e6:5.1f} Mo  {f}")


if __name__ == "__main__":
    main()
