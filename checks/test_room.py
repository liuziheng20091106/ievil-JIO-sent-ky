"""Room access, preparation, and legacy migration must preserve private seat state."""

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import auth, storage
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
            avatar = before["self"]["cards"][1]["role_id"]
            command(
                "player.profile", {"name": own["name"], "avatar": avatar}, headers=original_headers
            )
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


if __name__ == "__main__":
    unittest.main()
