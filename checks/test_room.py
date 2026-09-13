"""Room access, preparation, and legacy migration must preserve private seat state."""

import asyncio
import tempfile
import time
import unittest
from contextlib import suppress
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import auth, realtime, storage
from backend.app.game import DEFAULT_CODEX, create_game
from backend.app.game.state import deal_cards
from backend.app.main import app


class RoomAccess(unittest.TestCase):
    def test_shared_entry_and_spectator_replacement_preserve_dealt_state(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(storage, "DATA_DIR", Path(directory)),
            TestClient(app) as client,
        ):
            client.post("/api/host/login", json={"password": "114514"}).raise_for_status()
            host = {"Cookie": f"{auth.COOKIE}={client.cookies[auth.COOKIE]}"}
            game = client.post("/api/games", json={"codex": DEFAULT_CODEX}).json()
            root = f"/api/games/{game['id']}"
            client.cookies.clear()

            def state(headers=host):
                result = client.get(root + "/state", headers=headers)
                result.raise_for_status()
                return result.json()

            def command(action, payload=None, headers=host, status=200, version=None):
                result = client.post(
                    root + "/commands",
                    headers=headers,
                    json={
                        "expected_version": state()["version"] if version is None else version,
                        "action": action,
                        "payload": payload or {},
                    },
                )
                self.assertEqual(result.status_code, status, result.text)
                return result.json()

            def invite(kind):
                result = client.post(root + "/invites", headers=host, json={"kind": kind})
                result.raise_for_status()
                return result.json()["code"]

            def join(code, name):
                client.cookies.clear()
                result = client.post("/api/join", json={"code": code, "name": name})
                result.raise_for_status()
                headers = {"Cookie": f"{auth.COOKIE}={client.cookies[auth.COOKIE]}"}
                client.cookies.clear()
                return result.json()["actor"], headers

            player_code, spectator_code = invite("player"), invite("spectator")
            players = [join(player_code, f"玩家{i}") for i in range(7)]
            self.assertEqual({actor["seat_id"] for actor, _ in players}, set("1234567"))
            self.assertTrue(all(not s["cards"] for s in state()["seats"]))
            self.assertEqual(
                client.post("/api/join", json={"code": player_code, "name": "满席"}).status_code,
                409,
            )
            old, old_headers = players[0]
            command("room.kick", {"participant_id": old["id"]}, headers=old_headers, status=403)
            command("room.kick", {"participant_id": old["id"]})
            self.assertEqual(client.get(root + "/state", headers=old_headers).status_code, 401)
            players[0] = join(player_code, "重新入席")
            self.assertEqual(players[0][0]["seat_id"], old["seat_id"])
            stale_version = state()["version"]
            for _, headers in players:
                command("lobby.ready", headers=headers)
            command("lobby.ready", headers=players[0][1], version=stale_version, status=409)
            self.assertEqual(state()["phase"], "ordering")
            self.assertFalse(any(s["ready"] for s in state()["seats"]))
            command("host.start", status=422)
            original, original_headers = players[0]
            before = state(original_headers)
            own = next(s for s in before["seats"] if s["id"] == original["seat_id"])
            command("player.profile", {"name": own["name"]}, headers=original_headers)
            command(
                "lobby.order", {"top": before["self"]["cards"][1]["id"]}, headers=original_headers
            )
            sent = client.post(
                root + "/messages",
                headers=original_headers,
                json={"channel_id": "public", "text": "排牌时头像不可公开"},
            )
            sent.raise_for_status()
            self.assertIsNone(sent.json()["avatar_role_id"])
            substitute, substitute_headers = join(spectator_code, "替补")
            removed, removed_headers = join(spectator_code, "移出观战者")
            for headers in (host, original_headers, substitute_headers):
                self.assertTrue(all(s["avatar_role_id"] is None for s in state(headers)["seats"]))
            self.assertTrue(all("cards" not in s for s in state(substitute_headers)["seats"]))
            private = client.post(
                root + "/messages",
                headers=original_headers,
                json={"channel_id": "host:" + original["id"], "text": "不应交给替补的旧私聊"},
            )
            private.raise_for_status()
            with storage.transaction() as db:
                saved = storage.load_game(db, game["id"])
                assert saved is not None
                saved["cards"]["nanoka"]["uses"]["bullets"] = 2
                saved["cards"]["nanoka"]["injured"] = True
                storage.save_game(db, saved)
                cards = deepcopy(saved["cards"])
                pairs = [s["cards"][:] for s in saved["seats"]]
            command(
                "room.replace",
                {"seat_id": original["seat_id"], "participant_id": substitute["id"]},
                status=409,
            )
            command("room.kick", {"participant_id": removed["id"], "block": True})
            self.assertEqual(client.get(root + "/state", headers=removed_headers).status_code, 401)
            self.assertEqual(
                client.post(
                    "/api/join",
                    headers=removed_headers,
                    json={"code": spectator_code, "name": "被拉黑身份"},
                ).status_code,
                403,
            )
            command("room.kick", {"participant_id": original["id"]})
            self.assertEqual(client.get(root + "/state", headers=original_headers).status_code, 401)
            self.assertEqual(
                client.post(
                    "/api/join",
                    json={"code": player_code, "name": "发牌后不能重入空席"},
                ).status_code,
                409,
            )
            command(
                "room.replace",
                {"seat_id": original["seat_id"], "participant_id": players[1][0]["id"]},
                status=422,
            )
            replacement = {"seat_id": original["seat_id"], "participant_id": substitute["id"]}
            command("room.replace", replacement, headers=substitute_headers, status=403)
            command("room.replace", replacement)
            taken = client.get("/api/me", headers=substitute_headers).json()
            self.assertEqual(taken["actor"]["kind"], "player")
            self.assertEqual(taken["actor"]["seat_id"], original["seat_id"])
            history = client.get(root + "/messages", headers=substitute_headers).json()["messages"]
            self.assertNotIn(private.json()["id"], [m["id"] for m in history])
            for _, headers in [players[1], *players[2:], (substitute, substitute_headers)]:
                command("lobby.ready", headers=headers)
            started = command("host.start")
            self.assertEqual(started["status"], "playing")
            self.assertEqual(started["phase"], "witch")
            with storage.connect() as db:
                after = storage.load_game(db, game["id"])
                assert after is not None
                self.assertEqual(after["cards"], cards)
                self.assertEqual([s["cards"] for s in after["seats"]], pairs)
            join(spectator_code, "共用观战码仍有效")
            command("host.end", {"winner": "aborted", "reason": "回归验证结束"})
            self.assertEqual(
                client.post(
                    "/api/join",
                    json={"code": spectator_code, "name": "结束后拒绝"},
                ).status_code,
                403,
            )

    def test_legacy_dealt_lobby_migrates_without_redeal_or_disclosure(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(storage, "DATA_DIR", Path(directory)),
        ):
            storage.initialize()
            game = create_game(DEFAULT_CODEX)
            deal_cards(game)
            game["phase"] = "lobby"
            for seat in game["seats"]:
                seat["ready"] = True
                seat["avatar_role_id"] = seat["cards"][0]
            original = deepcopy(game)
            with storage.transaction() as db:
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
                for column in ("seat_id", "participant_id", "redeemed_by"):
                    db.execute(f"ALTER TABLE invites ADD COLUMN {column} TEXT")
                db.execute(
                    "INSERT INTO invites(code_hash,game_id,kind,seat_id) VALUES(?,?,?,?)",
                    ("old-code", game["id"], "player", "1"),
                )
                storage.add_message(
                    db,
                    game["id"],
                    kind="chat",
                    sender_id="old-player",
                    avatar_role_id="hiro",
                    text="旧候场记录",
                )
            storage.initialize()
            storage.initialize()
            with storage.connect() as db:
                migrated = storage.load_game(db, game["id"])
                assert migrated is not None
                self.assertEqual(migrated["phase"], "ordering")
                self.assertEqual(migrated["version"], original["version"] + 1)
                self.assertFalse(any(s["ready"] for s in migrated["seats"]))
                self.assertEqual(migrated["cards"], original["cards"])
                self.assertEqual(
                    [s["cards"] for s in migrated["seats"]], [s["cards"] for s in original["seats"]]
                )
                self.assertEqual(db.execute("SELECT valid FROM invites").fetchone()["valid"], 0)
                self.assertIsNone(
                    db.execute("SELECT avatar_role_id FROM messages").fetchone()["avatar_role_id"]
                )


class RoomReset(unittest.TestCase):
    def test_reset_and_next_game_clear_previous_game_data(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(storage, "DATA_DIR", Path(directory)),
            TestClient(app) as client,
        ):
            client.post("/api/host/login", json={"password": "114514"}).raise_for_status()
            host = {"Cookie": f"{auth.COOKIE}={client.cookies[auth.COOKIE]}"}
            game = client.post("/api/games", json={"codex": DEFAULT_CODEX}).json()
            root = f"/api/games/{game['id']}"
            code = client.post(
                root + "/invites", headers=host, json={"kind": "player"}
            ).json()["code"]

            def join(invite_code, name):
                client.cookies.clear()
                result = client.post("/api/join", json={"code": invite_code, "name": name})
                result.raise_for_status()
                headers = {"Cookie": f"{auth.COOKIE}={client.cookies[auth.COOKIE]}"}
                client.cookies.clear()
                return headers

            player = join(code, "一号玩家")
            self.assertEqual(client.post("/api/reset", json={}).status_code, 401)
            self.assertEqual(client.post("/api/reset", json={}, headers=player).status_code, 403)
            self.assertEqual(client.post("/api/reset", json={}, headers=host).status_code, 200)
            self.assertIsNone(client.get("/api/me", headers=host).json()["actor"]["game_id"])
            self.assertIsNone(client.get("/api/me", headers=player).json()["actor"])
            self.assertEqual(client.get(root + "/state", headers=host).status_code, 404)
            self.assertEqual(
                client.post("/api/join", json={"code": code, "name": "旧码"}).status_code, 403
            )
            with storage.connect() as db:
                for table in ("games", "participants", "invites", "channels", "messages", "evidence"):
                    self.assertEqual(
                        db.execute(f"SELECT count(*) AS total FROM {table}").fetchone()["total"],
                        0,
                        table,
                    )
                self.assertEqual(
                    db.execute("SELECT count(*) AS total FROM sessions WHERE kind='host'").fetchone()[
                        "total"
                    ],
                    1,
                )
            second = client.post("/api/games", json={"codex": DEFAULT_CODEX}, headers=host)
            second.raise_for_status()
            second_root = f"/api/games/{second.json()['id']}"
            second_code = client.post(
                second_root + "/invites", headers=host, json={"kind": "player"}
            ).json()["code"]
            player = join(second_code, "二号玩家")
            ended = client.post(
                second_root + "/commands",
                headers=host,
                json={
                    "expected_version": client.get(second_root + "/state", headers=host)
                    .json()["version"],
                    "action": "host.end",
                    "payload": {"winner": "aborted", "reason": "回归验证终止"},
                },
            )
            self.assertEqual(ended.status_code, 200, ended.text)
            self.assertEqual(ended.json()["status"], "ended")
            self.assertEqual(client.get(second_root + "/state", headers=host).status_code, 200)
            third = client.post("/api/games", json={"codex": DEFAULT_CODEX}, headers=host)
            third.raise_for_status()
            self.assertEqual(client.get(second_root + "/state", headers=host).status_code, 404)
            self.assertIsNone(client.get("/api/me", headers=player).json()["actor"])
            self.assertEqual(
                client.post("/api/join", json={"code": second_code, "name": "旧码"}).status_code,
                403,
            )
            third_code = client.post(
                f"/api/games/{third.json()['id']}/invites", headers=host, json={"kind": "player"}
            ).json()["code"]
            self.assertEqual(
                client.post("/api/join", json={"code": third_code, "name": "新码"}).status_code, 200
            )


class Heartbeat(unittest.IsolatedAsyncioTestCase):
    async def test_idle_connection_without_a_game_never_writes_presence(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(storage, "DATA_DIR", Path(directory)),
        ):
            storage.initialize()
            peer = realtime.Connection(
                socket=None,
                token_hash="stale",
                game_id=None,
                participant_id="host",
                name="主持人",
                kind="host",
                seat_id=None,
            )
            peer.last_pong = time.monotonic() - 61
            realtime.connections.add(peer)
            try:
                with patch.object(realtime.logger, "exception") as failed:
                    heartbeat = asyncio.create_task(realtime.clock())
                    await asyncio.sleep(1.3)
                    heartbeat.cancel()
                    with suppress(asyncio.CancelledError):
                        await heartbeat
                self.assertFalse(failed.called, failed.call_args)
                self.assertNotIn(peer, realtime.connections)
                with storage.connect() as db:
                    self.assertFalse(db.execute("SELECT id FROM messages").fetchall())
            finally:
                realtime.connections.clear()


class HostWorkbench(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.patch = patch.object(storage, "DATA_DIR", Path(self.directory.name))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.client.post("/api/host/login", json={"password": "114514"}).raise_for_status()
        self.host = {"Cookie": f"{auth.COOKIE}={self.client.cookies[auth.COOKIE]}"}
        self.game = self.client.post("/api/games", json={"codex": DEFAULT_CODEX}).json()
        self.root = f"/api/games/{self.game['id']}"
        self.client.cookies.clear()
        code = self.client.post(
            self.root + "/invites", headers=self.host, json={"kind": "player"}
        ).json()["code"]
        self.players = {}
        for index in range(7):
            self.client.cookies.clear()
            joined = self.client.post("/api/join", json={"code": code, "name": f"玩家{index}"})
            joined.raise_for_status()
            actor = joined.json()["actor"]
            self.players[actor["seat_id"]] = (
                actor,
                {"Cookie": f"{auth.COOKIE}={self.client.cookies[auth.COOKIE]}"},
            )
            self.client.cookies.clear()

    def state(self):
        result = self.client.get(self.root + "/state", headers=self.host)
        result.raise_for_status()
        return result.json()

    def test_host_acts_for_a_seat_and_leaves_a_public_trace(self):
        version = self.state()["version"]
        _, visitor = self.players["1"]
        refused = self.client.post(
            self.root + "/commands",
            headers=visitor,
            json={
                "expected_version": version,
                "action": "lobby.ready",
                "payload": {},
                "as_seat": "2",
            },
        )
        self.assertEqual(refused.status_code, 403, refused.text)
        done = self.client.post(
            self.root + "/commands",
            headers=self.host,
            json={
                "expected_version": version,
                "action": "lobby.ready",
                "payload": {},
                "as_seat": "1",
            },
        )
        self.assertEqual(done.status_code, 200, done.text)
        self.assertTrue(next(s for s in done.json()["seats"] if s["id"] == "1")["ready"])
        self.assertFalse(next(s for s in done.json()["seats"] if s["id"] == "2")["ready"])
        messages = self.client.get(
            self.root + "/messages?channel_id=public", headers=self.host
        ).json()["messages"]
        self.assertTrue(
            any("主持人为1号完成了本阶段操作" in item["text"] for item in messages), messages
        )
        denied = self.client.post(
            self.root + "/commands",
            headers=self.host,
            json={
                "expected_version": done.json()["version"],
                "action": "host.advance",
                "payload": {},
                "as_seat": "1",
            },
        )
        self.assertEqual(denied.status_code, 422, denied.text)
        view = self.client.get(f"{self.root}/seats/1/view", headers=self.host)
        self.assertEqual(view.status_code, 200, view.text)
        self.assertEqual(view.json()["seat_id"], "1")
        self.assertTrue(any(item["id"] == "lobby.ready" for item in view.json()["view"]["actions"]))
        self.assertNotIn("host", view.json()["view"])

    def start_game(self):
        for _ in range(2):
            for _, headers in self.players.values():
                ready = self.client.post(
                    self.root + "/commands",
                    headers=headers,
                    json={
                        "expected_version": self.state()["version"],
                        "action": "lobby.ready",
                        "payload": {},
                    },
                )
                self.assertEqual(ready.status_code, 200, ready.text)
        started = self.client.post(
            self.root + "/commands",
            headers=self.host,
            json={
                "expected_version": self.state()["version"],
                "action": "host.start",
                "payload": {},
            },
        )
        self.assertEqual(started.status_code, 200, started.text)
        self.assertEqual(started.json()["status"], "playing")

    def test_information_channel_returns_private_notices_to_the_right_player(self):
        actor, headers = self.players["1"]
        _, stranger = self.players["2"]
        self.start_game()
        channels = self.client.get(self.root + "/state", headers=headers).json()["channels"]
        system = next(item for item in channels if item["id"] == "system")
        self.assertFalse(system["can_send"])
        posted = self.client.post(
            self.root + "/messages",
            headers=headers,
            json={"channel_id": "system", "text": "不应发出"},
        )
        self.assertEqual(posted.status_code, 403, posted.text)
        sent = self.client.post(
            self.root + "/commands",
            headers=self.host,
            json={
                "expected_version": self.state()["version"],
                "action": "host.information",
                "payload": {
                    "title": "目击名单",
                    "text": "三名疑似凶手：甲、乙、丙",
                    "recipients": ["1"],
                },
            },
        )
        self.assertEqual(sent.status_code, 200, sent.text)
        mine = self.client.get(
            self.root + "/messages?channel_id=system", headers=headers
        ).json()["messages"]
        self.assertTrue(any("三名疑似凶手" in item["text"] for item in mine), mine)
        self.assertTrue(all(item["channel_id"] == "information" for item in mine))
        others = self.client.get(
            self.root + "/messages?channel_id=system", headers=stranger
        ).json()["messages"]
        self.assertFalse(any("三名疑似凶手" in item["text"] for item in others))
        self.assertEqual(actor["seat_id"], "1")


if __name__ == "__main__":
    unittest.main()
