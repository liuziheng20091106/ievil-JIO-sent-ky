"""Observable edge cases for simultaneous resolution and host adjudication."""

from copy import deepcopy
from time import time
import unittest

from backend.app.game import (
    DEFAULT_CODEX,
    GameError,
    apply_command,
    create_game,
    game_view,
    run_auto_advance,
)
from backend.app.game.actions import actions_for
from backend.app.game.resolution import begin_night, damage_preview, death_batch, revive
from backend.app.game.state import check_winner, pending, pending_nominators, rewind, save_snapshot

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
    for seat in game["seats"]:
        seat["occupant_id"] = "p" + seat["id"]
    for seat in game["seats"]:
        apply_command(game, player(game, seat["id"]), "lobby.ready", {})
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

    def test_players_nominate_at_the_same_time_and_the_phase_waits_for_all(self):
        game = arranged_game("nomination")
        self.assertIn("vote.nominate", [item["id"] for item in actions_for(game, player(game, "2"))])
        command(game, player(game, "2"), "vote.nominate", {"target": "3"})
        command(game, player(game, "4"), "vote.nominate", {"target": "3"})
        command(game, player(game, "1"), "vote.pass")
        self.assertNotIn("vote.nominate", [item["id"] for item in actions_for(game, player(game, "4"))])
        with self.assertRaises(GameError):
            command(game, HOST, "host.advance")
        for sid in ("3", "5", "6", "7"):
            command(game, player(game, sid), "vote.pass")
        command(game, HOST, "host.advance")
        self.assertEqual(game_view(game, player(game, "1"))["public"]["votes"]["candidate"], "3")
        self.assertEqual(game_view(game, player(game, "1"))["public"]["votes"]["total"], 1)

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
        self.assertTrue(any("示人" in item["text"] for item in game_view(game, HOST)["information"]))
        for viewer in (player(game, "1"), player(game, "7")):
            self.assertFalse(
                any("示人" in item["text"] for item in game_view(game, viewer)["information"])
            )


class PlaytestFixes(unittest.TestCase):
    def test_skill_less_seats_confirm_themselves_and_coco_still_acts_last(self):
        game = arranged_game("night", "night")
        layout = {
            "1": ["emma", "hiro"],
            "2": ["coco", "sherry"],
            "3": ["hanna", "meruru"],
            "4": ["annan", "noah"],
            "5": ["leia", "marg"],
            "6": ["nanoka", "millia"],
            "7": ["arisa", "honoka"],
        }
        for seat in game["seats"]:
            seat["cards"] = list(layout[seat["id"]])
        game["cards"]["coco"]["witch"] = True
        game["cards"]["nanoka"]["uses"]["bullets"] = 0
        begin_night(game, [])
        self.assertEqual(game["phase"], "night_coco")
        self.assertEqual(sorted(game["night"]["confirmed"]), ["1", "3", "4", "5", "6", "7"])
        coco = player(game, "2")
        self.assertIn("night.submit", [a["id"] for a in game_view(game, coco)["actions"]])
        command(game, coco, "night.confirm")
        command(game, HOST, "host.advance")
        self.assertEqual(game["phase"], "night_review")

    def test_evidence_waits_for_the_last_card_of_a_seat(self):
        game = arranged_game("night_results", "night")
        command(
            game,
            HOST,
            "host.damage",
            {"targets": ["meruru"], "effect": "unconditional", "reason": "回归：上层牌出局"},
        )
        self.assertFalse(game["cards"]["meruru"]["alive"])
        item = next(p for p in game["pending"] if p["kind"] == "suspects")
        command(
            game,
            HOST,
            "host.resolve",
            {
                "pending_id": item["id"],
                "true_source": "hanna",
                "suspects": ["hanna", "emma", "noah"],
                "omit_leia": False,
            },
        )
        seat_view = game_view(game, player(game, "3"))
        self.assertTrue(any("三名疑似凶手" in i["text"] for i in seat_view["information"]))
        self.assertFalse(game["cards"]["meruru"]["states"].get("evidence_allowed"))
        self.assertNotIn("evidence.submit", [a["id"] for a in seat_view["actions"]])
        game["day"] += 1
        command(
            game,
            HOST,
            "host.damage",
            {"targets": ["hanna"], "effect": "unconditional", "reason": "回归：下层牌出局"},
        )
        item = next(p for p in game["pending"] if p["kind"] == "suspects")
        command(
            game,
            HOST,
            "host.resolve",
            {
                "pending_id": item["id"],
                "true_source": "hanna",
                "suspects": ["hanna", "emma", "noah"],
                "omit_leia": False,
            },
        )
        self.assertTrue(game["cards"]["hanna"]["states"]["evidence_allowed"])
        self.assertIn("evidence.submit", [a["id"] for a in game_view(game, player(game, "3"))["actions"]])

    def test_challenge_settles_on_the_spot_instead_of_waiting_for_the_host(self):
        game = arranged_game("discussion")
        game["seats"][6]["cards"] = ["honoka", "nanoka"]
        honoka = player(game, "7")
        command(game, honoka, "day.skill", {"ability": "interrupt", "target": "1"})
        declaration = game["declarations"][0]
        self.assertTrue(declaration["fake"])
        command(game, player(game, "1"), "day.challenge", {"declaration_id": declaration["id"]})
        self.assertFalse(any(p["kind"] == "challenge" for p in game["pending"]))
        self.assertFalse(any(p.get("declaration_id") == declaration["id"] for p in game["pending"]))
        self.assertEqual(game["declarations"][0]["status"], "stopped")
        self.assertTrue(game["cards"]["millia"]["alive"])

    def test_failed_challenge_still_eliminates_the_challenger(self):
        game = arranged_game("discussion")
        game["seats"][0]["cards"] = ["emma", "millia"]
        command(game, player(game, "1"), "day.skill", {"ability": "interrupt", "target": "2"})
        declaration = game["declarations"][0]
        self.assertFalse(declaration["fake"])
        self.assertIn(
            "day.challenge", [a["id"] for a in actions_for(game, player(game, "3"))]
        )
        command(game, player(game, "3"), "day.challenge", {"declaration_id": declaration["id"]})
        self.assertFalse(game["cards"]["meruru"]["alive"])
        self.assertIn("p3", game["spiritual"]["personal_losses"])
        self.assertEqual(game["declarations"][0]["status"], "open")
        self.assertNotIn(
            "day.challenge", [a["id"] for a in actions_for(game, player(game, "3"))]
        )
        with self.assertRaises(GameError):
            command(game, player(game, "3"), "day.challenge", {"declaration_id": declaration["id"]})
        self.assertIn(
            "day.challenge", [a["id"] for a in actions_for(game, player(game, "4"))]
        )

    def test_must_notice_events_are_marked_as_alerts_only_when_needed(self):
        game = arranged_game("discussion")
        game["seats"][0]["cards"] = ["emma", "millia"]
        events = command(
            game, player(game, "1"), "day.skill", {"ability": "interrupt", "target": "2"}
        )
        self.assertEqual([event["kind"] for event in events], ["alert"])
        declaration = game["declarations"][0]
        events = command(
            game, player(game, "3"), "day.challenge", {"declaration_id": declaration["id"]}
        )
        self.assertTrue(
            any(
                event["kind"] == "alert" and "质疑失败" in event["text"]
                for event in events
            )
        )
        events = command(game, HOST, "host.speech", {"start": "1", "direction": "asc"})
        self.assertEqual(
            [event["kind"] for event in events if "发言顺序" in event["text"]],
            ["notice"],
        )

    def test_honoka_lobby_disguise_applies_only_from_the_top_card(self):
        game = arranged_game()
        game.update(status="lobby", phase="ordering", day=1, half="night")
        game["seats"][6]["cards"] = ["honoka", "nanoka"]
        for seat in game["seats"]:
            seat["ready"] = True
        command(game, player(game, "7"), "honoka.disguise", {"role": "emma"})
        self.assertEqual(game["cards"]["honoka"]["states"]["disguise"], "emma")
        command(game, HOST, "host.start")
        self.assertEqual(
            game_view(game, player(game, "1"))["seats"][6]["avatar_role_id"], "emma"
        )
        self.assertTrue(game["cards"]["honoka"]["states"]["disguise_locked"])
        with self.assertRaises(GameError):
            command(game, player(game, "7"), "honoka.disguise", {"role": "noah"})

    def test_honoka_bottom_disguise_is_dropped_and_redecided_on_entry(self):
        game = arranged_game()
        game.update(status="lobby", phase="ordering", day=1, half="night")
        game["seats"][6]["cards"] = ["nanoka", "honoka"]
        for seat in game["seats"]:
            seat["ready"] = True
        command(game, player(game, "7"), "honoka.disguise", {"role": "emma"})
        command(game, HOST, "host.start")
        self.assertEqual(
            game_view(game, player(game, "1"))["seats"][6]["avatar_role_id"], "nanoka"
        )
        self.assertNotIn("disguise", game["cards"]["honoka"]["states"])
        death_batch(
            game,
            [],
            damage_preview(
                game, [{"target_card": "nanoka", "cause": "host", "unconditional": True}]
            ),
        )
        self.assertEqual(
            game_view(game, player(game, "7"))["seats"][6]["avatar_role_id"], "honoka"
        )
        item = next(p for p in game["pending"] if p["kind"] == "lower_entry")
        command(game, HOST, "host.resolve", {"pending_id": item["id"], "allow": True})
        command(game, player(game, "7"), "honoka.disguise", {"role": "noah"})
        self.assertEqual(
            game_view(game, player(game, "1"))["seats"][6]["avatar_role_id"], "noah"
        )
        with self.assertRaises(GameError):
            command(game, player(game, "7"), "honoka.disguise", {"role": "emma"})

    def test_honoka_alone_sees_ready_upper_roles_during_ordering(self):
        game = arranged_game()
        game.update(status="lobby", phase="ordering", day=1, half="night")
        game["seats"][6]["cards"] = ["honoka", "nanoka"]
        for seat in game["seats"]:
            seat["ready"] = False
        game["seats"][0]["ready"] = True
        game["seats"][1]["ready"] = True
        honoka = game_view(game, player(game, "7"))["self"]["honoka_upper"]
        self.assertEqual(
            {item["seat_id"]: item["role_id"] for item in honoka},
            {"1": "millia", "2": "hiro"},
        )
        stranger = game_view(game, player(game, "1"))["self"]
        self.assertNotIn("honoka_upper", stranger)
        self.assertEqual(game_view(game, player(game, "1"))["ready_count"], 2)


class SpeechOrder(unittest.TestCase):
    def test_speech_start_and_direction_build_the_two_documented_orders(self):
        game = arranged_game("speech")
        command(game, HOST, "host.speech", {"start": "4", "direction": "asc"})
        self.assertEqual(game["public"]["speech_order"], ["4", "5", "6", "7", "1", "2", "3"])
        self.assertEqual(game["public"]["speaker"], "4")
        command(game, HOST, "host.speech", {"start": "4", "direction": "desc"})
        self.assertEqual(game["public"]["speech_order"], ["4", "3", "2", "1", "7", "6", "5"])
        self.assertEqual(game["public"]["speaker"], "4")
        default = next(
            item
            for item in game_view(game, HOST)["actions"]
            if item["id"] == "host.speech"
        )
        self.assertEqual(default["fields"][0]["default"], "1")


class AutoAdvance(unittest.TestCase):
    """玩家行动完的阶段由系统倒计时推进；自由发言这类仍等主持人。"""

    def finished_speech(self):
        game = arranged_game("speech")
        command(game, HOST, "host.speech", {"start": "1", "direction": "asc"})
        for sid in list(game["public"]["speech_order"]):
            command(game, player(game, sid), "speech.done", {})
        return game

    def test_speech_advances_itself_five_seconds_after_the_last_speaker(self):
        game = self.finished_speech()
        self.assertIsNone(game["public"]["speaker"])
        deadline = game["public"]["auto_advance_at"]
        self.assertIsNotNone(deadline)
        run_auto_advance(game, deadline - 1)
        self.assertEqual(game["phase"], "speech")
        run_auto_advance(game, deadline + 1)
        self.assertEqual(game["phase"], "discussion")
        self.assertNotIn("auto_advance_at", game["public"])

    def test_the_host_can_pause_and_restore_the_countdown(self):
        game = self.finished_speech()
        command(game, HOST, "host.auto", {})
        self.assertTrue(game["public"]["auto_advance_off"])
        self.assertNotIn("auto_advance_at", game["public"])
        run_auto_advance(game, time() + 60)
        self.assertEqual(game["phase"], "speech")
        command(game, HOST, "host.auto", {})
        self.assertFalse(game["public"]["auto_advance_off"])
        self.assertIsNotNone(game["public"]["auto_advance_at"])

    def test_pending_rulings_and_free_discussion_never_advance_themselves(self):
        game = self.finished_speech()
        deadline = game["public"]["auto_advance_at"]
        pending(game, "reaction", "夜前互动裁定", seat_id="1")
        run_auto_advance(game, deadline + 1)
        self.assertEqual(game["phase"], "speech")
        self.assertNotIn("auto_advance_at", game["public"])
        discussion = arranged_game("discussion")
        command(discussion, HOST, "host.water", {"seat_id": "1"})
        self.assertNotIn("auto_advance_at", discussion["public"])
        self.assertNotIn("host.auto", [item["id"] for item in actions_for(discussion, HOST)])


class NominationFlow(unittest.TestCase):
    """提名可提前提交、重复提名不失败、提名人自动投同意票。"""

    def test_pre_nominations_confirm_themselves_when_the_phase_opens(self):
        game = arranged_game("discussion")
        command(game, player(game, "1"), "vote.nominate", {"target": "3"})
        command(game, HOST, "host.advance", {})
        command(game, HOST, "host.advance", {})
        self.assertEqual(game["phase"], "nomination")
        self.assertEqual(game["nominations"][0]["by"], "1")
        self.assertNotIn("1", pending_nominators(game))

    def test_two_players_nominating_the_same_person_share_one_vote_round(self):
        game = arranged_game("nomination")
        command(game, player(game, "1"), "vote.nominate", {"target": "3"})
        command(game, player(game, "2"), "vote.nominate", {"target": "3"})
        for sid in ["3", "4", "5", "6", "7"]:
            command(game, player(game, sid), "vote.pass", {})
        command(game, HOST, "host.advance", {})
        self.assertEqual(game["phase"], "voting")
        self.assertEqual(game["public"]["votes"]["candidate"], "3")
        self.assertEqual(game["public"]["votes"]["total"], 1)
        self.assertEqual(game["votes"], {"1": "yes", "2": "yes"})
        for sid in ["3", "4", "5", "6", "7"]:
            command(game, player(game, sid), "vote.cast", {"choice": "no"})
        command(game, HOST, "host.advance", {})
        self.assertEqual(len(game["vote_rounds"]), 1)
        self.assertEqual(game["phase"], "execution")

    def test_nomination_is_offered_all_day_but_not_at_night(self):
        day = arranged_game("speech")
        actions = actions_for(day, player(day, "1"))
        nomination = next(item for item in actions if item["id"] == "vote.nominate")
        self.assertTrue(nomination["instant"])
        self.assertFalse(nomination.get("blocking"))
        night = arranged_game("night", "night")
        self.assertNotIn("vote.nominate", [item["id"] for item in actions_for(night, player(night, "1"))])

    def test_nominating_early_does_not_clear_the_phases_warning(self):
        game = arranged_game("speech")
        game["public"]["speaker"] = "1"
        command(game, HOST, "host.warn", {"seat_id": "1"})
        command(game, player(game, "1"), "vote.nominate", {"target": "3"})
        self.assertIn("1", game["warnings"])
        command(game, player(game, "1"), "speech.done", {})
        self.assertNotIn("1", game["warnings"])


class HostTodo(unittest.TestCase):
    """「完成当前阶段 / 推进」始终在主持人待办里，并标出现在是否可以推进。"""

    def test_the_host_todo_lists_the_phase_advance_with_its_readiness(self):
        game = arranged_game("speech")
        game["public"]["speaker"] = "2"
        waiting = next(
            item for item in game_view(game, HOST)["host"]["tasks"] if item["id"] == "advance"
        )
        self.assertEqual(waiting["action"], "host.advance")
        self.assertFalse(waiting["blocking"])
        game["public"]["speaker"] = None
        ready = next(
            item for item in game_view(game, HOST)["host"]["tasks"] if item["id"] == "advance"
        )
        self.assertTrue(ready["blocking"])
        self.assertEqual(ready["detail"], "顺序发言：现在可以推进")

    def test_a_pending_ruling_marks_the_advance_as_not_ready(self):
        game = arranged_game("discussion")
        pending(game, "reaction", "夜前互动裁定", seat_id="1")
        advance = next(
            item for item in game_view(game, HOST)["host"]["tasks"] if item["id"] == "advance"
        )
        self.assertFalse(advance["blocking"])


if __name__ == "__main__":
    unittest.main()
