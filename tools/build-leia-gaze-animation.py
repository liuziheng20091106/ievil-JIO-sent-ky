"""Build Leia's thirty-second full-body presentation with five neon captions."""

import importlib.util
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "animation_samples", ROOT / "tools/build-animation-samples.py"
)
assert SPEC is not None and SPEC.loader is not None
SAMPLES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SAMPLES)

NAME = "leia-gaze-fix"
TEXTS = (
    "今夜~星光闪闪~雷雅~出来~冒泡~",
    "我是一只可爱的简易长矛我宣布我是凶手!",
    "喵喵喵喵喵",
    "喵喵喵喵喵都来投我喵",
    "你们不能拒绝投我的热情~",
)
END = 900


def bitmap(identifier, filename, image, output):
    image.save(output / filename, format="WEBP", lossless=True, exact=True, method=6)
    return {
        "id": identifier,
        "w": image.width,
        "h": image.height,
        "u": f"images/{NAME}/",
        "p": filename,
        "e": 0,
    }


def caption(text, color):
    font = ImageFont.truetype(str(ROOT / "client/assets/fonts/HarmonyOS_Sans_SC_Bold.ttf"), 92)
    lines, line = [], ""
    for character in text:
        if font.getlength(line + character) > 920:
            lines.append(line)
            line = ""
        line += character
    lines.append(line)
    if len(lines) > 1:
        width = math.ceil(len(text) / len(lines))
        balanced = [text[index : index + width] for index in range(0, len(text), width)]
        if all(font.getlength(line) <= 920 for line in balanced):
            lines = balanced
    mask = Image.new("L", (1000, 360))
    draw = ImageDraw.Draw(mask)
    y = (mask.height - len(lines) * 112) / 2
    for line in lines:
        bounds = draw.textbbox((0, 0), line, font=font)
        draw.text(((1000 - bounds[2] - bounds[0]) / 2, y - bounds[1]), line, font=font, fill=255)
        y += 112
    image = Image.new("RGBA", mask.size)
    ImageDraw.Draw(image).rounded_rectangle((8, 8, 992, 352), radius=40, fill=(8, 8, 30, 180))
    glow = Image.new("RGBA", mask.size, (*color, 0))
    glow.putalpha(
        mask.filter(ImageFilter.GaussianBlur(13)).point(lambda value: min(230, value * 3))
    )
    image.alpha_composite(glow)
    outline = Image.new("RGBA", mask.size, (*color, 0))
    outline.putalpha(mask.filter(ImageFilter.MaxFilter(9)))
    image.alpha_composite(outline)
    shadow = Image.new("RGBA", mask.size, (20, 12, 55, 0))
    shadow.putalpha(mask.filter(ImageFilter.MaxFilter(5)))
    image.alpha_composite(shadow)
    gradient = Image.new("RGBA", mask.size)
    paint = ImageDraw.Draw(gradient)
    for row in range(mask.height):
        amount = row / (mask.height - 1)
        tint = tuple(round(255 * (1 - amount) + channel * amount) for channel in color)
        paint.line((0, row, 1000, row), fill=(*tint, 255))
    gradient.putalpha(mask)
    image.alpha_composite(gradient)
    shine = Image.new("RGBA", mask.size, "white")
    shine.putalpha(mask)
    return image, shine


def main():
    scripts = ROOT / "resources/animation/scripts"
    output = scripts / "images" / NAME
    output.mkdir(parents=True, exist_ok=True)
    assets = []
    layers = []
    for index in range(1, 4):
        with Image.open(ROOT / f"resources/animation/leia/full/{index}.png") as original:
            image = ImageOps.contain(
                original.convert("RGBA"), (1000, 1010), Image.Resampling.LANCZOS
            )
        identifier = f"portrait-{index}"
        assets.append(bitmap(identifier, f"{identifier}.webp", image, output))
        layers.append(
            SAMPLES.image_layer(
                identifier,
                index,
                identifier,
                (540, 510),
                (image.width / 2, image.height / 2),
                SAMPLES.fixed(100),
                ip=(index - 1) * 300,
                op=index * 300,
            )
        )

    colors = ((255, 185, 70), (255, 92, 190), (70, 225, 255), (200, 125, 255), (255, 205, 90))
    for index, (text, color) in enumerate(zip(TEXTS, colors, strict=True)):
        start, end = index * 180, (index + 1) * 180
        image, shine = caption(text, color)
        identifier = f"caption-{index + 1}"
        assets.append(bitmap(identifier, f"{identifier}.webp", image, output))
        assets.append(bitmap(identifier + "-shine", f"{identifier}-shine.webp", shine, output))
        direction = -1 if index % 2 == 0 else 1
        position = SAMPLES.animated(
            [
                (start, [540 + direction * 1150, 1240, 0]),
                (start + 16, [540 - direction * 24, 1240, 0]),
                (start + 25, [540, 1240, 0]),
                (end - 16, [540, 1240, 0]),
                (end, [540 - direction * 1150, 1240, 0]),
            ]
        )
        scale = SAMPLES.animated(
            [
                (start, [84, 84, 100]),
                (start + 16, [104, 104, 100]),
                (start + 25, [100, 100, 100]),
                (end, [100, 100, 100]),
            ]
        )
        opacity = SAMPLES.animated([(start, 0), (start + 10, 100), (end - 12, 100), (end, 0)])
        base = SAMPLES.image_layer(
            text,
            10 + index * 2,
            identifier,
            position,
            (500, 180),
            opacity,
            scale=scale,
            ip=start,
            op=end,
        )
        highlight = SAMPLES.image_layer(
            identifier + "-shine",
            11 + index * 2,
            identifier + "-shine",
            position,
            (500, 180),
            opacity,
            scale=scale,
            ip=start,
            op=end,
        )
        # A moving local mask sweeps only the glyphs; no external effects or expressions.
        highlight["hasMask"] = True
        highlight["masksProperties"] = [
            {
                "mode": "a",
                "inv": False,
                "o": SAMPLES.fixed(65),
                "x": SAMPLES.fixed(0),
                "pt": SAMPLES.animated(
                    [
                        (
                            start + offset,
                            SAMPLES.polygon([[x, 0], [x + 90, 0], [x - 30, 360], [x - 120, 360]]),
                        )
                        for offset, x in ((28, -100), (80, 1200), (94, -100), (155, 1200))
                    ]
                ),
            }
        ]
        layers[0:0] = [highlight, base]

    star = Image.new("RGBA", (96, 96))
    ImageDraw.Draw(star).polygon(
        [(48, 4), (58, 38), (92, 48), (58, 58), (48, 92), (38, 58), (4, 48), (38, 38)],
        fill=(255, 240, 180, 255),
    )
    assets.append(bitmap("star", "star.webp", SAMPLES.glowing(star, 6), output))
    for index in range(18):
        x = 95 + (index * 173) % 890
        y = 80 + (index * 137) % 950
        pulse = [(0, 0)]
        for frame in range(25 + index * 5, END, 150):
            pulse.extend([(frame, 0), (frame + 35, 65), (frame + 100, 0)])
        pulse = [(frame, value) for frame, value in pulse if frame <= END] + [(END, 0)]
        layers.append(
            SAMPLES.image_layer(
                "floating-star",
                40 + index,
                "star",
                SAMPLES.animated([(0, [x, y, 0]), (END, [x + 35, y - 100, 0])]),
                (48, 48),
                SAMPLES.animated(pulse),
                scale=SAMPLES.fixed([35, 35, 100]),
                rotation=SAMPLES.animated([(0, 0), (END, 90)]),
                op=END,
            )
        )
    for index in range(10):
        angle = index * math.tau / 10
        points = [
            [radius * math.cos(angle + spread), radius * math.sin(angle + spread)]
            for radius, spread in ((70, -0.03), (1100, -0.06), (1100, 0.06), (70, 0.03))
        ]
        rotation = SAMPLES.animated([(0, 0), (END, END / 90 * 360)])
        rotation["k"][0]["i"] = {"x": [1], "y": [1]}
        rotation["k"][0]["o"] = {"x": [0], "y": [0]}
        layers.append(
            SAMPLES.shape_layer(
                "starlight-ray",
                70 + index,
                points,
                [0.58, 0.32, 0.85, 1],
                SAMPLES.transforms(
                    (540, 510),
                    opacity=SAMPLES.fixed(12),
                    rotation=rotation,
                ),
                op=END,
            )
        )
    animation = SAMPLES.composition(NAME, layers, assets, end=END)
    animation.update(
        w=1080,
        h=1440,
        markers=[{"tm": index * 180, "cm": text, "dr": 180} for index, text in enumerate(TEXTS)],
    )
    target = scripts / f"{NAME}.json"
    target.write_text(
        json.dumps(animation, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    used = {asset["p"] for asset in assets}
    for stale in output.glob("*.webp"):
        if stale.name not in used:
            stale.unlink()
    print(f"{target}: 1080x1440, 30fps, {END} frames")
    for asset in assets:
        print(f"  {asset['p']}: {asset['w']}x{asset['h']}")


if __name__ == "__main__":
    main()
