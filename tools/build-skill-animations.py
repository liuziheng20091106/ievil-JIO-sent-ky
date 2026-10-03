"""Recompose the supplied PNG art and transparent shatter MOVs as local Lottie."""

import argparse
import importlib.util
import json
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "animation_samples", ROOT / "tools/build-animation-samples.py"
)
assert SPEC is not None and SPEC.loader is not None
SAMPLES = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SAMPLES)
fixed = SAMPLES.fixed
animated = SAMPLES.animated
transforms = SAMPLES.transforms
image_layer = SAMPLES.image_layer
shape_layer = SAMPLES.shape_layer
composition = SAMPLES.composition

SLOT = (736, 1024)
END = 108
SHATTER_START = 60


def webp(image, destination):
    image.save(destination, format="WEBP", lossless=True, exact=True, method=6)


def portrait(source, destination):
    with Image.open(source) as original:
        contained = ImageOps.contain(original.convert("RGBA"), SLOT, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", SLOT)
    canvas.alpha_composite(
        contained, ((SLOT[0] - contained.width) // 2, (SLOT[1] - contained.height) // 2)
    )
    webp(canvas, destination)


def bitmap(name, filename, dimensions, folder):
    return {
        "id": name,
        "w": dimensions[0],
        "h": dimensions[1],
        "u": f"images/{folder}/",
        "p": filename,
        "e": 0,
    }


def extract_shatter(source, output):
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=r_frame_rate,nb_frames,pix_fmt",
            "-of",
            "json",
            str(source),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    stream = json.loads(probe.stdout)["streams"][0]
    if stream["r_frame_rate"] != "30/1" or int(stream["nb_frames"]) != 31:
        raise ValueError(f"Expected 31 shatter frames at 30fps: {source}")
    with tempfile.TemporaryDirectory(prefix="seven-double-shatter-") as temporary:
        pattern = str(Path(temporary) / "frame-%02d.png")
        subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-vf",
                "scale=960:540:flags=lanczos,format=rgba",
                "-fps_mode",
                "passthrough",
                "-start_number",
                "0",
                pattern,
            ],
            check=True,
        )
        frames = sorted(Path(temporary).glob("frame-*.png"))
        if len(frames) != 31:
            raise ValueError(f"Expected 31 decoded shatter frames, got {len(frames)}")
        for index, frame in enumerate(frames):
            with Image.open(frame) as image:
                if image.mode != "RGBA":
                    raise ValueError("Shatter must retain its original alpha channel")
                webp(image, output / f"shatter-{index:02d}.webp")


def text_layer(name, value, size, y, color, index):
    # Use the same local font/document layout as the existing skill sample.
    return {
        "ddd": 0,
        "ind": index,
        "ty": 5,
        "nm": name,
        "ks": transforms(
            animated(
                [
                    (3, [-980, y, 0]),
                    (13, [156, y, 0]),
                    (58, [126, y - 12, 0]),
                    (91, [126, y - 12, 0]),
                    (106, [-980, y - 90, 0]),
                ]
            ),
            opacity=animated([(3, 0), (12, 100), (91, 100), (106, 0)]),
        ),
        "t": {
            "d": {
                "k": [
                    {
                        "t": 0,
                        "s": {
                            "t": value,
                            "s": size,
                            "f": "HarmonyOS Sans SC",
                            "j": 0,
                            "tr": 0,
                            "lh": size * 1.2,
                            "ls": 0,
                            "fc": color,
                            "sz": [780, size * 1.6],
                            "ps": [0, -size],
                        },
                    }
                ]
            },
            "p": {},
            "m": {"g": 1, "a": fixed([0, 0])},
            "a": [],
        },
        "ip": 3,
        "op": END,
        "st": 0,
        "bm": 0,
    }


def build(scripts, name, title, skill, color, source_folder, prefix, movie, alternate=None):
    directory = scripts / "images" / name
    directory.mkdir(parents=True, exist_ok=True)
    for index in range(1, 4):
        filename = f"portrait-{index}.webp"
        portrait(source_folder / f"{prefix}_{index:03d}.png", directory / filename)
        if alternate:
            portrait(
                source_folder / f"{alternate}_{index:03d}.png",
                directory / f"portrait-ex-{index}.webp",
            )
    extract_shatter(movie, directory)
    for expression in range(1, 4):
        build_script(scripts, name, title, skill, color, expression)
    (scripts / f"{name}.json").unlink(missing_ok=True)


def build_script(scripts, name, title, skill, color, expression):
    directory = scripts / "images" / name
    (directory / "stained-glass.webp").unlink(missing_ok=True)
    assets = [
        bitmap("skill-portrait", f"portrait-{expression}.webp", SLOT, name),
    ]

    layers = []

    layers.append(text_layer("role-title", title, 52, 598, [1, 0.9, 0.94], len(layers) + 1))
    layers.append(text_layer("skill-name", skill, 118, 758, [1, 1, 1], len(layers) + 1))
    line = shape_layer(
        "title-rule",
        len(layers) + 1,
        [[156, 628], [856, 628], [842, 632], [156, 632]],
        color,
        transforms(opacity=animated([(6, 0), (14, 100), (91, 100), (106, 0)])),
        op=END,
    )
    layers.append(line)

    position = animated(
        [
            (0, [2280, 130, 0]),
            (10, [840, 70, 0]),
            (58, [800, 54, 0]),
            (91, [800, 54, 0]),
            (98, [590, -70, 0]),
            (106, [-1420, -250, 0]),
        ]
    )
    opacity = animated([(0, 0), (8, 100), (91, 100), (106, 0)])
    layers.append(
        image_layer(
            "skill-portrait",
            len(layers) + 1,
            "skill-portrait",
            position,
            (0, 0),
            opacity,
            scale=fixed([145, 145, 100]),
            op=END,
        )
    )
    # Lottie draws earlier layers on top: shatter stays behind all portrait poses.
    glass_position = animated(
        [(0, [2150, 130, 0]), (10, [0, 0, 0]), (91, [0, 0, 0]), (106, [-2180, -90, 0])]
    )
    glass_opacity = animated([(0, 0), (8, 100), (91, 100), (106, 0)])
    layers.append(
        image_layer(
            "shatter-intro",
            len(layers) + 1,
            "shatter-00",
            glass_position,
            (0, 0),
            glass_opacity,
            scale=fixed([200, 200, 100]),
            op=SHATTER_START,
        )
    )
    for frame in range(31):
        asset_id = f"shatter-{frame:02d}"
        assets.append(bitmap(asset_id, f"{asset_id}.webp", (960, 540), name))
        layers.append(
            image_layer(
                asset_id,
                len(layers) + 1,
                asset_id,
                glass_position,
                (0, 0),
                glass_opacity,
                scale=fixed([200, 200, 100]),
                ip=SHATTER_START + frame,
                op=END if frame == 30 else SHATTER_START + frame + 1,
            )
        )

    layers.append(
        shape_layer(
            "colored-title-band",
            len(layers) + 1,
            [[-100, 462], [1920, 245], [1920, 840], [-100, 1055]],
            [component * 0.2 for component in color[:3]] + [1],
            transforms(glass_position, opacity=animated([(0, 0), (8, 92), (91, 92), (106, 0)])),
            op=END,
        )
    )
    result = composition(name, layers, assets, END)
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
    result["markers"] = [
        {"tm": 0, "cm": "intro", "dr": 10},
        {"tm": 10, "cm": "hold", "dr": 50},
        {"tm": 60, "cm": "shatter", "dr": 31},
        {"tm": 91, "cm": "exit", "dr": 17},
    ]
    target = scripts / f"{name}-{expression}.json"
    # Native Lottie consumes a shape's type before its properties; keep insertion order.
    target.write_text(
        json.dumps(result, ensure_ascii=True, allow_nan=False, separators=(",", ":")),
        encoding="utf-8",
    )
    dependencies = [scripts / asset["u"] / asset["p"] for asset in assets if "p" in asset]
    if not all(path.is_file() for path in dependencies):
        raise ValueError("A generated animation dependency is missing")
    total = target.stat().st_size + sum(path.stat().st_size for path in directory.glob("*.webp"))
    print(f"{target}: {END}/30 seconds, 31 shatter frames, {total:,} bytes")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "resources/animation")
    args = parser.parse_args()
    source = args.source_dir / "(\u7d20\u6750)"
    scripts = args.output_dir / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    build(
        scripts,
        "emma-interrupt",
        "\u827e\u739b",
        "\u6253\u65ad\u53d1\u8a00",
        [0.83, 0.3, 0.6, 1],
        source / "assets-Ema",
        "RefuteCutIn_Ema",
        source / "assets-Ema" / "\u7834\u788efinal\u53cd\u827e\u739b.mov",
    )
    build(
        scripts,
        "hiro-forgery",
        "\u5e0c\u7f57",
        "\u4f2a\u8bc1",
        [0.86, 0.12, 0.22, 1],
        source / "assets-hiro",
        "Hiro_CutIn",
        source / "\u7834\u788efinal\u53cd.mov",
        "Hiro_C",
    )


if __name__ == "__main__":
    main()
