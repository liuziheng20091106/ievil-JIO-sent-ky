"""Isolated resource ZIP uploads and per-URL Cloudflare cache purge boundaries."""

import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch

from backend.app import resource_packs as packs, storage

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "resource_uploads", ROOT / "tools/upload-resources.py"
)
assert spec is not None and spec.loader is not None
uploader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(uploader)


class ResourceUploads(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.resources = self.root / "resources"
        for pack, name, body in (
            ("animation", "frame.png", b"frame"),
            ("memes", "face.gif", b"face"),
        ):
            directory = self.resources / pack
            directory.mkdir(parents=True)
            (directory / name).write_bytes(body)
            packs.update_manifest(self.resources, pack)
        self.data = self.root / "data"
        self.data.mkdir()
        self.env_file = self.root / "release.env"
        self.env_patch = patch.dict(os.environ, {}, clear=True)
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        data_patch = patch.object(storage, "DATA_DIR", self.data)
        data_patch.start()
        self.addCleanup(data_patch.stop)
        self.events = []
        self.objects = {}
        self.types = {}
        self.purged = set()
        self.posts = []
        self.archives_ready = []
        self.require_purge = False
        self.failure = None
        self.failed_digest = hashlib.md5(b"face").hexdigest()
        self.old_url = "https://old.example/resources/" + "0" * 32
        self.old_record = {"path": "memes/old.gif", "size": 3, "md5": "0" * 32}
        self.log = self.data / "resource-uploads.json"
        self.log.write_text(json.dumps({self.old_url: self.old_record}), encoding="utf-8")

    def start_server(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def reply(self, status, body=b"", headers=None):
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                self.end_headers()
                if body:
                    self.wfile.write(body)

            def do_PUT(self):
                owner.archives_ready.append(
                    all(
                        (owner.data / "resource-archives" / f"{pack}.json").is_file()
                        for pack in packs.PACKS
                    )
                )
                digest = self.path.rsplit("/", 1)[-1]
                owner.events.append(("PUT", digest))
                owner.objects[digest] = self.rfile.read(int(self.headers["Content-Length"]))
                owner.types[digest] = self.headers["Content-Type"]
                self.reply(200)

            def do_HEAD(self):
                digest = self.path.rsplit("/", 1)[-1]
                owner.events.append(("HEAD", digest))
                body = owner.objects[digest]
                size = len(body)
                if owner.failure == "remote" and digest == owner.failed_digest:
                    size += 1
                self.send_response(200)
                self.send_header("Content-Length", str(size))
                self.send_header("ETag", f'"{hashlib.md5(body).hexdigest()}"')
                self.end_headers()

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                owner.posts.append((self.path, self.headers["Authorization"], payload))
                digest = payload["files"][0].rsplit("/", 1)[-1]
                owner.events.append(("POST", digest))
                success = not (owner.failure == "purge" and digest == owner.failed_digest)
                if success:
                    owner.purged.add(digest)
                self.reply(200, json.dumps({"success": success}).encode("utf-8"))

            def do_GET(self):
                digest = self.path.rsplit("/", 1)[-1]
                owner.events.append(("GET", digest))
                if owner.require_purge and digest not in owner.purged:
                    self.reply(404)
                    return
                body = owner.objects[digest]
                size = len(body)
                if owner.failure == "public" and digest == owner.failed_digest:
                    size += 1
                self.reply(206, body[:1], {"Content-Range": f"bytes 0-0/{size}"})

            def log_message(self, *_):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(server.shutdown)
        self.base = f"http://127.0.0.1:{server.server_port}"
        self.env_file.write_text(
            f"S3_ENDPOINT={self.base}\nS3_BUCKET=bucket\n"
            "S3_ACCESS_KEY_ID=test-key\nS3_SECRET_ACCESS_KEY=test-secret\n"
            f"S3_PUBLIC_BASE={self.base}\n",
            encoding="utf-8",
        )

    def upload(self):
        request_once = uploader.release.request_once

        def route(url, *args, **kwargs):
            if url.startswith("https://api.cloudflare.com/"):
                self.assertEqual(
                    url, "https://api.cloudflare.com/client/v4/zones/test-zone/purge_cache"
                )
                url = self.base + "/purge"
            return request_once(url, *args, **kwargs)

        argv = [
            "upload-resources.py",
            "--env",
            str(self.env_file),
            "--resources-dir",
            str(self.resources),
            "--prefix",
            "test/resources",
        ]
        with (
            patch.object(sys, "argv", argv),
            patch.object(uploader.release, "request_once", side_effect=route),
            redirect_stdout(io.StringIO()),
        ):
            return uploader.main()

    def test_uploads_both_local_archives_and_reuploads_logged_objects(self):
        self.start_server()
        self.assertEqual(self.upload(), 0)
        first_digests = set(self.objects)
        self.assertEqual(len(first_digests), 4)
        self.assertEqual(self.archives_ready, [True] * 4)
        records = packs.load_upload_log(self.log)
        self.assertEqual(records[self.old_url], self.old_record)
        for pack in packs.PACKS:
            metadata = json.loads((self.data / "resource-archives" / f"{pack}.json").read_text())
            digest = metadata["md5"]
            archive = self.data / "resource-archives" / f"{digest}.zip"
            self.assertEqual(archive.read_bytes(), self.objects[digest])
            self.assertEqual(self.types[digest], "application/zip")
            self.assertEqual(
                records[f"{self.base}/test/resources/{digest}"],
                {"path": f"archives/{pack}.zip", "size": metadata["size"], "md5": digest},
            )
        self.assertEqual(self.posts, [])
        self.events.clear()
        self.require_purge = True
        with patch.dict(os.environ, {"CF_API_TOKEN": "test-token", "CF_ZONE_ID": "test-zone"}):
            self.assertEqual(self.upload(), 0)
        self.assertEqual(
            {digest for method, digest in self.events if method == "PUT"}, first_digests
        )
        for digest in first_digests:
            self.assertEqual(
                [method for method, current in self.events if current == digest],
                ["PUT", "HEAD", "POST", "GET"],
            )
        self.assertEqual(len(self.posts), 4)
        for path, authorization, payload in self.posts:
            self.assertEqual(path, "/purge")
            self.assertEqual(authorization, "Bearer test-token")
            self.assertEqual(set(payload), {"files"})
            self.assertEqual(len(payload["files"]), 1)
            self.assertIn(payload["files"][0], records)

    def test_failed_stage_keeps_other_successes_and_prior_records(self):
        self.start_server()
        self.require_purge = True
        for failure in ("remote", "purge", "public"):
            with self.subTest(failure=failure):
                self.failure = failure
                self.events.clear()
                self.log.write_text(json.dumps({self.old_url: self.old_record}), encoding="utf-8")
                with patch.dict(
                    os.environ, {"CF_API_TOKEN": "test-token", "CF_ZONE_ID": "test-zone"}
                ):
                    with self.assertRaises((ValueError, uploader.release.ReleaseError)):
                        self.upload()
                records = packs.load_upload_log(self.log)
                self.assertEqual(len(records), 4)
                self.assertEqual(records[self.old_url], self.old_record)
                self.assertNotIn(f"{self.base}/test/resources/{self.failed_digest}", records)
                methods = [method for method, digest in self.events if digest == self.failed_digest]
                expected = ["PUT", "HEAD"]
                if failure != "remote":
                    expected.append("POST")
                if failure == "public":
                    expected.append("GET")
                self.assertEqual(methods, expected)

    def test_incomplete_cache_config_and_corrupt_log_fail_before_network(self):
        self.start_server()
        for config in ({"CF_API_TOKEN": "test-token"}, {"CF_ZONE_ID": "test-zone"}, {}):
            with self.subTest(config=config):
                if not config:
                    self.log.write_text("{broken", encoding="utf-8")
                with (
                    patch.dict(os.environ, config),
                    self.assertRaises((ValueError, uploader.release.ReleaseError)),
                ):
                    self.upload()
                self.assertEqual(self.events, [])

    def test_cache_config_reads_file_and_environment_override(self):
        self.env_file.write_text(
            "CF_API_TOKEN=file-token\nCF_ZONE_ID=file-zone\n", encoding="utf-8"
        )
        values = uploader.release.load_env(self.env_file)
        self.assertIsNone(uploader.cache_config({}))
        self.assertEqual(uploader.cache_config(values), ("file-token", "file-zone"))
        with patch.dict(os.environ, {"CF_API_TOKEN": "env-token", "CF_ZONE_ID": "env-zone"}):
            self.assertEqual(uploader.cache_config(values), ("env-token", "env-zone"))
            self.assertEqual(uploader.cache_config({}), ("env-token", "env-zone"))
        with patch.dict(os.environ, {"CF_API_TOKEN": " ", "CF_ZONE_ID": " "}):
            self.assertEqual(uploader.cache_config(values), ("file-token", "file-zone"))

    def test_purge_rejects_bad_responses_without_disclosing_token(self):
        token = "private-token"
        for response in (
            (200, {}, b"not-json"),
            (200, {}, b"\xff"),
            (200, {}, b"[]"),
            (200, {}, b'{"success": 1}'),
            (200, {}, b'{"success": false}'),
            (202, {}, b'{"success": true}'),
        ):
            with self.subTest(response=response):
                with patch.object(uploader.release, "request_once", return_value=response):
                    with self.assertRaises(uploader.release.ReleaseError) as failure:
                        uploader.purge_url({}, (token, "test-zone"), "https://example.org/file")
                    self.assertNotIn(token, str(failure.exception))
        response = io.BytesIO(token.encode("utf-8"))
        error = urllib.error.HTTPError("https://example.org", 403, token, {}, response)
        with patch.object(uploader.release, "request_once", side_effect=error):
            with self.assertRaises(uploader.release.ReleaseError) as failure:
                uploader.purge_url({}, (token, "test-zone"), "https://example.org/file")
            self.assertNotIn(token, str(failure.exception))
            self.assertTrue(response.closed)
        with patch.object(
            uploader.release, "request_once", side_effect=urllib.error.URLError(token)
        ):
            with self.assertRaises(uploader.release.ReleaseError) as failure:
                uploader.purge_url({}, (token, "test-zone"), "https://example.org/file")
            self.assertNotIn(token, str(failure.exception))


if __name__ == "__main__":
    unittest.main()
