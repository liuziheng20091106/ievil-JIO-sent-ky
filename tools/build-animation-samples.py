"""Author two standard Lottie samples; imagery stays outside the app binary."""

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]


def fixed(value):
    return {"a": 0, "k": value}


def animated(points):
    keys = []
    for index, (frame, value) in enumerate(points):
        key = {"t": frame, "s": value if isinstance(value, list) else [value]}
        if index + 1 < len(points):
            target = points[index + 1][1]
            key.update(
                {
                    "e": target if isinstance(target, list) else [target],
                    "i": {"x": [0.67], "y": [1]},
                    "o": {"x": [0.33], "y": [0]},
                }
            )
        keys.append(key)
    return {"a": 1, "k": keys}


def transforms(position=(0, 0), anchor=(0, 0), opacity=None, scale=None, rotation=None):
    return {
        "o": opacity or fixed(100),
        "r": rotation or fixed(0),
        "p": position if isinstance(position, dict) else fixed([*position, 0]),
        "a": fixed([*anchor, 0]),
        "s": scale or fixed([100, 100, 100]),
    }


def image_asset(name, image, output):
    image.save(output / "images" / f"{name}.png")
    return {
        "id": name,
        "w": image.width,
        "h": image.height,
        "u": "images/",
        "p": f"{name}.png",
        "e": 0,
    }


def image_layer(
    name, index, asset, position, anchor, opacity, scale=None, rotation=None, ip=0, op=120
):
    return {
        "ddd": 0,
        "ind": index,
        "ty": 2,
        "nm": name,
        "refId": asset,
        "ks": transforms(position, anchor, opacity, scale, rotation),
        "ip": ip,
        "op": op,
        "st": 0,
        "bm": 0,
    }


def polygon(points):
    return {"i": [[0, 0] for _ in points], "o": [[0, 0] for _ in points], "v": points, "c": True}


def shape_layer(name, index, points, color, ks, op=120):
    return {
        "ddd": 0,
        "ind": index,
        "ty": 4,
        "nm": name,
        "ks": ks,
        "shapes": [
            {"ty": "sh", "ks": fixed(polygon(points)), "nm": name},
            {"ty": "fl", "c": fixed(color), "o": fixed(100), "r": 1},
        ],
        "ip": 0,
        "op": op,
        "st": 0,
        "bm": 0,
    }


def glowing(art, radius=14):
    alpha = art.getchannel("A")
    result = Image.new("RGBA", art.size, (255, 245, 204, 0))
    result.putalpha(alpha.filter(ImageFilter.GaussianBlur(radius)).point(lambda v: min(220, v * 3)))
    tight = Image.new("RGBA", art.size, (255, 250, 225, 0))
    tight.putalpha(alpha.filter(ImageFilter.GaussianBlur(4)).point(lambda v: min(230, v * 2)))
    result.alpha_composite(tight)
    result.alpha_composite(art)
    return result


def title_glyph(character, font, texture):
    size = (240, 280)
    mask = Image.new("L", size)
    draw = ImageDraw.Draw(mask)
    box = draw.textbbox((0, 0), character, font=font)
    draw.text(
        ((size[0] - box[2] + box[0]) / 2 - box[0], (size[1] - box[3] + box[1]) / 2 - box[1]),
        character,
        font=font,
        fill=255,
    )
    source = texture.resize(size).convert("RGBA")
    source.putalpha(mask)
    stroke = Image.new("RGBA", size, (255, 244, 206, 0))
    stroke.putalpha(mask.filter(ImageFilter.MaxFilter(3)))
    stroke.alpha_composite(source)
    return glowing(stroke, 13)


def ornament():
    art = Image.new("RGBA", (240, 240))
    draw = ImageDraw.Draw(art)
    cream = "#fff7dc"
    ink = "#100a12"
    diamond = [(110, 48), (134, 72), (110, 96), (86, 72)]
    draw.polygon(diamond, fill=cream)
    draw.line(diamond + [diamond[0]], fill=ink, width=4)
    draw.polygon([(110, 59), (123, 72), (110, 85), (97, 72)], fill=ink)
    for y in (64, 72, 80):
        draw.line([(132, y), (202, y)], fill=cream, width=6)
        draw.line([(132, y), (202, y)], fill=ink, width=3)
    draw.line([(109, 101), (64, 150), (121, 174), (109, 101)], fill=cream, width=10)
    draw.line([(109, 101), (64, 150), (121, 174), (109, 101)], fill=ink, width=4)
    draw.line([(109, 105), (88, 155)], fill=cream, width=9)
    draw.line([(109, 105), (88, 155)], fill=ink, width=3)
    draw.polygon([(57, 158), (125, 182), (117, 194), (64, 178)], fill=cream)
    draw.polygon([(58, 158), (124, 182), (115, 189), (64, 176)], fill=ink)
    return glowing(art, 17)


def book():
    art = Image.new("RGBA", (450, 120))
    draw = ImageDraw.Draw(art)
    # Two curved open-page outlines rendered at source resolution before glow.
    left = [
        (48, 45),
        (77, 40),
        (108, 38),
        (145, 40),
        (180, 48),
        (216, 67),
        (216, 78),
        (179, 61),
        (145, 54),
        (107, 53),
        (77, 55),
        (48, 60),
        (48, 45),
    ]
    right = [(450 - x, y) for x, y in left]
    draw.line(left, fill="#fff9df", width=8, joint="curve")
    draw.line(left, fill="#120b12", width=3, joint="curve")
    draw.line(right, fill="#fff9df", width=8, joint="curve")
    draw.line(right, fill="#120b12", width=3, joint="curve")
    draw.polygon([(215, 67), (225, 73), (235, 67), (235, 80), (225, 86), (215, 80)], fill="#120b12")
    return glowing(art, 13)


def composition(name, layers, assets, end=120):
    return {
        "v": "5.13.0",
        "fr": 30,
        "ip": 0,
        "op": end,
        "w": 1920,
        "h": 1080,
        "nm": name,
        "ddd": 0,
        "assets": assets,
        "layers": layers,
        "markers": [{"tm": 0, "cm": "intro", "dr": 0}, {"tm": end * 0.7, "cm": "hold", "dr": 0}],
    }


def interrogation(output, font, texture):
    assets = []
    layers = []
    for index, character in enumerate("审问开始"):
        name = f"interrogation-title-{index}"
        image = title_glyph(character, font, texture)
        assets.append(image_asset(name, image, output))
        arrival = 63 + index * 3
        x = 720 + index * 160
        y = 563 if index in (0, 3) else 525
        opacity = animated([(arrival, 0), (arrival + 7, 100), (104, 100), (116, 0)])
        position = animated(
            [
                (arrival, [x, y + 160, 0]),
                (arrival + 7, [x, y - 12, 0]),
                (arrival + 12, [x, y, 0]),
                (102, [x, y - 3, 0]),
                (116, [x, y - 200, 0]),
            ]
        )
        scale = animated(
            [
                (arrival, [80, 125, 100]),
                (arrival + 7, [104, 95, 100]),
                (arrival + 12, [100, 100, 100]),
            ]
        )
        layers.append(
            image_layer(
                f"title-{character}",
                index + 1,
                name,
                position,
                (120, 140),
                opacity,
                scale,
                ip=arrival,
            )
        )
    assets.append(image_asset("interrogation-scale", ornament(), output))
    assets.append(
        image_asset(
            "interrogation-scale-mirror",
            ornament().transpose(Image.Transpose.FLIP_LEFT_RIGHT),
            output,
        )
    )
    for index, (destination, ref) in enumerate(
        [(548, "interrogation-scale"), (1372, "interrogation-scale-mirror")]
    ):
        position = animated(
            [
                (30, [960, 535, 0]),
                (45, [960, 535, 0]),
                (59, [destination + (90 if index == 0 else -90), 535, 0]),
                (77, [destination, 535, 0]),
                (104, [destination, 532, 0]),
                (117, [destination + (-80 if index == 0 else 80), 510, 0]),
            ]
        )
        opacity = animated([(30, 0), (39, 100), (107, 100), (120, 0)])
        scale = animated([(30, [30, 30, 100]), (39, [115, 115, 100]), (45, [100, 100, 100])])
        layers.append(
            image_layer(
                f"scale-{index}",
                5 + index,
                ref,
                position,
                (110 if index == 0 else 130, 72),
                opacity,
                scale,
            )
        )
    assets.append(image_asset("interrogation-book", book(), output))
    layers.append(
        image_layer(
            "open-book",
            7,
            "interrogation-book",
            (960, 630),
            (225, 60),
            animated([(61, 0), (70, 100), (104, 100), (117, 0)]),
            animated(
                [
                    (61, [30, 70, 100]),
                    (76, [100, 100, 100]),
                    (104, [100, 100, 100]),
                    (117, [100, 30, 100]),
                ]
            ),
        )
    )
    return composition("审问开始", layers, assets)


def skill_cut_in(output, source):
    image = Image.open(source).convert("RGBA")
    image = image.crop(image.getbbox())
    image.thumbnail((1400, 1400))
    assets = [image_asset("skill-portrait", image, output)]
    banner_position = animated(
        [(6, [2300, 518, 0]), (15, [0, 0, 0]), (36, [-32, -8, 0]), (45, [-2300, -518, 0])]
    )
    text_position = animated(
        [(9, [3260, 1358, 0]), (18, [960, 768, 0]), (33, [928, 760, 0]), (42, [-1340, 178, 0])]
    )
    layers = []
    for index, (name, text, size, offset, color) in enumerate(
        [
            ("role-title", "夏目安安 · 魔女", 45, 85, [0.965, 0.863, 0.773]),
            ("skill-name", "全场洗脑", 92, -5, [1, 1, 1]),
        ],
        start=1,
    ):
        layers.append(
            {
                "ddd": 0,
                "ind": index,
                "ty": 5,
                "nm": name,
                "ks": transforms(text_position, (0, offset), rotation=fixed(12.68)),
                "t": {
                    "d": {
                        "k": [
                            {
                                "t": 0,
                                "s": {
                                    "t": text,
                                    "s": size,
                                    "f": "HarmonyOS Sans SC",
                                    "j": 2,
                                    "tr": 0,
                                    "lh": size * 1.2,
                                    "ls": 0,
                                    "fc": color,
                                    "sz": [1000, size * 1.5],
                                    "ps": [-500, -size * 0.75],
                                },
                            }
                        ]
                    },
                    "p": {},
                    "m": {"g": 1, "a": fixed([0, 0])},
                    "a": [],
                },
                "ip": 9,
                "op": 42,
                "st": 0,
                "bm": 0,
            }
        )
    divider_path = polygon([[-500, 0], [500, 0]])
    divider_path["c"] = False
    layers.append(
        {
            "ddd": 0,
            "ind": 3,
            "ty": 4,
            "nm": "text-divider",
            "ks": transforms(text_position, (0, 44), rotation=fixed(12.68)),
            "shapes": [
                {"ty": "sh", "ks": fixed(divider_path)},
                {
                    "ty": "st",
                    "c": fixed([0.95, 0.77, 0.45, 1]),
                    "o": fixed(100),
                    "w": fixed(3),
                    "lc": 2,
                    "lj": 2,
                    "ml": 4,
                },
            ],
            "ip": 9,
            "op": 42,
            "st": 0,
            "bm": 0,
        }
    )
    banner = [[-300, 364], [2220, 932], [2220, 1148], [-300, 580]]
    layers.append(
        shape_layer(
            "crimson-banner", 4, banner, [0.53, 0.12, 0.24, 1], transforms(banner_position), op=45
        )
    )
    portrait_height = 983
    portrait_width = portrait_height * image.width / image.height
    portrait_layer = image_layer(
        "portrait",
        1,
        "skill-portrait",
        animated(
            [
                (6, [-1400, 108, 0]),
                (15, [(1920 - portrait_width) / 2, 108, 0]),
                (36, [(1920 - portrait_width) / 2 + 30, 103, 0]),
                (45, [2400, 90, 0]),
            ]
        ),
        (0, 0),
        fixed(100),
        fixed([portrait_width / image.width * 100, portrait_height / image.height * 100, 100]),
        ip=6,
        op=45,
    )
    assets.append({"id": "portrait-composition", "w": 1920, "h": 1080, "layers": [portrait_layer]})
    layers.append(
        {
            "ddd": 0,
            "ind": 5,
            "ty": 0,
            "nm": "portrait-clip",
            "refId": "portrait-composition",
            "w": 1920,
            "h": 1080,
            "ks": transforms(),
            "ip": 6,
            "op": 45,
            "st": 0,
            "bm": 0,
            "hasMask": True,
            "masksProperties": [
                {
                    "inv": False,
                    "mode": "a",
                    "pt": fixed(polygon([[0, 0], [1920, 0], [1920, 864], [0, 432]])),
                    "o": fixed(100),
                    "x": fixed(0),
                }
            ],
        }
    )
    result = composition("技能展示默认模板", layers, assets, 51)
    result["fonts"] = {
        "list": [
            {
                "fName": "HarmonyOS Sans SC",
                "fFamily": "HarmonyOS Sans SC",
                "fStyle": "Bold",
                "ascent": 75,
            }
        ]
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument(
        "--output-dir", type=Path, default=ROOT / "resources" / "animation" / "scripts"
    )
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "images").mkdir(exist_ok=True)
    font_path = args.source_dir / "SweiB2SugarCJKsc-Bold.ttf"
    font = ImageFont.truetype(str(font_path), 186)
    texture = Image.open(args.source_dir / "(素材)" / "纹理图案.png")
    samples = {
        "interrogation-start": interrogation(args.output_dir, font, texture),
        "skill-cut-in": skill_cut_in(
            args.output_dir, ROOT / "resources" / "animation" / "annan" / "EX" / "1.png"
        ),
    }
    for name, data in samples.items():
        target = args.output_dir / f"{name}.json"
        target.write_text(
            json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
        )
        print(f"{target}: {data['op'] / data['fr']:.1f}s, {len(data['layers'])} layers")


if __name__ == "__main__":
    main()
