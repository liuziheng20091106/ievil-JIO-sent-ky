#!/usr/bin/env python3
"""Compress oversized songs to complete MP3 files below 2,000,000 bytes."""

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.resource_packs import (  # noqa: E402
    AUDIO_SUFFIXES,
    ManifestError,
    is_link,
    media_file,
    pack_directory,
    update_manifest,
    valid_media_path,
)

MAX_BYTES = 2_000_000
BITRATES = (320, 256, 224, 192, 160, 128, 112, 96, 80, 64, 56, 48, 40, 32, 24, 16, 8)


def run(command, timeout):
    result = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode:
        raise ValueError(result.stderr.strip()[-2000:] or "FFmpeg command failed")
    return result.stdout


def duration(path):
    data = json.loads(
        run(
            [
                "ffprobe",
                "-v",
                "error",
                "-protocol_whitelist",
                "file",
                "-format_whitelist",
                "mp3,wav,ogg,flac",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=duration:format=duration",
                "-of",
                "json",
                str(path),
            ],
            30,
        )
    )
    if not data.get("streams"):
        raise ValueError("文件没有音轨")
    for value in (data["streams"][0].get("duration"), data.get("format", {}).get("duration")):
        try:
            seconds = float(value)
        except ValueError, TypeError:
            continue
        if math.isfinite(seconds) and seconds > 0:
            return seconds
    raise ValueError("无法读取完整歌曲时长")


def fingerprint(path):
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns, stat.st_ino


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").digest()


def compress(source, directory, backup_root, dry_run):
    before = fingerprint(source)
    if before[0] <= MAX_BYTES:
        return False
    target = source if source.suffix.lower() == ".mp3" else source.with_suffix(".mp3")
    if target != source and target.exists():
        raise ValueError(f"目标已存在，保留原文件：{target.name}")
    seconds = duration(source)
    budget_kbps = (MAX_BYTES - 32768) * 8 * 0.98 / seconds / 1000
    rates = [rate for rate in BITRATES if rate <= budget_kbps]
    if not rates:
        raise ValueError("完整歌曲即使使用最低 8kbps 也无法压到 2MB 内，保留原文件")
    relative = source.relative_to(directory)
    if dry_run:
        print(f"计划：{relative} ({before[0]:,} 字节) → {target.name}，{rates[0]}kbps", flush=True)
        return False
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".audio-compress-", suffix=".mp3", dir=source.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
        for rate in rates:
            sample_rate = 44100 if rate >= 32 else 22050 if rate >= 16 else 8000
            channels = 2 if rate >= 32 else 1
            print(f"压缩：{relative}，{rate}kbps", flush=True)
            run(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-v",
                    "error",
                    "-nostdin",
                    "-y",
                    "-protocol_whitelist",
                    "file",
                    "-format_whitelist",
                    "mp3,wav,ogg,flac",
                    "-i",
                    str(source),
                    "-map",
                    "0:a:0",
                    "-vn",
                    "-sn",
                    "-dn",
                    "-map_metadata",
                    "-1",
                    "-map_chapters",
                    "-1",
                    "-c:a",
                    "libmp3lame",
                    "-b:a",
                    f"{rate}k",
                    "-ar",
                    str(sample_rate),
                    "-ac",
                    str(channels),
                    str(temporary),
                ],
                max(60, seconds * 2),
            )
            if 0 < temporary.stat().st_size < MAX_BYTES:
                break
        else:
            raise ValueError("最低码率仍超出 2MB，保留原文件")
        if abs(duration(temporary) - seconds) > 0.35:
            raise ValueError("压缩后的歌曲时长不一致，保留原文件")
        run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-xerror",
                "-nostdin",
                "-i",
                str(temporary),
                "-map",
                "0:a:0",
                "-f",
                "null",
                "-",
            ],
            max(60, seconds * 2),
        )
        if fingerprint(source) != before or (target != source and target.exists()):
            raise ValueError("压缩期间源文件或目标发生变化，保留原文件")
        backup_root.mkdir(parents=True, exist_ok=True)
        backup_folder = Path(tempfile.mkdtemp(prefix="song-", dir=backup_root))
        backup = backup_folder / relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, backup)
        if fingerprint(source) != before or digest(backup) != digest(source):
            raise ValueError("原文件备份验证失败，未替换歌曲")
        # MP3 is an atomic replacement; other formats retain their original in backup.
        if target != source:
            # link is exclusive: a concurrently created target must never be overwritten.
            target.hardlink_to(temporary)
            source.unlink()
            temporary.unlink()
        else:
            temporary.replace(target)
        after = target.stat().st_size
        print(f"完成：{relative}，{before[0]:,} → {after:,} 字节；备份：{backup}", flush=True)
        return True
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="将 audio 包中超过 2MB 的完整歌曲压到 2,000,000 字节以内"
    )
    parser.add_argument("--resources-dir", type=Path, default=ROOT / "resources", help="资源根目录")
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=ROOT / "downloads" / "audio-originals",
        help="原歌曲备份目录",
    )
    parser.add_argument("--dry-run", action="store_true", help="只显示计划，不改歌曲、备份或清单")
    args = parser.parse_args(argv)
    try:
        if any(shutil.which(tool) is None for tool in ("ffmpeg", "ffprobe")):
            raise ValueError("请先安装 FFmpeg，并将 ffmpeg、ffprobe 加入 PATH")
        directory = pack_directory(args.resources_dir, "audio")
        if args.backup_dir.resolve().is_relative_to(directory.resolve()):
            raise ValueError("备份目录不能放在 audio 包内")
        songs = []

        def scan_error(error):
            raise error

        for parent, directories, names in directory.walk(
            follow_symlinks=False, on_error=scan_error
        ):
            directories[:] = [
                name
                for name in directories
                if not name.startswith((".", "~")) and not is_link(parent / name)
            ]
            for name in names:
                source = parent / name
                relative = source.relative_to(directory).as_posix()
                if (
                    source.suffix.lower() in AUDIO_SUFFIXES
                    and valid_media_path(relative, "audio")
                    and not is_link(source)
                ):
                    songs.append(media_file(directory, relative, "audio"))
        changed = failed = skipped = 0
        for source in sorted(songs):
            if source.stat().st_size <= MAX_BYTES:
                skipped += 1
                continue
            try:
                changed += compress(source, directory, args.backup_dir, args.dry_run)
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                failed += 1
                print(
                    f"失败：{source.relative_to(directory)}：{error}", file=sys.stderr, flush=True
                )
        if not args.dry_run:
            manifest = update_manifest(args.resources_dir, "audio")
            print(f"音频清单已刷新：{len(manifest['files'])} 首；未上传资源", flush=True)
        print(f"结束：压缩 {changed} 首，跳过 {skipped} 首，失败 {failed} 首", flush=True)
        return int(failed > 0)
    except (OSError, ValueError, ManifestError, subprocess.SubprocessError) as error:
        print(f"无法压缩音频：{error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
