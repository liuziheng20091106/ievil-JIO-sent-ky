"""Build Leia's uncropped three-image, thirty-second Lottie presentation."""

import importlib.util
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "animation_samples", ROOT / "tools/build-animation-samples.py"
)
assert SPEC is not None and SPEC.loader is not None
SAMPLES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SAMPLES)

NAME = "leia-gaze-fix"
TEXT = "\u5168\u4f53\u76ee\u5149\uff0c\u5411\u6211\u770b\u9f50"
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


def main():
    scripts = ROOT / "resources/animation/scripts"
    output = scripts / "images" / NAME
    output.mkdir(parents=True, exist_ok=True)
    assets = []
    layers = []
    for index in range(1, 4):
        with Image.open(ROOT / f"resources/animation/leia/full/{index}.png") as original:
            image = ImageOps.contain(
                original.convert("RGBA"), (1000, 1200), Image.Resampling.LANCZOS
            )
        identifier = f"portrait-{index}"
        assets.append(bitmap(identifier, f"{identifier}.webp", image, output))
        layers.append(
            SAMPLES.image_layer(
                identifier,
                index,
                identifier,
                (540, 620),
                (image.width / 2, image.height / 2),
                SAMPLES.fixed(100),
                ip=(index - 1) * 300,
                op=index * 300,
            )
        )

    # Bake the local font so every player renders the same persistent caption.
    caption = Image.new("RGBA", (1000, 144))
    font = ImageFont.truetype(str(ROOT / "client/assets/fonts/HarmonyOS_Sans_SC_Bold.ttf"), 96)
    draw = ImageDraw.Draw(caption)
    bounds = draw.textbbox((0, 0), TEXT, font=font, stroke_width=4)
    assert bounds[2] - bounds[0] <= caption.width
    assert bounds[3] - bounds[1] <= caption.height
    draw.text(
        (
            (caption.width - bounds[2] - bounds[0]) / 2,
            (caption.height - bounds[3] - bounds[1]) / 2,
        ),
        TEXT,
        font=font,
        fill="white",
        stroke_width=4,
        stroke_fill="black",
    )
    assets.append(bitmap("caption", "caption.webp", caption, output))
    layers.insert(
        0,
        SAMPLES.image_layer(TEXT, 4, "caption", (40, 1260), (0, 0), SAMPLES.fixed(100), op=END),
    )
    animation = SAMPLES.composition(NAME, layers, assets, end=END)
    animation.update(w=1080, h=1440, markers=[])
    target = scripts / f"{NAME}.json"
    target.write_text(
        json.dumps(animation, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    print(f"{target}: 1080x1440, 30fps, {END} frames")
    for asset in assets:
        print(f"  {asset['p']}: {asset['w']}x{asset['h']}")


if __name__ == "__main__":
    main()
