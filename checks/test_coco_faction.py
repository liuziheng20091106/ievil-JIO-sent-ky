"""Coco learns seat factions privately, independently of card transformation."""

import unittest
from unittest.mock import patch

from backend.app.game import game_view
from backend.app.game.resolution import begin_night
from checks.rule_factory import arranged_game, player


class CocoFactionInformation(unittest.TestCase):
    def game(self):
        game = arranged_game("witch", "night")
        game["seats"][1]["cards"] = ["coco", "hiro"]
        game["cards"]["coco"]["witch"] = True
        game["cards"]["emma"]["alive"] = False
        game["cards"]["millia"]["alive"] = False
        game["cards"]["marg"]["witch"] = True
        game["public"]["witch_destiny"]["first"] = ["2", "7"]
        return game

    def test_all_seats_use_faction_not_current_witch_state_and_remain_private(self):
        game = self.game()
        game["cards"]["coco"]["states"]["poisoned"] = False
        begin_night(game, [])
        own = game_view(game, player(game, "2"))
        report = next(item for item in own["information"] if item["title"] == "全员阵营")
        self.assertEqual(
            report["text"].splitlines(),
            [
                f"{sid}号：{'魔女阵营' if sid in ('2', '7') else '好人阵营'}"
                for sid in map(str, range(1, 8))
            ],
        )
        for actor in (
            player(game, "3"),
            {"kind": "spectator", "id": "observer", "game_id": game["id"]},
            {"kind": "host", "id": "host", "host_entered": False, "game_id": game["id"]},
        ):
            self.assertFalse(
                any(item["title"] == "全员阵营" for item in game_view(game, actor)["information"])
            )
        host = {"kind": "host", "id": "host", "host_entered": True}
        self.assertIn(report, game_view(game, host)["information"])

    def test_poisoned_false_report_has_all_seats_without_revealing_the_roll(self):
        game = self.game()
        game["cards"]["coco"]["states"]["poisoned"] = True
        with patch("backend.app.game.state.SystemRandom") as random:
            random.return_value.randrange.return_value = 1
            begin_night(game, [])
        report = next(
            item
            for item in game_view(game, player(game, "2"))["information"]
            if item["title"] == "全员阵营"
        )
        factions = dict(line.split("号：") for line in report["text"].splitlines())
        self.assertEqual(set(factions), set(map(str, range(1, 8))))
        self.assertEqual(sum(value == "魔女阵营" for value in factions.values()), 2)
        self.assertNotEqual(
            {sid for sid, value in factions.items() if value == "魔女阵营"}, {"2", "7"}
        )
        self.assertNotIn("中毒", report["text"])
        self.assertNotIn("roll", report)

    def test_normal_buried_and_dead_coco_do_not_receive_factions(self):
        for unavailable in ("normal", "buried", "dead"):
            with self.subTest(unavailable=unavailable):
                game = self.game()
                if unavailable == "normal":
                    game["cards"]["coco"]["witch"] = False
                elif unavailable == "buried":
                    game["seats"][1]["cards"] = ["hiro", "coco"]
                else:
                    game["cards"]["coco"]["alive"] = False
                begin_night(game, [])
                self.assertFalse(any(item["title"] == "全员阵营" for item in game["information"]))


if __name__ == "__main__":
    unittest.main()
