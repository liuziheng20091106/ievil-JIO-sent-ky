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
        native_host = self.client.post("/api/native/host/login", json={"password": "114514"})
        native_host.raise_for_status()
        self.host = {"Authorization": "Bearer " + native_host.json()["session_token"]}
        created = self.client.post("/api/games", headers=self.host, json={"codex": DEFAULT_CODEX})
        created.raise_for_status()
        self.game_id = created.json()["id"]
        self.root = f"/api/games/{self.game_id}"

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
        self.assertTrue(all(len(seat["cards"]) == 2 for seat in watched["seats"]))
        self.assertTrue(all("current_card_id" in seat for seat in watched["seats"]))
        self.assertNotIn("host", watched)
        denied = self.command(eighth, "lobby.ready", status=403)
        self.assertIn("观战者", denied.text)
        evidence = self.client.post(self.root + "/evidence", headers=eighth, json={"text": "x"})
        self.assertEqual(evidence.status_code, 403, evidence.text)

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
        channel = next(item for item in created["channels"] if item["label"].endswith("作战"))
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
        system = self.client.get(self.root + "/messages?scope=system", headers=stranger).json()
        self.assertTrue(any("正在与" in message["text"] for message in system["messages"]))
        self.assertTrue(any("已结束私信" in message["text"] for message in system["messages"]))

    def test_reset_preserves_accounts_and_tokens(self):
        self.open_join()
        player, _, _ = self.join("13001")
        before = self.client.get("/api/me", headers=player).json()["actor"]
        reset = self.client.post("/api/reset", headers=self.host)
        reset.raise_for_status()
        after = self.client.get("/api/me", headers=player).json()["actor"]
        self.assertEqual(after["kind"], "account")
        self.assertEqual(after["account_id"], before["account_id"])


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
                db.commit()
            finally:
                db.close()
            storage.initialize()
            storage.initialize()
            with storage.connect() as db:
                self.assertIsNotNone(storage.load_game(db, game["id"]))
                tables = {row["name"] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertNotIn("sessions", tables)
                self.assertNotIn("invites", tables)
                self.assertIn("account_id", {row["name"] for row in db.execute("PRAGMA table_info(participants)")})


class NoOriginGate(unittest.TestCase):
    """不再按来源拦截：没有 Origin 的原生客户端与网关必须能到达路由。

    曾按 Origin/Host 拦截，结果是原生 App 的 WebSocket 被 4403、网关的
    /api/internal/qq/* 被 403。鉴权改由各路由的会话令牌或网关密钥负责。
    """

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(
            os.environ,
            {
                "GAME_DATA_DIR": self.temp.name,
                "GAME_GATEWAY_TOKEN": "test-gateway-secret",
                "GAME_QQ_GROUP_ID": "1105925736",
            },
        )
        self.env.start()
        self.addCleanup(self.env.stop)
        storage.initialize()
        auth_storage.initialize()
        self.client = TestClient(app)

    def test_write_without_origin_or_token_reaches_route(self):
        response = self.client.post("/api/host/login", json={"password": "wrong"})
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
        login = self.client.post("/api/native/host/login", json={"password": "114514"})
        token = login.json()["session_token"]
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
