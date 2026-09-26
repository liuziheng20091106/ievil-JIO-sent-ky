"""历史对局删除（4 级及以上主持人的维护操作）。

删除只动历史库：不建对局、不模拟玩法，直接往 history_storage 里记一条最小留档，
再从接口层验证等级门槛与数据删除边界。
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import auth_storage, history_storage, storage
from backend.app.main import app


def record_stub(match_id):
    """记一条最小留档：一个参与身份 + 一条公开消息，走正式的 record 入库路径。"""
    game = {
        "id": match_id,
        "day": 2,
        "half": "day",
        "phase": "dusk",
        "seats": [{"id": "1", "cards": ["millia", "emma"]}],
        "result": {"winner": "good", "reason": "删除测试宣判", "personal_losses": []},
        "status": "ended",
    }
    snap = {
        "players": [
            {
                "id": "p1",
                "account_id": "acc1",
                "name": "玩家1",
                "kind": "player",
                "seat_id": "1",
                "active": 1,
                "blocked": 0,
            }
        ],
        "events": [
            {
                "kind": "chat",
                "sender_name": "玩家1",
                "avatar_role_id": "millia",
                "text": "公屏发言",
                "created_at": history_storage.now_text(),
            }
        ],
    }
    assert history_storage.record(game, "ended", snap)
    return match_id


class HistoryDeletion(unittest.TestCase):
    def setUp(self):
        # 与 checks/test_history.py 相同的环境隔离（独立临时 GAME_DATA_DIR），
        # 但不建对局：历史删除与对局玩法无关，主持人登录后就直接验证接口。
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
        self.host = self.host_login("10001")

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
        return {"Authorization": "Bearer " + completed.json()["session_token"]}

    def authorize(self, qq_id, level):
        # 账号在 QQ 登录时才建号：先以玩家身份登一次把号建出来，再给主持授权。
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
        account = auth_storage.account_by_qq(qq_id)
        auth_storage.authorize_host(account["id"], level, granted_by=account["id"])
        return self.host_login(qq_id)

    def test_admin_level5_can_delete_whole_match(self):
        match_id = record_stub("hist-del-1")
        listed = self.client.get("/api/history", headers=self.host)
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertIn(match_id, [row["id"] for row in listed.json()["matches"]])

        response = self.client.delete(f"/api/history/{match_id}", headers=self.host)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["ok"])

        # 连同参与身份与公开时间线一起删掉；再删一次就是 404。
        self.assertIsNone(history_storage.match(match_id))
        missing = self.client.delete(f"/api/history/{match_id}", headers=self.host)
        self.assertEqual(missing.status_code, 404, missing.text)

    def test_requires_host_level_4_and_login(self):
        match_id = record_stub("hist-del-2")

        # 玩家账号不行。
        player_challenge = self.client.post("/api/native/auth/challenges").json()
        self.client.post(
            "/api/internal/qq/login",
            headers={"X-Gateway-Token": "test-gateway-secret"},
            json={
                "code": player_challenge["code"],
                "qq_id": "30001",
                "nickname": "QQ30001",
                "avatar_url": "",
                "group_id": 123456,
            },
        ).raise_for_status()
        player = self.client.get(
            "/api/native/auth/challenges/" + player_challenge["id"]
        ).json()
        denied = self.client.delete(
            f"/api/history/{match_id}",
            headers={"Authorization": "Bearer " + player["session_token"]},
        )
        self.assertEqual(denied.status_code, 403, denied.text)
        self.assertIsNotNone(history_storage.match(match_id))

        # 3 级主持（能管成就）也够不到这条维护操作。
        low = self.authorize("30002", 3)
        denied = self.client.delete(f"/api/history/{match_id}", headers=low)
        self.assertEqual(denied.status_code, 403, denied.text)
        self.assertIsNotNone(history_storage.match(match_id))

        # 4 级主持可以删。
        allowed = self.authorize("30002", 4)
        response = self.client.delete(f"/api/history/{match_id}", headers=allowed)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIsNone(history_storage.match(match_id))

        # 未登录不行。
        anonymous = self.client.delete(f"/api/history/{match_id}")
        self.assertEqual(anonymous.status_code, 401, anonymous.text)
