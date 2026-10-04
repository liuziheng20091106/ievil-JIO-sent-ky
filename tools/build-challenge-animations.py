"""Clone existing Lottie templates for full-room challenge-success animations."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "resources/animation/scripts"
TEMPLATES = (
    ("emma-interrupt-2", "emma-challenge-success"),
    ("hiro-forgery-3", "hiro-challenge-success"),
    ("skill-cut-in", "challenge-success"),
)


def main():
    for source, name in TEMPLATES:
        animation = json.loads((SCRIPTS / f"{source}.json").read_text(encoding="utf-8"))
        animation["nm"] = name
        text_layers = {layer["nm"]: layer for layer in animation["layers"] if layer["ty"] == 5}
        assert {"role-title", "skill-name"} <= text_layers.keys()
        for keyframe in text_layers["skill-name"]["t"]["d"]["k"]:
            keyframe["s"]["t"] = "\u8d28\u7591\u6210\u529f"
        if name == "challenge-success":
            for keyframe in text_layers["role-title"]["t"]["d"]["k"]:
                keyframe["s"]["t"] = "\u8d28\u7591\u8005"
        assert any(asset["id"] == "skill-portrait" for asset in animation["assets"])
        dependencies = [
            SCRIPTS / asset["u"] / asset["p"] for asset in animation["assets"] if "p" in asset
        ]
        if not all(path.is_file() for path in dependencies):
            raise ValueError(f"Missing template image dependency: {source}")
        target = SCRIPTS / f"{name}.json"
        target.write_text(
            json.dumps(animation, ensure_ascii=True, allow_nan=False, separators=(",", ":")),
            encoding="utf-8",
        )
        print(
            f"{target.name}: {animation['op'] - animation['ip']}/{animation['fr']} seconds, "
            f"{len(dependencies)} existing image dependencies"
        )


if __name__ == "__main__":
    main()
