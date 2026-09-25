"""Stable auth, open participation, spectator, and private-channel boundaries."""

import ast
import inspect
import os
import sqlite3
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.app import auth_storage, realtime, storage
from backend.app.game import DEFAULT_CODEX, create_game
from backend.app.main import app


class BackendFlow(unittest.TestCase):
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
        # 主持人不再是共享密码：GAME_ADMIN_QQ 指定的 QQ 账号登录后即为 5 级主持。
        self.host, self.host_actor = self.host_login("10001")
        created = self.client.post("/api/games", headers=self.host, json={"codex": DEFAULT_CODEX})
        created.raise_for_status()
        self.game_id = created.json()["id"]
        self.root = f"/api/games/{self.game_id}"
        # 主持人同真实客户端一样先确认进入管理界面：服务端从这一步起才下发
        # 主持级数据与操作（未确认时只有最窄的观察者投影）。
        self.enter_host_admin(self.host)

    def enter_host_admin(self, headers):
        response = self.client.post(self.root + "/host/enter", headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def host_login(self, qq_id):
        """主持人入口的 QQ 登录：与玩家共用登录码，只是换成主持人挑战端点。"""
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
        completed = self.client.get(
            "/api/native/auth/host/challenges/" + challenge["id"]
        )
        completed.raise_for_status()
        self.assertEqual(completed.json().get("status"), "completed")
        return {
            "Authorization": "Bearer " + completed.json()["session_token"]
        }, completed.json()["session"]["actor"]

    def account(self, qq_id):
        challenge = self.client.post("/api/native/auth/challenges").json()
        bound = self.client.post(
            "/api/internal/qq/login",
            headers={"X-Gateway-Token": "test-gateway-secret"},
            json={
                "code": challenge["code"],
                "qq_id": qq_id,
                "nickname": "QQ" + qq_id,
                "avatar_url": "https://example.invalid/" + qq_id,
                "group_id": 123456,
            },
        )
        bound.raise_for_status()
        completed = self.client.get(
            "/api/native/auth/challenges/" + challenge["id"]
        )
        completed.raise_for_status()
        # 原生客户端同样按 status 判断登录完成，缺了它会继续轮询已消费的挑战。
        self.assertEqual(completed.json().get("status"), "completed")
        return {
            "Authorization": "Bearer " + completed.json()["session_token"]
        }, completed.json()["session"]["actor"]

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
        return response

    def open_join(self):
        self.command(self.host, "room.open_join", {"open": True})

    def join(self, qq_id, kind="player"):
        headers, session = self.account(qq_id)
        response = self.client.post(
            self.root + "/participations", headers=headers, json={"kind": kind}
        )
        response.raise_for_status()
        return headers, response.json()["actor"], session

    def test_challenges_are_one_time_and_web_never_receives_a_token(self):
        challenge = self.client.post("/api/auth/challenges").json()
        self.assertRegex(challenge["code"], r"^\d{6}$")
        bound = self.client.post(
            "/api/internal/qq/login",
            headers={"X-Gateway-Token": "test-gateway-secret"},
            json={
                "code": challenge["code"],
                "qq_id": "10001",
                "nickname": "网页玩家",
                "group_id": 123456,
            },
        )
        self.assertEqual(bound.status_code, 200, bound.text)
        replay = self.client.post(
            "/api/internal/qq/login",
            headers={"X-Gateway-Token": "test-gateway-secret"},
            json={
                "code": challenge["code"],
                "qq_id": "10002",
                "nickname": "重放",
                "group_id": 123456,
            },
        )
        self.assertEqual(replay.status_code, 409, replay.text)
        completed = self.client.get("/api/auth/challenges/" + challenge["id"])
        self.assertEqual(completed.status_code, 200, completed.text)
        # 完成后必须回 status=completed：前端靠它停止轮询。缺了它前端会继续轮询，
        # 挑战已消费于是下一次拿到 410，表现为「登录失败」但账号其实已经登录。
        self.assertEqual(completed.json().get("status"), "completed")
        self.assertEqual(set(completed.json()), {"status", "actor", "game_id"})
        self.assertNotIn("token", completed.text.lower())
        self.assertIn("seven_double_session", completed.cookies)
        self.assertEqual(
            self.client.get("/api/auth/challenges/" + challenge["id"]).status_code, 410
        )
        raw_cookie = completed.cookies["seven_double_session"]
        with auth_storage.connect() as db:
            rows = db.execute("SELECT token_hash FROM login_tokens").fetchall()
            self.assertNotIn(raw_cookie, {row["token_hash"] for row in rows})
            self.assertTrue(any(row["token_hash"] == auth_storage.secret_hash(raw_cookie) for row in rows))

    def test_open_join_stable_account_capacity_and_spectator_projection(self):
        waiting, _ = self.account("11000")
        closed = self.client.post(
            self.root + "/participations", headers=waiting, json={"kind": "player"}
        )
        self.assertEqual(closed.status_code, 409, closed.text)
        self.open_join()
        players = [self.join(str(11001 + index)) for index in range(7)]
        self.assertEqual({actor["seat_id"] for _, actor, _ in players}, set("1234567"))
        repeated = self.client.post(
            self.root + "/participations", headers=players[0][0], json={"kind": "player"}
        )
        self.assertEqual(repeated.json()["actor"]["id"], players[0][1]["id"])
        eighth, _ = self.account("11009")
        full = self.client.post(
            self.root + "/participations", headers=eighth, json={"kind": "player"}
        )
        self.assertEqual(full.status_code, 409, full.text)
        spectator = self.client.post(
            self.root + "/participations", headers=eighth, json={"kind": "spectator"}
        )
        spectator.raise_for_status()
        for headers, _, _ in players:
            self.command(headers, "lobby.ready")
        watched = self.client.get(self.root + "/state", headers=eighth).json()
        # 候场/调序阶段对观战者收起双牌明细，替补入场前不得提前知情。
        self.assertTrue(all(not seat.get("cards") for seat in watched["seats"]))
        self.assertTrue(all("current_card_id" not in seat for seat in watched["seats"]))
        self.assertNotIn("host", watched)
        denied = self.command(eighth, "lobby.ready", status=403)
        self.assertIn("观战者", denied.text)
        evidence = self.client.post(self.root + "/evidence", headers=eighth, json={"text": "x"})
        self.assertEqual(evidence.status_code, 403, evidence.text)

    def test_spectator_leaves_by_itself_but_player_cannot(self):
        self.open_join()
        player, _, _ = self.join("11101")
        spectator, spectator_actor, _ = self.join("11102", "spectator")

        # 占席玩家的退出仍由主持人裁量（room.kick），不能自己脱落。
        refused = self.client.post(self.root + "/leave", headers=player)
        self.assertEqual(refused.status_code, 403, refused.text)

        left = self.client.post(self.root + "/leave", headers=spectator)
        self.assertEqual(left.status_code, 200, left.text)
        # 离开即不再是本局参与身份，但重新观战仍然可以（参与身份只是置为不活跃）。
        self.assertEqual(
            self.client.get(self.root + "/state", headers=spectator).status_code, 401
        )
        notice = self.client.get(self.root + "/messages", headers=self.host).json()["messages"]
        self.assertTrue(any("已离开对局" in message["text"] for message in notice))
        rejoined = self.client.post(
            self.root + "/participations", headers=spectator, json={"kind": "spectator"}
        )
        self.assertEqual(rejoined.status_code, 200, rejoined.text)
        self.assertEqual(rejoined.json()["actor"]["id"], spectator_actor["id"])
        self.assertIsNone(rejoined.json()["actor"]["seat_id"])

    def test_unconfirmed_host_sees_no_cards_and_no_private_history(self):
        """未确认进入管理界面的主持人只有观察者投影：没有全席双牌，也读不到本局私聊。

        这是「确认进入」真正的边界：客户端上的确认页不能只是遮罩，服务端必须同时
        收回牌面、主持人面板、私聊历史与管理操作。
        """
        self.open_join()
        players = [self.join(str(13001 + index)) for index in range(7)]
        for headers, _, _ in players:
            self.command(headers, "lobby.ready")
        dealt = self.client.get(self.root + "/state", headers=self.host).json()
        self.assertTrue(all(seat.get("cards") for seat in dealt["seats"]), "七人准备后应已发牌")

        # 主持人与 1 号席的私聊：未确认进入的主持人连这段历史都不该读到。
        created = self.command(
            self.host, "channel.create", {"participant_ids": [players[0][1]["id"]]}
        ).json()
        channel = next(item for item in created["channels"] if item["id"].startswith("private:"))
        self.assertEqual(channel["status"], "active")
        self.client.post(
            self.root + "/messages",
            headers=self.host,
            json={"channel_id": channel["id"], "text": "私下确认一件事"},
        ).raise_for_status()

        # 第二个主持账号（5 级）：登录后先不确认进入。
        _, other_account = self.account("13099")
        granted = self.client.post(
            f"/api/hosts/{other_account['account_id']}", headers=self.host, json={"level": 5}
        )
        self.assertEqual(granted.status_code, 200, granted.text)
        other, _ = self.host_login("13099")

        view = self.client.get(self.root + "/state", headers=other).json()
        self.assertTrue(view["host_entry_required"])
        self.assertNotIn("host", view)
        self.assertTrue(all("cards" not in seat for seat in view["seats"]))
        self.assertTrue(all("current_card_id" not in seat for seat in view["seats"]))
        self.assertEqual(view["actions"], [], "未确认进入不该有任何行动入口")
        for scope in ("all", "private", "host"):
            page = self.client.get(
                self.root + "/messages", headers=other, params={"scope": scope}
            ).json()
            self.assertFalse(
                any("私下确认一件事" in item["text"] for item in page["messages"]),
                f"未确认进入的主持人不该读到本局私聊（scope={scope}）",
            )
        # 也不能在别人的私聊里发言，或执行房间管理（禁言等）。
        self.assertEqual(
            self.client.post(
                self.root + "/messages",
                headers=other,
                json={"channel_id": channel["id"], "text": "偷看"},
            ).status_code,
            403,
        )
        state = self.client.get(self.root + "/state", headers=other).json()
        self.assertEqual(
            self.client.post(
                self.root + "/commands",
                headers=other,
                json={
                    "expected_version": state["version"],
                    "action": "room.mute",
                    "payload": {"participant_id": players[0][1]["id"], "muted": True},
                },
            ).status_code,
            403,
        )

        # 确认进入后服务端立刻重推状态：原生客户端与网页端都不必再手动刷新。
        with self.client.websocket_connect("/api/live", headers=other) as socket:
            sync = socket.receive_json()
            self.assertEqual(sync["type"], "sync")
            self.assertNotIn("host", sync["state"])
            pushed = self.client.post(self.root + "/host/enter", headers=other)
            self.assertEqual(pushed.status_code, 200, pushed.text)
            frame = None
            # 连接建立时还会推一份未确认的投影，这里要等到确认之后的那一份。
            for _ in range(10):
                candidate = socket.receive_json()
                if candidate["type"] != "state" or "host" not in candidate["state"]:
                    continue
                frame = candidate["state"]
                break
            self.assertIsNotNone(frame, "确认进入后要推送升级后的状态")
            self.assertTrue(all(seat.get("cards") for seat in frame["seats"]))

        # 确认进入之后，同一批请求就拿到牌面、主持人面板与那段私聊。
        entered = self.client.post(self.root + "/host/enter", headers=other)
        self.assertEqual(entered.status_code, 200, entered.text)
        after = self.client.get(self.root + "/state", headers=other).json()
        self.assertFalse(after["host_entry_required"])
        self.assertIn("host", after)
        self.assertTrue(all(seat.get("cards") for seat in after["seats"]))
        page = self.client.get(
            self.root + "/messages", headers=other, params={"scope": "private"}
        ).json()
        self.assertTrue(any("私下确认一件事" in item["text"] for item in page["messages"]))

    def test_private_channel_lifecycle_locks_actions_and_history(self):
        self.open_join()
        first, first_actor, _ = self.join("12001")
        second, second_actor, _ = self.join("12002")
        stranger, _, _ = self.join("12003", "spectator")
        created = self.command(
            first,
            "channel.create",
            {"name": "作战", "participant_ids": [second_actor["id"], "host"]},
        ).json()
        channel = next(
            item
            for item in created["channels"]
            if {member["id"] for member in item["members"]}
            == {first_actor["id"], second_actor["id"], "host"}
        )
        self.assertEqual(channel["status"], "pending")
        invited = self.client.get(self.root + "/state", headers=second).json()
        pending = next(item for item in invited["channels"] if item["id"] == channel["id"])
        self.assertEqual(pending["invitation"], "pending")
        active = self.command(
            second, "channel.accept", {"channel_id": channel["id"]}
        ).json()
        channel = next(item for item in active["channels"] if item["id"] == channel["id"])
        self.assertEqual(channel["status"], "active")
        public = self.client.post(
            self.root + "/messages",
            headers=first,
            json={"channel_id": "public", "text": "blocked"},
        )
        self.assertEqual(public.status_code, 403, public.text)
        self.command(first, "lobby.ready", status=403)
        private = self.client.post(
            self.root + "/messages",
            headers=first,
            json={"channel_id": channel["id"], "text": "secret"},
        )
        private.raise_for_status()
        hidden = self.client.get(
            self.root + "/messages?scope=private", headers=stranger
        ).json()["messages"]
        self.assertNotIn(private.json()["id"], [message["id"] for message in hidden])
        host_busy = self.command(
            self.host,
            "channel.create",
            {"name": "强制", "participant_ids": [first_actor["id"]]},
            status=409,
        )
        self.assertIn("其他私信", host_busy.text)
        ended = self.command(
            second, "channel.end", {"channel_id": channel["id"]}
        ).json()
        channel = next(item for item in ended["channels"] if item["id"] == channel["id"])
        self.assertEqual(channel["status"], "ended")
        restored = self.client.post(
            self.root + "/messages",
            headers=first,
            json={"channel_id": "public", "text": "restored"},
        )
        restored.raise_for_status()
        host_scope = self.client.get(
            self.root + "/messages?scope=host", headers=self.host
        ).json()["messages"]
        self.assertIn(private.json()["id"], [message["id"] for message in host_scope])
        self.assertTrue(all(message["channel_id"] != "public" for message in host_scope))
        system = self.client.get(self.root + "/messages?scope=system", headers=second).json()
        self.assertTrue(any("正在与" in message["text"] for message in system["messages"]))
        self.assertTrue(any("已结束私信" in message["text"] for message in system["messages"]))
        # 私信开合只发给频道成员：不在频道里的旁观者看不到这两条。
        stranger_system = self.client.get(
            self.root + "/messages?scope=system", headers=stranger
        ).json()["messages"]
        self.assertFalse(any("正在与" in message["text"] for message in stranger_system))
        self.assertFalse(any("已结束私信" in message["text"] for message in stranger_system))

    def test_action_prompt_urges_the_blocked_player(self):
        """催办框由服务端决定：只有卡住流程的席位才有，在私聊里额外提示先结束私聊。"""
        self.open_join()
        players = [self.join(f"1270{i}") for i in range(1, 8)]
        headers = [item[0] for item in players]
        actors = [item[1] for item in players]
        prompt = self.client.get(self.root + "/state", headers=headers[0]).json()[
            "action_prompt"
        ]
        self.assertEqual(prompt["title"], "请准备")
        self.assertIsNone(prompt["hint"])
        # 已经准备完的席位不再被催。
        self.command(headers[0], "lobby.ready")
        self.assertNotIn(
            "action_prompt", self.client.get(self.root + "/state", headers=headers[0]).json()
        )
        # 进入私聊后仍要被催，并附带「先结束私聊」的说明。
        created = self.command(
            headers[0],
            "channel.create",
            {"name": "密谈", "participant_ids": [actors[1]["id"], "host"]},
        ).json()
        channel = next(item for item in created["channels"] if item["status"] == "pending")
        self.command(headers[1], "channel.accept", {"channel_id": channel["id"]})
        view = self.client.get(self.root + "/state", headers=headers[1]).json()
        self.assertEqual(view["action_prompt"]["title"], "请准备")
        self.assertIn("私聊", view["action_prompt"]["hint"])

    def test_host_player_pair_channel_skips_system_notice(self):
        self.open_join()
        player, player_actor, _ = self.join("12501")
        stranger, _, _ = self.join("12502", "spectator")
        baseline = self.client.get(self.root + "/messages?scope=system", headers=stranger).json()[
            "messages"
        ]
        created = self.command(
            self.host, "channel.create", {"name": "密谈", "participant_ids": [player_actor["id"]]}
        ).json()
        channel = next(
            item
            for item in created["channels"]
            if {member["id"] for member in item["members"]} == {player_actor["id"], "host"}
        )
        self.assertEqual(channel["status"], "active")
        self.command(player, "channel.end", {"channel_id": channel["id"]})
        system = self.client.get(self.root + "/messages?scope=system", headers=stranger).json()[
            "messages"
        ]
        self.assertEqual([message["id"] for message in system], [message["id"] for message in baseline])

    def test_night_closes_private_channels_and_allows_only_host_chats(self):
        self.open_join()
        players = [self.join(str(13001 + index)) for index in range(7)]
        first, first_actor, _ = players[0]
        second, second_actor, _ = players[1]
        third, third_actor, _ = players[2]
        for headers, _, _ in players:
            self.command(headers, "lobby.ready")
        for headers, _, _ in players:
            self.command(headers, "lobby.ready")
        created = self.command(
            first, "channel.create", {"participant_ids": [second_actor["id"]]}
        ).json()
        paired = next(item for item in created["channels"] if item["status"] == "pending")
        self.command(second, "channel.accept", {"channel_id": paired["id"]})
        host_chat = self.command(
            self.host, "channel.create", {"participant_ids": [third_actor["id"]]}
        ).json()
        host_channel = next(
            item
            for item in host_chat["channels"]
            if {member["id"] for member in item["members"]} == {third_actor["id"], "host"}
        )

        # 主持人开局就是第一夜：玩家私聊与主持人私聊都随天黑关闭。
        started = self.command(self.host, "host.start").json()
        statuses = {item["id"]: item["status"] for item in started["channels"]}
        self.assertEqual(statuses[paired["id"]], "ended")
        self.assertEqual(statuses[host_channel["id"]], "ended")
        notice = self.client.get(self.root + "/messages", headers=second).json()["messages"]
        self.assertTrue(any("夜间只能与主持人私聊" in message["text"] for message in notice))
        ended = self.client.post(
            self.root + "/messages", headers=first, json={"channel_id": paired["id"], "text": "x"}
        )
        self.assertEqual(ended.status_code, 403, ended.text)

        # 夜间玩家只剩主持人一个邀请对象，邀请其他玩家一律拒绝。
        denied = self.command(
            first,
            "channel.create",
            {"participant_ids": [second_actor["id"]]},
            status=403,
        )
        self.assertIn("夜间", denied.text)
        offered = next(
            item
            for item in self.client.get(self.root + "/state", headers=first).json()["actions"]
            if item["id"] == "channel.create"
        )
        self.assertEqual(
            [option["label"] for option in offered["fields"][0]["options"]],
            ["主持人(主持10001)"],
        )

        # 兜底：夜间残留的不含主持人的 active 频道既不能发言，也不锁住玩家行动。
        with storage.connect() as db:
            db.execute(
                "UPDATE channels SET status='active',ended_at=NULL WHERE id=?", (paired["id"],)
            )
            db.commit()
        leftover = next(
            item
            for item in self.client.get(self.root + "/state", headers=first).json()["channels"]
            if item["id"] == paired["id"]
        )
        self.assertFalse(leftover["can_send"])
        self.assertEqual(leftover["reason"], "夜间只能与主持人私聊")
        self.assertTrue(
            any(
                item["id"] == "channel.create"
                for item in self.client.get(self.root + "/state", headers=first).json()["actions"]
            )
        )

        # 与主持人私聊在夜间仍然可以建立；主持人的邀请对象不受限制。
        opened = self.command(first, "channel.create", {"participant_ids": ["host"]}).json()
        self.assertTrue(
            any(
                item["status"] == "active"
                and {member["id"] for member in item["members"]} == {first_actor["id"], "host"}
                for item in opened["channels"]
            )
        )
        host_offered = next(
            item
            for item in self.client.get(self.root + "/state", headers=self.host).json()["actions"]
            if item["id"] == "channel.create"
        )
        self.assertGreater(len(host_offered["fields"][0]["options"]), 1)

    def test_puppet_control_only_authorizes_its_owner_and_only_for_that_seat(self):
        self.open_join()
        players = [self.join(str(14001 + index)) for index in range(7)]
        for headers, _, _ in players:
            self.command(headers, "lobby.ready")
        for headers, _, _ in players:
            self.command(headers, "lobby.ready")
        self.command(self.host, "host.start")
        state = self.client.get(self.root + "/state", headers=self.host).json()
        seats = {seat["id"]: seat for seat in state["seats"]}
        # 控制者席位必须持有一张可魔女化的当前牌；被控席位取另一席。
        controller, controller_actor, _ = next(
            player
            for player in players
            if seats[player[1]["seat_id"]]["current_card_id"] not in {"sherry", "arisa", "emma"}
        )
        victim, victim_actor, _ = next(
            player for player in players if player[1]["seat_id"] != controller_actor["seat_id"]
        )
        stranger, _, _ = next(
            player
            for player in players
            if player[1]["seat_id"] not in {controller_actor["seat_id"], victim_actor["seat_id"]}
        )
        master_card = seats[controller_actor["seat_id"]]["current_card_id"]
        puppet_card = seats[victim_actor["seat_id"]]["current_card_id"]
        self.command(self.host, "host.state", {"card_id": master_card, "state": "witch", "value": True, "reason": "测试"})
        self.command(
            self.host,
            "host.state",
            {
                "card_id": puppet_card,
                "state": "puppet",
                "value": True,
                "master": master_card,
                "public": True,
                "reason": "测试傀儡控制",
            },
        )
        controlled = self.client.get(self.root + "/state", headers=controller).json()
        panels = controlled["self"]["puppet_controls"]
        self.assertEqual([panel["seat_id"] for panel in panels], [victim_actor["seat_id"]])
        self.assertTrue(
            all(item["as_seat"] == victim_actor["seat_id"] for item in panels[0]["actions"])
        )
        self.assertTrue(panels[0]["channels"][0]["label"].startswith("*"))
        for channel in panels[0]["channels"]:
            for item in channel["actions"]:
                self.assertTrue(2 <= len(item["short_label"]) <= 4, item["short_label"])
                self.assertTrue(item["label"].startswith("*"), item["label"])
        # 傀儡视角只能执行服务端按该席生成的动作：主持人的动作即使指定 as_seat 也被拒绝。
        state_view = self.client.get(self.root + "/state", headers=controller).json()
        refused_action = self.client.post(
            self.root + "/commands",
            headers=controller,
            json={
                "expected_version": state_view["version"],
                "action": "host.advance",
                "payload": {},
                "as_seat": victim_actor["seat_id"],
            },
        )
        self.assertEqual(refused_action.status_code, 403, refused_action.text)
        self.assertIn("傀儡席", refused_action.text)
        # 控制者不能借 as_seat 操作自己不在控制中的第三席。
        uninvolved = next(
            actor
            for _, actor, _ in players
            if actor["seat_id"] not in {controller_actor["seat_id"], victim_actor["seat_id"]}
        )
        self.assertEqual(
            self.client.post(
                self.root + "/commands",
                headers=controller,
                json={
                    "expected_version": state_view["version"],
                    "action": "lobby.ready",
                    "payload": {},
                    "as_seat": uninvolved["seat_id"],
                },
            ).status_code,
            403,
        )
        # 傀儡席原玩家：只能只读旁观，既没有行动也不能发言。
        victim_view = self.client.get(self.root + "/state", headers=victim).json()
        self.assertTrue(victim_view["self"]["puppet_spectator"])
        self.assertEqual(victim_view["actions"], [])
        self.assertFalse(victim_view["can_chat"])
        refused = self.client.post(
            self.root + "/messages",
            headers=victim,
            json={"channel_id": "public", "text": "还在玩"},
        )
        self.assertEqual(refused.status_code, 403, refused.text)
        # 无关玩家不能借用 as_seat 代表傀儡席说话。
        stolen = self.client.post(
            self.root + "/messages",
            headers=next(
                player[0]
                for player in players
                if player[1]["seat_id"]
                not in {controller_actor["seat_id"], victim_actor["seat_id"]}
            ),
            json={"channel_id": "public", "text": "越权", "as_seat": victim_actor["seat_id"]},
        )
        self.assertEqual(stolen.status_code, 403, stolen.text)
        # 控制者不能借 as_seat 代表傀儡席公开发言：夜间规则禁止公开发言，
        # 但拒绝原因必须是阶段规则（说明授权已通过），而不是权限不足。
        night_public = self.client.post(
            self.root + "/messages",
            headers=controller,
            json={"channel_id": "public", "text": "代为发言", "as_seat": victim_actor["seat_id"]},
        )
        self.assertEqual(night_public.status_code, 403, night_public.text)
        self.assertIn("夜间", night_public.text)
        # 傀儡席自己的私信频道：控制者可以按该席身份读和发。
        created = self.command(
            self.host,
            "channel.create",
            {"name": "傀儡私信", "participant_ids": [victim_actor["id"]]},
        ).json()
        private = next(
            item
            for item in created["channels"]
            if {member["id"] for member in item["members"]} == {victim_actor["id"], "host"}
        )
        self.assertEqual(private["status"], "active")
        puppet_message = self.client.post(
            self.root + "/messages",
            headers=controller,
            json={
                "channel_id": private["id"],
                "text": "代为私信",
                "as_seat": victim_actor["seat_id"],
            },
        )
        puppet_message.raise_for_status()
        self.assertEqual(puppet_message.json()["sender_name"], victim_actor["name"])
        # 代读只放行该席参与的聊天频道，不泄露其面向个人的系统情报。
        allowed = self.client.get(
            self.root + f"/messages?as_seat={victim_actor['seat_id']}&scope=all", headers=controller
        )
        allowed.raise_for_status()
        self.assertTrue(all(message["kind"] == "chat" for message in allowed.json()["messages"]))
        self.assertIn(
            puppet_message.json()["id"], [message["id"] for message in allowed.json()["messages"]]
        )
        # 主持人自行代操作仍走主持人授权路径。
        self.command(self.host, "host.state", {"card_id": puppet_card, "state": "injured", "value": True, "reason": "测试"})
        # 傀儡当前牌出局且该席下层仍存活：控制解除，原玩家收到恢复通知并能自己行动。
        self.command(
            self.host,
            "host.damage",
            {
                "targets": [puppet_card],
                "effect": "death",
                "source": master_card,
                "reason": "测试傀儡出局",
            },
        )
        restored = self.client.get(self.root + "/state", headers=victim).json()
        self.assertFalse(restored["self"]["puppet_spectator"])
        self.assertTrue(restored["actions"])
        back = self.client.post(
            self.root + "/messages",
            headers=victim,
            json={"channel_id": private["id"], "text": "我回来了"},
        )
        back.raise_for_status()
        self.assertEqual(back.json()["sender_name"], victim_actor["name"])
        notices = self.client.get(
            self.root + "/messages?scope=all", headers=victim
        ).json()["messages"]
        self.assertTrue(
            any("重新回到游戏" in message["text"] for message in notices), notices
        )
        # 控制关系已解除：控制者不再拿到该席的傀儡面板。
        after_death = self.client.get(self.root + "/state", headers=controller).json()
        self.assertEqual(after_death["self"]["puppet_controls"], [])

    def test_reset_preserves_accounts_and_tokens(self):
        self.open_join()
        player, _, _ = self.join("13001")
        before = self.client.get("/api/me", headers=player).json()["actor"]
        reset = self.client.post("/api/reset", headers=self.host)
        reset.raise_for_status()
        after = self.client.get("/api/me", headers=player).json()["actor"]
        self.assertEqual(after["kind"], "account")
        self.assertEqual(after["account_id"], before["account_id"])

    def test_online_roster_covers_lobby_accounts_and_expires(self):
        realtime.presence.clear()
        roster = self.client.get("/api/online", headers=self.host).json()
        self.assertTrue(roster["host_online"])
        self.assertEqual(roster["accounts"], [])
        headers, actor = self.account("20001")
        self.client.get("/api/lobby", headers=headers).raise_for_status()
        self.assertIn(actor["account_id"], realtime.online_keys())
        roster = self.client.get("/api/online", headers=self.host).json()
        self.assertEqual(
            [item["name"] for item in roster["accounts"]], ["QQ20001"]
        )
        realtime.presence[actor["account_id"]] -= realtime.PRESENCE_SECONDS + 1
        roster = self.client.get("/api/online", headers=self.host).json()
        self.assertEqual(roster["accounts"], [])

    def test_invites_need_open_join_and_then_seat_the_player(self):
        self.open_join()
        first, first_actor, _ = self.join("21001")
        self.command(self.host, "room.open_join", {"open": False})
        guest, guest_actor = self.account("21002")
        self.client.get("/api/lobby", headers=guest).raise_for_status()
        invited = self.client.post(
            self.root + "/invites",
            headers=self.host,
            json={"account_id": guest_actor["account_id"]},
        )
        invited.raise_for_status()
        invite_id = invited.json()["id"]
        lobby = self.client.get("/api/lobby", headers=guest).json()
        self.assertEqual(len(lobby["invites"]), 1)
        self.assertEqual(lobby["invites"][0]["id"], invite_id)
        self.assertEqual(lobby["invites"][0]["from_name"], "主持人(主持10001)")
        self.assertFalse(lobby["invites"][0]["game"]["can_join_player"])
        blocked = self.client.post(
            f"/api/invites/{invite_id}/accept", headers=guest
        )
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertIn("尚未开放", blocked.text)
        self.open_join()
        accepted = self.client.post(
            f"/api/invites/{invite_id}/accept", headers=guest
        )
        accepted.raise_for_status()
        self.assertEqual(accepted.json()["actor"]["kind"], "player")
        self.assertIsNotNone(accepted.json()["actor"]["seat_id"])
        lobby = self.client.get("/api/lobby", headers=guest).json()
        self.assertEqual(lobby["invites"], [])
        with storage.connect() as db:
            row = db.execute(
                "SELECT status FROM invites WHERE id=?", (invite_id,)
            ).fetchone()
        self.assertEqual(row["status"], "accepted")
        self.assertNotEqual(first_actor["id"], accepted.json()["actor"]["id"])

    def test_invites_reject_offline_self_and_spectators(self):
        self.open_join()
        player, player_actor, _ = self.join("22001")
        spectator, _, _ = self.join("22002", "spectator")
        offline, offline_actor = self.account("22003")
        realtime.presence.clear()
        not_online = self.client.post(
            self.root + "/invites",
            headers=player,
            json={"account_id": offline_actor["account_id"]},
        )
        self.assertEqual(not_online.status_code, 409, not_online.text)
        self.assertIn("不在线", not_online.text)
        self.client.get("/api/lobby", headers=offline).raise_for_status()
        self_invite = self.client.post(
            self.root + "/invites",
            headers=player,
            json={"account_id": player_actor["account_id"]},
        )
        self.assertEqual(self_invite.status_code, 422, self_invite.text)
        self.assertIn("自己", self_invite.text)
        by_spectator = self.client.post(
            self.root + "/invites",
            headers=spectator,
            json={"account_id": offline_actor["account_id"]},
        )
        self.assertEqual(by_spectator.status_code, 403, by_spectator.text)
        invited = self.client.post(
            self.root + "/invites",
            headers=player,
            json={"account_id": offline_actor["account_id"]},
        )
        invited.raise_for_status()
        invite_id = invited.json()["id"]
        rejected = self.client.post(
            f"/api/invites/{invite_id}/reject", headers=offline
        )
        rejected.raise_for_status()
        with storage.connect() as db:
            row = db.execute(
                "SELECT status FROM invites WHERE id=?", (invite_id,)
            ).fetchone()
        self.assertEqual(row["status"], "rejected")
        state = self.client.get(self.root + "/state", headers=self.host).json()
        names = {
            seat["name"] for seat in state["seats"] if seat.get("occupant_id")
        }
        self.assertNotIn("QQ22003", names)



class Migration(unittest.TestCase):
    def test_initialization_preserves_existing_game_while_dropping_legacy_auth_tables(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(
            storage, "DATA_DIR", Path(directory)
        ):
            path = Path(directory) / "seven-double.sqlite3"
            game = create_game(DEFAULT_CODEX)
            db = sqlite3.connect(path)
            try:
                db.executescript(
                    """
                    CREATE TABLE games(id TEXT PRIMARY KEY,state TEXT,version INTEGER,status TEXT,created_at TEXT);
                    CREATE TABLE participants(id TEXT PRIMARY KEY,game_id TEXT,kind TEXT,seat_id TEXT,name TEXT,access_ids TEXT,active INTEGER DEFAULT 1,blocked INTEGER DEFAULT 0,muted INTEGER DEFAULT 0);
                    CREATE TABLE sessions(token_hash TEXT PRIMARY KEY,participant_id TEXT,kind TEXT,valid INTEGER,created_at TEXT);
                    CREATE TABLE invites(code_hash TEXT PRIMARY KEY,game_id TEXT,kind TEXT,valid INTEGER);
                    CREATE TABLE channels(id TEXT PRIMARY KEY,game_id TEXT,name TEXT,participant_ids TEXT);
                    CREATE TABLE messages(id INTEGER PRIMARY KEY AUTOINCREMENT,game_id TEXT,kind TEXT,sender_id TEXT,sender_name TEXT,avatar_role_id TEXT,channel_id TEXT,text TEXT,created_at TEXT,audience TEXT,image_id TEXT);
                    CREATE TABLE evidence(id TEXT PRIMARY KEY,game_id TEXT,owner_id TEXT,text TEXT,mime TEXT,image BLOB,created_at TEXT);
                    """
                )
                db.execute(
                    "INSERT INTO games VALUES(?,?,?,?,?)",
                    (game["id"], storage.dumps(game), game["version"], game["status"], storage.now_text()),
                )
                db.execute(
                    "INSERT INTO messages(game_id,kind,sender_id,sender_name,avatar_role_id,"
                    "channel_id,text,created_at,audience,image_id) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        game["id"],
                        "chat",
                        "legacy",
                        "旧玩家",
                        None,
                        "public",
                        "旧消息",
                        storage.now_text(),
                        None,
                        None,
                    ),
                )
                db.commit()
            finally:
                db.close()
            storage.initialize()
            storage.initialize()
            with storage.connect() as db:
                self.assertIsNotNone(storage.load_game(db, game["id"]))
                tables = {row["name"] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertNotIn("sessions", tables)
                # 旧的邀请码 invites 表必须被替换为新的定向邀请表（带 account_id）。
                self.assertIn(
                    "account_id",
                    {row["name"] for row in db.execute("PRAGMA table_info(invites)")},
                )
                self.assertIn("account_id", {row["name"] for row in db.execute("PRAGMA table_info(participants)")})
                columns = {row["name"] for row in db.execute("PRAGMA table_info(messages)")}
                self.assertNotIn("mimic_seat_id", columns)
                legacy = db.execute("SELECT * FROM messages WHERE sender_id='legacy'").fetchone()
                self.assertEqual(legacy["text"], "旧消息")


class NoOriginGate(unittest.TestCase):
    """不再按来源拦截：没有 Origin 的原生客户端与网关必须能到达路由。

    曾按 Origin/Host 拦截，结果是原生 App 的 WebSocket 被 4403、网关的
    /api/internal/qq/* 被 403。鉴权改由各路由的会话令牌或网关密钥负责。
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # storage.DATA_DIR 是模块级常量，env 补丁不影响已绑定的值；直接改常量。
        self.data = patch.object(storage, "DATA_DIR", Path(self.temp.name))
        self.data.start()
        self.addCleanup(self.data.stop)
        self.env = patch.dict(
            os.environ,
            {
                "GAME_DATA_DIR": self.temp.name,
                "GAME_GATEWAY_TOKEN": "test-gateway-secret",
                "GAME_QQ_GROUP_ID": "1105925736",
                "GAME_ADMIN_QQ": "10001",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        storage.initialize()
        auth_storage.initialize()
        self.client = TestClient(app)

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
                "group_id": 1105925736,
            },
        )
        bound.raise_for_status()
        completed = self.client.get(
            "/api/native/auth/host/challenges/" + challenge["id"]
        )
        completed.raise_for_status()
        self.assertEqual(completed.json().get("status"), "completed")
        return {
            "Authorization": "Bearer " + completed.json()["session_token"]
        }, completed.json()["session"]["actor"]

    def test_write_without_origin_or_token_reaches_route(self):
        # 主持人专属写接口在没有令牌时由路由自身鉴权返回 401，
        # 而不是被来源校验拦成 403。
        response = self.client.post("/api/reset")
        self.assertEqual(
            response.status_code,
            401,
            "无 Origin 的写请求应到达路由并由该路由鉴权，而不是被来源校验拦成 403",
        )

    def test_gateway_write_is_accepted(self):
        response = self.client.post(
            "/api/internal/qq/members/sync",
            headers={"X-Gateway-Token": "test-gateway-secret"},
            json={
                "group_id": 1105925736,
                "members": [{"qq_id": "10001", "nickname": "测试甲"}],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)

    def test_gateway_write_without_token_is_rejected(self):
        response = self.client.post(
            "/api/internal/qq/members/sync",
            json={"group_id": 1105925736, "members": []},
        )
        self.assertEqual(response.status_code, 401)

    def test_gateway_accepts_every_configured_group(self):
        """GAME_QQ_GROUP_ID 是逗号分隔的群号列表，不能只放行第一个群。"""
        with patch.dict(os.environ, {"GAME_QQ_GROUP_ID": "1105925736, 775621176"}):
            for group_id in (1105925736, 775621176):
                response = self.client.post(
                    "/api/internal/qq/members/sync",
                    headers={"X-Gateway-Token": "test-gateway-secret"},
                    json={"group_id": group_id, "members": []},
                )
                self.assertEqual(response.status_code, 200, response.text)
            unlisted = self.client.post(
                "/api/internal/qq/members/sync",
                headers={"X-Gateway-Token": "test-gateway-secret"},
                json={"group_id": 867118030, "members": []},
            )
        self.assertEqual(unlisted.status_code, 403, unlisted.text)

    def test_websocket_without_token_is_closed_with_4401(self):
        with self.assertRaises(WebSocketDisconnect) as caught:
            with self.client.websocket_connect("/api/live") as socket:
                socket.receive_json()
        self.assertEqual(caught.exception.code, 4401)

    def test_websocket_accepts_before_any_close(self):
        """握手必须先 accept。

        在 accept 之前调用 close 会拒绝整个握手，uvicorn 直接回 HTTP 403，
        客户端只看得到「连不上」，既没有 4401 也没有原因。TestClient 的
        WebSocket 传输不经过 uvicorn 的握手实现，复现不出那个 403，
        所以这里直接钉住 live() 里 accept/close 的执行顺序。
        """
        source = textwrap.dedent(inspect.getsource(realtime.live))
        tree = ast.parse(source)
        calls = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr in ("accept", "close") and isinstance(
                    node.func.value, ast.Name
                ):
                    calls.append((node.lineno, node.func.attr))
        self.assertTrue(calls, "live() 里没有对 socket 调用 accept")
        calls.sort()
        self.assertEqual(
            calls[0][1],
            "accept",
            f"live() 第一次对 socket 的操作必须是 accept，实际是 {calls[0][1]}",
        )

    def test_websocket_with_valid_token_connects(self):
        host, _ = self.host_login("10001")
        token = host["Authorization"].removeprefix("Bearer ")
        catalog = self.client.get(
            "/api/catalog", headers={"Authorization": "Bearer " + token}
        ).json()
        created = self.client.post(
            "/api/games",
            headers={"Authorization": "Bearer " + token},
            json={"codex": catalog["default_codex"]},
        )
        self.assertEqual(created.status_code, 200)
        with self.client.websocket_connect(
            "/api/live", headers={"Authorization": "Bearer " + token}
        ) as socket:
            message = socket.receive_json()
        self.assertEqual(
            message["type"], "sync", "有效会话必须能建立实时连接并收到首帧状态"
        )


if __name__ == "__main__":
    unittest.main()
