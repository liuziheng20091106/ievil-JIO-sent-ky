"""Observable edge cases for simultaneous resolution and host adjudication."""

from copy import deepcopy
import unittest

from backend.app.game import DEFAULT_CODEX, GameError, apply_command, create_game, game_view
from backend.app.game.resolution import begin_night, damage_preview, death_batch, revive
from backend.app.game.state import check_winner, pending, rewind, save_snapshot

HOST = {"id": "host", "kind": "host", "seat_id": None, "access_ids": ["host"]}
PAIRS = [
    ["millia", "emma"],
    ["hiro", "coco"],
    ["meruru", "hanna"],
    ["marg", "sherry"],
    ["leia", "arisa"],
    ["noah", "annan"],
    ["nanoka", "honoka"],
]


def arranged_game(phase="discussion", half="day"):
    game = create_game(DEFAULT_CODEX)
    game.update(status="playing", phase=phase, half=half, day=2)
    for seat, pair in zip(game["seats"], PAIRS):
        seat.update(cards=list(pair), occupant_id="p" + seat["id"], ready=True)
    return game


def player(game, sid):
    return {
        "id": "p" + sid,
        "kind": "player",
        "seat_id": sid,
        "game_id": game["id"],
        "access_ids": ["p" + sid],
    }


def command(game, actor, action, payload=None):
    changed = deepcopy(game)
    events = apply_command(changed, actor, action, payload or {})
    game.clear()
    game.update(changed)
    return events


class ResolutionEdges(unittest.TestCase):
    def test_marg_must_attack_her_target_unless_gaze_disallows_it(self):
        game = arranged_game("night", "night")
        game["cards"]["marg"]["witch"] = True
        game["cards"]["marg"]["states"]["madness_target"] = "hiro"
        begin_night(game, [])
        actor = player(game, "4")
        with self.assertRaises(GameError):
            command(game, actor, "night.confirm")
        game["gaze"] = {"cards": ["leia", "meruru"], "night_day": 2}
        command(game, actor, "night.submit", {"ability": "knife", "target": "5"})
        command(game, actor, "night.confirm")
        self.assertTrue(game_view(game, actor)["self"]["night_confirmed"])

    def test_night_victory_cannot_turn_into_day_victory_on_advance(self):
        game = arranged_game("night_results", "night")
        for cid in ("millia", "arisa", "noah"):
            game["cards"][cid]["alive"] = False
        game["cards"]["noah"]["witch"] = True
        game["generated_witches"] = ["noah"]
        check_winner(game)
        with self.assertRaises(GameError):
            command(game, HOST, "host.advance")
        command(game, HOST, "host.confirm_winner", {"confirm": True})
        self.assertEqual(game_view(game, HOST)["result"]["winner"], "witch")

    def test_host_supplied_killer_must_appear_in_witness_list(self):
        game = arranged_game("night_results", "night")
        item = pending(game, "suspects", "目击裁定", seat_id="1", victim="millia", source_card=None)
        data = {
            "pending_id": item["id"],
            "true_source": "nanoka",
            "suspects": ["hanna", "emma", "noah"],
            "omit_leia": False,
        }
        with self.assertRaises(GameError):
            command(game, HOST, "host.resolve", data)
        data["suspects"] = ["hanna", "emma", "nanoka"]
        command(game, HOST, "host.resolve", data)
        self.assertTrue(game_view(game, player(game, "1"))["information"])
        self.assertFalse(game_view(game, player(game, "2"))["information"])

    def test_millia_can_react_to_daytime_damage_after_night_selection(self):
        game = arranged_game()
        game["night"]["actions"] = [
            {
                "ability": "swap",
                "card_id": "millia",
                "seat_id": "1",
                "target_seat": "3",
                "effective": True,
            }
        ]
        command(
            game,
            HOST,
            "host.damage",
            {"targets": ["millia"], "effect": "death", "source": "coco", "reason": "测试临死结算"},
        )
        self.assertEqual(game_view(game, player(game, "1"))["self"]["current_card_id"], "millia")
        item = next(item for item in game["pending"] if item["kind"] == "millia")
        command(game, HOST, "host.resolve", {"pending_id": item["id"], "follow": "seat"})
        self.assertEqual(game_view(game, player(game, "3"))["self"]["current_card_id"], "millia")
        self.assertFalse(game["cards"]["meruru"]["alive"])
        self.assertTrue(game["cards"]["millia"]["alive"])

    def test_protection_and_half_day_limit_prevent_extra_card_exit(self):
        game = arranged_game()
        attack = {"target_card": "millia", "source_card": "coco", "cause": "knife"}
        preview = damage_preview(game, [attack], ["millia"])
        self.assertFalse(preview["deaths"])
        self.assertTrue(preview["injured"]["millia"])
        death_batch(game, [], preview)
        death_batch(game, [], damage_preview(game, [attack], ["millia"]))
        self.assertFalse(game["cards"]["millia"]["alive"])
        second = damage_preview(game, [{**attack, "target_card": "emma"}])
        self.assertFalse(second["deaths"])
        self.assertTrue(game["cards"]["emma"]["alive"])

    def test_rewind_restores_skills_but_not_identity_or_spiritual_effects(self):
        game = arranged_game()
        snap = save_snapshot(game)
        game["cards"]["nanoka"]["uses"]["bullets"] = 1
        game["seats"][0]["occupant_id"] = "substitute"
        game["spiritual"]["sherry_bound"] = True
        game["spiritual"]["annan_penalty"]["annan"] = 3
        game["cards"]["hiro"]["witch"] = True
        game["information"].append(
            {"id": "memory", "title": "线索", "text": "保留记忆", "audience": ["p1"]}
        )
        rewind(game, snap["id"], [], mode="witch")
        self.assertEqual(game["cards"]["nanoka"]["uses"]["bullets"], 6)
        self.assertEqual(game["seats"][0]["occupant_id"], "substitute")
        self.assertTrue(game["spiritual"]["sherry_bound"])
        self.assertEqual(game["spiritual"]["annan_penalty"]["annan"], 3)
        self.assertTrue(game["cards"]["hiro"]["witch"])
        self.assertTrue(game["spiritual"]["hiro_used"]["witch"])
        self.assertTrue(any(item["id"] == "memory" for item in game["information"]))
        with self.assertRaises(GameError):
            rewind(game, snap["id"], [], mode="witch")

    def test_death_and_revival_interrupt_first_complete_day_for_binding(self):
        game = arranged_game("dusk")
        game["seats"][2]["cards"] = ["hanna", "meruru"]
        game["seats"][3]["cards"] = ["sherry", "marg"]
        game["day_binding"] = {"day": 2, "intact": True}
        death_batch(game, [], damage_preview(game, [{"target_card": "hanna", "cause": "host"}]))
        revive(game, [], "hanna")
        game["pending"] = []
        command(game, HOST, "host.advance")
        self.assertFalse(game["spiritual"]["sherry_bound"])

    def test_nomination_waits_for_each_player_and_allows_passing(self):
        game = arranged_game("nomination")
        with self.assertRaises(GameError):
            command(game, player(game, "2"), "vote.nominate", {"target": "3"})
        command(game, player(game, "1"), "vote.pass")
        command(game, player(game, "2"), "vote.nominate", {"target": "3"})
        with self.assertRaises(GameError):
            command(game, HOST, "host.advance")
        for sid in ("3", "4", "5", "6", "7"):
            command(game, player(game, sid), "vote.pass")
        command(game, HOST, "host.advance")
        self.assertEqual(game_view(game, player(game, "1"))["public"]["votes"]["candidate"], "3")

    def test_lower_card_waits_for_host_and_denial_expires_next_phase(self):
        game = arranged_game()
        game["cards"]["nanoka"]["alive"] = False
        item = pending(game, "lower_entry", "下层登场", seat_id="7", card_id="honoka")
        actor = player(game, "7")
        with self.assertRaises(GameError):
            command(game, actor, "honoka.disguise", {"role": "emma"})
        command(game, HOST, "host.resolve", {"pending_id": item["id"], "allow": False})
        with self.assertRaises(GameError):
            command(game, actor, "honoka.disguise", {"role": "emma"})
        command(game, HOST, "host.advance")
        command(game, actor, "honoka.disguise", {"role": "emma"})
        self.assertEqual(game_view(game, actor)["seats"][6]["avatar_role_id"], "emma")


if __name__ == "__main__":
    unittest.main()
