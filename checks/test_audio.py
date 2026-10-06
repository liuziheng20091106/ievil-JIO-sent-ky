"""Music controls, trusted event helpers, public projection and persistence."""

import asyncio
import json
import os
import tempfile
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import realtime, resource_packs, storage
from backend.app.game import DEFAULT_CODEX, GameError, apply_command, clock, game_view
from backend.app.game import audio, plugins
from backend.app.game.state import finish, rewind, save_snapshot, upgrade_game
from backend.app.main import app
from checks.rule_factory import arranged_game, player

HOST = {"id": "host", "kind": "host", "host_entered": True}


class Music(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        resources = self.root / "resources"
        music = resources / "audio"
        music.mkdir(parents=True)
        for name, seconds in (("theme.wav", 200), ("other.wav", 400), ("short.wav", 2)):
            with wave.open(str(music / name), "wb") as stream:
                stream.setparams((1, 1, 8000, 0, "NONE", "not compressed"))
                stream.writeframes(b"\x80" * (8000 * seconds))
        resource_packs.update_manifest(resources, "audio")
        for target, name, value in (
            (resource_packs, "RESOURCES_DIR", resources),
            (storage, "DATA_DIR", self.root / "data"),
        ):
            context = patch.object(target, name, value)
            context.start()
            self.addCleanup(context.stop)

    def test_independent_tracks_seek_rate_pause_resume_stop_and_public_progress(self):
        fake = clock.FakeClock(1000)
        with fake.installed():
            game = arranged_game()
            apply_command(game, HOST, "host.audio_play", {"song": "theme.wav"})
            first = audio.projection(game)["tracks"][0]["id"]
            apply_command(
                game, HOST, "host.audio_play", {"song": "theme.wav", "position": 20, "rate": 2}
            )
            second = audio.projection(game)["tracks"][1]["id"]
            self.assertNotEqual(first, second)
            fake.advance(10)
            before = audio.projection(game)
            self.assertEqual([track["position"] for track in before["tracks"]], [10, 40])
            revision = before["tracks"][0]["revision"]
            apply_command(
                game,
                HOST,
                "host.audio_update",
                {"id": first, "position": 7, "rate": 0.5, "playing": False},
            )
            paused = audio.projection(game)["tracks"][0]
            self.assertGreater(paused["revision"], revision)
            fake.advance(20)
            self.assertEqual(audio.projection(game)["tracks"][0]["position"], 7)
            self.assertEqual(audio.projection(game)["tracks"][1]["position"], 80)
            apply_command(game, HOST, "host.audio_update", {"id": first, "playing": True})
            fake.advance(4)
            for actor in (HOST, player(game, "1"), {"kind": "spectator", "game_id": game["id"]}):
                view = game_view(game, actor)["audio"]
                self.assertEqual(view["server_time"], 1034)
                self.assertEqual(view["tracks"][0]["position"], 9)
                self.assertEqual(
                    set(view["tracks"][0]),
                    {"id", "song", "position", "rate", "playing", "revision"},
                )
            apply_command(game, HOST, "host.audio_stop", {"id": first})
            self.assertEqual([track["id"] for track in audio.projection(game)["tracks"]], [second])
            finish(game, [], "aborted", "test")
            self.assertEqual(game["audio"]["tracks"], [])
            self.assertEqual(audio.projection(game)["tracks"], [])

    def test_trust_boundaries_and_invalid_input_leave_state_untouched(self):
        game = arranged_game()
        original = json.dumps(game, sort_keys=True)
        for actor in (player(game, "1"), {**HOST, "host_entered": False}):
            with self.assertRaises(GameError):
                apply_command(game, actor, "host.audio_play", {"song": "theme.wav"})
        for song in (
            "https://example.org/a.mp3",
            "../theme.wav",
            "/theme.wav",
            "missing.mp3",
            "image.png",
        ):
            with self.assertRaises(GameError):
                audio.play(game, song)
        for value in (-1, float("nan"), float("inf"), True, 10**400, audio.MAX_POSITION + 1):
            with self.assertRaises(GameError):
                audio.play(game, "theme.wav", position=value)
        for value in (0, -1, 0.1, 5, float("nan"), float("inf"), True):
            with self.assertRaises(GameError):
                audio.play(game, "theme.wav", rate=value)
        self.assertEqual(json.dumps(game, sort_keys=True), original)
        first = audio.play(game, "theme.wav", id="stable")
        before = json.dumps(game, sort_keys=True)
        for kwargs in (
            {"position": -1},
            {"rate": 5},
            {"playing": "false"},
            {"song": "missing.mp3"},
        ):
            with self.assertRaises(GameError):
                audio.change(game, first, **kwargs)
        self.assertEqual(json.dumps(game, sort_keys=True), before)
        revision = audio.projection(game)["tracks"][0]["revision"]
        audio.play(game, "other.wav", id="stable")
        tracks = audio.projection(game)["tracks"]
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0]["song"], "other.wav")
        self.assertGreater(tracks[0]["revision"], revision)

    def test_save_load_old_state_and_rewind_freeze_progress(self):
        fake = clock.FakeClock(1000)
        with fake.installed():
            game = arranged_game()
            first = audio.play(game, "theme.wav", id="event", position=3, rate=2)
            fake.advance(5)
            snapshot = save_snapshot(game)
            self.assertEqual(snapshot["state"]["audio"]["tracks"][0]["position"], 13)
            stored = json.loads(storage.dumps(game))
            fake.advance(5)
            self.assertEqual(audio.projection(stored)["tracks"][0]["position"], 23)
            audio.change(game, first, position=50, playing=False)
            old_revision = game["version"]
            fake.advance(100)
            rewind(game, snapshot["id"], [])
            restored = audio.projection(game)["tracks"][0]
            self.assertEqual(restored["position"], 13)
            self.assertGreater(restored["revision"], old_revision)
            fake.advance(5)
            self.assertEqual(audio.projection(game)["tracks"][0]["position"], 23)
            game.pop("audio")
            snapshot["state"].pop("audio")
            self.assertEqual(audio.projection(game)["tracks"], [])
            self.assertTrue(upgrade_game(game))
            self.assertEqual(game["audio"]["tracks"], [])
            rewind(game, snapshot["id"], [])
            self.assertEqual(game["audio"]["tracks"], [])

    def test_selected_plugin_handlers_play_change_stop_in_existing_command_flow(self):
        def start(game, events, context):
            audio.play(game, "theme.wav", id="event")
            audio.play(game, "other.wav", id="discard")

        def phase(game, events, context):
            audio.change(game, "event", position=12, rate=2, playing=False)
            audio.stop(game, "discard")

        module = SimpleNamespace(
            ID="musiccheck",
            VERSION=1,
            NAME="music check",
            DESCRIPTION="Event music behavior",
            CATEGORY="external_default_off",
            DEPENDS=(),
            HANDLERS={"game_started": start, "phase_enter": phase},
            COMMANDS={},
        )
        with patch.object(plugins, "REGISTRY", [*plugins.REGISTRY, module]):
            game = arranged_game("ordering", "night")
            game.update(status="lobby", rule_plugins=plugins.manifest([module.ID]))
            before = game["version"]
            apply_command(game, HOST, "host.start", {})
            track = game_view(game, player(game, "1"))["audio"]["tracks"]
            self.assertEqual(len(track), 1)
            self.assertEqual(
                (track[0]["id"], track[0]["position"], track[0]["rate"], track[0]["playing"]),
                ("event", 12, 2, False),
            )
            self.assertGreater(game["version"], before)
            self.assertEqual(game["snapshots"][-1]["state"]["audio"]["tracks"][0]["position"], 12)

    def test_completion_respects_rate_seek_pause_and_other_tracks(self):
        fake = clock.FakeClock(1000)
        with fake.installed():
            game = arranged_game()
            fast = audio.play(game, "short.wav", rate=2)
            paused = audio.play(game, "short.wav", position=1, playing=False)
            other = audio.play(game, "theme.wav")
            fake.advance(0.99)
            before = game["version"]
            self.assertFalse(audio.expire_finished(game))
            self.assertEqual(game["version"], before)
            fake.advance(0.01)
            self.assertTrue(audio.expire_finished(game))
            self.assertEqual([track["id"] for track in game["audio"]["tracks"]], [paused, other])
            self.assertNotIn(fast, [track["id"] for track in game["audio"]["tracks"]])
            fake.advance(20)
            self.assertFalse(audio.expire_finished(game))
            audio.change(game, paused, playing=True, rate=2)
            fake.advance(0.49)
            self.assertFalse(audio.expire_finished(game))
            fake.advance(0.01)
            self.assertTrue(audio.expire_finished(game))
            self.assertEqual([track["id"] for track in game["audio"]["tracks"]], [other])
            audio.change(game, other, position=200)
            self.assertTrue(audio.expire_finished(game))
            self.assertEqual(game_view(game, HOST)["audio"]["tracks"], [])

    def test_replacing_song_and_restoring_snapshot_keep_correct_end_time(self):
        fake = clock.FakeClock(1000)
        with fake.installed():
            game = arranged_game()
            audio.play(game, "short.wav", id="event")
            fake.advance(1)
            snapshot = save_snapshot(game)
            audio.change(game, "event", song="theme.wav", position=0)
            fake.advance(3)
            self.assertFalse(audio.expire_finished(game))
            self.assertEqual(game["audio"]["tracks"][0]["song"], "theme.wav")
            rewind(game, snapshot["id"], [])
            fake.advance(0.99)
            self.assertFalse(audio.expire_finished(game))
            fake.advance(0.01)
            self.assertTrue(audio.expire_finished(game))
            self.assertEqual(game["audio"]["tracks"], [])

    def test_legacy_track_without_duration_is_backfilled_then_removed(self):
        fake = clock.FakeClock(1000)
        with fake.installed():
            game = arranged_game()
            audio.play(game, "short.wav")
            game["audio"]["tracks"][0].pop("duration")
            saved = json.loads(storage.dumps(game))
            self.assertTrue(audio.expire_finished(saved))
            fake.advance(2)
            self.assertTrue(audio.expire_finished(saved))
            self.assertEqual(saved["audio"]["tracks"], [])

    def test_unreadable_audio_never_adds_or_replaces_a_track(self):
        music = resource_packs.RESOURCES_DIR / "audio"
        (music / "broken.mp3").write_bytes(b"not playable audio")
        resource_packs.update_manifest(resource_packs.RESOURCES_DIR, "audio")
        game = arranged_game()
        audio.play(game, "short.wav", id="event")
        before = json.dumps(game, sort_keys=True)
        for operation in (
            lambda: audio.play(game, "broken.mp3"),
            lambda: audio.change(game, "event", song="broken.mp3"),
        ):
            with self.assertRaises(GameError):
                operation()
            self.assertEqual(json.dumps(game, sort_keys=True), before)

    def login(self, client, qq, *, host=False):
        prefix = "/api/native/auth/host/challenges" if host else "/api/native/auth/challenges"
        challenge = client.post(prefix).json()
        client.post(
            "/api/internal/qq/login",
            headers={"X-Gateway-Token": "music-test-secret"},
            json={
                "code": challenge["code"],
                "qq_id": qq,
                "nickname": qq,
                "avatar_url": "https://example.invalid/avatar",
                "group_id": 123456,
            },
        ).raise_for_status()
        result = client.get(prefix + "/" + challenge["id"])
        result.raise_for_status()
        return {"Authorization": "Bearer " + result.json()["session_token"]}

    def test_http_permissions_conflicts_save_load_and_two_user_state_broadcast(self):
        with (
            patch.dict(
                os.environ,
                {
                    "GAME_ADMIN_QQ": "10001,10002",
                    "GAME_GATEWAY_TOKEN": "music-test-secret",
                    "GAME_QQ_GROUP_ID": "123456",
                },
            ),
            TestClient(
                app, base_url="http://testserver", headers={"Origin": "http://testserver"}
            ) as client,
        ):
            host = self.login(client, "10001", host=True)
            unentered = self.login(client, "10002", host=True)
            created = client.post("/api/games", headers=host, json={"codex": DEFAULT_CODEX})
            created.raise_for_status()
            root = "/api/games/" + created.json()["id"]
            client.post(root + "/host/enter", headers=host).raise_for_status()

            def command(headers, action, payload, version=None):
                if version is None:
                    version = client.get(root + "/state", headers=host).json()["version"]
                return client.post(
                    root + "/commands",
                    headers=headers,
                    json={"expected_version": version, "action": action, "payload": payload},
                )

            command(host, "room.open_join", {"open": True}).raise_for_status()
            participant = self.login(client, "20001")
            client.post(
                root + "/participations", headers=participant, json={"kind": "player"}
            ).raise_for_status()
            version = client.get(root + "/state", headers=host).json()["version"]
            self.assertEqual(
                command(unentered, "host.audio_play", {"song": "theme.wav"}, version).status_code,
                403,
            )
            self.assertEqual(
                command(participant, "host.audio_play", {"song": "theme.wav"}, version).status_code,
                422,
            )
            self.assertEqual(
                command(
                    host, "host.audio_play", {"song": "https://example.org/a.mp3"}, version
                ).status_code,
                422,
            )
            self.assertEqual(
                command(host, "host.audio_play", {"song": "theme.wav"}, version - 1).status_code,
                409,
            )
            self.assertEqual(client.get(root + "/state", headers=host).json()["version"], version)
            with (
                client.websocket_connect("/api/live", headers=host) as host_socket,
                client.websocket_connect("/api/live", headers=participant) as player_socket,
            ):
                self.assertEqual(host_socket.receive_json()["type"], "sync")
                self.assertEqual(player_socket.receive_json()["type"], "sync")
                response = command(
                    host,
                    "host.audio_play",
                    {"song": "theme.wav", "position": 8, "rate": 1.5},
                    version,
                )
                response.raise_for_status()
                track = response.json()["audio"]["tracks"][0]
                for socket in (host_socket, player_socket):
                    for _ in range(12):
                        frame = socket.receive_json()
                        if (
                            frame["type"] == "state"
                            and frame["state"]["version"] == response.json()["version"]
                        ):
                            self.assertEqual(
                                frame["state"]["audio"]["tracks"][0]["id"], track["id"]
                            )
                            break
                    else:
                        self.fail("Music state did not reach both connected users")
                self.assertEqual(
                    command(host, "host.audio_stop", {"id": track["id"]}, version).status_code, 409
                )
                command(
                    host, "host.audio_update", {"id": track["id"], "playing": False}
                ).raise_for_status()
                with storage.connect() as db:
                    saved = storage.load_game(db, created.json()["id"])
                self.assertFalse(saved["audio"]["tracks"][0]["playing"])
                self.assertGreater(saved["audio"]["tracks"][0]["revision"], track["revision"])
                command(host, "host.audio_stop", {"id": track["id"]}).raise_for_status()
                self.assertEqual(
                    client.get(root + "/state", headers=participant).json()["audio"]["tracks"], []
                )
                kept = command(host, "host.audio_play", {"song": "theme.wav"}).json()["audio"][
                    "tracks"
                ][0]["id"]
                command(
                    host, "host.audio_update", {"id": kept, "playing": False}
                ).raise_for_status()
                completed = command(
                    host, "host.audio_play", {"song": "short.wav", "position": 1, "rate": 4}
                )
                completed.raise_for_status()
                completed_version = completed.json()["version"]
                for socket in (host_socket, player_socket):
                    for _ in range(20):
                        frame = socket.receive_json()
                        if (
                            frame["type"] == "state"
                            and frame["state"]["version"] > completed_version
                        ):
                            self.assertEqual(
                                [item["id"] for item in frame["state"]["audio"]["tracks"]], [kept]
                            )
                            break
                    else:
                        self.fail("Finished song removal did not reach both connected users")
                with storage.connect() as db:
                    saved = storage.load_game(db, created.json()["id"])
                self.assertEqual([item["id"] for item in saved["audio"]["tracks"]], [kept])
                self.assertFalse(saved["audio"]["tracks"][0]["playing"])
                command(host, "host.audio_stop", {"id": kept}).raise_for_status()
                host_socket.close()
                player_socket.close()

                async def disconnected():
                    async with asyncio.timeout(2):
                        while any(
                            peer.game_id == created.json()["id"] for peer in realtime.connections
                        ):
                            await asyncio.sleep(0)

                player_socket.portal.call(disconnected)


if __name__ == "__main__":
    unittest.main()
