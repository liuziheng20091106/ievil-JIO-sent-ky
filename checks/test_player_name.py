"""昵称展示上限：发往界面的展示名一律不超过 16 个半角宽度（中文按 2 算）。

存储里保留完整昵称（账号昵称、参与身份快照、消息留档都不改写），只有下发到客户端
的字符串走 ``state.display_player_name``：席位名、聊天昵称、选择器标签、系统文案与
主持人展示名都要截断，主持人标签「主持人(昵称)」只截断括号里的昵称。
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import storage
from backend.app.game import DEFAULT_CODEX
from backend.app.game.actions import seat_options
from backend.app.game.state import display_player_name, host_display_name
from backend.app.main import app
from backend.app.views import participant_summary

LONG = "很长的昵称啊真的很长啊"
SHORT = "阿雪"


class DisplayPlayerNameTest(unittest.TestCase):
    def test_keeps_short_names(self):
        self.assertEqual(display_player_name(SHORT), SHORT)
        self.assertEqual(display_player_name(""), "")
        self.assertEqual(display_player_name(None), "")
        self.assertEqual(display_player_name("  阿雪  "), "阿雪")

    def test_truncates_beyond_the_width_limit(self):
        # 8 个汉字 = 16 半角宽度，正好占满；再长就在第 8 个字后截断。
        limit = "一二三四五六七八"
        self.assertEqual(display_player_name(limit), limit)
        self.assertEqual(display_player_name(limit + "九"), limit + "…")
        self.assertEqual(display_player_name(LONG), LONG[:8] + "…")

    def test_counts_each_chinese_character_as_two_units(self):
        # 16 个半角字母正好占满；多一个就截到 16。
        ascii16 = "abcdefghijklmnop"
        self.assertEqual(display_player_name(ascii16), ascii16)
        self.assertEqual(display_player_name(ascii16 + "q"), ascii16 + "…")
        # 中英混排按宽度累加：2 + 14 = 16 不截，再宽就截。
        mixed = "阿雪abcdefghijkl"
        self.assertEqual(display_player_name(mixed), mixed)
        self.assertEqual(display_player_name(mixed + "m"), mixed + "…")
        # 宽度超出时不会截出半个全角字符之外的歧义：按整字符保留。
        self.assertEqual(display_player_name("中文abc中文"), "中文abc中文")

    def test_only_truncates_the_nickname_inside_the_host_label(self):
        self.assertEqual(host_display_name(SHORT), "主持人(阿雪)")
        self.assertEqual(host_display_name(LONG), "主持人(" + LONG[:8] + "…)")
        # 已经拼好的主持人展示名再截断一次也不会丢掉「主持人(」。
        self.assertEqual(
            display_player_name(host_display_name(LONG)),
            "主持人(" + LONG[:8] + "…)",
        )

    def test_seat_options_use_the_display_name(self):
        game = {
            "status": "lobby",
            "seats": [{"id": "3", "name": LONG}, {"id": "4", "name": SHORT}],
        }
        self.assertEqual(
            seat_options(game, alive=False),
            [("3", "3号 · " + LONG[:8] + "…"), ("4", "4号 · 阿雪")],
        )

    def test_message_and_participant_projections_use_the_display_name(self):
        shown = LONG[:8] + "…"
        message = storage.message_view(
            {
                "id": 1,
                "kind": "chat",
                "sender_id": "p1",
                "sender_name": LONG,
                "avatar_role_id": None,
                "channel_id": "public",
                "text": "你好",
                "created_at": "2026-01-01T00:00:00+00:00",
                "image_id": None,
            },
            {"id": "p1", "access_ids": ["p1"]},
        )
        self.assertEqual(message["sender_name"], shown)
        # 主持人消息的展示名是「主持人(昵称)」：只截断括号里的昵称。
        self.assertEqual(
            storage.message_view(
                {
                    "id": 2,
                    "kind": "chat",
                    "sender_id": "host",
                    "sender_name": host_display_name(LONG),
                    "avatar_role_id": "host",
                    "channel_id": "public",
                    "text": "好",
                    "created_at": "2026-01-01T00:00:00+00:00",
                    "image_id": None,
                },
                {"id": "host", "access_ids": ["host"]},
            )["sender_name"],
            "主持人(" + shown + ")",
        )
        summary = participant_summary(
            {"id": "p1", "name": LONG, "kind": "player", "seat_id": "3"}
        )
        self.assertEqual(summary["name"], shown)


class PlayerNameProjectionTest(unittest.TestCase):
    """真实接口投影：给一个长昵称的玩家，检查下发的展示名都已截断。"""

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
        self.host, _ = self.login("10001", LONG, host=True)
        created = self.client.post(
            "/api/games", headers=self.host, json={"codex": DEFAULT_CODEX}
        )
        created.raise_for_status()
        self.game_id = created.json()["id"]
        self.root = f"/api/games/{self.game_id}"
        self.client.post(self.root + "/host/enter", headers=self.host).raise_for_status()
        state = self.client.get(self.root + "/state", headers=self.host).json()
        self.client.post(
            self.root + "/commands",
            headers=self.host,
            json={
                "expected_version": state["version"],
                "action": "room.open_join",
                "payload": {"open": True},
            },
        ).raise_for_status()

    def login(self, qq_id, nickname, *, host=False):
        kind = "/host" if host else ""
        challenge = self.client.post(f"/api/native/auth{kind}/challenges").json()
        bound = self.client.post(
            "/api/internal/qq/login",
            headers={"X-Gateway-Token": "test-gateway-secret"},
            json={
                "code": challenge["code"],
                "qq_id": qq_id,
                "nickname": nickname,
                "avatar_url": "https://example.invalid/" + qq_id,
                "group_id": 123456,
            },
        )
        bound.raise_for_status()
        completed = self.client.get(f"/api/native/auth{kind}/challenges/" + challenge["id"])
        completed.raise_for_status()
        return {"Authorization": "Bearer " + completed.json()["session_token"]}, completed.json()

    def test_seat_chat_and_system_text_show_truncated_names(self):
        _, session = self.login("20001", LONG)
        player = {"Authorization": "Bearer " + session["session_token"]}
        joined = self.client.post(
            self.root + "/participations", headers=player, json={"kind": "player"}
        )
        joined.raise_for_status()
        seat_id = joined.json()["actor"]["seat_id"]
        shown = LONG[:8] + "…"

        # 席位投影：昵称截断，客户端所有席位相关展示（席位卡、选择器、快捷菜单）都拿它。
        view = self.client.get(self.root + "/state", headers=self.host).json()
        seat = next(item for item in view["seats"] if item["id"] == seat_id)
        self.assertEqual(seat["name"], shown)
        # 主持人展示名同样是截断过的：主持人(昵称)。
        self.assertEqual(view["host_name"], "主持人(" + shown + ")")

        # 加入提示是系统文案，昵称必须与席位投影一致。
        page = self.client.get(self.root + "/messages", headers=self.host).json()
        notice = next(item for item in page["messages"] if "已加入对局" in item["text"])
        self.assertEqual(notice["text"], f"{seat_id}号玩家【{shown}】已加入对局")

        # 聊天昵称：实时返回与历史分页都走同一份投影。
        sent = self.client.post(
            self.root + "/messages",
            headers=player,
            json={"channel_id": "public", "text": "你好"},
        )
        sent.raise_for_status()
        self.assertEqual(sent.json()["sender_name"], shown)
        page = self.client.get(self.root + "/messages?scope=all", headers=self.host).json()
        chat = next(item for item in page["messages"] if item["text"] == "你好")
        self.assertEqual(chat["sender_name"], shown)

        # 原昵称不会出现在任何一份下发里。
        self.assertNotIn(LONG, self.client.get(self.root + "/state", headers=self.host).text)

    def test_room_action_labels_use_the_display_name(self):
        _, session = self.login("20002", LONG)
        player = {"Authorization": "Bearer " + session["session_token"]}
        joined = self.client.post(
            self.root + "/participations", headers=player, json={"kind": "player"}
        )
        joined.raise_for_status()
        shown = LONG[:8] + "…"
        view = self.client.get(self.root + "/state", headers=self.host).json()
        labels = [
            option["label"]
            for action in view["actions"]
            for field in action.get("fields", [])
            for option in field.get("options", [])
        ]
        self.assertTrue(
            any(shown in label and LONG not in label for label in labels),
            labels,
        )


if __name__ == "__main__":
    unittest.main()
