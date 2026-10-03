"""Stable auth, open participation, spectator, and private-channel boundaries."""

import asyncio
import ast
import inspect
import os
import sqlite3
import tempfile
import textwrap
import time
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
        completed = self.client.get("/api/native/auth/host/challenges/" + challenge["id"])
        completed.raise_for_status()
        self.assertEqual(completed.json().get("status"), "completed")
        return {"Authorization": "Bearer " + completed.json()["session_token"]}, completed.json()[
            "session"
        ]["actor"]

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
        completed = self.client.get("/api/native/auth/challenges/" + challenge["id"])
        completed.raise_for_status()
        # 原生客户端同样按 status 判断登录完成，缺了它会继续轮询已消费的挑战。
        self.assertEqual(completed.json().get("status"), "completed")
        return {"Authorization": "Bearer " + completed.json()["session_token"]}, completed.json()[
            "session"
        ]["actor"]

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

    def edit_state(self, mutate):
        """测试用的状态手术：直接改写本局持久状态，省去逐阶段推进。"""
        with storage.transaction() as db:
            game = storage.load_game(db, self.game_id)
            mutate(game)
            game["version"] += 1
            storage.save_game(db, game)

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
            self.assertTrue(
                any(row["token_hash"] == auth_storage.secret_hash(raw_cookie) for row in rows)
            )

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

    def test_spectator_leaves_by_itself(self):
        self.open_join()
        spectator, spectator_actor, _ = self.join("11102", "spectator")

        left = self.client.post(self.root + "/leave", headers=spectator)
        self.assertEqual(left.status_code, 200, left.text)
        # 离开即不再是本局参与身份，但重新观战仍然可以（参与身份只是置为不活跃）。
        self.assertEqual(self.client.get(self.root + "/state", headers=spectator).status_code, 401)
        notice = self.client.get(self.root + "/messages", headers=self.host).json()["messages"]
        self.assertTrue(any("已离开对局" in message["text"] for message in notice))
        rejoined = self.client.post(
            self.root + "/participations", headers=spectator, json={"kind": "spectator"}
        )
        self.assertEqual(rejoined.status_code, 200, rejoined.text)
        self.assertEqual(rejoined.json()["actor"]["id"], spectator_actor["id"])
        self.assertIsNone(rejoined.json()["actor"]["seat_id"])

    def test_player_leaves_lobby_without_revoking_login(self):
        self.open_join()
        player, actor, _ = self.join("11103")
        self.command(player, "lobby.ready")
        state = self.client.get(self.root + "/state", headers=player).json()
        missing = self.client.post(self.root + "/leave", headers=player)
        self.assertEqual(missing.status_code, 422, missing.text)
        stale = self.client.post(
            self.root + "/leave",
            headers=player,
            json={"expected_version": state["version"] - 1},
        )
        self.assertEqual(stale.status_code, 409, stale.text)
        self.assertEqual(self.client.get(self.root + "/state", headers=player).status_code, 200)
        left = self.client.post(
            self.root + "/leave",
            headers=player,
            json={"expected_version": state["version"]},
        )
        self.assertEqual(left.status_code, 200, left.text)
        self.assertEqual(self.client.get(self.root + "/state", headers=player).status_code, 401)
        self.assertEqual(self.client.get("/api/me", headers=player).status_code, 200)
        with storage.connect() as db:
            game = storage.load_game(db, self.game_id)
            seat = next(seat for seat in game["seats"] if seat["id"] == actor["seat_id"])
            self.assertIsNone(seat["occupant_id"])
            self.assertFalse(seat["ready"])
            self.assertEqual(game["version"], state["version"] + 1)
            participant = db.execute(
                "SELECT * FROM participants WHERE id=?", (actor["id"],)
            ).fetchone()
            self.assertFalse(participant["active"])
            self.assertFalse(participant["blocked"])
        rejoined = self.client.post(
            self.root + "/participations", headers=player, json={"kind": "player"}
        )
        self.assertEqual(rejoined.status_code, 200, rejoined.text)
        self.assertEqual(rejoined.json()["actor"]["seat_id"], actor["seat_id"])
        refused = self.client.post(self.root + "/leave", headers=self.host)
        self.assertEqual(refused.status_code, 403, refused.text)

    def test_player_leaving_preserves_dealt_seat_for_substitute(self):
        self.open_join()
        players = [self.join(str(11201 + index)) for index in range(7)]
        spectator, substitute, _ = self.join("11299", "spectator")
        for headers, _, _ in players:
            self.command(headers, "lobby.ready")
        player, actor, _ = players[0]
        self.edit_state(lambda game: game.update(status="playing"))
        with storage.connect() as db:
            before = storage.load_game(db, self.game_id)
        left = self.client.post(
            self.root + "/leave",
            headers=player,
            json={"expected_version": before["version"]},
        )
        self.assertEqual(left.status_code, 200, left.text)
        with storage.connect() as db:
            after = storage.load_game(db, self.game_id)
        expected = next(seat for seat in before["seats"] if seat["id"] == actor["seat_id"])
        expected["occupant_id"] = None
        before["version"] += 1
        self.assertEqual(after, before, "主动离开不得重置角色、技能或已提交行动")
        refused = self.client.post(
            self.root + "/participations", headers=player, json={"kind": "player"}
        )
        self.assertEqual(refused.status_code, 409, refused.text)
        self.command(
            self.host,
            "room.replace",
            {
                "seat_id": actor["seat_id"],
                "participant_id": substitute["id"],
                "keep_actions": True,
            },
        )
        with storage.connect() as db:
            replaced = storage.load_game(db, self.game_id)
        expected["occupant_id"], expected["name"] = substitute["id"], substitute["name"]
        seat = next(seat for seat in replaced["seats"] if seat["id"] == actor["seat_id"])
        self.assertEqual(seat, expected)
        self.assertEqual(replaced["cards"], after["cards"])
        self.assertEqual(self.client.get(self.root + "/state", headers=spectator).status_code, 200)

    def test_host_delegation_notice_is_private_to_the_seat(self):
        self.open_join()
        player, actor, _ = self.join("12901")
        stranger, _, _ = self.join("12902")
        spectator, _, _ = self.join("12903", "spectator")
        _, account = self.account("12999")
        self.client.post(
            f"/api/hosts/{account['account_id']}", headers=self.host, json={"level": 5}
        ).raise_for_status()
        unconfirmed_host, _ = self.host_login("12999")
        history = self.client.get(self.root + "/messages", headers=self.host).json()["messages"]
        after = history[-1]["id"]
        state = self.client.get(self.root + "/state", headers=self.host).json()
        delegated = self.client.post(
            self.root + "/commands",
            headers=self.host,
            json={
                "expected_version": state["version"],
                "action": "lobby.ready",
                "payload": {},
                "as_seat": actor["seat_id"],
            },
        )
        self.assertEqual(delegated.status_code, 200, delegated.text)
        seat = next(item for item in delegated.json()["seats"] if item["id"] == actor["seat_id"])
        self.assertTrue(seat["ready"])
        notices = self.client.get(
            self.root + "/messages", headers=self.host, params={"after": after}
        ).json()["messages"]
        notice = notices[0]
        self.assertEqual(notice["kind"], "information")
        self.assertEqual(notice["channel_id"], "information")
        self.assertEqual(notice["audience"], [actor["id"]])
        for headers, messages_allowed, information_allowed in (
            (self.host, True, True),
            (player, True, True),
            (stranger, False, False),
            (spectator, True, False),
            (unconfirmed_host, False, False),
        ):
            with self.subTest(headers=headers):
                messages = self.client.get(
                    self.root + "/messages", headers=headers, params={"after": after}
                ).json()["messages"]
                self.assertEqual(
                    any(item["id"] == notice["id"] for item in messages), messages_allowed
                )
                information = self.client.get(self.root + "/state", headers=headers).json()[
                    "information"
                ]
                self.assertEqual(
                    any(item["text"] == notice["text"] for item in information), information_allowed
                )

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
        stranger, _, _ = self.join("12003")
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
        active = self.command(second, "channel.accept", {"channel_id": channel["id"]}).json()
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
        hidden = self.client.get(self.root + "/messages?scope=private", headers=stranger).json()[
            "messages"
        ]
        self.assertNotIn(private.json()["id"], [message["id"] for message in hidden])
        host_busy = self.command(
            self.host,
            "channel.create",
            {"name": "强制", "participant_ids": [first_actor["id"]]},
            status=409,
        )
        self.assertIn("其他私信", host_busy.text)
        ended = self.command(second, "channel.end", {"channel_id": channel["id"]}).json()
        channel = next(item for item in ended["channels"] if item["id"] == channel["id"])
        self.assertEqual(channel["status"], "ended")
        restored = self.client.post(
            self.root + "/messages",
            headers=first,
            json={"channel_id": "public", "text": "restored"},
        )
        restored.raise_for_status()
        host_scope = self.client.get(self.root + "/messages?scope=host", headers=self.host).json()[
            "messages"
        ]
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
        prompt = self.client.get(self.root + "/state", headers=headers[0]).json()["action_prompt"]
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
        self.assertEqual(
            [message["id"] for message in system], [message["id"] for message in baseline]
        )

    def test_spectators_read_every_channel_without_write_access(self):
        self.open_join()
        first, first_actor, _ = self.join("12601")
        second, second_actor, _ = self.join("12602")
        outsider, outsider_actor, _ = self.join("12603")
        spectator, spectator_actor, _ = self.join("12604", "spectator")

        def send(headers, channel_id, text):
            response = self.client.post(
                self.root + "/messages",
                headers=headers,
                json={"channel_id": channel_id, "text": text},
            )
            response.raise_for_status()
            return response.json()

        def history(headers, **params):
            response = self.client.get(self.root + "/messages", headers=headers, params=params)
            response.raise_for_status()
            return response.json()["messages"]

        public = send(first, "public", "公共发言")
        created = self.command(
            first, "channel.create", {"participant_ids": [second_actor["id"]]}
        ).json()
        private = next(channel for channel in created["channels"] if channel["status"] == "pending")
        self.command(second, "channel.accept", {"channel_id": private["id"]})
        private_message = send(first, private["id"], "玩家之间的私信")
        self.command(first, "channel.end", {"channel_id": private["id"]})
        created = self.command(
            self.host, "channel.create", {"participant_ids": [second_actor["id"]]}
        ).json()
        host_channel = next(
            channel
            for channel in created["channels"]
            if {member["id"] for member in channel["members"]} == {"host", second_actor["id"]}
        )
        host_message = send(self.host, host_channel["id"], "主持人私信")
        created = self.command(
            first, "channel.create", {"participant_ids": [outsider_actor["id"]]}
        ).json()
        pending = next(channel for channel in created["channels"] if channel["status"] == "pending")
        spectator_message = send(self.host, "spectator", "观战频道消息")
        with storage.transaction() as db:
            personal = storage.add_message(
                db,
                self.game_id,
                kind="information",
                channel_id="information",
                text="只发给一号玩家的系统情报",
                audience=[first_actor["id"]],
            )
            host_only = storage.add_message(
                db, self.game_id, text="仅主持人的系统裁定", audience=[]
            )
            legacy = storage.add_message(
                db,
                self.game_id,
                kind="chat",
                sender_id=spectator_actor["id"],
                sender_name=spectator_actor["name"],
                channel_id="spectator",
                text="旧版观战发言也不能撤回",
            )

        host_view = self.client.get(self.root + "/state", headers=self.host).json()
        watched = self.client.get(self.root + "/state", headers=spectator).json()
        self.assertEqual(
            [channel["id"] for channel in watched["channels"]],
            [channel["id"] for channel in host_view["channels"]],
        )
        statuses = {channel["id"]: channel["status"] for channel in watched["channels"]}
        self.assertEqual(statuses[private["id"]], "ended")
        self.assertEqual(statuses[host_channel["id"]], "active")
        self.assertEqual(statuses[pending["id"]], "pending")
        self.assertTrue(all(not channel["can_send"] for channel in watched["channels"]))
        self.assertTrue(all(channel["actions"] == [] for channel in watched["channels"]))
        self.assertEqual(watched["actions"], [])
        self.assertFalse(watched["can_chat"])
        self.assertNotIn("host", watched)

        all_messages = history(self.host)
        all_ids = [message["id"] for message in all_messages]
        self.assertEqual([message["id"] for message in history(spectator)], all_ids)
        for message in (
            public,
            private_message,
            host_message,
            spectator_message,
            personal,
            host_only,
        ):
            self.assertIn(message["id"], all_ids)
        watched_personal = next(
            message for message in history(spectator) if message["id"] == personal["id"]
        )
        self.assertEqual(watched_personal["audience"], [first_actor["id"]])

        scopes = {
            "all": all_ids,
            "public": [public["id"]],
            "private": [private_message["id"], host_message["id"]],
            "host": [host_message["id"]],
            "system": [message["id"] for message in all_messages if message["kind"] != "chat"],
        }
        channel_ids = {
            "public": [
                message["id"] for message in all_messages if message["channel_id"] == "public"
            ],
            private["id"]: [private_message["id"]],
            host_channel["id"]: [host_message["id"]],
            pending["id"]: [],
            "spectator": [spectator_message["id"], legacy["id"]],
            "system": [personal["id"]],
            "information": [personal["id"]],
        }
        queries = [{"scope": scope} for scope in scopes]
        queries.extend({"channel_id": channel["id"]} for channel in watched["channels"])
        queries.append({"channel_id": "information"})
        for params in queries:
            with self.subTest(params=params):
                expected = history(self.host, **params)
                expected_ids = [message["id"] for message in expected]
                if "scope" in params:
                    self.assertEqual(expected_ids, scopes[params["scope"]])
                else:
                    self.assertEqual(expected_ids, channel_ids[params["channel_id"]])
                self.assertEqual(
                    [message["id"] for message in history(spectator, **params)], expected_ids
                )
                for cursor in ("before", "after"):
                    boundary = host_message["id"]
                    filtered = [
                        message_id
                        for message_id in expected_ids
                        if (message_id < boundary if cursor == "before" else message_id > boundary)
                    ]
                    page = history(spectator, **params, **{cursor: boundary})
                    self.assertEqual([message["id"] for message in page], filtered)

        private_ids = {
            private_message["id"],
            host_message["id"],
            spectator_message["id"],
            personal["id"],
            host_only["id"],
            legacy["id"],
        }
        self.assertTrue(private_ids.isdisjoint(message["id"] for message in history(outsider)))
        self.assertIn(
            public["id"], [message["id"] for message in history(outsider, scope="public")]
        )
        for channel_id in (private["id"], host_channel["id"], "spectator", "system"):
            messages = history(outsider, channel_id=channel_id)
            self.assertTrue(private_ids.isdisjoint(message["id"] for message in messages))
        self.command(
            first, "channel.create", {"participant_ids": [spectator_actor["id"]]}, status=422
        )

        image = (
            "data:image/png;base64,"
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
        for channel in watched["channels"]:
            for content in ({"text": "不能发言"}, {"image": image}):
                with self.subTest(channel_id=channel["id"], content=content):
                    denied = self.client.post(
                        self.root + "/messages",
                        headers=spectator,
                        json={"channel_id": channel["id"], **content},
                    )
                    self.assertEqual(denied.status_code, 403, denied.text)
        for action, payload in (
            ("channel.create", {"participant_ids": ["host"]}),
            ("channel.accept", {"channel_id": pending["id"]}),
            ("channel.reject", {"channel_id": pending["id"]}),
            ("channel.end", {"channel_id": host_channel["id"]}),
        ):
            self.command(spectator, action, payload, status=403)
        for message in (public, legacy):
            denied = self.client.post(
                self.root + f"/messages/{message['id']}/retract", headers=spectator, json={}
            )
            self.assertEqual(denied.status_code, 403, denied.text)
        unchanged = self.client.get(self.root + "/state", headers=spectator).json()
        self.assertEqual(unchanged["version"], watched["version"])
        self.assertEqual(unchanged["channels"], watched["channels"])
        self.assertEqual(history(spectator), history(self.host))
        self.assertEqual([message["id"] for message in history(spectator)], all_ids)
        self.assertFalse(any(message["recalled"] for message in history(spectator)))

        # pong 是同一接收循环的同步点，确保拒绝的输入帧处理完再发消息标记。
        with (
            self.client.websocket_connect("/api/live", headers=self.host) as host_socket,
            self.client.websocket_connect("/api/live", headers=spectator) as watcher,
        ):
            self.assertEqual(host_socket.receive_json()["type"], "sync")
            self.assertEqual(watcher.receive_json()["type"], "sync")
            peer = next(
                peer
                for peer in realtime.connections
                if peer.participant_id == spectator_actor["id"]
            )
            last_pong = peer.last_pong
            for channel in watched["channels"]:
                for active in (True, False):
                    watcher.send_json(
                        {"type": "typing", "channel_id": channel["id"], "active": active}
                    )
            watcher.send_json({"type": "pong"})
            for _ in range(100):
                if peer.last_pong != last_pong:
                    break
                time.sleep(0.01)
            else:
                self.fail("观战 WebSocket 未处理完输入状态请求")
            marker = send(self.host, "public", "输入状态校验同步点")
            for _ in range(60):
                frame = host_socket.receive_json()
                if frame["type"] == "typing":
                    self.assertNotEqual(frame["participant_id"], spectator_actor["id"])
                if frame["type"] == "message" and frame["message"]["id"] == marker["id"]:
                    break
            else:
                self.fail("主持人未收到消息同步点")
            host_socket.close()
            watcher.close()

            async def disconnected():
                async with asyncio.timeout(2):
                    while any(peer.game_id == self.game_id for peer in realtime.connections):
                        await asyncio.sleep(0)

            watcher.portal.call(disconnected)

        spectator_channel = next(
            channel for channel in host_view["channels"] if channel["id"] == "spectator"
        )
        self.assertTrue(spectator_channel["can_send"])

    def test_night_closes_private_channels_and_allows_only_host_chats(self):
        self.open_join()
        players = [self.join(str(13001 + index)) for index in range(7)]
        first, first_actor, _ = players[0]
        second, second_actor, _ = players[1]
        _, third_actor, _ = players[2]
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

    def test_eliminated_player_loses_surrender_and_player_private_chats(self):
        """整席出局：不再有「请求交牌」，也只能与主持人私信；复活后自动恢复。

        出局要按当前牌现场判断：希罗回溯、梅露露复活与主持人回溯都会让角色牌
        重新登场，不能靠一次性的记账把玩家永久锁死。
        """
        self.open_join()
        players = [self.join(str(15101 + index)) for index in range(7)]
        first, first_actor, _ = players[0]
        second, second_actor, _ = players[1]
        for headers, _, _ in players:
            self.command(headers, "lobby.ready")
        for headers, _, _ in players:
            self.command(headers, "lobby.ready")
        self.command(self.host, "host.start")
        # 拨到白天：夜间本来就已经只允许与主持人私信，验不出出局这条新限制。
        self.edit_state(lambda game: game.update(half="day", phase="discussion"))

        def actions_of(headers):
            return [
                item["id"]
                for item in self.client.get(self.root + "/state", headers=headers).json()["actions"]
            ]

        def set_seat_alive(alive):
            def mutate(game):
                seat = next(s for s in game["seats"] if s["id"] == first_actor["seat_id"])
                for card_id in seat["cards"]:
                    game["cards"][card_id]["alive"] = alive

            self.edit_state(mutate)

        # 出局前：既能请求交牌，也能与其他玩家建立私信。
        self.assertIn("player.surrender", actions_of(first))
        created = self.command(
            first, "channel.create", {"participant_ids": [second_actor["id"]]}
        ).json()
        paired = next(item for item in created["channels"] if item["status"] == "pending")
        self.command(second, "channel.accept", {"channel_id": paired["id"]})

        set_seat_alive(False)
        # 出局后旧频道立即失效（本人都发不出去），但可以自己结束它腾出私信位。
        frozen = self.client.post(
            self.root + "/messages",
            headers=first,
            json={"channel_id": paired["id"], "text": "还在"},
        )
        self.assertEqual(frozen.status_code, 403, frozen.text)
        self.assertIn("出局", frozen.text)
        self.command(first, "channel.end", {"channel_id": paired["id"]})

        view = self.client.get(self.root + "/state", headers=first).json()
        self.assertNotIn("player.surrender", [item["id"] for item in view["actions"]])
        create = next(item for item in view["actions"] if item["id"] == "channel.create")
        self.assertEqual(
            [option["label"] for option in create["fields"][0]["options"]], [view["host_name"]]
        )
        self.assertIn("出局", create["description"])
        # 出局者不能邀请别人，别人也不能再把出局者拉进私信。
        self.command(first, "channel.create", {"participant_ids": [second_actor["id"]]}, status=403)
        self.command(second, "channel.create", {"participant_ids": [first_actor["id"]]}, status=403)
        offered = next(
            item
            for item in self.client.get(self.root + "/state", headers=second).json()["actions"]
            if item["id"] == "channel.create"
        )
        self.assertNotIn(
            first_actor["name"], [option["label"] for option in offered["fields"][0]["options"]]
        )
        # 与主持人私信照常可用。
        host_chat = self.command(first, "channel.create", {"participant_ids": ["host"]}).json()
        with_host = next(
            item
            for item in host_chat["channels"]
            if {member["id"] for member in item["members"]} == {first_actor["id"], "host"}
        )
        self.assertEqual(with_host["status"], "active")
        self.client.post(
            self.root + "/messages",
            headers=first,
            json={"channel_id": with_host["id"], "text": "我要交牌"},
        ).raise_for_status()
        self.command(first, "channel.end", {"channel_id": with_host["id"]})

        # 复活（回溯同样走这一步）让当前牌重新登场：交牌按钮与多人私信一起恢复。
        set_seat_alive(True)
        restored = self.client.get(self.root + "/state", headers=first).json()
        self.assertIn("player.surrender", [item["id"] for item in restored["actions"]])
        reborn = next(item for item in restored["actions"] if item["id"] == "channel.create")
        self.assertIn(
            second_actor["name"], [option["label"] for option in reborn["fields"][0]["options"]]
        )
        self.command(first, "channel.create", {"participant_ids": [second_actor["id"]]})

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
            # 被控席位的当前牌不能是希罗：击杀希罗会立即触发自动回溯，
            # 时间线整体恢复，那不是这条用例要验的傀儡死亡流程（取牌随机，会偶发）。
            player
            for player in players
            if player[1]["seat_id"] != controller_actor["seat_id"]
            and seats[player[1]["seat_id"]]["current_card_id"] != "hiro"
        )
        stranger, stranger_actor, _ = next(
            player
            for player in players
            if player[1]["seat_id"] not in {controller_actor["seat_id"], victim_actor["seat_id"]}
        )
        master_card = seats[controller_actor["seat_id"]]["current_card_id"]
        puppet_card = seats[victim_actor["seat_id"]]["current_card_id"]
        self.command(
            self.host,
            "host.state",
            {"card_id": master_card, "state": "witch", "value": True, "reason": "测试"},
        )
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
        # 傀儡席原玩家：只能只读旁观，既没有行动也不能发言、不能接私信。
        victim_view = self.client.get(self.root + "/state", headers=victim).json()
        self.assertTrue(victim_view["self"]["puppet_spectator"])
        self.assertEqual(victim_view["actions"], [])
        self.assertEqual(victim_view["dialogs"], [])
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
            {"name": "傀儡私信", "participant_ids": [victim_actor["id"], stranger_actor["id"]]},
        ).json()
        private = next(
            item
            for item in created["channels"]
            if {member["id"] for member in item["members"]}
            == {victim_actor["id"], stranger_actor["id"], "host"}
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
        # 傀儡席原玩家连这条私信也不能回话：代操作期间它只读，投影里所有频道一并禁言。
        blocked_private = self.client.post(
            self.root + "/messages",
            headers=victim,
            json={"channel_id": private["id"], "text": "我自己说"},
        )
        self.assertEqual(blocked_private.status_code, 403, blocked_private.text)
        self.assertIn("傀儡", blocked_private.text)
        muted_view = self.client.get(self.root + "/state", headers=victim).json()
        self.assertTrue(all(not channel["can_send"] for channel in muted_view["channels"]))
        self.assertTrue(all(channel["actions"] == [] for channel in muted_view["channels"]))
        # 频道里的回话要实时推给控制者：它不在成员名单里，只能靠受控傀儡席的身份代读。
        with self.client.websocket_connect("/api/live", headers=controller) as socket:
            self.assertEqual(socket.receive_json()["type"], "sync")
            reply = self.client.post(
                self.root + "/messages",
                headers=stranger,
                json={"channel_id": private["id"], "text": "回话"},
            )
            reply.raise_for_status()
            delivered = False
            for _ in range(20):
                frame = socket.receive_json()
                if frame["type"] != "message":
                    continue
                if frame["message"]["id"] == reply.json()["id"]:
                    delivered = True
                    break
            self.assertTrue(delivered, "傀儡席私信里的回话必须实时推给控制者")
        # 主持人自行代操作仍走主持人授权路径。
        self.command(
            self.host,
            "host.state",
            {"card_id": puppet_card, "state": "injured", "value": True, "reason": "测试"},
        )
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
        notices = self.client.get(self.root + "/messages?scope=all", headers=victim).json()[
            "messages"
        ]
        self.assertTrue(any("重新回到游戏" in message["text"] for message in notices), notices)
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
        self.assertEqual([item["name"] for item in roster["accounts"]], ["QQ20001"])
        realtime.presence[actor["account_id"]] -= realtime.PRESENCE_SECONDS + 1
        roster = self.client.get("/api/online", headers=self.host).json()
        self.assertEqual(roster["accounts"], [])

    def test_invites_need_open_join_and_then_seat_the_player(self):
        self.open_join()
        _, first_actor, _ = self.join("21001")
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
        blocked = self.client.post(f"/api/invites/{invite_id}/accept", headers=guest)
        self.assertEqual(blocked.status_code, 409, blocked.text)
        self.assertIn("尚未开放", blocked.text)
        self.open_join()
        accepted = self.client.post(f"/api/invites/{invite_id}/accept", headers=guest)
        accepted.raise_for_status()
        self.assertEqual(accepted.json()["actor"]["kind"], "player")
        self.assertIsNotNone(accepted.json()["actor"]["seat_id"])
        lobby = self.client.get("/api/lobby", headers=guest).json()
        self.assertEqual(lobby["invites"], [])
        with storage.connect() as db:
            row = db.execute("SELECT status FROM invites WHERE id=?", (invite_id,)).fetchone()
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
        rejected = self.client.post(f"/api/invites/{invite_id}/reject", headers=offline)
        rejected.raise_for_status()
        with storage.connect() as db:
            row = db.execute("SELECT status FROM invites WHERE id=?", (invite_id,)).fetchone()
        self.assertEqual(row["status"], "rejected")
        state = self.client.get(self.root + "/state", headers=self.host).json()
        names = {seat["name"] for seat in state["seats"] if seat.get("occupant_id")}
        self.assertNotIn("QQ22003", names)


class Migration(unittest.TestCase):
    def test_initialization_preserves_existing_game_while_dropping_legacy_auth_tables(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(storage, "DATA_DIR", Path(directory)),
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
                    (
                        game["id"],
                        storage.dumps(game),
                        game["version"],
                        game["status"],
                        storage.now_text(),
                    ),
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
                tables = {
                    row["name"]
                    for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
                }
                self.assertNotIn("sessions", tables)
                # 旧的邀请码 invites 表必须被替换为新的定向邀请表（带 account_id）。
                self.assertIn(
                    "account_id",
                    {row["name"] for row in db.execute("PRAGMA table_info(invites)")},
                )
                self.assertIn(
                    "account_id",
                    {row["name"] for row in db.execute("PRAGMA table_info(participants)")},
                )
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
        completed = self.client.get("/api/native/auth/host/challenges/" + challenge["id"])
        completed.raise_for_status()
        self.assertEqual(completed.json().get("status"), "completed")
        return {"Authorization": "Bearer " + completed.json()["session_token"]}, completed.json()[
            "session"
        ]["actor"]

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
                if node.func.attr in ("accept", "close") and isinstance(node.func.value, ast.Name):
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
        self.assertEqual(message["type"], "sync", "有效会话必须能建立实时连接并收到首帧状态")


if __name__ == "__main__":
    unittest.main()
