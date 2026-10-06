"""Real FFmpeg compression protects complete songs, backups and failed inputs."""

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "compress-audio.py"
LIMIT = 2_000_000


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg unavailable")
class AudioCompression(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="audio-compression-check-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.resources = self.root / "resources"
        self.audio = self.resources / "audio"
        self.audio.mkdir(parents=True)
        self.backups = self.root / "backups"

    def generate(self, target, seconds=70, *, codec="libmp3lame"):
        target.parent.mkdir(parents=True, exist_ok=True)
        command = [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
            "-t",
            str(seconds),
            "-ac",
            "2",
            "-c:a",
            codec,
        ]
        if codec == "libmp3lame":
            command += ["-b:a", "320k"]
        subprocess.run(command + [str(target)], check=True, capture_output=True, timeout=30)

    def run_cli(self, *args):
        return subprocess.run(
            [
                sys.executable,
                "-X",
                "utf8",
                str(SCRIPT),
                "--resources-dir",
                str(self.resources),
                "--backup-dir",
                str(self.backups),
                *args,
            ],
            cwd=self.root,
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
            timeout=90,
        )

    def probe(self, path):
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return float(json.loads(result.stdout)["format"]["duration"])

    def test_unicode_nested_complete_song_backed_up_and_small_song_untouched(self):
        large = self.audio / "中文目录" / "歌曲 带空格.mp3"
        small = self.audio / "小曲.mp3"
        self.generate(large)
        self.generate(small, 1)
        self.assertGreater(large.stat().st_size, LIMIT)
        original_hash = digest(large)
        small_hash = digest(small)
        seconds = self.probe(large)
        planned = self.run_cli("--dry-run")
        self.assertEqual(planned.returncode, 0, planned.stderr)
        self.assertEqual(digest(large), original_hash)
        self.assertFalse(self.backups.exists())
        self.assertFalse((self.audio / "manifest.json").exists())
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertLess(large.stat().st_size, LIMIT)
        self.assertAlmostEqual(self.probe(large), seconds, delta=0.35)
        self.assertEqual(digest(small), small_hash)
        backed_up = list(self.backups.rglob("歌曲 带空格.mp3"))
        self.assertEqual(len(backed_up), 1)
        self.assertEqual(digest(backed_up[0]), original_hash)
        manifest = json.loads((self.audio / "manifest.json").read_text(encoding="utf-8"))
        entry = next(
            item for item in manifest["files"] if item["path"] == "中文目录/歌曲 带空格.mp3"
        )
        self.assertEqual(entry["size"], large.stat().st_size)
        self.assertEqual(entry["md5"], hashlib.md5(large.read_bytes()).hexdigest())
        compressed_hash = digest(large)
        repeated = self.run_cli()
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(digest(large), compressed_hash)
        self.assertEqual(len(list(self.backups.rglob("歌曲 带空格.mp3"))), 1)
        self.assertEqual(list(self.audio.rglob(".audio-compress-*")), [])

    def test_lossless_conversion_and_invalid_or_colliding_inputs_preserve_originals(self):
        convertible = self.audio / "转格式.wav"
        colliding = self.audio / "重名.wav"
        occupied = colliding.with_suffix(".mp3")
        invalid = self.audio / "损坏.mp3"
        self.generate(convertible, 15, codec="pcm_s16le")
        self.generate(colliding, 15, codec="pcm_s16le")
        self.generate(occupied, 1)
        invalid.write_bytes(b"not audio\n" * 250000)
        before = {path: digest(path) for path in (convertible, colliding, occupied, invalid)}
        result = self.run_cli()
        self.assertEqual(result.returncode, 1, result.stderr)
        target = convertible.with_suffix(".mp3")
        self.assertFalse(convertible.exists())
        self.assertLess(target.stat().st_size, LIMIT)
        self.assertAlmostEqual(self.probe(target), 15, delta=0.35)
        self.assertEqual(digest(next(self.backups.rglob("转格式.wav"))), before[convertible])
        for path in (colliding, occupied, invalid):
            self.assertEqual(digest(path), before[path])
        self.assertEqual(list(self.audio.rglob(".audio-compress-*")), [])


if __name__ == "__main__":
    unittest.main()
