"""网关多群监听：群号解析、成员合并去重、登录回执发回发言群。"""

import unittest

from gateway.gateway import LOGIN_HINT, QQGateway, clean_members, error_detail, parse_group_ids


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


class ErrorDetail(unittest.TestCase):
    class Response:
        def __init__(self, status_code, payload, raises=False):
            self.status_code = status_code
            self.payload = payload
            self.raises = raises

        def json(self):
            if self.raises:
                raise ValueError("not json")
            return self.payload

    def test_uses_backend_detail(self):
        response = self.Response(409, {"detail": "登录码无效、过期或已经使用"})
        self.assertEqual(error_detail(response), "登录码无效、过期或已经使用")

    def test_falls_back_when_body_is_not_a_string_detail(self):
        """Pydantic 校验错误是列表；取不到文案时退回状态码，别把整坨 JSON 发进群。"""
        self.assertEqual(
            error_detail(self.Response(422, {"detail": [{"loc": ["body"], "msg": "bad"}]})),
            "服务端返回 HTTP 422",
        )
        self.assertEqual(
            error_detail(self.Response(502, None, raises=True)), "服务端返回 HTTP 502"
        )


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
        self.reason = None

        async def bind_login(**kwargs):
            self.bound.append(kwargs)
            return self.reason

        self.gateway.bind_login = bind_login

    async def test_second_group_is_watched_and_ack_goes_to_source_group(self):
        connection = StubConnection()
        await self.gateway.handle_event(connection, group_message(775621176))
        self.assertEqual([item["group_id"] for item in self.bound], [775621176])
        self.assertEqual(
            connection.actions,
            [("send_group_msg", {"group_id": 775621176, "message": "玩家，登录成功~"})],
        )

    async def test_failure_reason_is_sent_back_to_source_group(self):
        """登录码无效/过期时群成员必须看到原因，而不是静默无反应。"""
        self.reason = "登录码无效、过期或已经使用"
        connection = StubConnection()
        await self.gateway.handle_event(connection, group_message(775621176))
        self.assertEqual(
            connection.actions,
            [
                (
                    "send_group_msg",
                    {
                        "group_id": 775621176,
                        "message": "玩家，登录失败：登录码无效、过期或已经使用",
                    },
                )
            ],
        )

    async def test_backend_failure_still_replies_in_group(self):
        async def boom(**kwargs):
            raise OSError("connection refused")

        self.gateway.bind_login = boom
        connection = StubConnection()
        await self.gateway.handle_event(connection, group_message(1105925736))
        self.assertEqual(
            connection.actions,
            [("send_group_msg", {"group_id": 1105925736, "message": "玩家，登录失败：服务端暂时不可用"})],
        )

    async def test_unlisted_group_is_ignored(self):
        connection = StubConnection()
        await self.gateway.handle_event(connection, group_message(867118030))
        self.assertEqual(self.bound, [])
        self.assertEqual(connection.actions, [])

    async def test_non_login_text_is_ignored(self):
        connection = StubConnection()
        await self.gateway.handle_event(connection, group_message(1105925736, "今天天气不错"))
        self.assertEqual(self.bound, [])
        self.assertEqual(connection.actions, [])

    async def test_malformed_login_attempt_gets_a_format_hint(self):
        """位数不对、没抄全的登录尝试也要有回音，别让玩家干等。"""
        connection = StubConnection()
        await self.gateway.handle_event(connection, group_message(1105925736, "活动登录 12345"))
        self.assertEqual(self.bound, [])
        self.assertEqual(
            connection.actions,
            [("send_group_msg", {"group_id": 1105925736, "message": LOGIN_HINT})],
        )


if __name__ == "__main__":
    unittest.main()
