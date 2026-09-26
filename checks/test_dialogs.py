"""对局内悬浮对话框：服务端决定弹什么、按什么优先级，并带上可直接提交的行动描述。"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import storage, views
from backend.app.game import DEFAULT_CODEX
from backend.app.main import app

HOST = {"id": "host", "kind": "host", "host_entered": True, "access_ids": ["host"]}


class DialogProjection(unittest.TestCase):
    """纯投影：顺序与内容，不依赖数据库。"""

    def test_priority_is_result_then_invite_then_witness(self):
        game = {
            "id": "game-x",
            "status": "playing",
            "result": {"winner": "good", "reason": "魔女阵营A、B两席出局"},
        }
        domain = {
            "channels": [
                {
                    "id": "private:abc",
                    "label": "私密 · 3号",
                    "invitation": "pending",
                    "creator_id": "p3",
                    "members": [{"id": "p3", "name": "庭雨", "seat_id": "3"}],
                    "actions": [{"id": "channel.accept", "payload": {"channel_id": "private:abc"}}],
                }
            ],
            "witness": {"day": 2, "text": "四名疑似凶手：梅露露、汉娜、可可、诺亚。"},
        }
        items = views.dialogs(game, HOST, domain)
        self.assertEqual([item["kind"] for item in items], ["result", "channel_invite", "witness"])
        self.assertEqual(items[0]["title"], "本局已结束 · 好人获胜")
        self.assertEqual(items[0]["match_id"], "game-x")
        self.assertIn("3号 庭雨 邀请你加入私信", items[1]["text"])
        self.assertEqual(items[1]["actions"][0]["id"], "channel.accept")

    def test_ended_game_keeps_only_the_result_dialog(self):
        game = {
            "id": "game-x",
            "status": "ended",
            "result": {"winner": "witch", "reason": "米莉亚与亚里沙均出局"},
        }
        domain = {
            "channels": [
                {"id": "private:abc", "invitation": "pending", "actions": [], "members": []}
            ],
            "witness": {"day": 2, "text": "四名疑似凶手：…"},
        }
        items = views.dialogs(game, HOST, domain)
        # 结束信息与目击名单可以同时存在；已结束的对局不再下发私聊申请。
        self.assertEqual([item["kind"] for item in items], ["result", "witness"])

    def test_nothing_to_show_is_an_empty_list(self):
        game = {"id": "game-x", "status": "playing", "result": None}
        self.assertEqual(views.dialogs(game, HOST, {"channels": [], "witness": None}), [])

    def test_result_titles_cover_aborted_matches(self):
        self.assertEqual(views.result_title({"winner": "aborted"}), "本局已终止")
        self.assertEqual(views.result_title({"winner": ""}), "本局已结束")


class DialogFlow(unittest.TestCase):
    """端到端：私聊申请真的会弹在被告知的人身上，并且能用同一份描述被接受。"""

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
        created = self.client.post(
            "/api/games", headers=self.host, json={"codex": DEFAULT_CODEX}
        )
        created.raise_for_status()
        self.game_id = created.json()["id"]
        self.root = f"/api/games/{self.game_id}"
        self.client.post(self.root + "/host/enter", headers=self.host).raise_for_status()

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

    def state(self, headers):
        response = self.client.get(self.root + "/state", headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def command(self, headers, action, payload=None):
        view = self.state(headers)
        response = self.client.post(
            self.root + "/commands",
            headers=headers,
            json={
                "expected_version": view["version"],
                "action": action,
                "payload": payload or {},
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def join(self, headers):
        response = self.client.post(
            self.root + "/participations", headers=headers, json={"kind": "player"}
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_pending_private_invite_dialog_for_the_invited_player(self):
        self.command(self.host, "room.open_join", {"open": True})
        first, second = self.account("20001"), self.account("20002")
        self.join(first)
        self.join(second)
        view = self.state(first)
        own = view["self"]["seat_id"]
        target = next(
            seat["participant_id"]
            for seat in view["seats"]
            if seat["occupied"] and seat["id"] != own
        )
        self.command(first, "channel.create", {"participant_ids": [target]})

        invited = self.state(second)
        dialogs = invited["dialogs"]
        self.assertEqual(len(dialogs), 1, dialogs)
        invite = dialogs[0]
        self.assertEqual(invite["kind"], "channel_invite")
        self.assertTrue(invite["dismissible"])
        self.assertEqual(
            [action["id"] for action in invite["actions"]],
            ["channel.accept", "channel.reject"],
        )
        # 发起人自己不该看到「等你回应」的对话框。
        self.assertEqual(self.state(first)["dialogs"], [])

        accepted = self.command(
            second, "channel.accept", invite["actions"][0]["payload"]
        )
        self.assertEqual(accepted["dialogs"], [])
        channel = next(
            item for item in accepted["channels"] if item["id"] == invite["id"].split(":", 1)[1]
        )
        self.assertEqual(channel["status"], "active")

    def test_result_dialog_appears_for_everyone_when_the_match_ends(self):
        player = self.account("20003")
        self.command(self.host, "room.open_join", {"open": True})
        self.join(player)
        self.command(self.host, "host.end", {"winner": "aborted", "reason": "测试终止"})
        for headers in (self.host, player):
            dialogs = self.state(headers)["dialogs"]
            self.assertEqual([item["kind"] for item in dialogs], ["result"], dialogs)
            self.assertEqual(dialogs[0]["title"], "本局已终止")
            self.assertEqual(dialogs[0]["text"], "测试终止")
            self.assertEqual(dialogs[0]["match_id"], self.game_id)
