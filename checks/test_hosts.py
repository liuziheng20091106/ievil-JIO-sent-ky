"""Host levels, authorization, single-use level 1, and announcements.

主持人不再是共享密码：GAME_ADMIN_QQ 指定的 QQ 账号是 5 级系统管理员，其余账号由
4/5 级主持授权，授权与账号绑定，令牌每次请求都重新核对等级。这里守住四条真实边界：
谁能登录主持入口、各级能授到几级、1 级用完一局后授权作废、公告只有 5 级能发布。
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import storage
from backend.app.game import DEFAULT_CODEX
from backend.app.main import app


class HostFlow(unittest.TestCase):
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
        # 先用网关同步出几个账号：授权页挑人时它们才会出现。
        self.sync_members(["10002", "10003", "10004", "10005"])
        self.admin, self.admin_actor = self.host_login("10001")
        # 预先给 10005 一个 5 级授权：4 级主持不能取消比自己高的授权。
        self.assertEqual(self.authorize("10005", 5).status_code, 200)

    # ------------------------------------------------------------------ 工具

    def sync_members(self, qq_ids):
        response = self.client.post(
            "/api/internal/qq/members/sync",
            headers={"X-Gateway-Token": "test-gateway-secret"},
            json={
                "group_id": 123456,
                "members": [
                    {"qq_id": qq_id, "nickname": "主持" + qq_id, "avatar_url": ""}
                    for qq_id in qq_ids
                ],
            },
        )
        response.raise_for_status()

    def host_login(self, qq_id):
        challenge = self.client.post("/api/native/auth/host/challenges").json()
        bound = self.client.post(
            "/api/internal/qq/login",
            headers={"X-Gateway-Token": "test-gateway-secret"},
            json={
                "code": challenge["code"],
                "qq_id": qq_id,
                "nickname": "主持" + qq_id,
                "avatar_url": "https://example.invalid/" + qq_id,
                "group_id": 123456,
            },
        )
        bound.raise_for_status()
        completed = self.client.get("/api/native/auth/host/challenges/" + challenge["id"])
        completed.raise_for_status()
        self.assertEqual(completed.json().get("status"), "completed")
        return (
            {"Authorization": "Bearer " + completed.json()["session_token"]},
            completed.json()["session"]["actor"],
        )

    def player_login(self, qq_id):
        challenge = self.client.post("/api/native/auth/challenges").json()
        self.client.post(
            "/api/internal/qq/login",
            headers={"X-Gateway-Token": "test-gateway-secret"},
            json={
                "code": challenge["code"],
                "qq_id": qq_id,
                "nickname": "玩家" + qq_id,
                "avatar_url": "",
                "group_id": 123456,
            },
        ).raise_for_status()
        completed = self.client.get("/api/native/auth/challenges/" + challenge["id"])
        completed.raise_for_status()
        return {"Authorization": "Bearer " + completed.json()["session_token"]}

    def account_id(self, qq_id):
        rows = self.client.get(
            "/api/hosts/accounts", headers=self.admin, params={"q": qq_id}
        ).json()["accounts"]
        matched = [row for row in rows if row["qq_id"] == qq_id]
        self.assertTrue(matched, f"账号 {qq_id} 不在授权页的候选人里")
        return matched[0]["account_id"]

    def authorize(self, qq_id, level, headers=None):
        return self.client.post(
            f"/api/hosts/{self.account_id(qq_id)}",
            headers=headers or self.admin,
            json={"level": level},
        )

    def revoke(self, qq_id, headers=None):
        return self.client.delete(
            f"/api/hosts/{self.account_id(qq_id)}", headers=headers or self.admin
        )

    def create_game(self, headers):
        return self.client.post(
            "/api/games", headers=headers, json={"codex": DEFAULT_CODEX}
        )

    def end_game(self, headers, game_id):
        state = self.client.get(f"/api/games/{game_id}/state", headers=headers).json()
        return self.client.post(
            f"/api/games/{game_id}/commands",
            headers=headers,
            json={
                "expected_version": state["version"],
                "action": "host.end",
                "payload": {"winner": "aborted", "reason": "测试结束"},
            },
        )

    # ------------------------------------------------------------------ 登录

    def test_only_authorized_accounts_reach_the_host_entry(self):
        self.assertEqual(self.admin_actor["kind"], "host")
        self.assertEqual(self.admin_actor["host_level"], 5)
        # 没被授权的账号走主持人入口会被当场拒绝。
        refused = self.client.post("/api/native/auth/host/challenges").json()
        self.client.post(
            "/api/internal/qq/login",
            headers={"X-Gateway-Token": "test-gateway-secret"},
            json={
                "code": refused["code"],
                "qq_id": "10002",
                "nickname": "主持10002",
                "avatar_url": "",
                "group_id": 123456,
            },
        ).raise_for_status()
        response = self.client.get("/api/native/auth/host/challenges/" + refused["id"])
        self.assertEqual(response.status_code, 403, response.text)
        # 密码登录入口已经彻底删掉：只剩下 SPA 兜底路由（只回 GET，所以 POST 是 405）。
        self.assertIn(
            self.client.post(
                "/api/native/host/login", json={"password": "114514"}
            ).status_code,
            (404, 405),
        )

    def test_missing_admin_configuration_locks_the_host_entry(self):
        with patch.dict(os.environ, {"GAME_ADMIN_QQ": ""}):
            challenge = self.client.post("/api/native/auth/host/challenges").json()
            self.client.post(
                "/api/internal/qq/login",
                headers={"X-Gateway-Token": "test-gateway-secret"},
                json={
                    "code": challenge["code"],
                    "qq_id": "10001",
                    "nickname": "主持10001",
                    "avatar_url": "",
                    "group_id": 123456,
                },
            ).raise_for_status()
            response = self.client.get(
                "/api/native/auth/host/challenges/" + challenge["id"]
            )
            self.assertEqual(response.status_code, 403, response.text)

    # ------------------------------------------------------------------ 等级

    def test_level_three_can_only_handle_low_rarity_achievements(self):
        self.assertEqual(self.authorize("10002", 3).status_code, 200)
        headers, actor = self.host_login("10002")
        self.assertEqual(actor["host_level"], 3)

        low = self.client.post(
            "/api/achievements/defs",
            headers=headers,
            json={"name": "小成就", "detail": "内容", "rarity": 3},
        )
        self.assertEqual(low.status_code, 200, low.text)
        high = self.client.post(
            "/api/achievements/defs",
            headers=headers,
            json={"name": "大成就", "detail": "内容", "rarity": 4},
        )
        self.assertEqual(high.status_code, 403, high.text)
        # 3 级看不到也不能改授权名单。
        self.assertEqual(self.client.get("/api/hosts", headers=headers).status_code, 403)
        # 已经获得授权的人不能再被 3 级主持取消。
        self.assertEqual(self.revoke("10002", headers=headers).status_code, 403)

    def test_level_four_grants_and_revokes_only_below_itself(self):
        self.assertEqual(self.authorize("10004", 4).status_code, 200)
        headers, actor = self.host_login("10004")
        self.assertEqual(actor["host_level"], 4)

        self.assertEqual(self.authorize("10002", 3, headers=headers).status_code, 200)
        too_high = self.authorize("10003", 4, headers=headers)
        self.assertEqual(too_high.status_code, 403, too_high.text)
        # 4 级可以用到稀有度 4 的成就，但 5 仍然不行。
        self.assertEqual(
            self.client.post(
                "/api/achievements/defs",
                headers=headers,
                json={"name": "四级成就", "detail": "内容", "rarity": 4},
            ).status_code,
            200,
        )
        self.assertEqual(
            self.client.post(
                "/api/achievements/defs",
                headers=headers,
                json={"name": "五级成就", "detail": "内容", "rarity": 5},
            ).status_code,
            403,
        )
        # 4 级能取消自己授权范围内的 3 级，但不能取消同为 4 级或被 5 级授权的人。
        self.assertEqual(self.revoke("10002", headers=headers).status_code, 200)
        self.assertEqual(self.revoke("10005", headers=headers).status_code, 403)

    def test_level_five_manages_every_level_and_builtin_admin_is_fixed(self):
        self.assertEqual(self.authorize("10005", 5).status_code, 200)
        headers, actor = self.host_login("10005")
        self.assertEqual(actor["host_level"], 5)
        self.assertEqual(self.authorize("10004", 5, headers=headers).status_code, 200)
        self.assertEqual(self.authorize("10003", 1, headers=headers).status_code, 200)
        self.assertEqual(self.revoke("10004", headers=headers).status_code, 200)
        # 内置管理员的等级来自服务端配置，界面既不能改也不能取消。
        builtin_id = self.account_id("10001")
        self.assertEqual(
            self.client.post(
                f"/api/hosts/{builtin_id}", headers=headers, json={"level": 2}
            ).status_code,
            409,
        )
        self.assertEqual(
            self.client.delete(f"/api/hosts/{builtin_id}", headers=headers).status_code,
            409,
        )

    def test_revoked_authorization_invalidates_the_existing_token(self):
        self.assertEqual(self.authorize("10003", 2).status_code, 200)
        headers, _ = self.host_login("10003")
        self.assertEqual(self.client.get("/api/me", headers=headers).status_code, 200)
        self.assertEqual(self.revoke("10003").status_code, 200)
        # 旧令牌立刻失效：等级每次请求重新核对，不靠登录时的快照。
        self.assertIsNone(
            self.client.get("/api/me", headers=headers).json()["actor"],
            "授权被取消后这个令牌不再给出主持人身份",
        )
        refused = self.create_game(headers)
        self.assertEqual(refused.status_code, 403, refused.text)
        self.assertIn("主持授权", refused.json()["detail"])

    def test_level_one_authorization_expires_after_that_game(self):
        self.assertEqual(self.authorize("10003", 1).status_code, 200)
        headers, actor = self.host_login("10003")
        self.assertEqual(actor["host_level"], 1)

        created = self.create_game(headers)
        self.assertEqual(created.status_code, 200, created.text)
        game_id = created.json()["id"]

        # 对局还在进行时，1 级主持照常行使主持权。
        self.assertEqual(self.client.get("/api/me", headers=headers).status_code, 200)
        ended = self.end_game(headers, game_id)
        self.assertEqual(ended.status_code, 200, ended.text)

        # 这一局结束后授权作废：旧令牌不再给出主持人身份，也不能再建新局或重新登录。
        self.assertIsNone(self.client.get("/api/me", headers=headers).json()["actor"])
        self.assertEqual(self.create_game(headers).status_code, 403)
        listed = self.client.get("/api/hosts", headers=self.admin).json()["hosts"]
        consumed = [row for row in listed if row["qq_id"] == "10003"][0]
        self.assertTrue(consumed["consumed"], "用完一局的授权要标成已用完")
        self.assertEqual(consumed["level"], 1)
        retry = self.client.post("/api/native/auth/host/challenges").json()
        self.client.post(
            "/api/internal/qq/login",
            headers={"X-Gateway-Token": "test-gateway-secret"},
            json={
                "code": retry["code"],
                "qq_id": "10003",
                "nickname": "主持10003",
                "avatar_url": "",
                "group_id": 123456,
            },
        ).raise_for_status()
        self.assertEqual(
            self.client.get("/api/native/auth/host/challenges/" + retry["id"]).status_code,
            403,
        )
        # 重新授权后又能主持一局。
        self.assertEqual(self.authorize("10003", 1).status_code, 200)
        again = self.host_login("10003")
        self.assertEqual(self.create_game(again[0]).status_code, 200)

    # ------------------------------------------------------------------ 主持人身份

    def test_game_records_its_host_and_announces_other_hosts(self):
        created = self.create_game(self.admin)
        self.assertEqual(created.status_code, 200, created.text)
        game_id = created.json()["id"]
        # 建局时记下主持身份：对局内一律显示「主持人(昵称)」。
        self.assertEqual(created.json()["host_name"], "主持人(主持10001)")

        other, _ = self.host_login("10005")
        entered = self.client.post(f"/api/games/{game_id}/host/enter", headers=other)
        self.assertEqual(entered.status_code, 200, entered.text)
        self.assertEqual(
            entered.json(), {"owner": False, "announced": True, "owner_name": "主持人(主持10001)"}
        )
        # 全服通告：任何已登录身份在大厅都能看到，并写清是谁进了谁的对局。
        lobby = self.client.get("/api/lobby", headers=other).json()
        listed = [item for item in lobby["announcements"] if item["title"] == "有主持人进入了他人建立的对局"]
        self.assertEqual(len(listed), 1)
        self.assertIn("主持10005", listed[0]["body"])
        self.assertIn("主持人(主持10001)", listed[0]["body"])

        # 同一账号在同一局只通告一次，重复打开管理界面不刷屏。
        again = self.client.post(f"/api/games/{game_id}/host/enter", headers=other)
        self.assertEqual(again.json()["announced"], False)
        lobby = self.client.get("/api/lobby", headers=other).json()
        self.assertEqual(
            len([item for item in lobby["announcements"] if item["title"] == "有主持人进入了他人建立的对局"]),
            1,
        )

        # 建局主持人自己进入不算越权，不产生通告。
        mine = self.client.post(f"/api/games/{game_id}/host/enter", headers=self.admin)
        self.assertEqual(mine.json(), {"owner": True, "announced": False, "owner_name": "主持人(主持10001)"})

    def test_level_one_expires_on_reset_too(self):
        self.assertEqual(self.authorize("10003", 1).status_code, 200)
        headers, _ = self.host_login("10003")
        self.assertEqual(self.create_game(headers).status_code, 200)
        # 一键初始化等于这一局被清空。
        self.assertEqual(
            self.client.post("/api/reset", headers=self.admin).status_code, 200
        )
        self.assertIsNone(self.client.get("/api/me", headers=headers).json()["actor"])


class AnnouncementFlow(unittest.TestCase):
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
        self.admin, _ = self.host_login("10001")

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

    def player_login(self, qq_id):
        challenge = self.client.post("/api/native/auth/challenges").json()
        self.client.post(
            "/api/internal/qq/login",
            headers={"X-Gateway-Token": "test-gateway-secret"},
            json={
                "code": challenge["code"],
                "qq_id": qq_id,
                "nickname": "玩家" + qq_id,
                "avatar_url": "",
                "group_id": 123456,
            },
        ).raise_for_status()
        completed = self.client.get("/api/native/auth/challenges/" + challenge["id"])
        completed.raise_for_status()
        return {"Authorization": "Bearer " + completed.json()["session_token"]}

    def test_only_level_five_publishes_and_everyone_reads(self):
        player = self.player_login("20001")
        self.assertEqual(
            self.client.post(
                "/api/announcements",
                headers=player,
                json={"title": "越权", "body": "x"},
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.get("/api/announcements", headers=player).status_code, 200
        )

        created = self.client.post(
            "/api/announcements",
            headers=self.admin,
            json={"title": "维护公告", "body": "# 标题\n\n- 第一条\n- 第二条"},
        )
        self.assertEqual(created.status_code, 200, created.text)
        announcement = created.json()
        self.assertTrue(announcement["hash"])
        self.assertEqual(announcement["author_name"], "主持10001")

        # 大厅轮询顺带下发公告与版本号：玩家也能看到。
        lobby = self.client.get("/api/lobby", headers=player).json()
        self.assertEqual([item["title"] for item in lobby["announcements"]], ["维护公告"])
        first_version = lobby["announcements_version"]
        self.assertTrue(first_version)

        edited = self.client.post(
            f"/api/announcements/{announcement['id']}",
            headers=self.admin,
            json={"title": "维护公告", "body": "改过的正文"},
        )
        self.assertEqual(edited.status_code, 200, edited.text)
        self.assertNotEqual(edited.json()["hash"], announcement["hash"], "改正文要换哈希")
        after = self.client.get("/api/lobby", headers=player).json()
        self.assertNotEqual(after["announcements_version"], first_version, "版本号要变")

        # 非 5 级主持不能改也不能删。
        challenge = self.client.post("/api/native/auth/host/challenges").json()
        self.client.post(
            "/api/internal/qq/login",
            headers={"X-Gateway-Token": "test-gateway-secret"},
            json={
                "code": challenge["code"],
                "qq_id": "20002",
                "nickname": "无授权",
                "avatar_url": "",
                "group_id": 123456,
            },
        ).raise_for_status()
        self.assertEqual(
            self.client.get("/api/native/auth/host/challenges/" + challenge["id"]).status_code,
            403,
        )

        removed = self.client.delete(
            f"/api/announcements/{announcement['id']}", headers=self.admin
        )
        self.assertEqual(removed.status_code, 200, removed.text)
        empty = self.client.get("/api/lobby", headers=player).json()
        self.assertEqual(empty["announcements"], [])
        self.assertNotEqual(empty["announcements_version"], after["announcements_version"])


if __name__ == "__main__":
    unittest.main()
