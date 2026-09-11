"""Regression checks for rules that can silently spoil a hidden-role game."""

import unittest

from backend.app.game import DEFAULT_CODEX, GameError, apply_command, create_game, game_view


HOST = {"id": "host", "kind": "host", "seat_id": None, "access_ids": ["host"]}


def players(game):
    actors = []
    for seat in game["seats"]:
        seat["occupant_id"] = "participant-" + seat["id"]
        actors.append(
            {
                "id": seat["occupant_id"],
                "kind": "player",
                "game_id": game["id"],
                "seat_id": seat["id"],
                "access_ids": [seat["occupant_id"]],
            }
        )
    return actors


class SetupRules(unittest.TestCase):
    def test_dealing_never_duplicates_cards_or_pairs_the_two_key_roles(self):
        for _ in range(100):
            game = create_game(DEFAULT_CODEX)
            for actor in players(game):
                apply_command(game, actor, "lobby.ready", {})
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
        actors = players(game)
        for actor in actors:
            apply_command(game, actor, "lobby.ready", {})
        actor = actors[0]
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

    def test_two_ready_rounds_keep_roles_private_until_host_start(self):
        game = create_game(DEFAULT_CODEX)
        actors = players(game)
        observer = {
            "id": "observer",
            "kind": "spectator",
            "game_id": game["id"],
            "seat_id": None,
            "access_ids": ["observer"],
        }
        for actor in [HOST, *actors, observer]:
            visible = game_view(game, actor)
            self.assertFalse(visible["self"]["cards"])
            self.assertIsNone(visible["self"]["current_card_id"])
            self.assertTrue(all(not seat.get("cards") for seat in visible["seats"]))
            self.assertTrue(all(seat["alive"] for seat in visible["seats"]))
        with self.assertRaises(GameError):
            apply_command(game, actors[0], "lobby.order", {"top": "emma"})
        with self.assertRaises(GameError):
            apply_command(game, HOST, "host.start", {})
        apply_command(game, actors[0], "player.profile", {"name": "甲", "avatar": "emma"})
        for actor in actors[:-1]:
            apply_command(game, actor, "lobby.ready", {})
            self.assertEqual(game["phase"], "lobby")
            self.assertFalse(game["cards"])
            self.assertTrue(all(not seat["cards"] for seat in game["seats"]))
        apply_command(game, actors[-1], "lobby.ready", {})
        self.assertEqual(game["phase"], "ordering")
        self.assertEqual(game["status"], "lobby")
        self.assertFalse(any(seat["ready"] for seat in game["seats"]))
        self.assertEqual(len(game["cards"]), 14)
        self.assertFalse(game["snapshots"])
        with self.assertRaises(GameError):
            apply_command(game, HOST, "host.start", {})
        public_before = game_view(game, observer)["seats"]
        for actor in actors[:2]:
            own = game_view(game, actor)["self"]
            apply_command(game, actor, "lobby.order", {"top": own["cards"][1]["id"]})
        self.assertEqual(game_view(game, observer)["seats"], public_before)
        for actor in [HOST, *actors, observer]:
            self.assertTrue(
                all(seat["avatar_role_id"] is None for seat in game_view(game, actor)["seats"])
            )
        self.assertEqual(game_view(game, actors[0])["seats"][0]["name"], "甲")
        self.assertEqual(len(game_view(game, actors[0])["self"]["cards"]), 2)
        self.assertTrue(all(len(seat["cards"]) == 2 for seat in game_view(game, HOST)["seats"]))
        for actor in actors[:-1]:
            apply_command(game, actor, "lobby.ready", {})
        with self.assertRaises(GameError):
            apply_command(game, HOST, "host.start", {})
        apply_command(game, actors[-1], "lobby.ready", {})
        own = game_view(game, actors[1])["self"]
        apply_command(game, actors[1], "lobby.order", {"top": own["cards"][1]["id"]})
        self.assertFalse(game["seats"][1]["ready"])
        with self.assertRaises(GameError):
            apply_command(game, HOST, "host.start", {})
        pairs = [list(seat["cards"]) for seat in game["seats"]]
        apply_command(game, actors[1], "lobby.ready", {})
        self.assertEqual([seat["cards"] for seat in game["seats"]], pairs)
        self.assertEqual(game["phase"], "ordering")
        self.assertTrue(
            all(seat["avatar_role_id"] is None for seat in game_view(game, observer)["seats"])
        )
        apply_command(game, HOST, "host.start", {})
        self.assertEqual((game["status"], game["phase"]), ("playing", "witch"))
        self.assertEqual(
            [seat["avatar_role_id"] for seat in game_view(game, observer)["seats"]],
            ["emma", *[game["cards"][pair[0]]["role_id"] for pair in pairs[1:]]],
        )
        with self.assertRaises(GameError):
            apply_command(game, actors[0], "lobby.order", {"top": pairs[0][1]})
        with self.assertRaises(GameError):
            apply_command(game, actors[0], "lobby.ready", {})

    def test_duplicate_codex_entry_is_rejected_even_with_eleven_entries(self):
        codex = list(DEFAULT_CODEX)
        codex[-1] = codex[0]
        with self.assertRaises(GameError):
            create_game(codex)


if __name__ == "__main__":
    unittest.main()
