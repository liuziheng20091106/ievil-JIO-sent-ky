"""Build the three-second host warning using the existing Lottie image pipeline."""

import importlib.util
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "animation_samples", ROOT / "tools/build-animation-samples.py"
)
assert SPEC is not None and SPEC.loader is not None
SAMPLES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SAMPLES)
NAME = "host-warning"
END = 90


def glow(image, color=(255, 82, 65), radius=22):
    halo = Image.new("RGBA", image.size, (*color, 0))
    halo.putalpha(image.getchannel("A").filter(ImageFilter.GaussianBlur(radius)))
    halo.alpha_composite(image)
    return halo


def lettering(text, size, dimensions, color):
    font = ImageFont.truetype(str(ROOT / "client/assets/fonts/HarmonyOS_Sans_SC_Bold.ttf"), size)
    image = Image.new("RGBA", dimensions)
    draw = ImageDraw.Draw(image)
    bounds = draw.textbbox((0, 0), text, font=font)
    draw.text(
        ((image.width - bounds[2] - bounds[0]) / 2, (image.height - bounds[3] - bounds[1]) / 2),
        text,
        font=font,
        fill=color,
    )
    return image


def artwork():
    panel = Image.new("RGBA", (1000, 900))
    draw = ImageDraw.Draw(panel)
    draw.rounded_rectangle((62, 62, 938, 838), radius=58, fill=(22, 12, 25, 242))
    draw.rounded_rectangle((62, 62, 938, 838), radius=58, outline=(240, 109, 90, 200), width=2)
    draw.rounded_rectangle((78, 78, 922, 822), radius=44, outline=(255, 208, 145, 45), width=1)
    for x, direction in ((111, 1), (889, -1)):
        for y in (117, 783):
            draw.line((x, y, x + direction * 86, y), fill=(255, 191, 123, 220), width=4)
    panel = glow(panel, radius=28)

    badge = Image.new("RGBA", (400, 400))
    draw = ImageDraw.Draw(badge)
    triangle = [(200, 64), (340, 302), (60, 302), (200, 64)]
    draw.polygon(triangle, fill=(60, 25, 30, 255))
    draw.line(triangle, fill=(255, 178, 110, 255), width=10, joint="curve")
    draw.line([(200, 88), (320, 291), (80, 291), (200, 88)], fill=(255, 103, 88, 150), width=2)
    draw.rounded_rectangle((188, 144, 212, 228), radius=12, fill=(255, 243, 212, 255))
    draw.ellipse((187, 247, 213, 273), fill=(255, 243, 212, 255))
    badge = glow(badge, (255, 141, 76), 18)

    ring = Image.new("RGBA", (620, 620))
    draw = ImageDraw.Draw(ring)
    draw.ellipse((57, 57, 563, 563), outline=(255, 128, 93, 35), width=2)
    for start in range(0, 360, 60):
        draw.arc((78, 78, 542, 542), start + 5, start + 43, fill=(255, 172, 102, 175), width=3)
        draw.arc((94, 94, 526, 526), start + 9, start + 20, fill=(255, 238, 195, 220), width=5)
    ring = glow(ring, (255, 154, 93), 8)
    return {
        "panel": panel,
        "badge": badge,
        "ring": ring,
        "title": glow(lettering("主持人警告", 112, (940, 174), (255, 239, 209, 255)), radius=8),
        "hint": lettering("请在 30 秒内完成当前操作", 42, (940, 92), (246, 182, 151, 255)),
        "label": lettering("H O S T   W A R N I N G", 25, (740, 70), (255, 179, 112, 230)),
    }


def main():
    output = ROOT / "resources/animation/scripts"
    images = output / "images" / NAME
    images.mkdir(parents=True, exist_ok=True)
    assets, layers = [], []
    fade = SAMPLES.animated([(0, 0), (9, 100), (76, 100), (90, 0)])

    def bitmap(name, image, position, scale=None, rotation=None, opacity=None):
        image.save(images / f"{name}.webp", format="WEBP", lossless=True, exact=True, method=6)
        assets.append(
            {
                "id": name,
                "w": image.width,
                "h": image.height,
                "u": f"images/{NAME}/",
                "p": f"{name}.webp",
                "e": 0,
            }
        )
        layers.append(
            SAMPLES.image_layer(
                name,
                len(layers) + 1,
                name,
                position,
                (image.width / 2, image.height / 2),
                opacity or fade,
                scale=scale,
                rotation=rotation,
                op=END,
            )
        )

    art = artwork()
    bitmap("label", art["label"], (540, 181))
    bitmap(
        "shine",
        lettering("主持人警告", 112, (940, 174), "white"),
        (540, 617),
        opacity=SAMPLES.animated([(24, 0), (27, 90), (59, 90), (63, 0)]),
    )
    layers[-1]["hasMask"] = True
    layers[-1]["masksProperties"] = [
        {
            "inv": False,
            "mode": "a",
            "o": SAMPLES.fixed(100),
            "x": SAMPLES.fixed(0),
            "pt": SAMPLES.animated(
                [
                    (24, SAMPLES.polygon([(-180, 0), (-90, 0), (-160, 174), (-250, 174)])),
                    (63, SAMPLES.polygon([(1120, 0), (1210, 0), (1140, 174), (1050, 174)])),
                ]
            ),
        }
    ]
    bitmap(
        "title",
        art["title"],
        SAMPLES.animated(
            [
                (0, [540, 657, 0]),
                (7, [540, 657, 0]),
                (17, [540, 611, 0]),
                (23, [540, 617, 0]),
                (76, [540, 617, 0]),
                (90, [540, 599, 0]),
            ]
        ),
        opacity=SAMPLES.animated([(0, 0), (7, 0), (17, 100), (76, 100), (90, 0)]),
    )
    bitmap(
        "hint",
        art["hint"],
        (540, 727),
        opacity=SAMPLES.animated([(0, 0), (16, 0), (26, 100), (76, 100), (90, 0)]),
    )
    bitmap(
        "badge",
        art["badge"],
        (540, 375),
        scale=SAMPLES.animated(
            [
                (0, [55, 55, 100]),
                (8, [110, 110, 100]),
                (15, [100, 100, 100]),
                (42, [104, 104, 100]),
                (64, [100, 100, 100]),
                (76, [100, 100, 100]),
                (90, [88, 88, 100]),
            ]
        ),
    )
    for start in (3, 33):
        layers.append(
            SAMPLES.image_layer(
                f"expanding-ring-{start}",
                len(layers) + 1,
                "ring",
                (540, 375),
                (310, 310),
                SAMPLES.animated([(start, 0), (start + 5, 55), (start + 28, 0)]),
                scale=SAMPLES.animated([(start, [62, 62, 100]), (start + 28, [122, 122, 100])]),
                op=END,
            )
        )
    bitmap(
        "ring",
        art["ring"],
        (540, 375),
        rotation=SAMPLES.animated([(0, -18), (76, 35), (90, 42)]),
        scale=SAMPLES.animated([(0, [76, 76, 100]), (15, [100, 100, 100]), (90, [104, 104, 100])]),
    )
    for index in range(10):
        angle = index * math.tau / 10
        position = SAMPLES.animated(
            [
                (5, [540 + math.cos(angle) * 205, 375 + math.sin(angle) * 205, 0]),
                (49, [540 + math.cos(angle) * 380, 375 + math.sin(angle) * 380, 0]),
            ]
        )
        layers.append(
            SAMPLES.shape_layer(
                f"ember-{index}",
                len(layers) + 1,
                [(-3, 0), (0, -9), (3, 0), (0, 9)],
                [1, 0.66, 0.38, 1],
                SAMPLES.transforms(
                    position=position,
                    rotation=SAMPLES.fixed(index * 36),
                    opacity=SAMPLES.animated([(5, 0), (12, 85), (49, 0)]),
                ),
                op=END,
            )
        )
    bitmap(
        "panel",
        art["panel"],
        (540, 487),
        scale=SAMPLES.animated(
            [
                (0, [86, 94, 100]),
                (12, [100, 100, 100]),
                (76, [100, 100, 100]),
                (90, [98, 96, 100]),
            ]
        ),
    )
    animation = SAMPLES.composition("主持人警告 · 3 秒", layers, assets, end=END)
    animation.update(w=1080, h=1080)
    target = output / f"{NAME}.json"
    target.write_text(
        json.dumps(animation, ensure_ascii=True, allow_nan=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"{target.name}: 90 frames / 30 fps = 3 seconds; {len(assets)} local image assets")


if __name__ == "__main__":
    main()
