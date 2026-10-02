"""聊天提及和撤回：实际 HTTP/WebSocket 口径及旧库迁移。"""

import base64
import struct
import zlib
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
        env_patch = patch.dict(
            os.environ,
            {
                "GAME_DATA_DIR": directory.name,
                "GAME_GATEWAY_TOKEN": "test-gateway-secret",
                "GAME_QQ_GROUP_ID": "123456",
                "GAME_ADMIN_QQ": "10001",
            },
        )
        env_patch.start()
        self.addCleanup(env_patch.stop)
        self.client = TestClient(
            app, base_url="http://testserver", headers={"Origin": "http://testserver"}
        )
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
        response = self.client.post(
            "/api/internal/qq/login",
            headers={"X-Gateway-Token": "test-gateway-secret"},
            json={
                "code": challenge["code"],
                "qq_id": qq,
                "nickname": "QQ" + qq,
                "avatar_url": "https://example.invalid/" + qq,
                "group_id": 123456,
            },
        )
        response.raise_for_status()
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

    def command(self, headers, action, payload):
        version = self.client.get(self.root + "/state", headers=headers).json()["version"]
        response = self.client.post(
            self.root + "/commands",
            headers=headers,
            json={
                "expected_version": version,
                "action": action,
                "payload": payload,
            },
        )
        response.raise_for_status()
        return response.json()

    def send(self, headers, channel, text, **extra):
        response = self.client.post(
            self.root + "/messages",
            headers=headers,
            json={
                "channel_id": channel,
                "text": text,
                **extra,
            },
        )
        response.raise_for_status()
        return response.json()

    def history(self, headers, message_id):
        page = self.client.get(self.root + "/messages", headers=headers)
        page.raise_for_status()
        return next((m for m in page.json()["messages"] if m["id"] == message_id), None)

    def test_chat_images_are_bounded_private_persistent_and_retractable(self):
        def png_data(size=0):
            def chunk(tag, data):
                return (
                    struct.pack(">I", len(data))
                    + tag
                    + data
                    + struct.pack(">I", zlib.crc32(tag + data))
                )

            png = b"\x89PNG\r\n\x1a\n"
            png += chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            png += chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
            if size:
                png += chunk(b"tEXt", b"Comment\x00" + b"x" * (size - len(png) - 32))
            png += chunk(b"IEND", b"")
            return "data:image/png;base64," + base64.b64encode(png).decode()

        first, a = self.join("25001")
        second, b = self.join("25002")
        third, _ = self.join("25003")
        created = self.command(self.host, "channel.create", {"participant_ids": [a["id"], b["id"]]})
        private = next(
            item["id"] for item in created["channels"] if item["id"].startswith("private:")
        )
        image = png_data(100 * 1024)
        self.assertEqual(len(base64.b64decode(image.split(",")[1])), 100 * 1024)
        with self.client.websocket_connect(
            "/api/live?game_id=" + self.root.rsplit("/", 1)[-1], headers=second
        ) as socket:
            socket.receive_json()
            sent = self.send(first, private, "", image=image)
            live = socket.receive_json()
            while live["type"] != "message":
                live = socket.receive_json()
            self.assertEqual(live["message"]["payload"]["image"], image)
        self.assertEqual(self.history(second, sent["id"])["payload"]["image"], image)
        self.assertIsNone(self.history(third, sent["id"]))
        with storage.connect() as db:
            row = db.execute("SELECT payload FROM messages WHERE id=?", (sent["id"],)).fetchone()
            self.assertIn(image, row["payload"])
        for invalid in (
            png_data(100 * 1024 + 1),
            "data:image/png;base64,ZmFrZQ==",
            "data:image/svg+xml;base64,PHN2Zz4=",
        ):
            response = self.client.post(
                self.root + "/messages",
                headers=first,
                json={"channel_id": private, "image": invalid},
            )
            self.assertEqual(response.status_code, 422)
        response = self.client.post(
            self.root + f"/messages/{sent['id']}/retract", headers=first, json={}
        )
        response.raise_for_status()
        self.assertNotIn("payload", self.history(second, sent["id"]))
        self.assertEqual(
            self.client.post(
                self.root + "/messages", headers=first, json={"channel_id": "public", "text": "   "}
            ).status_code,
            422,
        )

    def test_public_private_and_self_mentions_use_visible_occupied_player_ids(self):
        first, a = self.join("21001")
        second, b = self.join("21002")
        third, c = self.join("21003")
        spectator, _ = self.join("21004", "spectator")
        public = self.send(
            first, "public", f"@{b['seat_id']}号 @{b['seat_id']}号 @{a['seat_id']}号 @9号 @11号"
        )
        self.assertEqual(public["mention_ids"], [b["id"]])
        self.assertEqual(self.history(second, public["id"])["mention_ids"], [b["id"]])
        self.assertEqual(self.history(third, public["id"])["mention_ids"], [b["id"]])
        self.assertIsNone(self.history(spectator, public["id"]))
        forged = self.client.post(
            self.root + "/messages",
            headers=first,
            json={
                "channel_id": "public",
                "text": "不含提及",
                "mention_ids": [b["id"]],
            },
        )
        self.assertEqual(forged.status_code, 422)
        # 主持建的频道直接生效；外部席位、自己及同名伪 token 都不是收件人。
        created = self.command(self.host, "channel.create", {"participant_ids": [a["id"], b["id"]]})
        private = next(
            item["id"] for item in created["channels"] if item["id"].startswith("private:")
        )
        text = f"@{b['seat_id']}号 @{c['seat_id']}号 @{a['seat_id']}号 @9号"
        sent = self.send(first, private, text)
        self.assertEqual(sent["mention_ids"], [b["id"]])
        self.assertEqual(self.history(second, sent["id"])["mention_ids"], [b["id"]])
        self.assertIsNone(self.history(third, sent["id"]))
        recalled = self.client.post(
            self.root + f"/messages/{sent['id']}/retract", headers=first, json={}
        )
        recalled.raise_for_status()
        self.assertEqual(self.history(second, sent["id"]), recalled.json())
        self.assertIsNone(self.history(third, sent["id"]))
        # 未占席座号及观战频道即使带相同 token 也不能引发提及。
        empty = next(
            str(n) for n in range(1, 8) if str(n) not in {a["seat_id"], b["seat_id"], c["seat_id"]}
        )
        self.assertEqual(self.send(self.host, "spectator", f"@{b['seat_id']}号")["mention_ids"], [])
        self.assertEqual(self.send(self.host, "public", f"@{empty}号")["mention_ids"], [])

    def test_retract_persists_same_id_redacted_to_history_and_realtime(self):
        first, a = self.join("22001")
        second, b = self.join("22002")
        with self.client.websocket_connect("/api/live", headers=second) as socket:
            self.assertEqual(socket.receive_json()["type"], "sync")
            sent = self.send(first, "public", f"@{b['seat_id']}号 保留位置")
            frame = next(
                frame for _ in range(5) if (frame := socket.receive_json())["type"] == "message"
            )
            self.assertEqual(frame["type"], "message")
            self.assertEqual(frame["message"]["mention_ids"], [b["id"]])
            endpoint = self.root + f"/messages/{sent['id']}/retract"
            self.assertEqual(self.client.post(endpoint, headers=second, json={}).status_code, 403)
            self.assertEqual(
                self.client.post(
                    endpoint, headers=first, json={"as_seat": b["seat_id"]}
                ).status_code,
                403,
            )
            with storage.transaction() as db:
                db.execute(
                    "UPDATE messages SET image_id=?,payload=? WHERE id=?",
                    (
                        "private-image",
                        '{"type":"extra"}',
                        sent["id"],
                    ),
                )
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
            frame = next(
                frame for _ in range(5) if (frame := socket.receive_json())["type"] == "message"
            )
            self.assertEqual(frame, {"type": "message", "message": result})
            self.assertEqual(self.history(second, sent["id"]), result)
            self.assertEqual(self.client.post(endpoint, headers=first, json={}).status_code, 409)
            with storage.connect() as db:
                row = db.execute("SELECT * FROM messages WHERE id=?", (sent["id"],)).fetchone()
                self.assertIsNotNone(row["recalled_at"])
                self.assertEqual(
                    (row["text"], row["mention_ids"], row["payload"], row["image_id"]),
                    ("", "[]", None, None),
                )

    def test_retract_nonchat_and_host_without_sender_identity_forbidden(self):
        first, actor = self.join("23001")
        sent = self.send(first, "public", "只由本人撤回")
        self.assertEqual(
            self.client.post(
                self.root + f"/messages/{sent['id']}/retract", headers=self.host, json={}
            ).status_code,
            403,
        )
        with storage.connect() as db:
            notice_id = db.execute(
                "SELECT id FROM messages WHERE game_id=? AND kind='notice' LIMIT 1",
                (self.root.removeprefix("/api/games/"),),
            ).fetchone()["id"]
        self.assertEqual(
            self.client.post(
                self.root + f"/messages/{notice_id}/retract", headers=self.host, json={}
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                self.root + "/messages/999999/retract", headers=first, json={}
            ).status_code,
            404,
        )
        # 合法主持代操作必须明确指定原发送席位，不能作为主持人直接抹除玩家消息。
        delegated = self.client.post(
            self.root + f"/messages/{sent['id']}/retract",
            headers=self.host,
            json={"as_seat": actor["seat_id"]},
        )
        delegated.raise_for_status()
        self.assertTrue(delegated.json()["recalled"])
        own = self.send(self.host, "public", "主持人此前的聊天")
        with storage.transaction() as db:
            game = storage.load_game(db, self.root.removeprefix("/api/games/"))
            game["host_entries"] = []
            storage.save_game(db, game)
        self.assertEqual(
            self.client.post(
                self.root + f"/messages/{own['id']}/retract", headers=self.host, json={}
            ).status_code,
            403,
        )

    def test_public_reference_snapshot_history_realtime_and_retract(self):
        first, _ = self.join("24001")
        second, _ = self.join("24002")
        game_id = self.root.removeprefix("/api/games/")
        with storage.transaction() as db:
            public = storage.add_message(
                db, game_id, kind="alert", text="第1夜是平安夜。", reference_title="夜终公告"
            )
            storage.add_message(db, game_id, text="公开遗物", reference_title="遗留证物")
            storage.add_message(db, game_id, text="公开裁定", reference_title="主持人状态裁定")
            storage.add_message(
                db, game_id, text="私密证物", audience=["private"], reference_title="遗留证物"
            )
        catalog = self.client.get(self.root + "/references", headers=first).json()
        self.assertEqual(len(catalog["events"]), 3)
        self.assertEqual(len(catalog["roles"]), 14)
        self.assertIn("emma:treasure", {item["id"] for item in catalog["skills"]})
        event = catalog["events"][0]
        role = next(item for item in catalog["roles"] if item["id"] == "emma")
        text = f"😀 #{event['label']} #{role['label']}"
        event_start = 3
        role_start = event_start + len(event["label"]) + 2
        refs = [
            {
                "start": event_start,
                "end": event_start + len(event["label"]) + 1,
                "type": "event",
                "id": str(public["id"]),
            },
            {
                "start": role_start,
                "end": role_start + len(role["label"]) + 1,
                "type": "role",
                "id": role["id"],
            },
        ]
        with self.client.websocket_connect("/api/live", headers=second) as socket:
            self.assertEqual(socket.receive_json()["type"], "sync")
            sent = self.send(first, "public", text, references=refs)
            frame = next(
                frame for _ in range(5) if (frame := socket.receive_json())["type"] == "message"
            )
            self.assertEqual(frame["message"]["payload"], sent["payload"])
            self.assertEqual(self.history(second, sent["id"])["payload"], sent["payload"])
            self.assertEqual(sent["payload"]["items"][0]["text"], event["text"])
            recalled = self.client.post(
                self.root + f"/messages/{sent['id']}/retract", headers=first, json={}
            ).json()
            self.assertNotIn("payload", recalled)
            self.assertNotIn("payload", self.history(second, sent["id"]))

    def test_references_reject_private_cross_game_mismatch_and_utf16_splits(self):
        first, _ = self.join("25001")
        game_id = self.root.removeprefix("/api/games/")
        with storage.transaction() as db:
            private = storage.add_message(
                db,
                game_id,
                kind="information",
                text="秘密",
                audience=["private"],
                reference_title="遗留证物",
            )
            db.execute(
                "INSERT INTO games(id,state,version,status,created_at) VALUES(?,?,?,?,?)",
                ("elsewhere", "{}", 1, "playing", "now"),
            )
            foreign = storage.add_message(
                db, "elsewhere", kind="alert", text="第1夜是平安夜。", reference_title="夜终公告"
            )
        role = next(
            item
            for item in self.client.get(self.root + "/references", headers=first).json()["roles"]
            if item["id"] == "emma"
        )
        text = f"😀 #{role['label']}"
        valid = {
            "start": 3,
            "end": len(text.encode("utf-16-le")) // 2,
            "type": "role",
            "id": "emma",
        }
        for ref in [
            {**valid, "start": 1},
            {**valid, "end": 500},
            {**valid, "id": "hiro"},
            {**valid, "type": "event", "id": str(private["id"])},
            {**valid, "type": "event", "id": str(foreign["id"])},
        ]:
            response = self.client.post(
                self.root + "/messages",
                headers=first,
                json={
                    "channel_id": "public",
                    "text": text,
                    "references": [ref],
                },
            )
            self.assertEqual(response.status_code, 422, ref)

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
                    self.assertEqual(
                        storage.message_view(row, {"kind": "player", "access_ids": ["original"]})[
                            "mention_ids"
                        ],
                        [],
                    )
                    self.assertFalse(
                        storage.message_view(row, {"kind": "player", "access_ids": ["original"]})[
                            "recalled"
                        ]
                    )
                    self.assertEqual(row["text"], "以前的消息")
                    self.assertIn("reference_title", row.keys())
