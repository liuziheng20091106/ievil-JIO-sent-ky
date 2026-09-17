"""从 img/月代雪.png 生成各端 app 图标。

用法（在项目根目录执行）：
    .venv/Scripts/python.exe tools/gen_app_icons.py

生成内容：
    client/windows/runner/resources/app_icon.ico   Windows 可执行文件图标
    client/android/app/src/main/res/mipmap-*/ic_launcher.png          传统启动图标
    client/android/app/src/main/res/mipmap-*/ic_launcher_foreground.png  自适应图标前景
    client/android/app/src/main/res/values/ic_launcher_background.xml   自适应图标底色
    client/android/app/src/main/res/mipmap-anydpi-v26/ic_launcher.xml   自适应图标声明
    frontend/public/favicon.ico / favicon.png / apple-touch-icon.png    Web 图标

源图是透明背景的圆形胸像：图标保留圆形、四周透明，不做方形底板。
自适应图标的前景按 Android 安全区（66/108）缩放，圆形胸像因此完整落在裁切区内。
"""

from __future__ import annotations

import io
import struct
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "img" / "月代雪.png"

# 应用主题底色（frontend/index.html 的 theme-color），用作自适应图标背景。
ADAPTIVE_BACKGROUND = "#191721"

# Android 自适应图标：108dp 画布中仅中间 72dp 可见，安全区为 66dp。
ADAPTIVE_CANVAS = 108
ADAPTIVE_SAFE = 66

ANDROID_MIPMAPS = {
    "mdpi": 48,
    "hdpi": 72,
    "xhdpi": 96,
    "xxhdpi": 144,
    "xxxhdpi": 192,
}

WINDOWS_ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]
WEB_FAVICON_SIZES = [16, 32, 48]
APPLE_TOUCH_SIZE = 180


def load_source() -> Image.Image:
    if not SOURCE.exists():
        raise SystemExit(f"找不到源图：{SOURCE}")
    image = Image.open(SOURCE).convert("RGBA")
    if image.width != image.height:
        raise SystemExit(f"源图必须是正方形，当前为 {image.width}x{image.height}")
    return image


def strip_padding(image: Image.Image) -> Image.Image:
    """裁掉源图四周的全透明边缘，让圆形胸像紧贴方形画布。"""
    bbox = image.getchannel("A").getbbox()
    if bbox is None:
        raise SystemExit("源图完全透明，无法生成图标")
    cropped = image.crop(bbox)
    size = max(cropped.width, cropped.height)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(cropped, ((size - cropped.width) // 2, (size - cropped.height) // 2))
    return canvas


def render(source: Image.Image, size: int, scale: float = 1.0) -> Image.Image:
    """把源图等比缩放到画布内。scale<1 时在四周留出透明边距。"""
    inner = max(1, round(size * scale))
    resized = source.resize((inner, inner), Image.LANCZOS)
    if inner == size:
        return resized
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    offset = (size - inner) // 2
    canvas.paste(resized, (offset, offset))
    return canvas


def save_ico(image: Image.Image, target: Path, sizes: list[int]) -> None:
    """写入多尺寸 ICO。

    Pillow 的 ICO 编码器会把多帧合成交给系统编码器，在部分环境下只写出最上面
    一帧（甚至写出非法目录），因此这里显式拼装包含 PNG 帧的 ICO 文件。
    """
    entries = []
    for size in sizes:
        buffer = io.BytesIO()
        render(image, size).save(buffer, format="PNG", optimize=True)
        entries.append((size, buffer.getvalue()))

    header = struct.pack("<HHH", 0, 1, len(entries))
    offset = len(header) + 16 * len(entries)
    directory = bytearray()
    payload = bytearray()
    for size, data in entries:
        dimension = 0 if size >= 256 else size
        directory += struct.pack(
            "<BBBBHHII",
            dimension,
            dimension,
            0,
            0,
            1,
            32,
            len(data),
            offset,
        )
        offset += len(data)
        payload += data

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(header + bytes(directory) + bytes(payload))


def write_windows_ico(source: Image.Image) -> Path:
    target = ROOT / "client" / "windows" / "runner" / "resources" / "app_icon.ico"
    save_ico(source, target, WINDOWS_ICO_SIZES)
    return target


def write_android(source: Image.Image) -> list[Path]:
    written: list[Path] = []
    res = ROOT / "client" / "android" / "app" / "src" / "main" / "res"

    # 传统启动图标：与源图一致，圆形胸像四周透明。
    for density, size in ANDROID_MIPMAPS.items():
        directory = res / f"mipmap-{density}"
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / "ic_launcher.png"
        render(source, size).save(target, format="PNG", optimize=True)
        written.append(target)

    # 自适应图标前景：按安全区缩放，透明背景。
    for density, size in ANDROID_MIPMAPS.items():
        directory = res / f"mipmap-{density}"
        target = directory / "ic_launcher_foreground.png"
        foreground = render(
            source, size, scale=ADAPTIVE_SAFE / ADAPTIVE_CANVAS
        )
        foreground.save(target, format="PNG", optimize=True)
        written.append(target)

    values = res / "values"
    values.mkdir(parents=True, exist_ok=True)
    background = values / "ic_launcher_background.xml"
    background.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        "<resources>\n"
        f'    <color name="ic_launcher_background">{ADAPTIVE_BACKGROUND}</color>\n'
        "</resources>\n",
        encoding="utf-8",
    )
    written.append(background)

    anydpi = res / "mipmap-anydpi-v26"
    anydpi.mkdir(parents=True, exist_ok=True)
    launcher = anydpi / "ic_launcher.xml"
    launcher.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
        '    <background android:drawable="@color/ic_launcher_background" />\n'
        '    <foreground android:drawable="@mipmap/ic_launcher_foreground" />\n'
        "</adaptive-icon>\n",
        encoding="utf-8",
    )
    written.append(launcher)
    return written


def write_web(source: Image.Image) -> list[Path]:
    written: list[Path] = []
    public = ROOT / "frontend" / "public"
    public.mkdir(parents=True, exist_ok=True)

    favicon = public / "favicon.ico"
    save_ico(source, favicon, WEB_FAVICON_SIZES)
    written.append(favicon)

    favicon_png = public / "favicon.png"
    render(source, 512).save(favicon_png, format="PNG", optimize=True)
    written.append(favicon_png)

    apple = public / "apple-touch-icon.png"
    render(source, APPLE_TOUCH_SIZE).save(apple, format="PNG", optimize=True)
    written.append(apple)
    return written


def main() -> int:
    source = strip_padding(load_source())
    written = [write_windows_ico(source)]
    written.extend(write_android(source))
    written.extend(write_web(source))
    for path in written:
        print(f"写入 {path.relative_to(ROOT)}")
    print(f"完成，共 {len(written)} 个文件。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
