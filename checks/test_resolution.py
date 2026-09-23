"""Observable edge cases for simultaneous resolution and host adjudication."""

from copy import deepcopy
from time import time
import unittest
from unittest.mock import patch

from backend.app.game import (
    DEFAULT_CODEX,
    GameError,
    apply_command,
    create_game,
    game_view,
    run_auto_advance,
)
from backend.app.game.actions import actions_for, challengeable, outstanding_seats
from backend.app.game.resolution import (
    begin_night,
    damage_preview,
    day_damage_preview,
    death_batch,
    lock_night,
    night_damage,
    prepare_night_preview,
    unlock_coco,
    revive,
    treasure_protected,
)
from backend.app.game.state import (
    check_winner,
    effect_effective,
    eligible_voters,
    owner,
    pending,
    pending_nominators,
    poison_sources,
    rewind,
    save_snapshot,
)
from backend.app.game.views import host_tasks

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


class PoisonAndDeclarations(unittest.TestCase):
    def test_dynamic_poison_sources_and_each_effect_roll_independently(self):
        game = arranged_game()
        self.assertIn("艾玛毒素", poison_sources(game, game["cards"]["millia"]))
        self.assertIn("艾玛毒素", poison_sources(game, game["cards"]["hiro"]))
        self.assertIn("艾玛毒素", poison_sources(game, game["cards"]["nanoka"]))
        # 安安与诺亚同席：诺亚不是该席下层牌，因此不算来源。
        self.assertNotIn("诺亚邻接", poison_sources(game, game["cards"]["annan"]))
        game["seats"][5]["cards"] = ["annan", "noah"]
        self.assertIn("诺亚邻接", poison_sources(game, game["cards"]["annan"]))
        with patch("backend.app.game.state.SystemRandom") as random:
            random.return_value.randrange.side_effect = [0, 1]
            events = []
            self.assertTrue(effect_effective(game, events, game["cards"]["millia"], "测试技能"))
            self.assertFalse(effect_effective(game, events, game["cards"]["millia"], "测试技能"))
        self.assertEqual([entry["kind"] for entry in game["log"][-2:]], ["poison", "poison"])

    def test_status_projection_hides_poison_source_and_host_secrets(self):
        game = arranged_game()
        game["cards"]["noah"]["states"]["display_killer"] = "coco"
        player_view = game_view(game, player(game, "1"))
        self.assertEqual(player_view["self"]["statuses"][0]["id"], "poison")
        self.assertNotIn("艾玛", player_view["self"]["statuses"][0]["text"])
        host_view = game_view(game, HOST)
        self.assertIn("millia", host_view["host"]["poison_sources"])
        spectator = game_view(
            game,
            {"id": "watcher", "kind": "spectator", "game_id": game["id"], "access_ids": []},
        )
        self.assertNotIn("host", spectator)
        noah = next(
            card
            for seat_view in spectator["seats"]
            for card in seat_view["cards"]
            if card["id"] == "noah"
        )
        self.assertNotIn("display_killer", noah["states"])

    def test_real_photo_creates_plain_token_but_fake_photo_does_not(self):
        game = arranged_game()
        game["cards"]["hiro"]["alive"] = False
        game["cards"]["emma"]["alive"] = False
        command(game, player(game, "2"), "day.skill", {"ability": "photo", "target": "1"})
        self.assertEqual(
            set(game["photos"][0]), {"id", "sender", "target", "day", "allowed"}
        )

        fake = arranged_game()
        fake["cards"]["nanoka"]["alive"] = False
        fake["cards"]["honoka"]["states"]["disguise"] = "coco"
        command(fake, player(fake, "7"), "day.skill", {"ability": "photo", "target": "1"})
        self.assertFalse(fake["photos"])

    def test_fake_mass_brainwash_keeps_execution_but_challenge_cancels_penalty(self):
        game = arranged_game()
        game["cards"]["noah"]["alive"] = False
        command(
            game,
            player(game, "6"),
            "day.skill",
            {"ability": "mass_brainwash", "target": "1"},
        )
        declaration = game["declarations"][-1]
        self.assertTrue(declaration["fake"])
        self.assertIn("millia", game["execution"])
        self.assertEqual(
            game["spiritual"]["annan_penalty"]["annan"]["declaration_id"], declaration["id"]
        )
        command(
            game,
            player(game, "2"),
            "day.challenge",
            {"declaration_id": declaration["id"]},
        )
        self.assertIn("millia", game["execution"])
        self.assertNotIn("annan", game["spiritual"]["annan_penalty"])

    def test_gaze_reports_whether_todays_execution_list_holds_a_witch(self):
        game = arranged_game("execution")
        # 默认发牌里艾玛在1号席，与7号席的奈乃香环形相邻，先移除这个毒源。
        game["cards"]["emma"]["alive"] = False
        game["execution"] = ["millia"]
        events = command(game, player(game, "7"), "day.skill", {"ability": "gaze"})
        self.assertEqual(
            [e["text"] for e in events if e["title"] == "处决幻视"],
            ["本日处决名单不含魔女。"],
        )

        game = arranged_game("execution")
        game["cards"]["emma"]["alive"] = False
        game["cards"]["millia"]["witch"] = True
        game["execution"] = ["millia", "coco"]
        events = command(game, player(game, "7"), "day.skill", {"ability": "gaze"})
        self.assertEqual(
            [e["text"] for e in events if e["title"] == "处决幻视"],
            ["本日处决名单含有魔女。"],
        )
        self.assertEqual(game["cards"]["nanoka"]["uses"]["gaze_day"], game["day"])
        # 处决名单进入新白天即清空，幻视只回答当天名单。
        fresh = arranged_game("night_results", "night")
        fresh["cards"]["hanna"]["witch"] = True
        fresh["execution"] = ["hanna"]
        apply_command(fresh, HOST, "host.advance", {})
        self.assertEqual(fresh["execution"], [])

    def test_poisoned_gaze_always_answers_and_may_lie(self):
        for roll, expected in ((0, "本日处决名单含有魔女。"), (1, "本日处决名单不含魔女。")):
            game = arranged_game("execution")
            game["cards"]["nanoka"]["states"]["poisoned"] = True
            game["cards"]["hanna"]["witch"] = True
            game["execution"] = ["hanna"]
            with patch("backend.app.game.state.SystemRandom") as random:
                random.return_value.randrange.return_value = roll
                events = command(game, player(game, "7"), "day.skill", {"ability": "gaze"})
            # 中毒的奈乃香一定拿到一条结果、声明不算假，但不会被告知掷骰结果。
            self.assertFalse(game["declarations"][-1]["fake"])
            self.assertEqual([e["text"] for e in events if e["title"] == "处决幻视"], [expected])
            self.assertFalse([e for e in events if e["title"] == "中毒判定"])
            self.assertIn("poison", [entry["kind"] for entry in game["log"]])

    def test_gaze_cannot_be_faked_or_challenged(self):
        game = arranged_game("execution")
        game["seats"][6]["cards"] = ["honoka", "nanoka"]
        game["cards"]["honoka"]["states"]["disguise"] = "nanoka"
        fake = player(game, "7")
        offered = [
            item["label"] for item in actions_for(game, fake) if item["id"] == "day.skill"
        ]
        self.assertNotIn("声称处决幻视", offered)
        with self.assertRaises(GameError):
            command(game, fake, "day.skill", {"ability": "gaze"})

        real = arranged_game("execution")
        real["execution"] = ["hanna"]
        command(real, player(real, "7"), "day.skill", {"ability": "gaze"})
        declaration = real["declarations"][-1]
        self.assertFalse(declaration["fake"])
        self.assertFalse(challengeable(real, declaration))
        with self.assertRaises(GameError):
            command(
                real,
                player(real, "1"),
                "day.challenge",
                {"declaration_id": declaration["id"]},
            )


class NewNightRules(unittest.TestCase):
    def test_once_injury_never_upgrades_existing_injury_to_death(self):
        game = arranged_game("night_review", "night")
        game["cards"]["marg"]["injured"] = True
        preview = damage_preview(
            game,
            [{"target_card": "marg", "source_card": "arisa", "once_injury": True}],
        )
        self.assertTrue(preview["injured"]["marg"])
        self.assertFalse(preview["deaths"])

    def test_treasure_immediately_locks_night_and_grants_safe_protection(self):
        game = arranged_game("night", "night")
        game["cards"]["millia"]["alive"] = False
        begin_night(game, [])
        with patch("backend.app.game.engine.SystemRandom") as random:
            random.return_value.randrange.return_value = 1
            command(game, player(game, "1"), "night.submit", {"ability": "treasure"})
        self.assertTrue(game["night"]["locked"])
        self.assertEqual(game["phase"], "night_review")
        self.assertEqual(game["cards"]["emma"]["states"]["treasure_protected_day"], 2)
        self.assertEqual([action["ability"] for action in game["night"]["actions"]], ["treasure"])

    def test_arisa_rolls_each_neighbor_and_marg_love_only_injures_once(self):
        game = arranged_game("night", "night")
        game["cards"]["leia"]["alive"] = False
        game["night"] = {
            "actors": {"5": "arisa"},
            "actions": [
                {"card_id": "arisa", "seat_id": "5", "ability": "arisa_injure", "confirmed": True}
            ],
            "confirmed": ["5"],
            "locked": False,
            "preview": None,
            "reactions": [],
        }
        with patch("backend.app.game.resolution.SystemRandom") as random:
            random.return_value.randrange.side_effect = [0, 1]
            lock_night(game, [])
        self.assertTrue(game["night"]["preview"]["injured"]["marg"])
        self.assertFalse(game["night"]["preview"]["injured"]["noah"])

        love = arranged_game("night_review", "night")
        love["marg_love"] = {"seat_id": "2", "day": 2}
        love["cards"]["hiro"]["injured"] = True
        preview, _ = night_damage(love)
        self.assertTrue(preview["injured"]["hiro"])
        self.assertFalse(preview["deaths"])

    def test_nanoka_hit_threshold_rises_from_one_to_six(self):
        game = arranged_game("execution")
        game["cards"]["emma"]["alive"] = False
        game["execution"] = ["nanoka"]
        game["execution_ready"] = []
        game["execution_shots"] = []
        with patch("backend.app.game.engine.SystemRandom") as random:
            random.return_value.randrange.return_value = 5
            for _ in range(6):
                command(game, player(game, "7"), "execution.shoot", {"target": "2"})
                game["execution_ready"].clear()
        self.assertEqual([roll["threshold"] for roll in game["execution_rolls"]], [1, 2, 3, 4, 5, 6])
        self.assertEqual(len(game["execution_shots"]), 1)
        self.assertEqual(game["cards"]["nanoka"]["uses"]["shot_misses"], 0)

    def test_witch_honoka_renames_each_four_person_witness_list(self):
        game = arranged_game("night_results", "night")
        game["cards"]["nanoka"]["alive"] = False
        game["cards"]["honoka"]["witch"] = True
        item = pending(
            game,
            "suspects",
            "目击裁定",
            seat_id="1",
            victim="millia",
            source_card="noah",
        )
        command(
            game,
            HOST,
            "host.resolve",
            {
                "pending_id": item["id"],
                "suspects": ["hanna", "honoka", "noah", "coco"],
            },
        )
        witness = next(action for action in actions_for(game, player(game, "7")) if action["id"] == "honoka.witness")
        command(
            game,
            player(game, "7"),
            "honoka.witness",
            {"pending_id": witness["payload"]["pending_id"], "role": "coco"},
        )
        self.assertIn("可可", game["witness"]["text"])
        self.assertNotIn("穗乃香", game["witness"]["text"])


class ResolutionEdges(unittest.TestCase):

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
            "suspects": ["hanna", "emma", "noah", "coco"],
        }
        with self.assertRaises(GameError):
            command(game, HOST, "host.resolve", data)
        data["suspects"] = ["hanna", "emma", "nanoka", "coco"]
        command(game, HOST, "host.resolve", data)
        self.assertTrue(game_view(game, player(game, "1"))["information"])
        # 他人信息里没有这份目击名单；开局告知的魔女化命运属公开规则，不算泄露。
        others = game_view(game, player(game, "2"))["information"]
        self.assertFalse([item for item in others if item["title"] != "魔女化命运"])

    def test_poisoned_victims_witness_list_hides_the_killer_half_the_time(self):
        """死者中毒时目击是中毒信息：信息骰失败给出不含真凶的名单，生效才含真凶。"""
        for roll, killer_shown in ((0, True), (1, False)):
            game = arranged_game("night_review", "night")
            game["cards"]["noah"]["states"]["poisoned"] = True
            preview = damage_preview(
                game, [{"target_card": "noah", "source_card": "coco", "cause": "knife"}]
            )
            with patch("backend.app.game.state.SystemRandom") as random:
                random.return_value.randrange.return_value = roll
                death_batch(game, [], preview)
            item = next(p for p in game["pending"] if p["kind"] == "suspects")
            self.assertEqual(item["truthful"], killer_shown)
            command(
                game,
                HOST,
                "host.resolve",
                {"pending_id": item["id"], "suspects": ["hanna", "coco", "emma", "leia"]},
            )
            text = game["witness"]["text"]
            names = text.removeprefix("四名疑似凶手：").split("、")
            self.assertEqual(len(names), 4)
            self.assertEqual(len(set(names)), 4)
            self.assertIn("汉娜", names)
            self.assertEqual("可可" in names, killer_shown)
            # 中毒骰只写主持人日志，不发给死者。
            self.assertFalse(
                [e for e in game["information"] if e["title"] == "中毒判定"]
            )

    def test_poisoned_water_victim_can_get_a_list_without_the_water_user(self):
        game = arranged_game("night", "night")
        game["water"]["holders"] = ["1"]
        command(game, player(game, "1"), "water.use", {"target": "3"})
        game["cards"]["meruru"]["states"]["poisoned"] = True
        lock_night(game, [])
        with patch("backend.app.game.state.SystemRandom") as random:
            random.return_value.randrange.return_value = 1
            command(game, HOST, "host.advance")
        names = game["witness"]["text"].removeprefix("四名疑似凶手：").split("、")
        self.assertEqual(len(names), 4)
        self.assertEqual(len(set(names)), 4)
        self.assertNotIn("米莉亚", names)

    def test_millia_substitution_lasts_through_the_next_day_but_not_execution(self):
        # 换血目标持久保存：白天普通伤害仍由米莉亚代死，处刑不走替死。
        game = arranged_game("discussion", "day")
        game["millia_swap"] = {"seat": "3", "day": 1, "key": f"{game['day']}:{game['half']}", "effective": True}
        game["seats"][2]["avatar_role_id"] = "meruru"
        death_batch(
            game,
            [],
            day_damage_preview(
                game, [{"target_card": "meruru", "source_card": "coco", "cause": "host"}]
            ),
        )
        self.assertFalse(game["cards"]["millia"]["alive"])
        self.assertTrue(game["cards"]["meruru"]["alive"])

        # 处刑显式绕过替死：目标按处刑出局。
        game = arranged_game("execution", "day")
        game["millia_swap"] = {"seat": "3", "day": 2, "key": f"{game['day']}:{game['half']}", "effective": True}
        preview = damage_preview(
            game, [{"target_card": "meruru", "source_card": None, "cause": "execution"}]
        )
        death_batch(game, [], preview)
        self.assertFalse(game["cards"]["meruru"]["alive"])
        self.assertTrue(game["cards"]["millia"]["alive"])

    def test_millia_substitutes_the_swapped_players_death(self):
        # 米莉亚：换血对象即将死亡时，米莉亚牌代替其死亡，不产生主持人待办。
        game = arranged_game("night_review", "night")
        game["night"]["reactions"] = []
        game["night"]["actions"] = [
            {
                "ability": "knife",
                "card_id": "emma",
                "seat_id": "2",
                "target_card": "meruru",
                "effective": True,
                "hit": True,
            },
            {
                "ability": "swap",
                "card_id": "millia",
                "seat_id": "1",
                "target_seat": "3",
                "effective": True,
            },
        ]
        game["millia_swap"] = {"seat": "3", "day": 2}
        game["cards"]["emma"]["alive"] = False
        with patch("backend.app.game.state.SystemRandom") as random, patch(
            "backend.app.game.resolution.SystemRandom"
        ) as resolution_random:
            random.return_value.randrange.return_value = 0  # 中毒骰固定生效
            resolution_random.return_value.randrange.return_value = 0
            prepare_night_preview(game)
        self.assertFalse(any(item["kind"] == "millia" for item in game["pending"]))
        deaths = {death["target_card"] for death in game["night"]["preview"]["deaths"]}
        self.assertEqual(deaths, {"millia"})
        self.assertTrue(game["cards"]["meruru"]["alive"])

    def test_millia_does_not_substitute_when_swap_mill_roll_fails(self):
        # 中毒骰值1：换血本半天失效，不替死。
        game = arranged_game("night_review", "night")
        game["night"]["reactions"] = []
        game["night"]["actions"] = [
            {
                "ability": "knife",
                "card_id": "noah",
                "seat_id": "5",
                "target_card": "meruru",
                "effective": True,
                "hit": True,
            },
        ]
        game["millia_swap"] = {"seat": "3", "day": 2}
        with patch("backend.app.game.state.SystemRandom") as random, patch(
            "backend.app.game.resolution.SystemRandom"
        ) as resolution_random:
            random.return_value.randrange.return_value = 1  # 中毒骰值1：技能失效
            resolution_random.return_value.randrange.return_value = 1
            prepare_night_preview(game)
        deaths = {death["target_card"] for death in game["night"]["preview"]["deaths"]}
        self.assertEqual(deaths, {"meruru"})

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
        self.assertIn(
            "vote.nominate", [item["id"] for item in actions_for(game, player(game, "2"))]
        )
        command(game, player(game, "2"), "vote.nominate", {"target": "3"})
        command(game, player(game, "4"), "vote.nominate", {"target": "3"})
        command(game, player(game, "1"), "vote.pass")
        self.assertNotIn(
            "vote.nominate", [item["id"] for item in actions_for(game, player(game, "4"))]
        )
        with self.assertRaises(GameError):
            command(game, HOST, "host.advance")
        for sid in ("3", "5", "6", "7"):
            command(game, player(game, sid), "vote.pass")
        command(game, HOST, "host.advance")
        self.assertEqual(game_view(game, player(game, "1"))["public"]["votes"]["candidate"], "3")
        self.assertEqual(game_view(game, player(game, "1"))["public"]["votes"]["total"], 1)

    def test_daytime_lower_entry_needs_no_host_step_and_grants_its_actions(self):
        game = arranged_game()
        game["seats"][6]["cards"] = ["nanoka", "honoka"]
        game["seats"][6]["avatar_role_id"] = "nanoka"
        actor = player(game, "7")
        death_batch(
            game,
            [],
            damage_preview(
                game, [{"target_card": "nanoka", "cause": "host", "unconditional": True}]
            ),
        )
        # 下层立即登场：无需主持人裁定，本人当场就能使用登场后的行动。
        self.assertEqual(game["pending"], [])
        self.assertEqual(game_view(game, actor)["seats"][6]["avatar_role_id"], "honoka")
        command(game, actor, "honoka.disguise", {"role": "emma"})
        self.assertEqual(game_view(game, actor)["seats"][6]["avatar_role_id"], "emma")
        self.assertTrue(
            any(item["title"] == "穗乃香示人" for item in game_view(game, HOST)["information"])
        )
        # 示人另发的系统提示只给本人，不写进其他人的信息栏。
        for viewer in (player(game, "1"), actor):
            self.assertFalse(
                any(
                    item["title"] == "穗乃香示人"
                    for item in game_view(game, viewer)["information"]
                )
            )


class PlaytestFixes(unittest.TestCase):
    def test_coco_still_acts_after_every_other_night_actor_confirms(self):
        game = arranged_game("night", "night")
        game["cards"]["hiro"]["alive"] = False
        game["cards"]["coco"]["witch"] = True
        begin_night(game, [])
        coco_seat = owner(game, "coco")["id"]
        game["night"]["confirmed"] = [sid for sid in game["night"]["actors"] if sid != coco_seat]
        unlock_coco(game, [])
        self.assertEqual(game["phase"], "night_coco")
        coco = player(game, coco_seat)
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
                "suspects": ["hanna", "emma", "noah", "coco"],
            },
        )
        seat_view = game_view(game, player(game, "3"))
        self.assertTrue(any("四名疑似凶手" in i["text"] for i in seat_view["information"]))
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
                "suspects": ["hanna", "emma", "noah", "coco"],
            },
        )
        self.assertTrue(game["cards"]["hanna"]["states"]["evidence_allowed"])
        self.assertIn(
            "evidence.submit", [a["id"] for a in game_view(game, player(game, "3"))["actions"]]
        )

    def test_challenge_settles_on_the_spot_instead_of_waiting_for_the_host(self):
        game = arranged_game("discussion")
        game["seats"][6]["cards"] = ["honoka", "nanoka"]
        game["cards"]["honoka"]["states"]["disguise"] = "emma"
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
        self.assertIn("day.challenge", [a["id"] for a in actions_for(game, player(game, "3"))])
        challenged_cards = list(game["seats"][2]["cards"])
        command(game, player(game, "3"), "day.challenge", {"declaration_id": declaration["id"]})
        # 质疑失败整席出局：两张牌一起作废，跳过亡语、回溯、证物与疑似凶手
        self.assertEqual(
            [game["cards"][card_id]["alive"] for card_id in challenged_cards],
            [False, False],
        )
        self.assertEqual(game["pending"], [])
        self.assertIsNone(game_view(game, player(game, "3"))["self"]["current_card_id"])
        self.assertIn("p3", game["spiritual"]["personal_losses"])
        self.assertEqual(game["declarations"][0]["status"], "open")
        self.assertNotIn("day.challenge", [a["id"] for a in actions_for(game, player(game, "3"))])
        with self.assertRaises(GameError):
            command(game, player(game, "3"), "day.challenge", {"declaration_id": declaration["id"]})
        self.assertIn("day.challenge", [a["id"] for a in actions_for(game, player(game, "4"))])

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
            any(event["kind"] == "alert" and "质疑失败" in event["text"] for event in events)
        )
        game["phase"] = "speech"
        game["public"]["speech_order"] = [s["id"] for s in game["seats"]]
        game["public"]["speaker"] = "1"
        events = command(game, HOST, "host.speech", {"start": "1", "direction": "asc"})
        self.assertEqual(
            [event["kind"] for event in events if "发言顺序" in event["text"]],
            ["notice"],
        )

    def test_only_emma_and_witch_brainwash_claims_can_be_challenged(self):
        game = arranged_game("discussion")
        game["seats"][0]["cards"] = ["emma", "millia"]
        command(game, player(game, "1"), "day.skill", {"ability": "interrupt", "target": "2"})
        game["seats"][2]["cards"] = ["annan", "meruru"]
        game["cards"]["annan"]["witch"] = True
        command(game, player(game, "3"), "day.skill", {"ability": "mass_brainwash", "target": "4"})
        game["seats"][3]["cards"] = ["marg", "sherry"]
        command(game, player(game, "4"), "day.skill", {"ability": "love", "target": "2"})
        game["cards"]["marg"]["witch"] = True
        game["cards"]["marg"]["states"]["learned_brainwash"] = True
        game["phase"] = "voting"
        command(game, player(game, "4"), "day.skill", {"ability": "brainwash", "target": "2"})
        game["seats"][6]["cards"] = ["honoka", "nanoka"]
        game["cards"]["honoka"]["states"]["disguise"] = "marg"
        command(game, player(game, "7"), "day.skill", {"ability": "brainwash", "target": "5"})
        ids = {
            declaration["ability"] + ("(伪装)" if declaration["fake"] else ""): declaration["id"]
            for declaration in game["declarations"]
        }
        offered = sorted(
            item["payload"]["declaration_id"]
            for item in actions_for(game, player(game, "5"))
            if item["id"] == "day.challenge"
        )
        self.assertEqual(
            offered,
            sorted(
                [
                    ids["interrupt"],
                    ids["mass_brainwash"],
                    ids["brainwash"],
                    ids["brainwash(伪装)"],
                ]
            ),
        )
        self.assertNotIn(ids["love"], offered)
        with self.assertRaises(GameError):
            command(game, player(game, "5"), "day.challenge", {"declaration_id": ids["love"]})

    def test_honoka_only_fakes_the_role_she_shows(self):
        game = arranged_game("discussion")
        game["seats"][6]["cards"] = ["honoka", "nanoka"]
        honoka = player(game, "7")
        self.assertNotIn("day.skill", [item["id"] for item in actions_for(game, honoka)])
        game["cards"]["honoka"]["states"]["disguise"] = "emma"
        self.assertEqual(
            [item["label"] for item in actions_for(game, honoka) if item["id"] == "day.skill"],
            ["声称打断发言"],
        )
        with self.assertRaises(GameError):
            command(game, honoka, "day.skill", {"ability": "gaze", "target": "1"})
        command(game, honoka, "day.skill", {"ability": "interrupt", "target": "1"})
        self.assertTrue(game["declarations"][0]["fake"])
        self.assertEqual(game["declarations"][0]["status"], "open")

    def test_honoka_lobby_disguise_applies_only_from_the_top_card(self):
        game = arranged_game()
        game.update(status="lobby", phase="ordering", day=1, half="night")
        game["seats"][6]["cards"] = ["honoka", "nanoka"]
        for seat in game["seats"]:
            seat["ready"] = True
        command(game, player(game, "7"), "honoka.disguise", {"role": "emma"})
        self.assertEqual(game["cards"]["honoka"]["states"]["disguise"], "emma")
        command(game, HOST, "host.start")
        self.assertEqual(game_view(game, player(game, "1"))["seats"][6]["avatar_role_id"], "emma")
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
        self.assertEqual(game_view(game, player(game, "1"))["seats"][6]["avatar_role_id"], "nanoka")
        self.assertNotIn("disguise", game["cards"]["honoka"]["states"])
        game["half"] = "day"
        death_batch(
            game,
            [],
            damage_preview(
                game, [{"target_card": "nanoka", "cause": "host", "unconditional": True}]
            ),
        )
        self.assertEqual(game_view(game, player(game, "7"))["seats"][6]["avatar_role_id"], "honoka")
        command(game, player(game, "7"), "honoka.disguise", {"role": "noah"})
        self.assertEqual(game_view(game, player(game, "1"))["seats"][6]["avatar_role_id"], "noah")
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


class NightReveal(unittest.TestCase):
    def test_night_deaths_are_announced_with_the_next_day(self):
        game = arranged_game("night_review", "night")
        game["night"]["reactions"] = []
        game["night"]["preview"] = damage_preview(
            game, [{"target_card": "meruru", "source_card": "emma", "cause": "knife"}]
        )
        game["seats"][2]["avatar_role_id"] = "meruru"
        events = command(game, HOST, "host.advance")
        self.assertNotIn("3号玩家一张角色牌出局。", [item["text"] for item in events])
        self.assertFalse(game["cards"]["meruru"]["alive"])
        self.assertEqual(game["queued_notices"], ["3号玩家一张角色牌出局。"])
        # 夜间结算时对外仍是出局前的位置，避免头像与出局标记提前泄露
        held = game_view(game, player(game, "1"))["seats"]
        self.assertEqual(held[2]["avatar_role_id"], "meruru")
        self.assertIsNone(held[2]["previous_role_id"])
        self.assertTrue(held[2]["alive"])
        game["pending"] = []
        events = command(game, HOST, "host.advance")
        self.assertIn("3号玩家一张角色牌出局。", [item["text"] for item in events])
        self.assertEqual(game["queued_notices"], [])
        self.assertEqual(game["phase"], "speech")
        open_view = game_view(game, player(game, "1"))["seats"]
        self.assertEqual(open_view[2]["avatar_role_id"], "hanna")
        self.assertEqual(open_view[2]["previous_role_id"], "meruru")
        self.assertTrue(open_view[2]["alive"])

    def test_daytime_deaths_are_announced_right_away(self):
        game = arranged_game()
        events = command(
            game,
            HOST,
            "host.damage",
            {"targets": ["meruru"], "effect": "death", "source": "coco", "reason": "测试白天出局"},
        )
        self.assertIn("3号玩家一张角色牌出局。", [item["text"] for item in events])
        self.assertEqual(game["queued_notices"], [])
        seats = {seat["id"]: seat for seat in game_view(game, player(game, "1"))["seats"]}
        self.assertEqual(seats["3"]["previous_role_id"], "meruru")
        self.assertEqual(seats["3"]["avatar_role_id"], "hanna")
        self.assertIsNone(seats["1"]["previous_role_id"])


class NightSummaryAndWitness(unittest.TestCase):
    def test_peaceful_night_and_named_death_summary(self):
        game = arranged_game("night_review", "night")
        game["night"]["reactions"] = []
        game["night"]["preview"] = {"injured": {}, "deaths": []}
        command(game, HOST, "host.advance")
        events = command(game, HOST, "host.advance")
        self.assertIn(f"第{game['day']}夜是平安夜。", [item["text"] for item in events])
        self.assertEqual(game["phase"], "speech")

        game = arranged_game("night_review", "night")
        game["night"]["reactions"] = []
        game["night"]["preview"] = damage_preview(
            game, [{"target_card": "meruru", "source_card": "coco", "cause": "knife"}]
        )
        command(game, HOST, "host.advance")
        game["pending"] = []
        events = command(game, HOST, "host.advance")
        self.assertIn(
            f"第{game['day']}夜，梅露露死了。", [item["text"] for item in events]
        )

    def test_revive_revokes_the_death_record_and_its_publication(self):
        game = arranged_game("night_review", "night")
        # 3号的梅露露为当前牌且已魔女化；1号上层米莉亚被其刀杀。
        game["cards"]["meruru"]["witch"] = True
        game["night"]["reactions"] = []
        game["night"]["preview"] = damage_preview(
            game, [{"target_card": "millia", "source_card": "meruru", "cause": "knife"}]
        )
        command(game, HOST, "host.advance")
        death = next(item for item in game["deaths"] if item["target_card"] == "millia")
        self.assertIn(death["notice"], game["queued_notices"])
        self.assertTrue(any(item.get("death_id") == death["id"] for item in game["pending"]))
        command(game, player(game, "3"), "meruru.revive", {"death_id": death["id"]})
        # 复活撤销该次死亡的全部痕迹：记录、公告、目击、半天出局与待办。
        self.assertTrue(game["cards"]["millia"]["alive"])
        self.assertNotIn("millia", [item["target_card"] for item in game["deaths"]])
        self.assertNotIn(death["notice"], game["queued_notices"])
        self.assertFalse(any(item.get("death_id") == death["id"] for item in game["pending"]))
        self.assertIsNone(game["witness"])
        # 傀儡化：该牌无投票权、无技能，且控制者是 3 号的梅露露。
        self.assertEqual(game["cards"]["millia"]["states"]["puppet"], "meruru")
        self.assertTrue(game["cards"]["millia"]["states"]["no_ability"])
        self.assertEqual(
            [panel["seat_id"] for panel in game_view(game, player(game, "3"))["self"]["puppet_controls"]],
            ["1"],
        )
        # 投票阶段：控制者能以该傀儡席投票，傀儡本身不产生第二个身份。
        game.update(day=2, phase="voting", half="day")
        game["votes"] = {}
        game["public"]["votes"] = {"candidate": "3"}
        panels = game_view(game, player(game, "3"))["self"]["puppet_controls"]
        self.assertEqual([panel["seat_id"] for panel in panels], ["1"])
        self.assertIn("vote.cast", [item["id"] for item in panels[0]["actions"]])
        # 星号只进 label：short_label 必须留在动作协议的 2—4 字内，
        # 否则两个客户端都会判定协议不符并整体禁用傀儡面板。
        for item in panels[0]["actions"]:
            self.assertTrue(2 <= len(item["short_label"]) <= 4, item["short_label"])
            self.assertTrue(item["label"].startswith("*"), item["label"])
        # 傀儡被击杀后控制者缺位：该席不再计票，控制者也失去代投。
        game["cards"]["meruru"]["alive"] = False
        self.assertEqual([s["id"] for s in eligible_voters(game)], ["2", "3", "4", "5", "6", "7"])
        panels = game_view(game, player(game, "3"))["self"]["puppet_controls"]
        self.assertEqual(panels, [])

    def test_a_puppet_seat_with_a_night_ability_stays_drivable(self):
        """傀儡席的夜间行动只能由控制者代提交，不能既无行动又占着阻塞待办。"""
        game = arranged_game("night", "night")
        # 傀儡当前牌带刀：该席本夜确实有可执行技能，不会被自动确认。
        # 主人必须是魔女牌，否则控制关系不成立。
        game["cards"]["marg"]["witch"] = True
        game["cards"]["meruru"]["witch"] = True
        begin_night(game, [])
        self.assertNotIn("4", game["night"]["confirmed"])
        self.assertTrue(
            any(task["kind"] == "night" and task["seats"] == ["4"] for task in host_tasks(game))
        )
        command(
            game,
            HOST,
            "host.state",
            {
                "card_id": "marg",
                "state": "puppet",
                "value": True,
                "master": "meruru",
                "reason": "测试傀儡控制",
            },
        )
        # 原玩家没有夜间行动，但控制者拿得到该席的刀与确认。
        self.assertEqual(actions_for(game, player(game, "4")), [])
        puppet = next(
            panel
            for panel in game_view(game, player(game, "3"))["self"]["puppet_controls"]
            if panel["seat_id"] == "4"
        )
        labels = [item["id"] for item in puppet["actions"]]
        self.assertIn("night.submit", labels)
        self.assertIn("night.confirm", labels)
        # 由控制者代提交后该席进入已确认，阻塞待办随之消失。
        controller = {**player(game, "4"), "puppet_controlled": True}
        command(game, controller, "night.confirm", {})
        self.assertIn("4", game["night"]["confirmed"])
        self.assertFalse(
            any(task["kind"] == "night" and task["seats"] == ["4"] for task in host_tasks(game))
        )

    def test_unconcealed_water_death_publishes_a_fixed_four_name_witness(self):
        game = arranged_game("night", "night")
        game["water"]["holders"] = ["1"]
        command(game, player(game, "1"), "water.use", {"target": "3"})
        self.assertEqual(game["pending"], [])
        lock_night(game, [])
        self.assertIn(
            "meruru", [item["target_card"] for item in game["night"]["preview"]["deaths"]]
        )
        command(game, HOST, "host.advance")
        # 未隐藏死因的13水死亡由系统直接发固定四人目击，不产生主持人待办。
        self.assertFalse(any(item["kind"] == "suspects" for item in game["pending"]))
        death = next(item for item in game["deaths"] if item["target_card"] == "meruru")
        self.assertIn(f"{death['seat_id']}号玩家被13水毒杀。", death["notice"])
        witness = game["witness"]
        self.assertEqual(witness["death_id"], death["id"])
        names = witness["text"].removeprefix("四名疑似凶手：").split("、")
        # 名单固定四人且不重复，真实来源（1号上层米莉亚）必定入选。
        self.assertEqual(len(names), 4)
        self.assertEqual(len(set(names)), 4)
        self.assertIn("米莉亚", names)

    def test_multiple_bottles_expire_at_night_end_and_can_hide_the_cause(self):
        game = arranged_game("night", "night")
        command(game, HOST, "host.water", {"seat_id": "1"})
        command(game, HOST, "host.water", {"seat_id": "2"})
        self.assertEqual(game["water"]["holders"], ["1", "2"])
        # 同一席位本夜不能重复领取。
        with self.assertRaises(GameError):
            command(game, HOST, "host.water", {"seat_id": "1"})
        # 两位持有者各自用一瓶，各自指定目标，都直接进入本夜预结算。
        command(game, player(game, "1"), "water.use", {"target": "3"})
        command(game, player(game, "2"), "water.use", {"target": "4"})
        self.assertEqual(game["water"]["holders"], [])
        self.assertEqual(game["pending"], [])
        # 用完后本夜已无13水，再提交会被拒。
        with self.assertRaises(GameError):
            command(game, player(game, "1"), "water.use", {"target": "5"})
        lock_night(game, [])
        preview = {item["cause"] for item in game["night"]["preview"]["deaths"]}
        self.assertEqual(preview, {"water"})
        command(game, HOST, "host.advance")
        # 两处未隐藏死因的13水死亡各自公开毒杀死讯与四人目击。
        notices = [item["notice"] for item in game["deaths"] if item["cause"] == "water"]
        self.assertEqual(len(notices), 2)
        for notice in notices:
            self.assertIn("被13水毒杀。", notice)
        self.assertEqual(game["witness"]["death_id"], game["deaths"][-1]["id"])
        # 次夜开始：未使用的13水过期收回。
        expiry = arranged_game("night", "night")
        command(expiry, HOST, "host.water", {"seat_id": "1"})
        begin_night(expiry, [])
        self.assertEqual(expiry["water"]["holders"], [])

    def test_meruru_can_use_water_without_publishing_the_cause(self):
        game = arranged_game("night", "night")
        game["cards"]["meruru"]["witch"] = True
        command(game, HOST, "host.water", {"seat_id": "3"})
        command(game, player(game, "3"), "water.use", {"target": "2", "hide_cause": True})
        lock_night(game, [])
        command(game, HOST, "host.advance")
        death = next(item for item in game["deaths"] if item["target_card"] == "hiro")
        # 死因不公开：按普通夜间死亡处理，不出现“被13水毒杀”。
        self.assertNotIn("13水", death["notice"])
        self.assertNotIn("13水", death["notice"] + str(game["queued_notices"]))
        # 未隐藏的那条规则不适用：改由主持人填写名单，且不自动发目击。
        self.assertTrue(any(item["kind"] == "suspects" for item in game["pending"]))
        self.assertIsNone(game["witness"])


class HostFreeAdjudication(unittest.TestCase):
    def test_real_day_skill_settles_without_a_host_step(self):
        game = arranged_game("discussion")
        game["seats"][0]["cards"] = ["emma", "millia"]
        command(game, player(game, "1"), "day.skill", {"ability": "interrupt", "target": "2"})
        self.assertEqual(game["pending"], [])
        declaration = game["declarations"][0]
        self.assertFalse(declaration["fake"])
        self.assertTrue(declaration["executed"])
        self.assertEqual(declaration["status"], "open")
        self.assertIn(
            "day.challenge", [item["id"] for item in actions_for(game, player(game, "3"))]
        )

    def test_disguised_photo_or_love_executes_without_state_or_host_todo(self):
        game = arranged_game()
        game["seats"][6]["cards"] = ["honoka", "nanoka"]
        game["cards"]["honoka"]["states"]["disguise"] = "marg"
        command(game, player(game, "7"), "day.skill", {"ability": "love", "target": "3"})
        declaration = game["declarations"][0]
        self.assertTrue(declaration["fake"])
        self.assertTrue(declaration["executed"])
        self.assertEqual(game["pending"], [])
        self.assertIsNone(game["marg_love"])

    def test_day_declarations_close_when_the_day_ends(self):
        game = arranged_game()
        command(game, player(game, "4"), "day.skill", {"ability": "love", "target": "3"})
        game["pending"] = []
        game.update(phase="night_results", half="night")
        command(game, HOST, "host.advance")
        self.assertEqual(game["phase"], "speech")
        self.assertEqual(game["declarations"][0]["status"], "complete")
        self.assertNotIn(
            "day.challenge", [item["id"] for item in actions_for(game, player(game, "1"))]
        )

    def test_hiro_rewinds_himself_without_a_host_step_or_player_choice(self):
        game = arranged_game()
        game.update(day=1, phase="discussion")
        save_snapshot(game)
        game.update(day=2, phase="discussion")
        game["cards"]["emma"]["alive"] = False
        events = command(
            game,
            HOST,
            "host.damage",
            {"targets": ["hiro"], "effect": "death", "source": "coco", "reason": "测试希罗回溯"},
        )
        # 白天死亡立即回溯到前一天自由发言：没有待办、没有选择类行动。
        self.assertEqual(game["pending"], [])
        self.assertEqual(game["day"], 1)
        self.assertEqual(game["phase"], "discussion")
        self.assertTrue(game["spiritual"]["hiro_used"]["normal"])
        self.assertTrue(game["cards"]["hiro"]["alive"])
        self.assertTrue(any("回溯" in item["text"] for item in events))
        labels = [entry["id"] for entry in actions_for(game, player(game, "2"))]
        self.assertNotIn("hiro.rewind", labels)
        self.assertNotIn("hiro.decline", labels)

    def test_a_night_review_rewind_keeps_the_restored_phase(self):
        # 预结算回溯后不能再写回 night_review/night_results，否则会覆盖恢复的时间线。
        game = arranged_game("night_review", "night")
        game.update(day=1, phase="speech")
        game["half"] = "night"
        save_snapshot(game)
        game.update(day=2, phase="night_review", half="night")
        game["cards"]["emma"]["alive"] = False
        game["night"]["reactions"] = []
        game["night"]["preview"] = damage_preview(
            game, [{"target_card": "hiro", "source_card": "coco", "cause": "knife"}]
        )
        command(game, HOST, "host.advance")
        self.assertEqual(game["day"], 1)
        self.assertEqual(game["phase"], "speech")
        self.assertTrue(game["spiritual"]["hiro_used"]["normal"])
        self.assertTrue(game["cards"]["hiro"]["alive"])

    def test_the_fixed_target_falls_back_to_the_opening_snapshot(self):
        game = arranged_game("night", "night")
        game.update(day=1, phase="night")
        save_snapshot(game)
        game["cards"]["emma"]["alive"] = False
        game["night"]["reactions"] = []
        game["night"]["preview"] = damage_preview(
            game, [{"target_card": "hiro", "source_card": "coco", "cause": "knife"}]
        )
        command(game, HOST, "host.advance")
        # 第1天夜里没有前一天快照：回到开局保存的最早快照。
        self.assertEqual(game["day"], 1)
        self.assertTrue(game["cards"]["hiro"]["alive"])


class WitchHiroMandate(unittest.TestCase):
    """魔女希罗「必须疯狂地使艾玛出局」由主持人裁定，绝不能把整夜锁死。"""

    def witch_hiro_night(self):
        game = arranged_game("night", "night")
        # 艾玛是1号的下层牌，只有米莉亚出局后它才是1号的当前牌。
        game["cards"]["millia"]["alive"] = False
        game["cards"]["hiro"]["witch"] = True
        begin_night(game, [])
        return game

    def knife_targets(self, game):
        knife = next(
            item
            for item in actions_for(game, player(game, "2"))
            if item["id"] == "night.submit" and item["payload"]["ability"] == "knife"
        )
        return [option["value"] for option in knife["fields"][0]["options"]]

    def test_attacking_emma_needs_no_ruling_and_keeps_the_exception(self):
        game = self.witch_hiro_night()
        command(game, player(game, "2"), "night.submit", {"ability": "knife", "target": "1"})
        command(game, player(game, "2"), "night.confirm", {})
        self.assertIn("2", game["night"]["confirmed"])
        self.assertEqual(game["pending"], [])
        self.assertFalse(game["spiritual"]["hiro_exception"], "照做时不消耗至多一个夜晚的额度")

    def test_the_first_skipped_attack_spends_the_only_exception_night(self):
        game = self.witch_hiro_night()
        command(game, player(game, "2"), "night.confirm", {})
        self.assertIn("2", game["night"]["confirmed"])
        self.assertEqual(game["pending"], [])
        self.assertTrue(game["spiritual"]["hiro_exception"])

    def test_a_later_skipped_attack_becomes_a_host_ruling_instead_of_a_wall(self):
        game = self.witch_hiro_night()
        game["spiritual"]["hiro_exception"] = True
        command(game, player(game, "2"), "night.confirm", {})
        # 关键：确认仍然成功。硬拒会让整个夜晚没有任何人能推进。
        self.assertIn("2", game["night"]["confirmed"])
        item = next(entry for entry in host_tasks(game) if entry["kind"] == "pending")
        self.assertEqual(item["seats"], ["2"])
        self.assertIn("疯狂", item["title"])
        # 主持人按界面默认值即可结清，模拟主持人的自动裁定走的就是这条路。
        ruling = next(
            action for action in game_view(game, HOST)["actions"] if action["id"] == "host.resolve"
        )
        self.assertEqual(ruling["payload"]["pending_id"], item["payload"]["pending_id"])
        command(
            game,
            HOST,
            "host.resolve",
            {
                "pending_id": item["payload"]["pending_id"],
                "outcome": "warn",
                "penalty": "none",
                "target": "hiro",
                "reason": "测试裁定",
            },
        )
        self.assertEqual(game["pending"], [])

    def test_a_treasure_protected_emma_is_never_required_as_a_target(self):
        """寻宝保护当天魔女刀点不到艾玛，条件与刀口必须同步，否则整夜无解。"""
        game = self.witch_hiro_night()
        game["cards"]["emma"]["states"]["treasure_protected_day"] = game["day"]
        self.assertTrue(treasure_protected(game, "emma"))
        self.assertNotIn("1", self.knife_targets(game))
        # 提名同样不能选中受保护的牌：刀口与提名选项共用同一个判定。
        game["phase"] = "nomination"
        nomination = next(
            item
            for item in actions_for(game, player(game, "2"))
            if item["id"] == "vote.nominate"
        )
        self.assertNotIn("1", [o["value"] for o in nomination["fields"][0]["options"]])
        # 例外夜用完后确认仍然成功：受保护当天根本没有「攻击艾玛」这个选项。
        game["phase"] = "night"
        game["spiritual"]["hiro_exception"] = True
        command(game, player(game, "2"), "night.confirm", {})
        self.assertIn("2", game["night"]["confirmed"])
        self.assertEqual(game["pending"], [])


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
            item for item in game_view(game, HOST)["actions"] if item["id"] == "host.speech"
        )
        self.assertEqual(default["fields"][0]["default"], "1")

    def test_the_day_start_picks_the_side_where_the_witch_speaks_earlier(self):
        cases = {
            "4": ["3", "4", "5", "6", "7", "1", "2"],
            "2": ["3", "2", "1", "7", "6", "5", "4"],
        }
        for witch_seat, expected in cases.items():
            game = arranged_game("night_review", "night")
            game["night"]["reactions"] = []
            game["night"]["preview"] = damage_preview(
                game,
                [{"target_card": "meruru", "source_card": "emma", "cause": "knife"}],
            )
            game["seats"][2]["avatar_role_id"] = "meruru"
            for card in game["cards"].values():
                card["witch"] = False
            seat = game["seats"][int(witch_seat) - 1]
            game["cards"][seat["cards"][0]]["witch"] = True
            command(game, HOST, "host.advance")
            game["pending"] = []
            command(game, HOST, "host.advance")
            self.assertEqual(game["public"]["speech_order"], expected)
            self.assertEqual(game["public"]["speaker"], expected[0])

    def test_the_plan_falls_back_to_ascending_order(self):
        game = arranged_game("night_review", "night")
        game["night"]["reactions"] = []
        game["night"]["preview"] = damage_preview(game, [])
        for card in game["cards"].values():
            card["witch"] = False
        game["cards"][game["seats"][5]["cards"][0]]["witch"] = True
        command(game, HOST, "host.advance")
        game["pending"] = []
        command(game, HOST, "host.advance")
        self.assertEqual(game["public"]["speech_order"], ["1", "7", "6", "5", "4", "3", "2"])
        self.assertEqual(game["public"]["speaker"], "1")

    def test_a_seat_can_confirm_its_speech_before_its_turn(self):
        game = arranged_game("speech")
        command(game, HOST, "host.speech", {"start": "1", "direction": "asc"})
        early = next(
            item for item in actions_for(game, player(game, "3")) if item["id"] == "speech.done"
        )
        self.assertEqual(early["label"], "本轮不发言（跳过我的顺序）")
        self.assertNotIn("instant", early)
        self.assertFalse(early.get("blocking"))
        command(game, player(game, "3"), "speech.done", {})
        self.assertIn("3", game["speech_passed"])
        command(game, player(game, "1"), "speech.done", {})
        self.assertEqual(game["public"]["speaker"], "2")
        command(game, player(game, "2"), "speech.done", {})
        self.assertEqual(game["public"]["speaker"], "4")

    def test_a_seat_can_speak_early_and_the_text_waits_for_its_turn(self):
        game = arranged_game("speech")
        command(game, HOST, "host.speech", {"start": "1", "direction": "asc"})
        speak = next(
            item for item in actions_for(game, player(game, "4")) if item["id"] == "speech.speak"
        )
        self.assertNotIn("instant", speak)
        self.assertEqual([(f["name"], f["type"]) for f in speak["fields"]], [("text", "textarea")])
        with self.assertRaises(GameError):
            command(game, player(game, "4"), "speech.speak", {"text": "   "})
        events = command(game, player(game, "4"), "speech.speak", {"text": "我提前说完了"})
        self.assertEqual(
            [item["text"] for item in events if item["text"].startswith("4号")],
            ["4号已写好发言，轮到时自动公开。"],
        )
        self.assertEqual(game["speech_queued"], {"4": "我提前说完了"})
        self.assertIn("4", game["speech_passed"])
        for sid in ("1", "2"):
            command(game, player(game, sid), "speech.done", {})
        events = command(game, player(game, "3"), "speech.done", {})
        self.assertEqual(
            [item["text"] for item in events if item["kind"] == "chat"],
            ["我提前说完了"],
        )
        self.assertEqual(game["speech_queued"], {})
        self.assertEqual(game["public"]["speaker"], "5")

    def test_pre_submitted_speech_is_published_as_a_player_message(self):
        """预发言公开时必须是玩家消息（chat），不能显示成系统通知。"""
        game = arranged_game("speech")
        command(game, HOST, "host.speech", {"start": "1", "direction": "asc"})
        command(game, player(game, "4"), "speech.speak", {"text": "我提前说完了"})
        for sid in ("1", "2"):
            command(game, player(game, sid), "speech.done", {})
        events = command(game, player(game, "3"), "speech.done", {})
        published = next(item for item in events if item["kind"] == "chat")
        self.assertEqual(published["text"], "我提前说完了")
        self.assertEqual(published["channel_id"], "public")
        self.assertIsNone(published["audience"])

    def test_the_current_speaker_can_publish_its_speech_text_and_move_on(self):
        game = arranged_game("speech")
        command(game, HOST, "host.speech", {"start": "1", "direction": "asc"})
        events = command(game, player(game, "1"), "speech.speak", {"text": "我先讲"})
        chat = next(item for item in events if item["kind"] == "chat")
        self.assertEqual(chat["text"], "我先讲")
        self.assertEqual(game["public"]["speaker"], "2")

    def test_a_fully_pre_submitted_speech_phase_counts_as_finished(self):
        game = arranged_game("speech")
        command(game, HOST, "host.speech", {"start": "1", "direction": "asc"})
        for sid in ("2", "3", "4", "5", "6", "7", "1"):
            command(game, player(game, sid), "speech.done", {})
        self.assertIsNone(game["public"]["speaker"])
        self.assertEqual(outstanding_seats(game), [])
        self.assertIn("auto_advance_at", game["public"])

    def test_speech_confirmation_is_only_offered_while_speaking(self):
        game = arranged_game("discussion")
        self.assertNotIn(
            "speech.done", [item["id"] for item in actions_for(game, player(game, "1"))]
        )

    def test_pre_submitted_speeches_reset_at_the_day_boundary(self):
        game = arranged_game("speech")
        command(game, HOST, "host.speech", {"start": "1", "direction": "asc"})
        command(game, player(game, "3"), "speech.done", {})
        game["phase"] = "dusk"
        game["public"]["speaker"] = None
        command(game, HOST, "host.advance", {})
        self.assertEqual(game["phase"], "witch")
        self.assertEqual(game["speech_passed"], [])

    def test_fully_eliminated_seats_leave_the_speech_order(self):
        """两张牌都出局的席位不再占发言序列，流程也不能停在它身上。"""
        game = arranged_game("night_review", "night")
        game["night"]["reactions"] = []
        game["night"]["preview"] = damage_preview(game, [])
        dead = game["seats"][0]
        for cid in dead["cards"]:
            game["cards"][cid]["alive"] = False
        game["deaths"] = [
            {
                "seat_id": "1",
                "card_id": dead["cards"][0],
                "day": 2,
                "half": "night",
                "cause": "knife",
                "source_card": None,
            }
        ]
        command(game, HOST, "host.advance")
        command(game, HOST, "host.advance")
        self.assertEqual(game["public"]["speech_order"], ["2", "3", "4", "5", "6", "7"])
        self.assertEqual(game["public"]["speaker"], "2")
        self.assertEqual(outstanding_seats(game), ["2"])
        self.assertNotIn("speech.done", [item["id"] for item in actions_for(game, player(game, "1"))])
        with self.assertRaises(GameError):
            command(game, HOST, "host.speech", {"start": "1", "direction": "asc"})
        # 轮到之前出局的席位同样跳过，不留一个等不到人的发言位。
        for cid in game["seats"][1]["cards"]:
            game["cards"][cid]["alive"] = False
        command(game, player(game, "2"), "speech.done", {})
        self.assertEqual(game["public"]["speaker"], "3")

    def test_a_puppet_whose_master_died_mid_speech_never_holds_the_round(self):
        """傀儡主人出局后该席无人可代发言：轮次必须立刻顺延，也不能只剩主持人空等。"""
        game = arranged_game("speech")
        game["cards"]["meruru"]["witch"] = True
        game["cards"]["marg"]["states"]["puppet"] = "meruru"
        command(game, HOST, "host.speech", {"start": "1", "direction": "asc"})
        self.assertIn("4", game["public"]["speech_order"])
        for sid in ("1", "2", "3"):
            command(game, player(game, sid), "speech.done", {})
        self.assertEqual(game["public"]["speaker"], "4")
        self.assertEqual(outstanding_seats(game), ["4"])
        # 主人出局：席位4 当场失去操作者，轮次在同一条命令里顺延给5号。
        command(
            game,
            HOST,
            "host.state",
            {
                "card_id": "meruru",
                "state": "alive",
                "value": False,
                "reason": "测试傀儡主人出局",
            },
        )
        self.assertEqual(game["public"]["speaker"], "5")
        self.assertEqual(outstanding_seats(game), ["5"])
        self.assertNotIn(
            "speech.done", [item["id"] for item in actions_for(game, player(game, "4"))]
        )
        # 主持人的发言待办也不再指向那个等不到的席位。
        self.assertNotIn(
            "4", [seat for task in host_tasks(game) for seat in task["seats"]]
        )
        # 5、6、7 都无人可操作：待办清空，一次推进就收尾，不会停在等不到的席位。
        for card_id in ("noah", "leia", "nanoka"):
            game["cards"][card_id]["states"]["puppet"] = "meruru"
        self.assertEqual(outstanding_seats(game), [])
        command(game, HOST, "host.advance", {})
        self.assertIsNone(game["public"]["speaker"])
        self.assertEqual(game["phase"], "discussion")
        # 主持人也不能把起点设到无人可操作的席位。
        retry = arranged_game("speech")
        retry["cards"]["meruru"]["witch"] = True
        retry["cards"]["marg"]["states"]["puppet"] = "meruru"
        retry["cards"]["meruru"]["alive"] = False
        with self.assertRaises(GameError):
            command(retry, HOST, "host.speech", {"start": "4", "direction": "asc"})


class BalloonFlow(unittest.TestCase):
    def test_arisa_starts_the_balloon_without_any_host_step(self):
        game = arranged_game()
        game["seats"][4].update(cards=["arisa", "leia"])
        command(
            game,
            player(game, "5"),
            "day.skill",
            {"ability": "balloon", "participants": ["2", "3"]},
        )
        balloon = game["public"]["balloon"]
        self.assertEqual(balloon["status"], "collecting")
        self.assertEqual(balloon["participants"], ["5", "2", "3"])
        self.assertEqual(game["pending"], [])
        declaration = next(d for d in game["declarations"] if d["ability"] == "balloon")
        self.assertTrue(declaration["executed"])
        self.assertEqual(declaration["status"], "open")
        options = next(
            item for item in actions_for(game, player(game, "2")) if item["id"] == "balloon.choose"
        )
        self.assertEqual(
            [item["value"] for item in options["fields"][0]["options"]], ["make", "skip"]
        )
        for sid in ("5", "2", "3"):
            command(game, player(game, sid), "balloon.choose", {"choice": "make"})
        self.assertEqual(game["public"]["balloon"]["status"], "complete")
        self.assertEqual(game["public"]["balloon"]["progress"], 3)
        self.assertEqual(
            next(d for d in game["declarations"] if d["ability"] == "balloon")["status"],
            "complete",
        )
        self.assertEqual(game["pending"], [])

    def test_players_only_see_the_result_not_the_making_details(self):
        game = arranged_game()
        game["seats"][4].update(cards=["arisa", "leia"])
        game["seats"][2].update(cards=["annan", "hanna"])
        command(
            game,
            player(game, "5"),
            "day.skill",
            {"ability": "balloon", "participants": ["3", "4"]},
        )
        command(game, player(game, "4"), "balloon.choose", {"choice": "make"})
        events = command(game, player(game, "5"), "balloon.choose", {"choice": "make"})
        self.assertEqual(game["public"]["balloon"]["last"]["breakers"], ["3"])
        self.assertEqual(game["public"]["balloon"]["progress"], 0)
        public = "".join(event["text"] for event in events if event["audience"] is None)
        self.assertEqual(public, "热气球制作结束：当前进度0/13。")
        detail = game_view(game, player(game, "4"))["public"]["balloon"]
        self.assertIsNone(detail.get("last"))
        self.assertEqual(detail["progress"], 0)
        self.assertEqual(
            game_view(game, HOST)["host"]["balloon_choices"],
            {"3": "break", "4": "make", "5": "make"},
        )

    def test_good_players_cannot_break_the_balloon(self):
        game = arranged_game()
        game["seats"][4].update(cards=["arisa", "leia"])
        command(game, player(game, "5"), "day.skill", {"ability": "balloon", "participants": ["2"]})
        with self.assertRaises(GameError):
            command(game, player(game, "2"), "balloon.choose", {"choice": "break"})

    def test_annan_breaks_the_balloon_just_by_joining(self):
        game = arranged_game()
        game["cards"]["arisa"]["alive"] = False
        game["seats"][2].update(cards=["annan", "meruru"])
        command(
            game,
            player(game, "1"),
            "balloon.propose",
            {"participants": ["3", "4"]},
        )
        for sid in ("2", "3", "4"):
            command(game, player(game, sid), "balloon.agree", {})
        balloon = game["public"]["balloon"]
        self.assertEqual(balloon["participants"], ["3", "4"])
        self.assertEqual(game["balloon_choices"], {"3": "break"})
        self.assertNotIn(
            "balloon.choose", [item["id"] for item in actions_for(game, player(game, "3"))]
        )
        self.assertIn(
            "balloon.choose", [item["id"] for item in actions_for(game, player(game, "4"))]
        )
        command(game, player(game, "4"), "balloon.choose", {"choice": "make"})
        settled = game["public"]["balloon"]
        self.assertEqual(settled["status"], "complete")
        self.assertEqual(settled["progress"], 0)
        self.assertEqual(settled["last"]["breakers"], ["3"])

    def test_proposal_needs_more_than_half_of_the_living_players(self):
        game = arranged_game()
        game["cards"]["arisa"]["alive"] = False
        command(game, player(game, "1"), "balloon.propose", {"participants": ["2", "3"]})
        self.assertEqual(game["balloon_proposal"]["votes"], {"1": True})
        self.assertEqual(game["public"]["balloon"]["status"], "idle")
        for sid in ("2", "3"):
            command(game, player(game, sid), "balloon.agree", {})
        self.assertEqual(game["public"]["balloon"]["status"], "idle")
        command(game, player(game, "4"), "balloon.agree", {})
        self.assertIsNone(game["balloon_proposal"])
        balloon = game["public"]["balloon"]
        self.assertEqual(balloon["status"], "collecting")
        self.assertEqual(balloon["participants"], ["2", "3"])
        self.assertEqual(balloon["organizer"], "1号提议")

    def test_a_proposal_that_can_no_longer_pass_is_dropped(self):
        game = arranged_game()
        game["cards"]["arisa"]["alive"] = False
        command(game, player(game, "1"), "balloon.propose", {"participants": ["2"]})
        for sid in ("2", "3", "4", "5"):
            command(game, player(game, sid), "balloon.decline", {})
        self.assertIsNone(game["balloon_proposal"])
        self.assertEqual(game["public"]["balloon"]["status"], "idle")

    def test_a_listed_player_who_dies_mid_vote_is_dropped_instead_of_blocking(self):
        """表决期间名单里的人出局：过半同意照常组织，只带存活者。"""
        game = arranged_game()
        game["cards"]["arisa"]["alive"] = False
        command(game, player(game, "1"), "balloon.propose", {"participants": ["2", "3"]})
        for card_id in game["seats"][1]["cards"]:
            game["cards"][card_id]["alive"] = False
        for sid in ("3", "4", "5"):
            command(game, player(game, sid), "balloon.agree", {})
        self.assertIsNone(game["balloon_proposal"])
        balloon = game["public"]["balloon"]
        self.assertEqual(balloon["status"], "collecting")
        self.assertEqual(balloon["participants"], ["3"])
        self.assertEqual(balloon["organizer"], "1号提议")

    def test_a_proposal_whose_list_all_died_is_dropped(self):
        game = arranged_game()
        game["cards"]["arisa"]["alive"] = False
        command(game, player(game, "1"), "balloon.propose", {"participants": ["2", "3"]})
        for index in (1, 2):
            for card_id in game["seats"][index]["cards"]:
                game["cards"][card_id]["alive"] = False
        command(game, player(game, "4"), "balloon.agree", {})
        events = command(game, player(game, "5"), "balloon.agree", {})
        self.assertIsNone(game["balloon_proposal"])
        self.assertEqual(game["public"]["balloon"]["status"], "idle")
        self.assertIn(
            "作废", "".join(event["text"] for event in events if event["audience"] is None)
        )


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
        # 自由发言只有不足六人请求结束时不自动推进。
        discussion = arranged_game("discussion")
        for sid in ("1", "2", "3", "4", "5"):
            command(discussion, player(discussion, sid), "discussion.request_end", {})
        self.assertNotIn("auto_advance_at", discussion["public"])
        # 13水只在夜间发放，且不会因此产生主持人待办。
        night = arranged_game("night", "night")
        command(night, HOST, "host.water", {"seat_id": "1"})
        self.assertEqual(night["water"]["holders"], ["1"])
        self.assertEqual(night["pending"], [])

    def test_six_requests_end_free_discussion_ten_seconds_later(self):
        game = arranged_game("discussion")
        for sid in ("1", "2", "3", "4", "5"):
            command(game, player(game, sid), "discussion.request_end", {})
        self.assertNotIn("auto_advance_at", game["public"])
        events = command(game, player(game, "6"), "discussion.request_end", {})
        self.assertIn("10秒后自动进入热气球", "".join(e["text"] for e in events))
        deadline = game["public"]["auto_advance_at"]
        self.assertIsNotNone(deadline)
        run_auto_advance(game, deadline - 1)
        self.assertEqual(game["phase"], "discussion")
        run_auto_advance(game, deadline + 1)
        self.assertEqual(game["phase"], "balloon")
        self.assertEqual(game["discussion_end_requests"], [])
        # 同一席位不能重复提交。
        with self.assertRaises(GameError):
            command(game, player(game, "6"), "discussion.request_end", {})


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
        self.assertEqual(nomination["ui_version"], 1)
        self.assertTrue(2 <= len(nomination["short_label"]) <= 4)
        self.assertNotIn("instant", nomination)
        self.assertFalse(nomination.get("blocking"))
        night = arranged_game("night", "night")
        self.assertNotIn(
            "vote.nominate", [item["id"] for item in actions_for(night, player(night, "1"))]
        )

    def test_a_seat_that_cannot_nominate_does_not_hold_up_the_phase(self):
        """傀儡等当前牌不能行动的席位没有提名按钮，就只能视为跳过，否则阶段永远卡住。"""
        game = arranged_game("nomination")
        game["cards"][game["seats"][1]["cards"][0]]["states"]["no_ability"] = True
        self.assertNotIn("2", pending_nominators(game))
        offered = [item["id"] for item in actions_for(game, player(game, "2"))]
        self.assertNotIn("vote.nominate", offered)
        for sid in ("1", "3", "4", "5", "6", "7"):
            command(game, player(game, sid), "vote.pass", {})
        command(game, HOST, "host.advance", {})
        self.assertEqual(game["phase"], "execution")

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


class ActionDescriptions(unittest.TestCase):
    """行动说明由服务端下发，客户端只负责渲染：每个行动都要带非空说明。"""

    def test_every_offered_action_carries_a_description(self):
        # 玩家点开行动先看到说明；漏一个 id 就会退回「无说明」的空窗，
        # 所以按阶段扫一遍双方实际能拿到的行动，而不是抽查。
        for phase in ("ordering", "witch", "night", "night_results", "speech", "voting"):
            for half in ("day", "night"):
                game = arranged_game(phase, half)
                game["public"]["speaker"] = "2"
                actors = [HOST] + [player(game, s["id"]) for s in game["seats"]]
                for actor in actors:
                    for action in actions_for(game, actor):
                        with self.subTest(phase=phase, half=half, action=action["id"]):
                            self.assertTrue(action["description"].strip())

    def test_the_vote_action_names_the_candidate_and_the_threshold(self):
        game = arranged_game("nomination")
        command(game, player(game, "2"), "vote.nominate", {"target": "3"})
        for sid in ("4", "1", "3", "5", "6", "7"):
            command(game, player(game, sid), "vote.pass")
        command(game, HOST, "host.advance")
        self.assertEqual(game["public"]["votes"]["candidate"], "3")
        action = next(
            item
            for item in actions_for(game, player(game, "4"))
            if item["id"] == "vote.cast"
        )
        self.assertIn("3号", action["label"])
        self.assertIn("候选：3号", action["description"])
        self.assertIn("至少4票", action["description"])

    def test_a_disguised_skill_says_it_can_be_challenged(self):
        game = arranged_game()
        game["seats"][6]["cards"] = ["honoka", "nanoka"]
        game["cards"]["honoka"]["states"]["disguise"] = "marg"
        fake = next(
            item
            for item in actions_for(game, player(game, "7"))
            if item["id"] == "day.skill"
        )
        self.assertIn("伪装声明", fake["description"])
        self.assertIn("可质疑", fake["description"])


if __name__ == "__main__":
    unittest.main()
