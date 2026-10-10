"""Keep unconvertible Sherry seats out of the opening witch faction."""

import unittest
from unittest.mock import patch

from backend.app.game import DEFAULT_CODEX, create_game, plugins
from backend.app.game.state import deal_cards
from checks.rule_factory import player
from checks.test_resolution import HOST, command, settle_night_witnesses


class WitchFactionDealRules(unittest.TestCase):
    def test_sherry_is_excluded_in_either_layer(self):
        for pair in (("sherry", "noah"), ("noah", "sherry")):
            with self.subTest(pair=pair):
                order = [
                    *pair,
                    "hanna",
                    "nanoka",
                    "coco",
                    "millia",
                    "annan",
                    "arisa",
                    "marg",
                    "emma",
                    "leia",
                    "hiro",
                    "meruru",
                    "honoka",
                ]
                with patch("backend.app.game.state.SystemRandom") as random:
                    random.return_value.shuffle.side_effect = lambda cards, order=order: (
                        cards.__setitem__(slice(None), order)
                    )
                    random.return_value.sample.side_effect = lambda seats, count: seats[:count]
                    game = create_game(DEFAULT_CODEX)
                    deal_cards(game)
                faction = game["public"]["witch_destiny"]["first"]
                self.assertEqual(len(set(faction)), 2)
                self.assertNotIn("1", faction)
                for seat in game["seats"]:
                    if set(seat["cards"]) & {"emma", "millia", "arisa", "sherry"}:
                        self.assertNotIn(seat["id"], faction)

    def opening_game(self):
        order = [
            "sherry",
            "noah",
            "hanna",
            "nanoka",
            "coco",
            "millia",
            "marg",
            "arisa",
            "annan",
            "emma",
            "hiro",
            "leia",
            "meruru",
            "honoka",
        ]
        game = create_game(DEFAULT_CODEX)
        first = ["annan", "noah", "coco", "marg", "hanna"]
        game["codex"] = first + [cid for cid in DEFAULT_CODEX if cid not in first]
        with patch("backend.app.game.state.SystemRandom") as random:
            random.return_value.shuffle.side_effect = lambda cards: cards.__setitem__(
                slice(None), order
            )
            random.return_value.sample.return_value = [5, 6]
            deal_cards(game)
        for seat in game["seats"]:
            seat.update(occupant_id="p" + seat["id"], ready=True)
        game["public"]["auto_advance_off"] = True
        command(game, HOST, "host.start")
        return game

    def rewound_opening_game(self):
        game = self.opening_game()
        command(game, HOST, "host.advance")
        self.assertTrue(game["cards"]["hiro"]["witch"])
        command(game, player(game, "6"), "hiro.exit")
        game["night"]["confirmed"] = list(game["night"]["actors"])
        command(game, HOST, "host.advance")
        command(game, HOST, "host.advance")
        settle_night_witnesses(game)
        command(game, HOST, "host.advance")
        self.assertEqual((game["day"], game["phase"]), (1, "witch"))
        self.assertTrue(game["cards"]["hiro"]["witch"])
        return game

    def test_opening_hiro_witch_rewind_converts_original_second_day_seat(self):
        game = self.rewound_opening_game()
        command(game, HOST, "host.advance")
        self.assertEqual(game["phase"], "night")
        self.assertEqual(game["public"]["witch_destiny"]["first"], ["6", "7"])
        self.assertEqual(
            {cid for cid, card in game["cards"].items() if card["witch"]}, {"hiro", "meruru"}
        )
        self.assertEqual(game["generated_witches"], ["hiro", "meruru"])
        game.update(day=2, phase="witch")
        command(game, HOST, "host.advance")
        self.assertEqual(game["generated_witches"], ["hiro", "meruru"])

    def test_first_two_days_codex_fallback_excludes_all_forbidden_seats(self):
        for day, unavailable, expected in (
            (1, ("hiro", "leia"), "hanna"),
            (2, ("meruru", "honoka"), "hanna"),
        ):
            with self.subTest(day=day):
                game = self.opening_game()
                game["day"] = day
                game["seats"][0]["cards"] = ["noah", "sherry"]
                for cid in unavailable:
                    game["cards"][cid]["alive"] = False
                command(game, HOST, "host.advance")
                self.assertEqual(game["phase"], "night")
                self.assertEqual(
                    {cid for cid, card in game["cards"].items() if card["witch"]}, {expected}
                )

    def test_fourth_day_can_convert_emma_seat_partner(self):
        game = self.opening_game()
        game["day"] = 4
        game["rule_plugins"] = plugins.manifest([])
        command(game, HOST, "host.advance")
        self.assertEqual(game["phase"], "night")
        self.assertEqual({cid for cid, card in game["cards"].items() if card["witch"]}, {"annan"})

    def test_unavailable_second_day_rewind_target_requires_ruling_without_codex(self):
        game = self.rewound_opening_game()
        for cid in game["seats"][6]["cards"]:
            game["cards"][cid]["alive"] = False
        command(game, HOST, "host.advance")
        self.assertEqual(game["phase"], "witch")
        self.assertEqual({cid for cid, card in game["cards"].items() if card["witch"]}, {"hiro"})
        self.assertEqual([item["kind"] for item in game["pending"]], ["codex"])
