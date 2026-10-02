"""Isolated publication, integrity and public download boundaries."""

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app import resource_packs as packs, resources_api


class ResourcePacks(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        for pack in packs.PACKS:
            (self.root / pack).mkdir()
        (self.root / "animation" / "frame.png").write_bytes(b"frame")
        (self.root / "memes" / "face.gif").write_bytes(b"face")
        self.patch = patch.object(packs, "RESOURCES_DIR", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        app = FastAPI()
        app.include_router(resources_api.router)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def publish(self, pack="animation"):
        return packs.update_manifest(self.root, pack)

    def write_manifest(self, value, pack="animation"):
        (self.root / pack / "manifest.json").write_text(json.dumps(value), encoding="utf-8")

    def animation(self):
        return {
            "v": "5.13.0",
            "w": 1920,
            "h": 1080,
            "fr": 30,
            "ip": 0,
            "op": 120,
            "layers": [
                {"ty": 4, "shapes": [{"ty": "rc", "p": {"k": [960, 540]}, "s": {"k": [100, 100]}}]},
                {"ty": 2, "refId": "title"},
            ],
            "assets": [{"id": "title", "u": "images/", "p": "title.png", "e": 0}],
        }

    def write_animation(self, value, path="scripts/start.json"):
        script = self.root / "animation" / path
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(json.dumps(value), encoding="utf-8")
        image = script.parent / "images" / "title.png"
        image.parent.mkdir(exist_ok=True)
        image.write_bytes(b"title image")
        return script

    def test_lottie_images_shapes_versions_and_json_publication_boundary(self):
        animation = self.animation()
        script = self.write_animation(animation, "scripts/nested/start.json")
        original = self.publish()
        self.assertEqual(
            self.client.get("/api/resources/animation/files/scripts/nested/start.json").json(),
            animation,
        )
        self.assertEqual(
            self.client.get(
                "/api/resources/animation/files/scripts/nested/images/title.png"
            ).content,
            b"title image",
        )
        excluded = (
            "root.json",
            "other/start.json",
            "scripts/manifest.json",
            "scripts/nested/manifest.json",
        )
        for path in excluded:
            file = self.root / "animation" / path
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("not a Lottie script", encoding="utf-8")
        meme_script = self.root / "memes" / "scripts" / "start.json"
        meme_script.parent.mkdir()
        meme_script.write_text(json.dumps(animation), encoding="utf-8")
        self.assertEqual(self.publish(), original)
        self.assertEqual([entry["path"] for entry in self.publish("memes")["files"]], ["face.gif"])
        for path in (*excluded, "manifest.json"):
            self.assertEqual(
                self.client.get(f"/api/resources/animation/files/{path}").status_code, 404, path
            )
        for url in (
            "/api/resources/memes/files/scripts/start.json",
            "/api/resources/unknown/files/scripts/start.json",
        ):
            self.assertEqual(self.client.get(url).status_code, 404, url)
        animation["op"] = 150
        script.write_text(json.dumps(animation), encoding="utf-8")
        modified = self.publish()
        self.assertNotEqual(modified["version"], original["version"])
        self.assertEqual(packs.load_manifest(self.root, "animation"), modified)

    def test_unsafe_lottie_rejects_publication_and_read_only_api(self):
        self.write_animation(self.animation())
        valid = self.publish()
        cases = (
            ("expression", {"layers": [{"ty": 4, "ks": {"o": {"x": "time * 10"}}}]}),
            ("external font", {"fonts": {"list": [{"fPath": "https://example.org/font.ttf"}]}}),
            (
                "external directory",
                {"assets": [{"id": "title", "u": "https://example.org/", "p": "title.png"}]},
            ),
            (
                "external image",
                {"assets": [{"id": "title", "u": "", "p": "https://example.org/title.png"}]},
            ),
            ("absolute image", {"assets": [{"id": "title", "u": "", "p": "/title.png"}]}),
            ("parent directory", {"assets": [{"id": "title", "u": "../", "p": "frame.png"}]}),
            ("parent image", {"assets": [{"id": "title", "u": "images/", "p": "../title.png"}]}),
            (
                "noncanonical directory",
                {"assets": [{"id": "title", "u": "images", "p": "title.png"}]},
            ),
            ("missing image", {"assets": [{"id": "title", "u": "images/", "p": "missing.png"}]}),
            (
                "embedded image",
                {"assets": [{"id": "title", "e": 1, "u": "", "p": "data:image/png;base64,AAAA"}]},
            ),
            (
                "base64 image",
                {"assets": [{"id": "title", "e": 0, "u": "", "p": "data:image/png;base64,AAAA"}]},
            ),
            ("missing image id", {"assets": [{"u": "images/", "p": "title.png"}]}),
            (
                "duplicate image id",
                {
                    "assets": [
                        {"id": "title", "u": "images/", "p": "title.png"},
                        {"id": "title", "u": "images/", "p": "title.png"},
                    ]
                },
            ),
            ("audio layer", {"layers": [{"ty": 6}]}),
            ("precomp audio", {"assets": [{"id": "nested", "layers": [{"ty": 6}]}]}),
            ("boolean dimension", {"w": True}),
            ("huge dimension", {"h": 8193}),
            ("zero rate", {"fr": 0}),
            ("infinite rate", {"fr": float("inf")}),
            ("negative start", {"ip": -1}),
            ("empty duration", {"op": 0}),
            ("long duration", {"op": 1801}),
            ("nested nonfinite", {"layers": [{"ty": 4, "ks": {"o": {"k": float("nan")}}}]}),
        )
        for label, change in cases:
            with self.subTest(label=label):
                animation = self.animation()
                animation.update(change)
                script = self.write_animation(animation)
                self.write_manifest(valid)
                original_bytes = (self.root / "animation" / "manifest.json").read_bytes()
                with self.assertRaises(packs.ManifestError):
                    self.publish()
                self.assertEqual(
                    (self.root / "animation" / "manifest.json").read_bytes(), original_bytes
                )
                raw = script.read_bytes()
                metadata = copy.deepcopy(valid)
                entry = next(
                    item for item in metadata["files"] if item["path"] == "scripts/start.json"
                )
                entry.update(size=len(raw), md5=hashlib.md5(raw, usedforsecurity=False).hexdigest())
                metadata["total_size"] = sum(entry["size"] for entry in metadata["files"])
                metadata["version"] = packs.files_version(metadata["files"])
                self.write_manifest(metadata)
                before = (self.root / "animation" / "manifest.json").read_bytes()
                for url in (
                    "/api/resources/animation/manifest",
                    "/api/resources/animation/files/scripts/start.json",
                ):
                    self.assertEqual(self.client.get(url).status_code, 503)
                self.assertEqual((self.root / "animation" / "manifest.json").read_bytes(), before)

    def test_published_lottie_requires_fresh_script_and_published_existing_images(self):
        animation = self.animation()
        script = self.write_animation(animation)
        valid = self.publish()
        raw = script.read_bytes()
        animation["op"] = 121
        script.write_text(json.dumps(animation), encoding="utf-8")
        self.assertEqual(script.stat().st_size, len(raw))
        self.assertEqual(self.client.get("/api/resources/animation/manifest").status_code, 503)
        script.write_bytes(raw)
        image = "scripts/images/title.png"
        missing = copy.deepcopy(valid)
        missing["files"] = [entry for entry in missing["files"] if entry["path"] != image]
        missing["total_size"] = sum(entry["size"] for entry in missing["files"])
        missing["version"] = packs.files_version(missing["files"])
        self.write_manifest(missing)
        self.assertEqual(self.client.get("/api/resources/animation/manifest").status_code, 503)
        self.write_manifest(valid)
        (self.root / "animation" / image).unlink()
        self.assertEqual(
            self.client.get("/api/resources/animation/files/scripts/start.json").status_code, 503
        )

    def test_fingerprint_tracks_add_modify_delete_but_not_nonmedia(self):
        original = self.publish()
        stable_bytes = (self.root / "animation" / "manifest.json").read_bytes()
        (self.root / "animation" / "notes.txt").write_text("private instructions")
        (self.root / "animation" / ".draft.png").write_bytes(b"draft")
        self.assertEqual(self.publish(), original)
        self.assertEqual((self.root / "animation" / "manifest.json").read_bytes(), stable_bytes)
        addition = self.root / "animation" / "extra.webp"
        addition.write_bytes(b"extra")
        self.assertNotEqual(self.publish()["version"], original["version"])
        addition.unlink()
        self.assertEqual(self.publish()["version"], original["version"])
        (self.root / "animation" / "frame.png").write_bytes(b"other")
        self.assertNotEqual(self.publish()["version"], original["version"])
        self.assertFalse((self.root / "memes" / "manifest.json").exists())

    def test_public_downloads_require_published_pack_and_exact_file(self):
        self.assertEqual(self.client.get("/api/resources/animation/manifest").status_code, 404)
        self.publish()
        self.publish("memes")
        self.assertEqual(
            self.client.get("/api/resources/animation/files/frame.png").content, b"frame"
        )
        for url in (
            "/api/resources/unknown/manifest",
            "/api/resources/memes/files/frame.png",
            "/api/resources/animation/files/notes.txt",
            "/api/resources/animation/files/%2E%2E/memes/face.gif",
            "/api/resources/animation/files/C%3A/frame.png",
            "/api/resources/animation/files/%2Ehidden.png",
            "/api/resources/animation/files/a%5Cframe.png",
        ):
            self.assertEqual(self.client.get(url).status_code, 404, url)
        (self.root / "animation" / "frame.png").write_bytes(b"changed size")
        self.assertEqual(
            self.client.get("/api/resources/animation/files/frame.png").status_code, 503
        )
        (self.root / "animation" / "frame.png").unlink()
        self.assertEqual(
            self.client.get("/api/resources/animation/files/frame.png").status_code, 404
        )

    def test_corrupt_metadata_fails_closed_and_is_read_fresh(self):
        valid = self.publish()
        mutations = (
            {"pack": "memes"},
            {"version": "0" * 32},
            {"total_size": 999},
            {"total_size": True},
            {"files": [{"path": "../face.png", "size": 1, "md5": "0" * 32}]},
            {"files": valid["files"] * 2},
            {"files": [valid["files"][0], {**valid["files"][0], "path": "FRAME.png"}]},
            {"files": [{**valid["files"][0], "size": True}]},
            {"files": [{**valid["files"][0], "md5": "A" * 32}]},
            {"files": [{**valid["files"][0], "path": "CON.png"}]},
            {"files": [{**valid["files"][0], "path": "notes.txt"}]},
        )
        for change in mutations:
            value = copy.deepcopy(valid)
            value.update(change)
            self.write_manifest(value)
            self.assertEqual(
                self.client.get("/api/resources/animation/manifest").status_code, 503, change
            )
            self.assertEqual(
                self.client.get("/api/resources/animation/files/frame.png").status_code, 503, change
            )
        (self.root / "animation" / "manifest.json").write_text("{broken", encoding="utf-8")
        self.assertEqual(self.client.get("/api/resources/animation/manifest").status_code, 503)
        self.write_manifest(valid)
        self.assertEqual(self.client.get("/api/resources/animation/manifest").json(), valid)

    def test_symlink_files_and_directories_never_publish_or_download(self):
        self.publish()
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "secret.png").write_bytes(b"secret")
        try:
            (self.root / "animation" / "linked").symlink_to(outside, target_is_directory=True)
            (self.root / "animation" / "alias.png").symlink_to(outside / "secret.png")
        except OSError as error:
            self.skipTest(f"Symlinks unavailable: {error}")
        self.assertEqual([entry["path"] for entry in self.publish()["files"]], ["frame.png"])
        file = self.root / "animation" / "frame.png"
        file.unlink()
        file.symlink_to(outside / "secret.png")
        self.assertEqual(
            self.client.get("/api/resources/animation/files/frame.png").status_code, 404
        )
        with self.assertRaises(FileNotFoundError):
            packs.media_file(self.root / "animation", "linked/secret.png", "animation")

    def test_cli_runs_from_another_directory_and_selects_one_pack(self):
        script = Path(__file__).resolve().parents[1] / "tools" / "update-resource-manifests.py"
        command = [sys.executable, str(script), "--resources-dir", str(self.root)]
        result = subprocess.run(
            command + ["--pack", "memes"],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "animation" / "manifest.json").exists())
        self.assertEqual(packs.load_manifest(self.root, "memes")["files"][0]["path"], "face.gif")
        result = subprocess.run(command, cwd=self.root, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            packs.load_manifest(self.root, "animation")["files"][0]["path"], "frame.png"
        )


if __name__ == "__main__":
    unittest.main()
