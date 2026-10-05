"""历史对局：全量归档、进行中隔离、撤回保护与旧库迁移。"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import history_storage, storage
from backend.app.game import DEFAULT_CODEX, create_game
from backend.app.game.state import log_event, rewind, save_snapshot
from backend.app.main import app

PAIRS = [
    ["millia", "emma"],
    ["hiro", "coco"],
    ["meruru", "hanna"],
    ["marg", "sherry"],
    ["leia", "arisa"],
    ["noah", "annan"],
    ["nanoka", "honoka"],
]


class HistoryFlow(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.data_patch = patch.object(storage, "DATA_DIR", Path(self.directory.name))
        self.data_patch.start()
        self.addCleanup(self.data_patch.stop)
        self.env_patch = patch.dict(
            os.environ,
            {
                "GAME_GATEWAY_TOKEN": "test-gateway-secret",
                "GAME_QQ_GROUP_ID": "123456",
                "GAME_ADMIN_QQ": "10001",
            },
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.client = TestClient(
            app,
            base_url="http://testserver",
            headers={"Origin": "http://testserver"},
        )
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.host, _ = self.host_login("10001")
        self.new_game()

    def new_game(self):
        created = self.client.post("/api/games", headers=self.host, json={"codex": DEFAULT_CODEX})
        created.raise_for_status()
        self.game_id = created.json()["id"]
        self.root = f"/api/games/{self.game_id}"
        self.client.post(self.root + "/host/enter", headers=self.host).raise_for_status()
        return self.game_id

    def host_login(self, qq_id):
        challenge = self.client.post("/api/native/auth/host/challenges").json()
        self.client.post(
            "/api/internal/qq/login",
            headers={"X-Gateway-Token": "test-gateway-secret"},
            json={
                "code": challenge["code"],
                "qq_id": qq_id,
                "nickname": "主持" + qq_id,
                "avatar_url": "",
                "group_id": 123456,
            },
        ).raise_for_status()
        completed = self.client.get("/api/native/auth/host/challenges/" + challenge["id"])
        completed.raise_for_status()
        return {"Authorization": "Bearer " + completed.json()["session_token"]}, completed.json()

    def account(self, qq_id):
        challenge = self.client.post("/api/native/auth/challenges").json()
        self.client.post(
            "/api/internal/qq/login",
            headers={"X-Gateway-Token": "test-gateway-secret"},
            json={
                "code": challenge["code"],
                "qq_id": qq_id,
                "nickname": "QQ" + qq_id,
                "avatar_url": "",
                "group_id": 123456,
            },
        ).raise_for_status()
        completed = self.client.get("/api/native/auth/challenges/" + challenge["id"])
        completed.raise_for_status()
        return {"Authorization": "Bearer " + completed.json()["session_token"]}

    def command(self, headers, action, payload=None, status=200):
        state = self.client.get(self.root + "/state", headers=headers)
        state.raise_for_status()
        response = self.client.post(
            self.root + "/commands",
            headers=headers,
            json={
                "expected_version": state.json()["version"],
                "action": action,
                "payload": payload or {},
            },
        )
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def history(self, headers=None, **query):
        response = self.client.get("/api/history", headers=headers or self.host, params=query)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_finished_match_is_public_to_other_logged_in_players(self):
        player = self.account("20001")
        self.command(self.host, "room.open_join", {"open": True})
        joined = self.client.post(
            self.root + "/participations", headers=player, json={"kind": "player"}
        )
        self.assertEqual(joined.status_code, 200, joined.text)
        public = self.client.post(
            self.root + "/messages",
            headers=player,
            json={"channel_id": "public", "text": "公屏发言可见"},
        )
        self.assertEqual(public.status_code, 200, public.text)
        # 与主持人的双人私信：建立即生效，随后只能在该频道发言。
        view = self.command(player, "channel.create", {"participant_ids": ["host"]})
        channel = next(item for item in view["channels"] if item["id"].startswith("private:"))
        private = self.client.post(
            self.root + "/messages",
            headers=player,
            json={"channel_id": channel["id"], "text": "结束后公开私信"},
        )
        self.assertEqual(private.status_code, 200, private.text)
        outsider = self.account("20099")
        self.assertEqual(
            self.client.get(f"/api/history/{self.game_id}", headers=outsider).status_code, 404
        )
        self.assertEqual(self.history(outsider)["matches"], [])
        with storage.transaction() as db:
            game = storage.load_game(db, self.game_id)
            log_event(game, "host", "仅主持可见的裁定")
            storage.save_game(db, game)
            participant = db.execute(
                "SELECT id FROM participants WHERE game_id=?", (self.game_id,)
            ).fetchone()
            storage.add_message(
                db,
                self.game_id,
                kind="information",
                channel_id="information",
                text="仅本局玩家可见的定向情报",
                audience=[participant["id"]],
            )

        self.command(self.host, "host.end", {"winner": "aborted", "reason": "测试终止"})

        listed = self.history()
        self.assertEqual(len(listed["matches"]), 1, listed)
        item = listed["matches"][0]
        self.assertEqual(item["id"], self.game_id)
        self.assertEqual(item["winner"], "aborted")
        self.assertEqual(item["reason"], "测试终止")
        self.assertEqual(item["source"], "ended")
        self.assertEqual(item["host_name"], "主持人(主持10001)")
        self.assertEqual([row["name"] for row in item["players"]], ["QQ20001"])

        detail = self.client.get(f"/api/history/{self.game_id}", headers=outsider)
        self.assertEqual(detail.status_code, 200, detail.text)
        texts = [event["text"] for event in detail.json()["events"]]
        self.assertTrue(any("公屏发言可见" in text for text in texts), texts)
        self.assertIn("结束后公开私信", texts)
        private_event = next(
            event for event in detail.json()["events"] if event["text"] == "结束后公开私信"
        )
        private_label = "私信" + joined.json()["actor"]["seat_id"]
        self.assertTrue(private_event["channel_name"].startswith(private_label + "："))
        self.assertIn(private_label + "：", detail.json()["export_text"])
        self.assertIn("QQ20001", private_event["channel_name"])
        self.assertIn("主持人(主持10001)", private_event["channel_name"])
        self.assertEqual(set(private_event["audience_names"]), {"QQ20001", "主持人(主持10001)"})
        self.assertIn("结束后公开私信", detail.json()["export_text"])
        self.assertTrue(detail.json()["archive_complete"])
        target_event = next(
            event
            for event in detail.json()["events"]
            if event["text"] == "仅本局玩家可见的定向情报"
        )
        self.assertEqual(target_event["audience_names"], ["QQ20001"])
        self.assertIn("仅主持可见的裁定", [entry["text"] for entry in detail.json()["host_log"]])
        self.assertIn("仅本局玩家可见的定向情报", detail.json()["export_text"])

        # 历史库是独立文件：清空对局库不会牵动它。
        self.assertTrue((Path(self.directory.name) / "history.sqlite3").is_file())
        self.assertEqual(self.client.post("/api/reset", headers=self.host).status_code, 200)
        self.assertEqual(len(self.history()["matches"]), 1, "清空对局后历史仍在且不重复")
        preserved = self.client.get(f"/api/history/{self.game_id}", headers=outsider).json()
        self.assertEqual(preserved, detail.json())

    def test_unfinished_match_is_archived_as_aborted(self):
        self.command(self.host, "room.open_join", {"open": True})
        self.client.post(
            self.root + "/participations", headers=self.account("20002"), json={"kind": "player"}
        ).raise_for_status()
        with storage.connect() as db:
            self.assertEqual(history_storage.record_known(db, [self.game_id]), 0)
        self.assertEqual(self.history()["matches"], [])
        self.assertEqual(
            self.client.get(f"/api/history/{self.game_id}", headers=self.host).status_code, 404
        )
        self.assertEqual(self.client.post("/api/reset", headers=self.host).status_code, 200)
        listed = self.history()
        self.assertEqual(len(listed["matches"]), 1, listed)
        self.assertEqual(listed["matches"][0]["source"], "aborted")
        self.assertEqual(listed["matches"][0]["winner"], "")

    def test_reading_history_requires_login(self):
        anonymous = self.client.get("/api/history")
        self.assertEqual(anonymous.status_code, 401)
        missing = self.client.get("/api/history/does-not-exist", headers=self.host)
        self.assertEqual(missing.status_code, 404)

    def test_full_messages_logs_rule_state_and_recall_survive_purge(self):
        game = create_game(DEFAULT_CODEX)
        for seat, pair in zip(game["seats"], PAIRS, strict=True):
            seat.update(cards=list(pair), occupant_id="p" + seat["id"], name="玩家" + seat["id"])
        game["cards"] = {
            role: {
                "id": role,
                "role_id": role,
                "original_role_id": role,
                "alive": True,
                "witch": False,
                "injured": False,
                "states": {},
                "uses": {},
            }
            for pair in PAIRS
            for role in pair
        }
        game["cards"]["millia"].update(alive=False, witch=True, injured=True)
        game["cards"]["nanoka"]["uses"] = {"bullets": 2, "shot_misses": 1}
        game["cards"]["emma"]["states"] = {"no_ability": True}
        game["nominations"] = [{"seat_id": "2", "card_id": "emma"}]
        game["ballots"] = {"2": {"emma": "yes"}}
        game["night"]["actions"] = [{"seat_id": "3", "ability": "protect", "target_seat": "2"}]
        game["host"] = {"name": "测试主持", "qq_id": "private-qq", "token": "private-token"}
        game["host_entries"] = ["private-host-account"]
        for index in range(450):
            log_event(game, "host", f"有效裁定{index}")
        saved = save_snapshot(game)
        for index in range(20):
            log_event(game, "host", f"已回溯裁定{index}")
        rewind(game, saved["id"], [])
        self.assertEqual(game["log"][0]["text"], "有效裁定0")
        self.assertEqual(game["log"][449]["text"], "有效裁定449")
        self.assertFalse(any("已回溯裁定" in row["text"] for row in game["log"]))
        game["deadline"] = 987654321.25
        game["public"]["speech_deadline"] = 987654321.25
        game["status"] = "ended"
        game["result"] = {"winner": "good", "reason": "测试宣判", "personal_losses": ["p1"]}
        with storage.transaction() as db:
            db.execute(
                "INSERT INTO games(id,state,version,status,created_at) VALUES(?,?,?,?,?)",
                (game["id"], storage.dumps(game), game["version"], "ended", storage.now_text()),
            )
            for seat in game["seats"]:
                db.execute(
                    """INSERT INTO participants
                       (id,game_id,account_id,kind,seat_id,name,access_ids,active,blocked,muted)
                       VALUES(?,?,?,?,?,?,?,1,0,0)""",
                    (
                        seat["occupant_id"],
                        game["id"],
                        "acc" + seat["id"],
                        "player",
                        seat["id"],
                        seat["name"],
                        storage.dumps([seat["occupant_id"]]),
                    ),
                )
            for index in range(450):
                storage.add_message(
                    db,
                    game["id"],
                    kind="chat",
                    sender_id="p1",
                    sender_name="玩家1",
                    avatar_role_id="millia",
                    text=f"完整聊天{index}",
                )
            storage.add_message(
                db,
                game["id"],
                kind="information",
                sender_id="host",
                sender_name="主持人",
                avatar_role_id=None,
                text="定向情报内容",
                channel_id="information",
                audience=["p2"],
            )
            storage.add_message(
                db,
                game["id"],
                kind="chat",
                sender_id="p3",
                sender_name="玩家3",
                avatar_role_id="meruru",
                text="观战频道内容",
                channel_id="spectator",
                audience=["p3"],
            )
            storage.add_message(
                db,
                game["id"],
                kind="presence",
                sender_id="p1",
                sender_name="玩家1",
                avatar_role_id=None,
                text="无效连接状态",
            )
            recalled = storage.add_message(
                db,
                game["id"],
                kind="chat",
                sender_id="p1",
                sender_name="玩家1",
                avatar_role_id=None,
                text="撤回的正文不可复活",
                image_id="recalled-image",
                payload={"type": "references", "image": "recalled-base64", "items": []},
            )
            storage.recall_message(db, recalled)
            storage.add_message(
                db,
                game["id"],
                kind="chat",
                sender_id="p1",
                sender_name="玩家1",
                avatar_role_id=None,
                text="图片说明",
                payload={"type": "references", "image": "private-base64", "items": []},
            )
            storage.add_message(
                db,
                game["id"],
                kind="notice",
                sender_id="host",
                sender_name="主持人",
                avatar_role_id=None,
                text="技能公告",
                payload={
                    "type": "skill",
                    "ability_name": "爱人",
                    "target": "4",
                    "effect": "目标是玛格",
                    "_animation": {"private": "private-animation"},
                },
            )
            db.execute(
                "INSERT INTO evidence(id,game_id,owner_id,text,mime,image,created_at) VALUES(?,?,?,?,?,?,?)",
                (
                    "proof",
                    game["id"],
                    "p1",
                    "证物原文",
                    "image/png",
                    b"picture",
                    storage.now_text(),
                ),
            )
            snap = history_storage.snapshot(db, game["id"])
            self.assertTrue(history_storage.record(game, "ended", snap))
            # 同一局再记一次不会产生第二条，也不会覆盖已有记录。
            self.assertFalse(history_storage.record(game, "aborted", snap))
        detail = history_storage.match(game["id"])
        self.assertEqual(detail["winner"], "good")
        self.assertEqual(detail["source"], "ended")
        self.assertEqual(len(detail["players"]), 7)
        self.assertEqual(detail["players"][0]["role_ids"], ["millia", "emma"])
        self.assertEqual(detail["personal_losses"], ["p1"])
        self.assertEqual(len(history_storage.matches(limit=10)["matches"]), 1, "只应有一条历史")
        texts = [event["text"] for event in detail["events"]]
        self.assertIn("完整聊天0", texts)
        self.assertIn("完整聊天449", texts)
        self.assertIn("定向情报内容", texts)
        self.assertIn("观战频道内容", texts)
        self.assertNotIn("无效连接状态", texts)
        target = next(event for event in detail["events"] if event["text"] == "定向情报内容")
        self.assertEqual(target["audience_names"], ["玩家2"])
        recalled = next(event for event in detail["events"] if event["recalled_at"])
        self.assertEqual(recalled["text"], "[消息已撤回]")
        self.assertIsNone(recalled["image_id"])
        self.assertEqual(detail["host_log"][0]["text"], "有效裁定0")
        self.assertEqual(detail["host_log"][449]["text"], "有效裁定449")
        exported = detail["export_text"]
        for content in (
            "完整聊天0",
            "完整聊天449",
            "定向情报内容",
            "玩家2",
            "证物原文",
            "聊天图片",
            "证物图片",
            "有效裁定0",
            "有效裁定449",
            "米莉亚",
            "艾玛",
            "死亡",
            "负伤",
            "剩余子弹",
            "失去技能",
            "提名",
            "选票",
            "庇护",
            "目标：4号",
            "测试宣判",
            "个人失败",
        ):
            self.assertIn(content, exported)
        for private in (
            "撤回的正文不可复活",
            "recalled-base64",
            "private-base64",
            "private-token",
            "private-qq",
            "private-host-account",
            "private-animation",
            "987654321.25",
            "已回溯裁定",
        ):
            self.assertNotIn(private, exported)
        with storage.transaction() as db:
            storage.purge(db)
        self.assertEqual(history_storage.match(game["id"]), detail)

    def test_legacy_schema_reads_and_only_backfills_existing_ended_games(self):
        stamp = "2000-01-01T00:00:00+00:00"
        with history_storage.transaction() as db:
            db.executescript("""
                DROP TABLE match_events;
                DROP TABLE match_players;
                DROP TABLE matches;
                CREATE TABLE matches (
                    id TEXT PRIMARY KEY, ended_at TEXT NOT NULL, recorded_at TEXT NOT NULL,
                    day INTEGER NOT NULL, half TEXT NOT NULL DEFAULT '', phase TEXT NOT NULL DEFAULT '',
                    winner TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL, host_name TEXT NOT NULL DEFAULT '',
                    personal_losses TEXT NOT NULL DEFAULT '[]'
                );
                CREATE TABLE match_players (
                    match_id TEXT NOT NULL, participant_id TEXT NOT NULL, account_id TEXT,
                    name TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'player', seat_id TEXT,
                    role_ids TEXT NOT NULL DEFAULT '[]', active INTEGER NOT NULL DEFAULT 1,
                    blocked INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(match_id,participant_id)
                );
                CREATE TABLE match_events (
                    match_id TEXT NOT NULL, seq INTEGER NOT NULL, kind TEXT NOT NULL,
                    sender_name TEXT NOT NULL DEFAULT '', avatar_role_id TEXT,
                    text TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, PRIMARY KEY(match_id,seq)
                );
            """)
            for match_id in ("legacy-cleared", self.game_id):
                db.execute(
                    "INSERT INTO matches(id,ended_at,recorded_at,day,source) VALUES(?,?,?,?,?)",
                    (match_id, stamp, stamp, 1, "ended"),
                )
                db.execute(
                    "INSERT INTO match_events VALUES(?,?,?,?,?,?,?)",
                    (match_id, 0, "chat", "旧玩家", None, "旧公开记录", stamp),
                )
        history_storage.initialize()
        history_storage.initialize()
        old = history_storage.match("legacy-cleared")
        self.assertFalse(old["archive_complete"])
        self.assertEqual(old["ended_at"], stamp)
        self.assertEqual(old["host_log"], [])
        self.assertIn("旧公开记录", old["export_text"])
        self.assertIn("无法恢复", old["export_text"])
        ongoing = history_storage.match(self.game_id)
        self.assertEqual([row["text"] for row in ongoing["events"]], ["旧公开记录"])
        with storage.transaction() as db:
            game = storage.load_game(db, self.game_id)
            game["status"] = "ended"
            game["result"] = {"winner": "good", "reason": "旧结束局补齐", "personal_losses": []}
            log_event(game, "host", "仍在原库的主持日志")
            storage.save_game(db, game)
            storage.add_message(
                db,
                self.game_id,
                kind="information",
                sender_id="host",
                sender_name="主持人",
                avatar_role_id=None,
                text="仍在原库的定向消息",
                channel_id="information",
                audience=["host"],
            )
        restored = history_storage.match(self.game_id)
        self.assertEqual(restored["ended_at"], stamp)
        self.assertFalse(restored["archive_complete"], "旧日志可能已被截断，不能伪称完整")
        self.assertIn("仍在原库的定向消息", restored["export_text"])
        self.assertIn("旧公开记录", restored["export_text"])
        self.assertIn("仍在原库的主持日志", [entry["text"] for entry in restored["host_log"]])
        self.assertEqual(history_storage.match("legacy-cleared"), old)
