"""Regression checks for rules that can silently spoil a hidden-role game."""

import unittest

from backend.app.game import DEFAULT_CODEX, GameError, create_game, game_view


HOST = {"id": "host", "kind": "host", "seat_id": None, "access_ids": ["host"]}


class SetupRules(unittest.TestCase):
    def test_dealing_never_duplicates_cards_or_pairs_the_two_key_roles(self):
        for _ in range(100):
            game = create_game(DEFAULT_CODEX)
            visible = game_view(game, HOST)
            cards = [card for seat in visible["seats"] for card in seat["cards"]]
            self.assertEqual(len(cards), 14)
            self.assertEqual(len({card["id"] for card in cards}), 14)
            for seat in visible["seats"]:
                self.assertEqual(len(seat["cards"]), 2)
                self.assertFalse(
                    {"millia", "arisa"}.issubset({card["role_id"] for card in seat["cards"]})
                )

    def test_player_and_spectator_views_do_not_disclose_other_cards(self):
        game = create_game(DEFAULT_CODEX)
        for seat in game["seats"]:
            seat["occupant_id"] = "participant-" + seat["id"]
        actor = {
            "id": "participant-1",
            "kind": "player",
            "game_id": game["id"],
            "seat_id": "1",
            "access_ids": ["participant-1"],
        }
        visible = game_view(game, actor)
        self.assertEqual(len(visible["self"]["cards"]), 2)
        self.assertFalse(visible.get("host"))
        for seat in visible["seats"]:
            if seat["id"] != "1":
                self.assertFalse(seat.get("cards"))
        observer = game_view(
            game,
            {
                "id": "observer",
                "kind": "spectator",
                "game_id": game["id"],
                "seat_id": None,
                "access_ids": ["observer"],
            },
        )
        self.assertFalse(observer["self"]["cards"])
        self.assertFalse(observer.get("host"))
        self.assertTrue(all(not seat.get("cards") for seat in observer["seats"]))

    def test_duplicate_codex_entry_is_rejected_even_with_eleven_entries(self):
        codex = list(DEFAULT_CODEX)
        codex[-1] = codex[0]
        with self.assertRaises(GameError):
            create_game(codex)


if __name__ == "__main__":
    unittest.main()
