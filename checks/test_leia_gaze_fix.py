"""Gaze fix: daily permission boundaries, public animation and mechanical rewind."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.app import storage
from backend.app.game import GameError, apply_command, clear_seat_actions, game_view, plugins
from backend.app.game.actions import actions_for
from backend.app.game.engine import sync_auto_advance, sync_speaker
from backend.app.game.external_plugins import leia_gaze_fix
from backend.app.game.state import rewind, save_snapshot
from checks.rule_factory import arranged_game, player

ACTION = leia_gaze_fix.ID + ".use"
HOST = {"id": "host", "kind": "host", "host_entered": True, "access_ids": ["host"]}
UNENTERED = {**HOST, "host_entered": False, "access_ids": []}


class LeiaGazeFix(unittest.TestCase):
    def game(self, phase="discussion", *, enabled=True, witch=False):
        game = arranged_game(phase)
        game["rule_plugins"] = plugins.manifest([leia_gaze_fix.ID] if enabled else [])
        game["cards"]["leia"]["witch"] = witch
        if phase == "speech":
            game["public"].update(speaker="1", speech_order=list(map(str, range(1, 8))))
        sync_speaker(game, [])
        sync_auto_advance(game)
        return game

    def action_ids(self, game, actor):
        return {item["id"] for item in game_view(game, actor)["actions"]}

    def reject(self, game, actor, payload=None):
        before = deepcopy(game)
        with self.assertRaises(GameError):
            apply_command(game, actor, ACTION, {} if payload is None else payload)
        self.assertEqual(game, before, "A rejected command must not change any game state")

    def test_unselected_module_has_no_action_or_consumption(self):
        game = self.game(enabled=False)
        actor = player(game, "5")
        self.assertNotIn(ACTION, self.action_ids(game, actor))
        self.reject(game, actor)
        before = deepcopy(game)
        events = []
        with self.assertRaises(GameError):
            leia_gaze_fix.use(game, actor, events, {})
        self.assertEqual(game, before)
        self.assertEqual(events, [])

    def test_once_per_day_in_every_day_phase_without_rule_effects(self):
        for phase in ("speech", "discussion", "nomination", "voting", "execution", "dusk"):
            for witch in (False, True):
                with self.subTest(phase=phase, witch=witch):
                    game = self.game(phase, witch=witch)
                    actor = player(game, "5")
                    self.assertIn(ACTION, self.action_ids(game, actor))
                    keys = (
                        "cards",
                        "public",
                        "duel",
                        "declarations",
                        "night",
                        "pending",
                        "deadline",
                        "warnings",
                        "water",
                        "spiritual",
                        "information",
                    )
                    before = {key: deepcopy(game[key]) for key in keys}
                    events = apply_command(game, actor, ACTION, {})
                    self.assertEqual(len(events), 1)
                    self.assertEqual(events[0]["kind"], "alert")
                    self.assertIsNone(events[0]["audience"])
                    self.assertFalse(events[0]["payload"]["challengeable"])
                    self.assertEqual({key: game[key] for key in keys}, before)
                    self.assertEqual(game["plugin_state"][leia_gaze_fix.ID]["day"], game["day"])
                    self.assertNotIn(ACTION, self.action_ids(game, actor))
                    self.reject(game, actor)
                    game["day"] += 1
                    self.assertIn(ACTION, self.action_ids(game, actor))
                    apply_command(game, actor, ACTION, {})
                    self.assertNotIn(ACTION, self.action_ids(game, actor))

    def test_invalid_actor_and_ability_states_do_not_pollute_state(self):
        for case in (
            "night",
            "lobby",
            "finished",
            "wrong_role",
            "spectator",
            "host",
            "unentered",
            "different_game",
            "former_occupant",
            "no_ability",
            "lower_card",
            "dead",
            "puppet",
            "puppet_controlled",
            "forged_payload",
        ):
            with self.subTest(case=case):
                game = self.game()
                actor = player(game, "5")
                payload = {}
                if case == "night":
                    game.update(half="night", phase="night")
                elif case == "lobby":
                    game.update(status="lobby", phase="ordering")
                elif case == "finished":
                    game["status"] = "ended"
                elif case == "wrong_role":
                    actor = player(game, "1")
                elif case == "spectator":
                    actor = {"id": "watch", "kind": "spectator", "game_id": game["id"]}
                elif case == "host":
                    actor = HOST
                elif case == "unentered":
                    actor = {**UNENTERED, "game_id": game["id"]}
                elif case == "different_game":
                    actor = {**actor, "game_id": "another-game"}
                elif case == "former_occupant":
                    game["seats"][4]["occupant_id"] = "replacement"
                elif case == "no_ability":
                    game["cards"]["leia"]["states"]["no_ability"] = True
                elif case == "lower_card":
                    game["seats"][4]["cards"].reverse()
                elif case == "dead":
                    for cid in game["seats"][4]["cards"]:
                        game["cards"][cid]["alive"] = False
                elif case == "puppet":
                    game["cards"]["leia"]["states"].update(puppet="meruru", no_ability=True)
                elif case == "puppet_controlled":
                    actor = {**actor, "puppet_controlled": True}
                elif case == "forged_payload":
                    payload = {"ability": "duel", "target": "1"}
                if case not in {"different_game", "former_occupant", "forged_payload"}:
                    self.assertNotIn(ACTION, self.action_ids(game, actor))
                self.reject(game, actor, payload)
                if case != "forged_payload":
                    before = deepcopy(game)
                    events = []
                    with self.assertRaises(GameError):
                        leia_gaze_fix.use(game, actor, events, {})
                    self.assertEqual(game, before)
                    self.assertEqual(events, [])
        game = self.game()
        self.assertNotIn(
            ACTION,
            {item["id"] for item in actions_for(game, player(game, "5"), as_seat="1")},
        )

    def test_every_recipient_gets_the_same_animation_without_witch_disclosure(self):
        messages_by_form = []
        for witch in (False, True):
            game = self.game(witch=witch)
            actor = player(game, "5")
            events = apply_command(game, actor, ACTION, {})
            recipients = (
                actor,
                player(game, "1"),
                HOST,
                UNENTERED,
                {"id": "watch", "kind": "spectator", "game_id": game["id"]},
            )
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
                    storage.add_events(db, game["id"], events)
                    projected = [
                        storage.messages(db, game["id"], recipient)["messages"]
                        for recipient in recipients
                    ]
                    for messages in projected:
                        self.assertEqual(len(messages), 1)
                        payload = messages[0]["payload"]
                        self.assertEqual(
                            payload["animation"],
                            {"script": "scripts/leia-gaze-fix.json", "images": {}, "texts": {}},
                        )
                        self.assertNotIn("_animation", payload)
                        self.assertNotIn("witch", payload)
                        self.assertNotIn("plugin_state", game_view(game, recipients[1]))
                    messages_by_form.append([messages[0]["payload"] for messages in projected])
        self.assertEqual(messages_by_form[0], messages_by_form[1])

    def test_replacement_retains_daily_use_and_rewind_restores_it(self):
        game = self.game()
        actor = player(game, "5")
        selected = deepcopy(game["rule_plugins"])
        before = save_snapshot(game)
        apply_command(game, actor, ACTION, {})
        after = save_snapshot(game)
        seat = game["seats"][4]
        seat.update(occupant_id="replacement", name="Replacement")
        replacement = {**actor, "id": "replacement", "access_ids": ["replacement"]}
        self.reject(game, actor)
        self.reject(game, replacement)
        clear_seat_actions(game, "5")
        self.reject(game, replacement)
        rewind(game, after["id"], [])
        self.assertEqual(seat["occupant_id"], "replacement")
        self.assertNotIn(ACTION, self.action_ids(game, replacement))
        self.reject(game, replacement)
        rewind(game, before["id"], [])
        self.assertEqual(seat["occupant_id"], "replacement")
        self.assertEqual(game["rule_plugins"], selected)
        self.assertIn(ACTION, self.action_ids(game, replacement))
        apply_command(game, replacement, ACTION, {})
        self.assertNotIn(ACTION, self.action_ids(game, replacement))


if __name__ == "__main__":
    unittest.main()
