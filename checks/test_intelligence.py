"""Public intelligence: real-day quotas, actor permissions and event references."""

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from fastapi import HTTPException

from backend.app import storage
from backend.app.api import chat_references
from backend.app.game import GameError, apply_command, clear_seat_actions, game_view
from backend.app.game.state import display_player_name, rewind, save_snapshot, start_phase
from checks.rule_factory import arranged_game, player


ACTION = "day.intelligence"


class Intelligence(unittest.TestCase):
    def action_ids(self, game, actor):
        return {item["id"] for item in game_view(game, actor)["actions"]}

    def reject(self, game, actor, payload=None):
        before = deepcopy(game)
        with self.assertRaises(GameError):
            apply_command(game, actor, ACTION, {"text": "blocked"} if payload is None else payload)
        self.assertEqual(
            game, before, "Rejected intelligence must not consume a use or mutate state"
        )

    def test_each_seat_has_one_independent_use_across_day_phases(self):
        game = arranged_game()
        for seat in game["seats"]:
            actor = player(game, seat["id"])
            self.assertIn(ACTION, self.action_ids(game, actor))
            events = apply_command(
                game, actor, ACTION, {"text": " \n report " + seat["id"] + "\t "}
            )
            event = next(
                item for item in events if item.get("payload", {}).get("type") == "intelligence"
            )
            self.assertEqual(event["payload"]["text"], "report " + seat["id"])
            self.assertEqual(event["payload"]["seat_id"], seat["id"])
            self.assertEqual(seat["intelligence_days"], [2])
            self.assertNotIn(ACTION, self.action_ids(game, actor))
            self.reject(game, actor)
        for phase in ("speech", "nomination", "voting", "execution", "dusk"):
            with self.subTest(phase=phase):
                start_phase(game, phase)
                for seat in game["seats"]:
                    actor = player(game, seat["id"])
                    self.assertNotIn(ACTION, self.action_ids(game, actor))
                    self.reject(game, actor)
                fresh = arranged_game(phase)
                self.assertIn(ACTION, self.action_ids(fresh, player(fresh, "1")))
                apply_command(fresh, player(fresh, "1"), ACTION, {"text": phase})
                self.assertEqual(fresh["seats"][0]["intelligence_days"], [2])

    def test_invalid_text_does_not_consume_use_and_raw_length_is_limited(self):
        game = arranged_game()
        actor = player(game, "1")
        for payload in (
            {},
            {"text": ""},
            {"text": " \n\t "},
            {"text": "x" * 4001},
            {"text": " " * 4000 + "x"},
            {"text": 123},
            {"text": "valid", "seat_id": "2"},
        ):
            with self.subTest(payload=repr(payload)[:60]):
                self.reject(game, actor, payload)
                self.assertIn(ACTION, self.action_ids(game, actor))
                self.assertEqual(game["seats"][0].get("intelligence_days", []), [])
        events = apply_command(game, actor, ACTION, {"text": "x" * 4000})
        event = next(
            item for item in events if item.get("payload", {}).get("type") == "intelligence"
        )
        self.assertEqual(event["payload"]["text"], "x" * 4000)
        self.assertEqual(game["seats"][0]["intelligence_days"], [2])

    def test_requires_playing_day_and_current_player_identity(self):
        for status, half in (("lobby", "day"), ("ended", "day"), ("playing", "night")):
            with self.subTest(status=status, half=half):
                game = arranged_game()
                game.update(status=status, half=half)
                actor = player(game, "1")
                self.assertNotIn(ACTION, self.action_ids(game, actor))
                self.reject(game, actor)
        game = arranged_game()
        for actor in (
            {**player(game, "1"), "kind": "spectator"},
            {**player(game, "1"), "kind": "host", "host_entered": True},
            {**player(game, "1"), "kind": "host", "host_entered": False},
            {**player(game, "1"), "game_id": "another-game"},
            {**player(game, "1"), "seat_id": "2"},
        ):
            with self.subTest(actor=actor):
                self.reject(game, actor)
        apply_command(game, player(game, "1"), ACTION, {"text": "still available"})
        self.assertEqual(game["seats"][0]["intelligence_days"], [2])

    def test_eliminated_seat_can_publish_but_puppet_owner_cannot_bypass_control(self):
        game = arranged_game()
        for card_id in game["seats"][0]["cards"]:
            game["cards"][card_id]["alive"] = False
        actor = player(game, "1")
        self.assertFalse(game_view(game, actor)["seats"][0]["alive"])
        self.assertIn(ACTION, self.action_ids(game, actor))
        apply_command(game, actor, ACTION, {"text": "after elimination"})
        self.assertEqual(game["seats"][0]["intelligence_days"], [2])

        game = arranged_game()
        game["cards"]["meruru"]["witch"] = True
        game["cards"]["millia"]["states"].update(puppet="meruru", no_ability=True)
        victim = player(game, "1")
        self.assertNotIn(ACTION, self.action_ids(game, victim))
        self.reject(game, victim)
        controller = player(game, "3")
        panels = game_view(game, controller)["self"]["puppet_controls"]
        delegated = next(
            action
            for panel in panels
            if panel["seat_id"] == "1"
            for action in panel["actions"]
            if action["id"] == ACTION
        )
        self.assertEqual(delegated["as_seat"], "1")
        events = apply_command(
            game, {**victim, "puppet_controlled": True}, ACTION, {"text": "delegated"}
        )
        event = next(
            item for item in events if item.get("payload", {}).get("type") == "intelligence"
        )
        self.assertEqual(event["payload"]["seat_id"], "1")
        self.assertEqual(game["seats"][0]["intelligence_days"], [2])
        self.assertEqual(game["seats"][2].get("intelligence_days", []), [])
        self.assertIn(ACTION, self.action_ids(game, controller))
        self.reject(game, {**victim, "puppet_controlled": True})

    def test_cards_substitution_and_rewind_never_restore_used_days(self):
        game = arranged_game()
        seat = game["seats"][0]
        seat.pop("intelligence_days", None)
        actor = player(game, "1")
        snapshot = save_snapshot(game)
        self.assertIn(ACTION, self.action_ids(game, actor))
        apply_command(game, actor, ACTION, {"text": "legacy seat on day two"})
        seat["cards"].reverse()
        self.reject(game, actor)
        seat.update(occupant_id="replacement", name="Replacement")
        replacement = {**actor, "id": "replacement", "access_ids": ["replacement"]}
        self.reject(game, actor)
        clear_seat_actions(game, "1")
        self.reject(game, replacement)
        rewind(game, snapshot["id"], [])
        self.assertEqual(seat["occupant_id"], "replacement")
        self.assertEqual(seat["intelligence_days"], [2])
        self.assertNotIn(ACTION, self.action_ids(game, replacement))
        self.reject(game, replacement)

        game.update(day=3, half="night")
        self.reject(game, replacement)
        game["half"] = "day"
        self.assertIn(ACTION, self.action_ids(game, replacement))
        apply_command(game, replacement, ACTION, {"text": "next day"})
        self.assertEqual(seat["intelligence_days"], [2, 3])
        rewind(game, snapshot["id"], [])
        self.assertEqual(game["day"], 2)
        self.assertEqual(seat["intelligence_days"], [2, 3])
        self.reject(game, replacement)
        game["day"] = 3
        self.reject(game, replacement)
        game["day"] = 4
        self.assertIn(ACTION, self.action_ids(game, replacement))
        apply_command(game, replacement, ACTION, {"text": "unused day"})
        self.assertEqual(seat["intelligence_days"], [2, 3, 4])

    def test_public_storage_projection_and_full_utf16_event_references(self):
        game = arranged_game()
        game["seats"][0]["name"] = "LongPublicPlayerName"
        name = display_player_name(game["seats"][0]["name"])
        body = "\U0001f50e first line\n" + "evidence " * 300 + "\nlast \U0001f600"
        expected_text = f"\u7b2c2\u5929 \u00b7 1\u53f7 {name}\u7684\u60c5\u62a5\n{body}"
        expected_payload = {
            "type": "intelligence",
            "day": 2,
            "seat_id": "1",
            "actor_name": name,
            "text": body,
        }
        events = apply_command(game, player(game, "1"), ACTION, {"text": " \n" + body + "\t "})
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual(event["kind"], "alert")
        self.assertIsNone(event["audience"])
        self.assertEqual(event["reference_title"], "\u60c5\u62a5")
        self.assertEqual(event["text"], expected_text)
        self.assertEqual(event["payload"], expected_payload)
        actors = [
            player(game, "1"),
            player(game, "2"),
            {"id": "watcher", "kind": "spectator", "game_id": game["id"], "access_ids": []},
            {
                "id": "host",
                "kind": "host",
                "game_id": game["id"],
                "host_entered": False,
                "access_ids": [],
            },
            {"id": "host", "kind": "host", "host_entered": True, "access_ids": ["host"]},
        ]
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(storage, "DATA_DIR", Path(directory)),
        ):
            storage.initialize()
            with storage.transaction() as db:
                db.execute(
                    "INSERT INTO games(id,state,version,status,created_at) VALUES(?,?,?,?,?)",
                    (
                        game["id"],
                        storage.dumps(game),
                        game["version"],
                        game["status"],
                        storage.now_text(),
                    ),
                )
                saved = storage.add_events(db, game["id"], events)
                for actor in actors:
                    visible = storage.messages(db, game["id"], actor, scope="system")["messages"]
                    self.assertEqual([item["id"] for item in visible], [saved[0]["id"]])
                    self.assertEqual(visible[0]["kind"], "alert")
                    self.assertEqual(visible[0]["text"], expected_text)
                    self.assertEqual(visible[0]["payload"], expected_payload)
                    tainted = {
                        **event["payload"],
                        "role_id": "millia",
                        "card_id": "emma",
                        "actor_participant_id": "p1",
                        "fake": True,
                        "challengeable": True,
                    }
                    self.assertEqual(
                        storage.project_message_payload(tainted, actor, "alert"), expected_payload
                    )
                references = storage.reference_events(db, game["id"])
                self.assertEqual(len(references), 1)
                item = references[0]
                self.assertEqual(item["type"], "event")
                self.assertEqual(item["id"], str(saved[0]["id"]))
                self.assertTrue(item["label"].startswith("\u60c5\u62a5\u00b7"))
                self.assertEqual(item["text"], expected_text)
                prefix = "\U0001f600 quote\n"
                label = "#" + item["label"]
                start = len(prefix.encode("utf-16-le")) // 2
                end = start + len(label.encode("utf-16-le")) // 2
                self.assertGreater(start, len(prefix))
                ref = SimpleNamespace(type="event", id=item["id"], start=start, end=end)
                quoted = chat_references(db, game["id"], prefix + label + "\nend", [ref])
                self.assertEqual(quoted["items"], [{"start": start, "end": end, **item}])
                bad = SimpleNamespace(type="event", id=item["id"], start=1, end=end)
                with self.assertRaises(HTTPException) as rejected:
                    chat_references(db, game["id"], prefix + label, [bad])
                self.assertEqual(rejected.exception.status_code, 422)


if __name__ == "__main__":
    unittest.main()
