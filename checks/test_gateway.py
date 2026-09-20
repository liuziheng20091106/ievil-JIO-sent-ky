"""网关多群监听：群号解析、成员合并去重、登录回执发回发言群。"""

import unittest

from gateway.gateway import QQGateway, clean_members, parse_group_ids


class GroupIds(unittest.TestCase):
    def test_parses_comma_separated_list(self):
        self.assertEqual(
            parse_group_ids("1105925736,775621176, 867118030"),
            (1105925736, 775621176, 867118030),
        )
        self.assertEqual(parse_group_ids(" 123456 "), (123456,))

    def test_rejects_empty_list(self):
        with self.assertRaises(RuntimeError):
            parse_group_ids(" , ")


class MemberMerge(unittest.TestCase):
    def test_merges_groups_and_keeps_first_nickname_per_qq_id(self):
        """多群合并去重：同一 QQ 号只提交一次，先出现的群优先。"""
        members = clean_members(
            [
                {"user_id": 10001, "nickname": "甲"},
                {"user_id": 10002, "card": "乙的群名片"},
                {"user_id": 10001, "nickname": "甲在第二个群的名字"},
            ]
        )
        self.assertEqual([member["qq_id"] for member in members], ["10001", "10002"])
        self.assertEqual(members[0]["nickname"], "甲")
        self.assertEqual(members[1]["nickname"], "乙的群名片")
        self.assertEqual(members[0]["avatar_url"], "https://q1.qlogo.cn/g?b=qq&nk=10001&s=100")

    def test_drops_invalid_qq_and_cleans_nickname(self):
        members = clean_members(
            [
                {"user_id": "abc"},
                {"user_id": "123"},
                {"user_id": 10003, "nickname": "   "},
                {"user_id": 10004, "nickname": "长" * 100},
            ]
        )
        self.assertEqual([member["qq_id"] for member in members], ["10003", "10004"])
        self.assertEqual(members[0]["nickname"], "10003")
        self.assertEqual(len(members[1]["nickname"]), 64)


class StubConnection:
    def __init__(self):
        self.actions = []

    async def action(self, action, params, timeout=20):
        self.actions.append((action, params))
        return {"retcode": 0, "data": []}


def group_message(group_id, text="活动登录 123456"):
    return {
        "post_type": "message",
        "message_type": "group",
        "group_id": group_id,
        "user_id": 10001,
        "raw_message": text,
        "sender": {"nickname": "玩家"},
    }


class EventRouting(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.gateway = QQGateway(
            ws_url="ws://127.0.0.1:1",
            token="",
            backend_url="https://backend.invalid",
            gateway_token="test-gateway-secret",
            group_ids=(1105925736, 775621176),
        )
        self.bound = []

        async def bind_login(**kwargs):
            self.bound.append(kwargs)
            return True

        self.gateway.bind_login = bind_login

    async def test_second_group_is_watched_and_ack_goes_to_source_group(self):
        connection = StubConnection()
        await self.gateway.handle_event(connection, group_message(775621176))
        self.assertEqual([item["group_id"] for item in self.bound], [775621176])
        self.assertEqual(
            connection.actions,
            [("send_group_msg", {"group_id": 775621176, "message": "玩家，登录成功~"})],
        )

    async def test_unlisted_group_is_ignored(self):
        connection = StubConnection()
        await self.gateway.handle_event(connection, group_message(867118030))
        self.assertEqual(self.bound, [])
        self.assertEqual(connection.actions, [])

    async def test_non_login_text_is_ignored(self):
        connection = StubConnection()
        await self.gateway.handle_event(connection, group_message(1105925736, "活动登录 12345"))
        self.assertEqual(self.bound, [])
        self.assertEqual(connection.actions, [])


if __name__ == "__main__":
    unittest.main()
