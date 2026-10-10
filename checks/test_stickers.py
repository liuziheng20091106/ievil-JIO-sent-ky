"""MD5-only stickers through isolated HTTP, durable history and WebSocket delivery."""

import asyncio
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import realtime, resource_packs, storage
from backend.app.game import DEFAULT_CODEX
from backend.app.main import app


class Stickers(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        self.resources = root / "resources"
        memes = self.resources / "memes"
        memes.mkdir(parents=True)
        content = b"<svg xmlns='http://www.w3.org/2000/svg' width='1' height='1'/>"
        (memes / "sticker.svg").write_bytes(content)
        self.md5 = hashlib.md5(content, usedforsecurity=False).hexdigest()
        self.manifest = resource_packs.update_manifest(self.resources, "memes")
        for replacement in (
            patch.object(storage, "DATA_DIR", root / "data"),
            patch.object(resource_packs, "RESOURCES_DIR", self.resources),
            patch.dict(
                os.environ,
                {
                    "GAME_DATA_DIR": str(root / "data"),
                    "GAME_GATEWAY_TOKEN": "test-gateway-secret",
                    "GAME_QQ_GROUP_ID": "123456",
                    "GAME_ADMIN_QQ": "10001",
                },
            ),
        ):
            replacement.start()
            self.addCleanup(replacement.stop)
        self.client = TestClient(
            app,
            base_url="http://testserver",
            headers={
                "Origin": "http://testserver",
                "User-Agent": "seven-double-flutter/1.1.0 (windows)",
            },
        )
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.host = self.login("10001", host=True)
        response = self.client.post("/api/games", headers=self.host, json={"codex": DEFAULT_CODEX})
        response.raise_for_status()
        self.game_id = response.json()["id"]
        self.root = "/api/games/" + self.game_id
        self.client.post(self.root + "/host/enter", headers=self.host).raise_for_status()
        self.command("room.open_join", {"open": True})

    def login(self, qq, host=False):
        prefix = "/api/native/auth/host" if host else "/api/native/auth"
        challenge = self.client.post(prefix + "/challenges").json()
        self.client.post(
            "/api/internal/qq/login",
            headers={"X-Gateway-Token": "test-gateway-secret"},
            json={
                "code": challenge["code"],
                "qq_id": qq,
                "nickname": "QQ" + qq,
                "avatar_url": "https://example.invalid/" + qq,
                "group_id": 123456,
            },
        ).raise_for_status()
        completed = self.client.get(prefix + "/challenges/" + challenge["id"])
        completed.raise_for_status()
        return {"Authorization": "Bearer " + completed.json()["session_token"]}

    def join(self, qq, kind="player"):
        headers = self.login(qq)
        response = self.client.post(
            self.root + "/participations", headers=headers, json={"kind": kind}
        )
        response.raise_for_status()
        return headers, response.json()["actor"]

    def command(self, action, payload):
        version = self.client.get(self.root + "/state", headers=self.host).json()["version"]
        response = self.client.post(
            self.root + "/commands",
            headers=self.host,
            json={
                "expected_version": version,
                "action": action,
                "payload": payload,
            },
        )
        response.raise_for_status()
        return response.json()

    def send(self, headers, channel="public", **extra):
        response = self.client.post(
            self.root + "/messages",
            headers=headers,
            json={
                "channel_id": channel,
                "sticker_md5": self.md5,
                **extra,
            },
        )
        response.raise_for_status()
        return response.json()

    def history(self, headers):
        response = self.client.get(self.root + "/messages", headers=headers)
        response.raise_for_status()
        return {item["id"]: item for item in response.json()["messages"]}

    def socket_message(self, socket):
        while True:
            frame = socket.receive_json()
            if frame["type"] == "message":
                return frame["message"]

    def assert_sticker(self, message):
        self.assertEqual(message["kind"], "chat")
        self.assertEqual(message["text"], "")
        self.assertEqual(message["sticker_md5"], self.md5)
        self.assertEqual(message["payload"], {"type": "sticker", "md5": self.md5})
        self.assertNotIn("image_id", message)

    def test_public_history_replay_and_recall_survive_resource_removal(self):
        first, _ = self.join("31001")
        second, _ = self.join("31002")
        with self.client.websocket_connect(
            "/api/live?game_id=" + self.game_id, headers=second
        ) as socket:
            self.assertEqual(socket.receive_json()["type"], "sync")
            sent = self.send(first)
            self.assert_sticker(sent)
            self.assert_sticker(self.socket_message(socket))
            (self.resources / "memes" / "sticker.svg").unlink()
            resource_packs.update_manifest(self.resources, "memes")
            self.assert_sticker(self.history(second)[sent["id"]])
            replay = self.client.get(
                self.root + "/messages", headers=second, params={"after": sent["id"] - 1}
            )
            replay.raise_for_status()
            self.assert_sticker(next(m for m in replay.json()["messages"] if m["id"] == sent["id"]))
            self.assertEqual(
                self.client.post(
                    self.root + "/messages",
                    headers=first,
                    json={
                        "channel_id": "public",
                        "sticker_md5": self.md5,
                    },
                ).status_code,
                422,
            )
            recalled = self.client.post(
                self.root + f"/messages/{sent['id']}/retract", headers=first, json={}
            )
            recalled.raise_for_status()
            for message in (
                recalled.json(),
                self.socket_message(socket),
                self.history(second)[sent["id"]],
            ):
                self.assertTrue(message["recalled"])
                self.assertNotIn("sticker_md5", message)
                self.assertNotIn("payload", message)
                self.assertEqual(message["id"], sent["id"])
        with storage.connect() as db:
            row = db.execute("SELECT * FROM messages WHERE id=?", (sent["id"],)).fetchone()
            self.assertIsNone(row["payload"])
            self.assertIsNone(row["image_id"])

    def test_spectators_read_private_and_public_stickers_without_player_leaks(self):
        first, a = self.join("32001")
        second, b = self.join("32002")
        third, _ = self.join("32003")
        spectator, _ = self.join("32004", "spectator")
        state = self.command("channel.create", {"participant_ids": [a["id"], b["id"]]})
        private = next(c["id"] for c in state["channels"] if c["id"].startswith("private:"))

        async def disconnected():
            async with asyncio.timeout(2):
                while any(peer.game_id == self.game_id for peer in realtime.connections):
                    await asyncio.sleep(0)

        with (
            self.client.websocket_connect(
                "/api/live?game_id=" + self.game_id, headers=second
            ) as recipient,
            self.client.websocket_connect(
                "/api/live?game_id=" + self.game_id, headers=third
            ) as outsider,
            self.client.websocket_connect(
                "/api/live?game_id=" + self.game_id, headers=spectator
            ) as watcher,
        ):
            for socket in (recipient, outsider, watcher):
                self.assertEqual(socket.receive_json()["type"], "sync")
            sent = self.send(first, private)
            delivered = self.socket_message(recipient)
            self.assertEqual(delivered["id"], sent["id"])
            self.assert_sticker(delivered)
            delivered = self.socket_message(watcher)
            self.assertEqual(delivered["id"], sent["id"])
            self.assert_sticker(delivered)
            self.assert_sticker(self.history(second)[sent["id"]])
            self.assertNotIn(sent["id"], self.history(third))
            self.assert_sticker(self.history(spectator)[sent["id"]])
            self.assert_sticker(self.history(self.host)[sent["id"]])
            public = self.send(self.host)
            self.assertEqual(self.socket_message(outsider)["id"], public["id"])
            delivered = self.socket_message(watcher)
            self.assertEqual(delivered["id"], public["id"])
            self.assert_sticker(delivered)
            self.assert_sticker(self.history(spectator)[public["id"]])
            for channel in ("public", private, "spectator", "system"):
                with self.subTest(channel=channel):
                    denied = self.client.post(
                        self.root + "/messages",
                        headers=spectator,
                        json={"channel_id": channel, "sticker_md5": self.md5},
                    )
                    self.assertEqual(denied.status_code, 403, denied.text)
            self.assertEqual(set(self.history(self.host)), set(self.history(spectator)))
            for socket in (recipient, outsider, watcher):
                socket.close()
            watcher.portal.call(disconnected)
        with self.client.websocket_connect(
            "/api/live?game_id=" + self.game_id, headers=spectator
        ) as watcher:
            sync = watcher.receive_json()
            self.assertEqual(sync["type"], "sync")
            replay = {message["id"]: message for message in sync["messages"]}
            for message in (sent, public):
                self.assert_sticker(replay[message["id"]])
            watcher.close()
            watcher.portal.call(disconnected)
        with storage.connect() as db:
            row = db.execute("SELECT * FROM messages WHERE id=?", (sent["id"],)).fetchone()
            self.assertEqual(json.loads(row["payload"]), {"type": "sticker", "md5": self.md5})
            self.assertEqual(row["text"], "")
            self.assertIsNone(row["image_id"])
        denied = self.client.post(
            self.root + "/messages",
            headers=third,
            json={
                "channel_id": private,
                "sticker_md5": self.md5,
            },
        )
        self.assertEqual(denied.status_code, 403)

    def test_invalid_hashes_mixed_bodies_and_unavailable_manifests_are_rejected(self):
        player, _ = self.join("33001")
        for changes in (
            {"sticker_md5": "0" * 32},
            {"sticker_md5": self.md5.upper()},
            {"sticker_md5": " " + self.md5},
            {"sticker_md5": self.md5 + "\n"},
            {"sticker_md5": 123},
            {"sticker_md5": "abc"},
            {"text": "hello"},
            {"image": "data:image/png;base64,ZmFrZQ=="},
            {"references": [{"start": 0, "end": 1, "type": "role", "id": "host"}]},
        ):
            with self.subTest(changes=changes):
                response = self.client.post(
                    self.root + "/messages",
                    headers=player,
                    json={
                        "channel_id": "public",
                        "sticker_md5": self.md5,
                        **changes,
                    },
                )
                self.assertEqual(response.status_code, 422)
        manifest = self.resources / "memes" / "manifest.json"
        for content in ("not json", json.dumps({**self.manifest, "version": "0" * 32}), None):
            if content is None:
                manifest.unlink()
            else:
                manifest.write_text(content, encoding="utf-8")
            response = self.client.post(
                self.root + "/messages",
                headers=player,
                json={
                    "channel_id": "public",
                    "sticker_md5": self.md5,
                },
            )
            self.assertEqual(response.status_code, 503)
        with storage.connect() as db:
            self.assertEqual(
                db.execute("SELECT count(*) FROM messages WHERE kind='chat'").fetchone()[0], 0
            )

    def test_mute_and_host_enter_confirmation_apply_to_stickers(self):
        for qq, kind in (("34001", "player"), ("34002", "spectator")):
            headers, actor = self.join(qq, kind)
            self.command("room.mute", {"participant_id": actor["id"], "muted": True})
            response = self.client.post(
                self.root + "/messages",
                headers=headers,
                json={
                    "channel_id": "public",
                    "sticker_md5": self.md5,
                },
            )
            self.assertEqual(response.status_code, 403)
        other = self.login("34003")
        account = self.client.get("/api/me", headers=other)
        account.raise_for_status()
        self.client.post(
            "/api/hosts/" + account.json()["actor"]["account_id"],
            headers=self.host,
            json={"level": 5},
        ).raise_for_status()
        unconfirmed = self.login("34003", host=True)
        response = self.client.post(
            self.root + "/messages",
            headers=unconfirmed,
            json={
                "channel_id": "public",
                "sticker_md5": self.md5,
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_sticker_projection_whitelists_payload_for_every_identity(self):
        for actor in (
            {"kind": "host", "host_entered": True},
            {"kind": "player", "access_ids": ["p"]},
            {"kind": "spectator", "access_ids": ["s"]},
        ):
            raw = {"type": "sticker", "md5": self.md5, "image": "private bytes", "target": "secret"}
            self.assertEqual(
                storage.project_message_payload(raw, actor, "chat"),
                {"type": "sticker", "md5": self.md5},
            )
            self.assertIsNone(storage.project_message_payload(raw, actor, "notice"))
            self.assertIsNone(storage.project_message_payload({**raw, "md5": "bad"}, actor, "chat"))


if __name__ == "__main__":
    unittest.main()
