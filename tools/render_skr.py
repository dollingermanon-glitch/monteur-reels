#!/usr/bin/env python3
"""Lance le rendu du skill reels-studio-skr avec les animations de tools/skr_extra.py.

Usage : python3 tools/render_skr.py <workdir> [--photos | --rapide]  (mêmes options que render.py)
"""
import glob, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = glob.glob("/root/.claude/skills/**/reels-studio-skr/scripts", recursive=True)
if not SKILL:
    sys.exit("Skill reels-studio-skr introuvable")
sys.path.insert(0, SKILL[0])
sys.path.insert(0, HERE)

import fx, render  # noqa: E402
import skr_extra  # noqa: E402

fx.TYPES.update(skr_extra.TYPES)
_orig = render.build_anims


def build_anims(ed, by_i, total, brand, layout):
    for spec in ed.get("animations", []):
        if spec["type"] in skr_extra.TYPES:
            a, j = spec["at"], spec.get("jusqu_a", spec["at"])
            spec["_words"] = [(by_i[i]["ns"], by_i[i]["ne"], by_i[i]["text"])
                              for i in sorted(by_i) if a <= i <= j and by_i[i]["text"]]
    return _orig(ed, by_i, total, brand, layout)


render.build_anims = build_anims

if __name__ == "__main__":
    render.main()
