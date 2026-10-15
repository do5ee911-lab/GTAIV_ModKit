import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "icon.ico")
S = 256


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def make_base():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    top, bottom = (28, 42, 78), (8, 10, 18)
    for y in range(S):
        c = lerp(top, bottom, y / (S - 1))
        draw.line([(16, y), (S - 16, y)], fill=c + (255,))
    mask = Image.new("L", (S, S), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([8, 8, S - 8, S - 8], radius=40, fill=255)
    img.putalpha(mask)
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([8, 8, S - 8, S - 8], radius=40,
                           outline=(212, 175, 55, 255), width=4)
    draw.rounded_rectangle([14, 14, S - 14, S - 14], radius=34,
                           outline=(255, 220, 120, 70), width=2)
    shine = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shine)
    sd.ellipse([-60, -90, S + 20, 110], fill=(255, 255, 255, 28))
    img = Image.alpha_composite(img, Image.composite(
        shine, Image.new("RGBA", (S, S), (0, 0, 0, 0)), mask))
    return img, mask


def gold_text(draw_img, text, font, box, top_gold=(255, 236, 150),
              bot_gold=(180, 130, 20)):
    x0, y0, x1, y1 = box
    layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.text(((x0 + x1) / 2, (y0 + y1) / 2), text, font=font, fill=(255, 255, 255, 255),
            anchor="mm")
    grad = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grad)
    for y in range(y0, y1 + 1):
        gd.line([(x0, y), (x1, y)], fill=lerp(top_gold, bot_gold, (y - y0) / max(1, y1 - y0)) + (255,))
    text_mask = layer.split()[3]
    grad.putalpha(Image.composite(grad.split()[3], Image.new("L", (S, S), 0), text_mask))
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).text(((x0 + x1) / 2 + 2, (y0 + y1) / 2 + 3), text,
                                font=font, fill=(0, 0, 0, 160), anchor="mm")
    base = draw_img
    base.alpha_composite(shadow)
    base.alpha_composite(grad)


def main():
    img, mask = make_base()
    f_impact = ImageFont.truetype(r"C:\Windows\Fonts\impact.ttf", 40)
    f_iv = ImageFont.truetype(r"C:\Windows\Fonts\impact.ttf", 110)
    f_small = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", 26)
    d = ImageDraw.Draw(img)
    d.text((S / 2, 48), "GTA", font=f_impact, fill=(235, 235, 235, 255), anchor="mm")
    gold_text(img, "IV", f_iv, (50, 62, S - 50, 175))
    ribbon = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    rd = ImageDraw.Draw(ribbon)
    rd.rounded_rectangle([30, 190, S - 30, 228], radius=10, fill=(12, 12, 16, 235))
    rd.rounded_rectangle([30, 190, S - 30, 228], radius=10,
                         outline=(212, 175, 55, 255), width=2)
    img.alpha_composite(ribbon)
    d = ImageDraw.Draw(img)
    d.text((S / 2, 209), "MOD KIT", font=f_small, fill=(255, 220, 120, 255), anchor="mm")
    disc = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    dd = ImageDraw.Draw(disc)
    dd.ellipse([S - 74, 28, S - 30, 72], outline=(200, 200, 210, 200), width=3)
    dd.ellipse([S - 60, 42, S - 44, 58], outline=(212, 175, 55, 220), width=2)
    img.alpha_composite(disc)
    img.save(OUT, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                         (128, 128), (256, 256)])
    print("wrote", OUT, os.path.getsize(OUT), "bytes")


if __name__ == "__main__":
    main()
