"""Keep unconvertible Sherry seats out of the opening witch faction."""

import unittest
from unittest.mock import patch

from backend.app.game import DEFAULT_CODEX, create_game
from backend.app.game.state import deal_cards


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
