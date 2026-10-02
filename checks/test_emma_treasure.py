"""Optional treasure selection, private results and mechanical rewind boundaries."""

from copy import deepcopy
import unittest
from unittest.mock import patch

from backend.app.game import GameError, apply_command, game_view, plugins
from backend.app.game.actions import actions_for, night_abilities, target_field
from backend.app.game.external_plugins import emma_treasure
from backend.app.game.resolution import begin_night, night_damage
from backend.app.game.state import rewind, save_snapshot, upgrade_game
from backend.app.game.views import card_view, status_cards
from checks.rule_factory import arranged_game, player


class EmmaTreasure(unittest.TestCase):
    def game(self, *, enabled=False):
        game = arranged_game("night", "night")
        if enabled:
            game["rule_plugins"] = plugins.manifest([emma_treasure.ID])
        game["cards"]["millia"]["alive"] = False
        begin_night(game, [])
        return game

    def test_disabled_and_legacy_games_have_no_treasure_effects(self):
        game = self.game()
        del game["rule_plugins"]
        upgrade_game(game)
        plugins.require_compatible(game)
        card = game["cards"]["emma"]
        card["states"]["treasure_protected_day"] = game["day"]
        game["plugin_state"][emma_treasure.ID] = {"card_id": "emma", "protected_day": game["day"]}
        self.assertNotIn("treasure", night_abilities(game, card))
        self.assertIn("1", game["night"]["confirmed"])
        self.assertIn(
            "1", {item["value"] for item in target_field(game, avoid_treasure=True)["options"]}
        )
        self.assertFalse(emma_treasure.treasure_protected(game, "emma"))
        self.assertNotIn("treasure_protected_day", card_view(game, card)["states"])
        self.assertNotIn("treasure", {item["id"] for item in status_cards(game, game["seats"][0])})
        for action, payload in (
            (emma_treasure.ID + ".submit", {}),
            ("night.submit", {"ability": "treasure"}),
        ):
            with self.assertRaises(GameError):
                apply_command(deepcopy(game), player(game, "1"), action, payload)
        game["night"]["actions"] = [
            {
                "ability": "treasure",
                "card_id": "emma",
                "seat_id": "1",
                "effective": True,
                "mine": True,
            }
        ]
        self.assertEqual(night_damage(game)[0]["deaths"], [])

    def test_enabled_treasure_rejects_other_roles_and_hides_the_roll(self):
        game = self.game(enabled=True)
        spectator = {"id": "watch", "kind": "spectator", "game_id": game["id"]}
        unentered_host = {
            "id": "other-host",
            "kind": "host",
            "game_id": game["id"],
            "host_entered": False,
        }
        for actor in (player(game, "2"), spectator, unentered_host):
            with self.assertRaises(GameError):
                apply_command(deepcopy(game), actor, emma_treasure.ID + ".submit", {})
        with patch.object(emma_treasure, "SystemRandom") as random:
            random.return_value.randrange.return_value = 1
            apply_command(game, player(game, "1"), emma_treasure.ID + ".submit", {})
        own = game_view(game, player(game, "1"))
        self.assertTrue(any(item["title"] == "寻宝结果" for item in own["information"]))
        self.assertNotIn("roll", own["self"]["cards"][1]["states"])
        self.assertEqual(own["self"]["cards"][1]["states"]["treasure_protected_day"], game["day"])
        for actor in (player(game, "2"), spectator, unentered_host):
            view = game_view(game, actor)
            self.assertFalse(any(item["title"] == "寻宝结果" for item in view["information"]))
            self.assertNotIn("plugin_state", view)

    def test_rewind_restores_protection_and_does_not_change_selection(self):
        game = self.game(enabled=True)
        selected = deepcopy(game["rule_plugins"])
        before = save_snapshot(game)
        with patch.object(emma_treasure, "SystemRandom") as random:
            random.return_value.randrange.return_value = 1
            apply_command(game, player(game, "1"), emma_treasure.ID + ".submit", {})
        after = save_snapshot(game)
        game["day"] += 1
        self.assertFalse(emma_treasure.treasure_protected(game, "emma"))
        rewind(game, after["id"], [])
        self.assertTrue(emma_treasure.treasure_protected(game, "emma"))
        self.assertNotIn(
            emma_treasure.ID + ".submit", {a["id"] for a in actions_for(game, player(game, "1"))}
        )
        rewind(game, before["id"], [])
        self.assertFalse(emma_treasure.treasure_protected(game, "emma"))
        self.assertIn(
            emma_treasure.ID + ".submit", {a["id"] for a in actions_for(game, player(game, "1"))}
        )
        self.assertEqual(game["rule_plugins"], selected)
