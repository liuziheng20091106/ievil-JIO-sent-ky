"""Codex suppression must preserve early conversions and saved-game selection."""

import unittest

from backend.app.game import apply_command, plugins
from backend.app.game.state import upgrade_game
from checks.test_rules import HOST, staged_game


class CodexDisabledRules(unittest.TestCase):
    def test_fourth_and_later_days_keep_existing_witches_and_enter_night(self):
        for day in (4, 5):
            with self.subTest(day=day):
                game = staged_game(day=day)
                game["cards"]["coco"]["witch"] = True
                game["generated_witches"] = ["coco"]
                apply_command(game, HOST, "host.advance", {})
                self.assertEqual(
                    {cid for cid, card in game["cards"].items() if card["witch"]},
                    {"coco"},
                )
                self.assertEqual(game["generated_witches"], ["coco"])
                self.assertEqual(game["phase"], "night")
                self.assertEqual(game["pending"], [])
                self.assertEqual(game["witch_checked_day"], day)

    def test_first_three_days_still_convert_the_original_targets(self):
        for day, target in ((1, "noah"), (2, "nanoka"), (3, "emma")):
            with self.subTest(day=day):
                game = staged_game(day=day, faction=("6", "7"))
                game["seats"][0]["cards"] = ["emma", "coco"]
                apply_command(game, HOST, "host.advance", {})
                self.assertEqual(
                    {cid for cid, card in game["cards"].items() if card["witch"]},
                    {target},
                )
                self.assertEqual(game["phase"], "night")

    def test_deselecting_restores_codex_conversion(self):
        game = staged_game(day=4)
        game["rule_plugins"] = plugins.manifest([])
        game["codex"] = ["coco"]
        apply_command(game, HOST, "host.advance", {})
        self.assertTrue(game["cards"]["coco"]["witch"])
        self.assertEqual(game["generated_witches"], ["coco"])
        self.assertEqual(game["phase"], "night")

    def test_disabled_codex_does_not_request_a_conversion_ruling(self):
        for selected, phase in ((None, "night"), ([], "witch")):
            with self.subTest(selected=selected):
                game = staged_game(day=4)
                game["rule_plugins"] = plugins.manifest(selected)
                game["codex"] = ["arisa", "sherry"]
                apply_command(game, HOST, "host.advance", {})
                self.assertFalse(any(card["witch"] for card in game["cards"].values()))
                self.assertEqual(game["phase"], phase)
                self.assertEqual(
                    [item["kind"] for item in game["pending"]],
                    [] if selected is None else ["codex"],
                )

    def test_old_save_does_not_silently_enable_the_new_plugin(self):
        game = staged_game(day=4)
        del game["rule_plugins"]
        upgrade_game(game)
        game["codex"] = ["coco"]
        apply_command(game, HOST, "host.advance", {})
        self.assertTrue(game["cards"]["coco"]["witch"])


if __name__ == "__main__":
    unittest.main()
