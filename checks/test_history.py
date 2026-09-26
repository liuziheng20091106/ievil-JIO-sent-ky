"""历史对局：独立库留档、按局幂等、公开记录边界与接口可见性。

历史对局库（``data/history.sqlite3``）与对局库分开：这里既验证「对局结束就留档」，
也验证「清空对局库不牵动历史」，还守住「私信与只发给个人的情报不入档」这条隐私边界。
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import history_storage, storage
from backend.app.game import DEFAULT_CODEX, create_game
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
        created = self.client.post(
            "/api/games", headers=self.host, json={"codex": DEFAULT_CODEX}
        )
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

    def test_finished_match_is_archived_and_public_record_only(self):
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
            json={"channel_id": channel["id"], "text": "私信内容不可入档"},
        )
        self.assertEqual(private.status_code, 200, private.text)

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

        detail = self.client.get(f"/api/history/{self.game_id}", headers=self.host)
        self.assertEqual(detail.status_code, 200, detail.text)
        texts = [event["text"] for event in detail.json()["events"]]
        self.assertTrue(any("公屏发言可见" in text for text in texts), texts)
        self.assertTrue(any("新对局已创建" in text for text in texts), texts)
        self.assertFalse(any("私信内容不可入档" in text for text in texts), texts)
        self.assertFalse(any("正在与" in text for text in texts), "私信开合公告也不入档")

        # 历史库是独立文件：清空对局库不会牵动它。
        self.assertTrue((Path(self.directory.name) / "history.sqlite3").is_file())
        self.assertEqual(self.client.post("/api/reset", headers=self.host).status_code, 200)
        self.assertEqual(len(self.history()["matches"]), 1, "清空对局后历史仍在且不重复")

    def test_unfinished_match_is_archived_as_aborted(self):
        self.command(self.host, "room.open_join", {"open": True})
        self.client.post(
            self.root + "/participations", headers=self.account("20002"), json={"kind": "player"}
        ).raise_for_status()
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

    def test_record_keeps_both_role_cards_and_is_idempotent(self):
        game = create_game(DEFAULT_CODEX)
        for seat, pair in zip(game["seats"], PAIRS):
            seat.update(cards=list(pair), occupant_id="p" + seat["id"], name="玩家" + seat["id"])
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
