"""聊天提及和撤回：实际 HTTP/WebSocket 口径及旧库迁移。"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import storage
from backend.app.game import DEFAULT_CODEX
from backend.app.main import app


class ChatInteractions(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        data_patch = patch.object(storage, "DATA_DIR", Path(directory.name))
        data_patch.start()
        self.addCleanup(data_patch.stop)
        env_patch = patch.dict(os.environ, {
            "GAME_DATA_DIR": directory.name,
            "GAME_GATEWAY_TOKEN": "test-gateway-secret",
            "GAME_QQ_GROUP_ID": "123456",
            "GAME_ADMIN_QQ": "10001",
        })
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.client = TestClient(app, base_url="http://testserver", headers={"Origin": "http://testserver"})
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.host = self.login("10001", host=True)
        created = self.client.post("/api/games", headers=self.host, json={"codex": DEFAULT_CODEX})
        created.raise_for_status()
        self.root = "/api/games/" + created.json()["id"]
        self.client.post(self.root + "/host/enter", headers=self.host).raise_for_status()
        self.command(self.host, "room.open_join", {"open": True})

    def login(self, qq, host=False):
        prefix = "/api/native/auth/host" if host else "/api/native/auth"
        challenge = self.client.post(prefix + "/challenges").json()
        response = self.client.post("/api/internal/qq/login", headers={"X-Gateway-Token": "test-gateway-secret"}, json={
            "code": challenge["code"], "qq_id": qq, "nickname": "QQ" + qq,
            "avatar_url": "https://example.invalid/" + qq, "group_id": 123456,
        })
        response.raise_for_status()
        completed = self.client.get(prefix + "/challenges/" + challenge["id"])
        completed.raise_for_status()
        return {"Authorization": "Bearer " + completed.json()["session_token"]}

    def join(self, qq, kind="player"):
        headers = self.login(qq)
        response = self.client.post(self.root + "/participations", headers=headers, json={"kind": kind})
        response.raise_for_status()
        return headers, response.json()["actor"]

    def command(self, headers, action, payload):
        version = self.client.get(self.root + "/state", headers=headers).json()["version"]
        response = self.client.post(self.root + "/commands", headers=headers, json={
            "expected_version": version, "action": action, "payload": payload,
        })
        response.raise_for_status()
        return response.json()

    def send(self, headers, channel, text, **extra):
        response = self.client.post(self.root + "/messages", headers=headers, json={
            "channel_id": channel, "text": text, **extra,
        })
        response.raise_for_status()
        return response.json()

    def history(self, headers, message_id):
        page = self.client.get(self.root + "/messages", headers=headers)
        page.raise_for_status()
        return next((m for m in page.json()["messages"] if m["id"] == message_id), None)

    def test_public_private_and_self_mentions_use_visible_occupied_player_ids(self):
        first, a = self.join("21001")
        second, b = self.join("21002")
        third, c = self.join("21003")
        spectator, _ = self.join("21004", "spectator")
        public = self.send(first, "public", f"@{b['seat_id']}号 @{b['seat_id']}号 @{a['seat_id']}号 @9号 @11号")
        self.assertEqual(public["mention_ids"], [b["id"]])
        self.assertEqual(self.history(second, public["id"])["mention_ids"], [b["id"]])
        self.assertEqual(self.history(third, public["id"])["mention_ids"], [b["id"]])
        self.assertIsNone(self.history(spectator, public["id"]))
        forged = self.client.post(self.root + "/messages", headers=first, json={
            "channel_id": "public", "text": "不含提及", "mention_ids": [b["id"]],
        })
        self.assertEqual(forged.status_code, 422)
        # 主持建的频道直接生效；外部席位、自己及同名伪 token 都不是收件人。
        created = self.command(self.host, "channel.create", {"participant_ids": [a["id"], b["id"]]})
        private = next(item["id"] for item in created["channels"] if item["id"].startswith("private:"))
        text = f"@{b['seat_id']}号 @{c['seat_id']}号 @{a['seat_id']}号 @9号"
        sent = self.send(first, private, text)
        self.assertEqual(sent["mention_ids"], [b["id"]])
        self.assertEqual(self.history(second, sent["id"])["mention_ids"], [b["id"]])
        self.assertIsNone(self.history(third, sent["id"]))
        recalled = self.client.post(self.root + f"/messages/{sent['id']}/retract", headers=first, json={})
        recalled.raise_for_status()
        self.assertEqual(self.history(second, sent["id"]), recalled.json())
        self.assertIsNone(self.history(third, sent["id"]))
        # 未占席座号及观战频道即使带相同 token 也不能引发提及。
        empty = next(str(n) for n in range(1, 8) if str(n) not in {a["seat_id"], b["seat_id"], c["seat_id"]})
        self.assertEqual(self.send(self.host, "spectator", f"@{b['seat_id']}号")["mention_ids"], [])
        self.assertEqual(self.send(self.host, "public", f"@{empty}号")["mention_ids"], [])

    def test_retract_persists_same_id_redacted_to_history_and_realtime(self):
        first, a = self.join("22001")
        second, b = self.join("22002")
        with self.client.websocket_connect("/api/live", headers=second) as socket:
            self.assertEqual(socket.receive_json()["type"], "sync")
            sent = self.send(first, "public", f"@{b['seat_id']}号 保留位置")
            frame = next(frame for _ in range(5) if (frame := socket.receive_json())["type"] == "message")
            self.assertEqual(frame["type"], "message")
            self.assertEqual(frame["message"]["mention_ids"], [b["id"]])
            endpoint = self.root + f"/messages/{sent['id']}/retract"
            self.assertEqual(self.client.post(endpoint, headers=second, json={}).status_code, 403)
            self.assertEqual(self.client.post(endpoint, headers=first, json={"as_seat": b["seat_id"]}).status_code, 403)
            with storage.transaction() as db:
                db.execute("UPDATE messages SET image_id=?,payload=? WHERE id=?", (
                    "private-image", '{"type":"extra"}', sent["id"],
                ))
            # 本局结束后的旧聊天仍可由原发送身份撤回。
            with storage.transaction() as db:
                game = storage.load_game(db, self.root.removeprefix("/api/games/"))
                game["status"] = "ended"
                storage.save_game(db, game)
            recalled = self.client.post(endpoint, headers=first, json={})
            recalled.raise_for_status()
            result = recalled.json()
            self.assertEqual(result["id"], sent["id"])
            self.assertEqual(result["created_at"], sent["created_at"])
            self.assertEqual(result["sender_id"], a["id"])
            self.assertEqual(result["text"], "")
            self.assertTrue(result["recalled"])
            self.assertEqual(result["mention_ids"], [])
            self.assertNotIn("image_id", result)
            self.assertNotIn("payload", result)
            frame = next(frame for _ in range(5) if (frame := socket.receive_json())["type"] == "message")
            self.assertEqual(frame, {"type": "message", "message": result})
            self.assertEqual(self.history(second, sent["id"]), result)
            self.assertEqual(self.client.post(endpoint, headers=first, json={}).status_code, 409)
            with storage.connect() as db:
                row = db.execute("SELECT * FROM messages WHERE id=?", (sent["id"],)).fetchone()
                self.assertIsNotNone(row["recalled_at"])
                self.assertEqual((row["text"], row["mention_ids"], row["payload"], row["image_id"]), ("", "[]", None, None))

    def test_retract_nonchat_and_host_without_sender_identity_forbidden(self):
        first, actor = self.join("23001")
        sent = self.send(first, "public", "只由本人撤回")
        self.assertEqual(self.client.post(self.root + f"/messages/{sent['id']}/retract", headers=self.host, json={}).status_code, 403)
        with storage.connect() as db:
            notice_id = db.execute("SELECT id FROM messages WHERE game_id=? AND kind='notice' LIMIT 1", (self.root.removeprefix("/api/games/"),)).fetchone()["id"]
        self.assertEqual(self.client.post(self.root + f"/messages/{notice_id}/retract", headers=self.host, json={}).status_code, 403)
        self.assertEqual(self.client.post(self.root + "/messages/999999/retract", headers=first, json={}).status_code, 404)
        # 合法主持代操作必须明确指定原发送席位，不能作为主持人直接抹除玩家消息。
        delegated = self.client.post(self.root + f"/messages/{sent['id']}/retract", headers=self.host, json={"as_seat": actor["seat_id"]})
        delegated.raise_for_status()
        self.assertTrue(delegated.json()["recalled"])
        own = self.send(self.host, "public", "主持人此前的聊天")
        with storage.transaction() as db:
            game = storage.load_game(db, self.root.removeprefix("/api/games/"))
            game["host_entries"] = []
            storage.save_game(db, game)
        self.assertEqual(self.client.post(self.root + f"/messages/{own['id']}/retract", headers=self.host, json={}).status_code, 403)


    def test_existing_message_table_migrates_without_changing_old_history(self):
        with tempfile.TemporaryDirectory() as legacy_dir:
            with patch.object(storage, "DATA_DIR", Path(legacy_dir)):
                with storage.transaction() as db:
                    db.execute("""CREATE TABLE messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT, game_id TEXT NOT NULL, kind TEXT NOT NULL,
                        sender_id TEXT NOT NULL, sender_name TEXT NOT NULL, avatar_role_id TEXT,
                        channel_id TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL,
                        audience TEXT, image_id TEXT, payload TEXT)""")
                    db.execute("""INSERT INTO messages(game_id,kind,sender_id,sender_name,channel_id,text,created_at)
                        VALUES('old','chat','original','玩家','public','以前的消息','2000-01-01')""")
                storage.initialize()
                storage.initialize()
                with storage.connect() as db:
                    row = db.execute("SELECT * FROM messages WHERE game_id='old'").fetchone()
                    self.assertEqual(storage.message_view(row, {"kind": "player", "access_ids": ["original"]})["mention_ids"], [])
                    self.assertFalse(storage.message_view(row, {"kind": "player", "access_ids": ["original"]})["recalled"])
                    self.assertEqual(row["text"], "以前的消息")
