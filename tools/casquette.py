"""Dessine un emoji casquette (style sticker) aux couleurs SKR."""
import sys
from PIL import Image, ImageDraw, ImageFilter

def casquette(col=(242, 210, 127), dark=(214, 168, 80), ink=(122, 91, 56), size=420):
    S = 4; w = h = size * S
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    lw = int(9 * S)
    # visière (derrière la base, vers la droite)
    d.ellipse((w*.30, h*.58, w*.99, h*.80), fill=dark, outline=ink, width=lw)
    # dôme
    box = (w*.08, h*.22, w*.78, h*1.08)
    d.chord(box, 180, 360, fill=col, outline=ink, width=lw)
    d.line((w*.08 + lw/2, h*.65, w*.78 - lw/2, h*.65), fill=ink, width=lw)
    # bande de base
    d.rounded_rectangle((w*.09, h*.60, w*.77, h*.70), radius=int(h*.04), fill=dark, outline=ink, width=lw)
    # coutures
    d.arc((w*.30, h*.23, w*.56, h*1.05), 190, 270, fill=ink, width=int(lw*.6))
    d.arc((w*.30, h*.23, w*.56, h*1.05), 270, 350, fill=ink, width=int(lw*.6))
    d.line((w*.43, h*.235, w*.43, h*.60), fill=ink, width=int(lw*.6))
    # reflet
    d.arc((w*.16, h*.32, w*.50, h*.95), 200, 240, fill=(255, 246, 220), width=int(lw*1.2))
    # bouton
    d.ellipse((w*.39, h*.18, w*.47, h*.26), fill=dark, outline=ink, width=int(lw*.8))
    im = im.resize((size, size), Image.LANCZOS)
    # contour blanc façon sticker + ombre douce
    a = im.getchannel("A")
    halo = a.filter(ImageFilter.MaxFilter(17))
    out = Image.new("RGBA", (size + 60, size + 60), (0, 0, 0, 0))
    sh = Image.new("RGBA", out.size, (70, 45, 20, 0))
    sh.putalpha(Image.new("L", out.size, 0)); sh.paste((70, 45, 20, 110), (30, 42), halo)
    out.alpha_composite(sh.filter(ImageFilter.GaussianBlur(10)))
    wh = Image.new("RGBA", im.size, (255, 255, 255, 255)); wh.putalpha(halo)
    out.alpha_composite(wh, (30, 30)); out.alpha_composite(im, (30, 30))
    return out.crop(out.getbbox())

if __name__ == "__main__":
    casquette().save(sys.argv[1])
    casquette(col=(252, 238, 201), dark=(224, 196, 150)).save(sys.argv[2])
