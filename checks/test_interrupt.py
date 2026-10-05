"""Observable regressions for the shared Emma interruption declaration."""

from copy import deepcopy
import unittest

from backend.app.game import GameError, game_view
from checks.rule_factory import arranged_game, player
from checks.test_resolution import command


HOST = {"id": "host", "kind": "host", "seat_id": None, "access_ids": ["host"]}


def speech_game():
    game = arranged_game("speech")
    command(game, HOST, "host.speech", {"start": "2", "direction": "asc"})
    return game


def interrupt_actions(game, sid):
    return [
        action
        for action in game_view(game, player(game, sid))["actions"]
        if action["id"] == "day.skill" and action["payload"].get("ability") == "interrupt"
    ]


def interrupt(game, sid):
    command(
        game,
        player(game, sid),
        "day.skill",
        {"ability": "interrupt", "target": game["public"]["speaker"]},
    )
    return game["declarations"][-1]["id"]


def next_day(game):
    game.update(day=game["day"] + 1, half="night", phase="night_results")
    command(game, HOST, "host.advance")
    command(game, HOST, "host.speech", {"start": "2", "direction": "asc"})


class InterruptChecks(unittest.TestCase):
    def assert_speaker(self, game, sid):
        self.assertEqual(game_view(game, player(game, "5"))["public"]["speaker"], sid)

    def assert_rejected_interrupt(self, game, sid):
        self.assertEqual(interrupt_actions(game, sid), [])
        before = deepcopy(game)
        with self.assertRaises(GameError):
            interrupt(game, sid)
        self.assertEqual(game, before)

    def test_non_emma_takes_the_floor_and_debunking_restores_it_permanently(self):
        game = speech_game()
        self.assertEqual(len(interrupt_actions(game, "3")), 1)
        declaration_id = interrupt(game, "3")
        self.assert_speaker(game, "3")
        self.assertTrue(game["declarations"][-1]["fake"])
        self.assertIn(
            declaration_id,
            [
                action["payload"]["declaration_id"]
                for action in game_view(game, player(game, "4"))["actions"]
                if action["id"] == "day.challenge"
            ],
        )
        # 同席持有艾玛，即使她在下层，也不能质疑其他艾玛声明。
        self.assertFalse(
            any(
                action["id"] == "day.challenge"
                for action in game_view(game, player(game, "1"))["actions"]
            )
        )
        with self.assertRaises(GameError):
            command(game, player(game, "1"), "day.challenge", {"declaration_id": declaration_id})
        command(game, player(game, "4"), "day.challenge", {"declaration_id": declaration_id})
        self.assert_speaker(game, "2")
        self.assertEqual(game["declarations"][-1]["status"], "stopped")
        self.assert_rejected_interrupt(game, "3")
        next_day(game)
        self.assert_rejected_interrupt(game, "3")

    def test_emma_ownership_is_real_in_either_layer_even_after_emma_dies(self):
        for pair, emma_alive in (
            (["emma", "millia"], True),
            (["millia", "emma"], True),
            (["emma", "millia"], False),
        ):
            with self.subTest(pair=pair, emma_alive=emma_alive):
                game = speech_game()
                game["seats"][0]["cards"] = pair
                game["cards"]["emma"]["alive"] = emma_alive
                action = interrupt_actions(game, "1")
                self.assertEqual(len(action), 1)
                self.assertNotIn("card_id", action[0]["payload"])
                declaration_id = interrupt(game, "1")
                self.assertFalse(game["declarations"][-1]["fake"])
                self.assert_speaker(game, "1")
                command(
                    game,
                    player(game, "4"),
                    "day.challenge",
                    {"declaration_id": declaration_id},
                )
                self.assert_speaker(game, "1")
                self.assertEqual(game["declarations"][-1]["status"], "open")
                challenger = game_view(game, player(game, "4"))
                self.assertIsNone(challenger["self"]["current_card_id"])
                self.assertFalse(
                    next(seat for seat in challenger["seats"] if seat["id"] == "4")["alive"]
                )
                self.assertIn("p4", game["spiritual"]["personal_losses"])
                self.assertFalse(
                    any(action["id"] == "day.challenge" for action in challenger["actions"])
                )
                command(game, player(game, "1"), "speech.done")
                self.assert_speaker(game, "2")

    def test_daily_limit_belongs_to_the_seat_and_resets_next_day(self):
        game = speech_game()
        interrupt(game, "3")
        command(game, player(game, "3"), "speech.done")
        self.assert_speaker(game, "2")
        self.assert_rejected_interrupt(game, "3")
        # 上层出局、下层登场不能刷新同席的当天次数。
        game["cards"]["meruru"]["alive"] = False
        self.assertEqual(game_view(game, player(game, "3"))["self"]["current_card_id"], "hanna")
        self.assert_rejected_interrupt(game, "3")
        next_day(game)
        self.assertEqual(len(interrupt_actions(game, "3")), 1)
        interrupt(game, "3")
        self.assert_speaker(game, "3")

    def test_nested_interruptions_resume_each_previous_speaker(self):
        game = speech_game()
        interrupt(game, "3")
        self.assert_speaker(game, "3")
        interrupt(game, "4")
        self.assert_speaker(game, "4")
        command(game, player(game, "4"), "speech.done")
        self.assert_speaker(game, "3")
        command(game, player(game, "3"), "speech.done")
        self.assert_speaker(game, "2")

    def test_debunking_middle_interruption_preserves_later_real_interruption(self):
        game = speech_game()
        # 4号持有艾玛，让后一次打断是真技能。
        game["seats"][0]["cards"], game["seats"][3]["cards"] = (
            game["seats"][3]["cards"],
            game["seats"][0]["cards"],
        )
        middle_id = interrupt(game, "3")
        last_id = interrupt(game, "4")
        self.assertFalse(game["declarations"][-1]["fake"])
        interrupt(game, "5")
        command(game, player(game, "6"), "day.challenge", {"declaration_id": middle_id})
        self.assert_speaker(game, "5")
        statuses = {
            declaration["id"]: declaration["status"] for declaration in game["declarations"]
        }
        self.assertEqual(statuses[middle_id], "stopped")
        self.assertEqual(statuses[last_id], "open")
        self.assert_rejected_interrupt(game, "3")
        command(game, player(game, "5"), "speech.done")
        self.assert_speaker(game, "4")
        command(game, player(game, "4"), "speech.done")
        self.assert_speaker(game, "2")

    def test_challenge_does_not_restore_interruptions_after_host_reorders_speech(self):
        game = speech_game()
        earlier = interrupt(game, "3")
        interrupt(game, "4")
        command(game, HOST, "host.speech", {"start": "4", "direction": "asc"})
        command(game, player(game, "5"), "day.challenge", {"declaration_id": earlier})
        self.assert_speaker(game, "4")
        command(game, player(game, "4"), "speech.done")
        self.assert_speaker(game, "5")

    def test_no_ability_does_not_remove_shared_interrupt(self):
        for sid, card_id, fake in (("3", "meruru", True), ("1", "millia", False)):
            with self.subTest(sid=sid):
                game = speech_game()
                game["cards"][card_id]["states"]["no_ability"] = True
                self.assertEqual(len(interrupt_actions(game, sid)), 1)
                interrupt(game, sid)
                self.assert_speaker(game, sid)
                self.assertEqual(game["declarations"][-1]["fake"], fake)

    def test_night_and_eliminated_seats_have_no_interrupt(self):
        for night in (False, True):
            with self.subTest(night=night):
                game = speech_game()
                if night:
                    game.update(phase="night", half="night")
                else:
                    for card_id in game["seats"][2]["cards"]:
                        game["cards"][card_id]["alive"] = False
                self.assert_rejected_interrupt(game, "3")

    def test_actions_and_public_declarations_do_not_reveal_truth(self):
        fake_game = speech_game()
        real_game = deepcopy(fake_game)
        real_game["seats"][0]["cards"], real_game["seats"][2]["cards"] = (
            real_game["seats"][2]["cards"],
            real_game["seats"][0]["cards"],
        )
        self.assertEqual(len(interrupt_actions(fake_game, "3")), 1)
        projections = []
        for game in (fake_game, real_game):
            declaration_id = interrupt(game, "3")
            observer = game_view(game, player(game, "5"))
            declarations = deepcopy(observer["public"]["declarations"])
            for declaration in declarations:
                self.assertNotIn("fake", declaration)
                declaration["id"] = "claim"
            challenges = [
                deepcopy(action)
                for action in observer["actions"]
                if action["id"] == "day.challenge"
                and action["payload"]["declaration_id"] == declaration_id
            ]
            self.assertEqual(len(challenges), 1)
            challenges[0]["payload"]["declaration_id"] = "claim"
            projections.append((declarations, challenges))
        self.assertTrue(fake_game["declarations"][-1]["fake"])
        self.assertFalse(real_game["declarations"][-1]["fake"])
        self.assertEqual(projections[0], projections[1])


if __name__ == "__main__":
    unittest.main()
