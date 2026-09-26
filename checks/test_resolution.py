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
from backend.app.game.actions import (
    actions_for,
    can_day_ability,
    challengeable,
    outstanding_seats,
    seat_options,
)
from backend.app.game.engine import open_vote, timeout_seat
from backend.app.game.resolution import (
    begin_night,
    damage_preview,
    death_batch,
    lock_night,
    loved_card_id,
    millia_substitute,
    night_damage,
    prepare_night_preview,
    unlock_coco,
    revive,
    treasure_protected,
    witch_witness_targets,
)
from backend.app.game.state import (
    ballot_complete,
    check_winner,
    current,
    effect_effective,
    eligible_voters,
    nomination_rounds,
    owner,
    pending,
    pending_nominators,
    poison_sources,
    protection_active,
    rewind,
    save_snapshot,
    seat_choice,
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
            self.assertTrue(effect_effective(game, game["cards"]["millia"], "测试技能"))
            self.assertFalse(effect_effective(game, game["cards"]["millia"], "测试技能"))
        self.assertEqual([entry["kind"] for entry in game["log"][-2:]], ["poison", "poison"])

    def test_poisoned_witch_knife_is_not_a_skill_and_still_kills(self):
        """魔女杀人不算技能：中毒不为魔女刀掷效果骰，刀口照常生效。"""
        game = arranged_game(phase="night", half="night")
        # 把可可换到席2的上层，使其成为当前牌并吃到相邻艾玛的中毒。
        game["seats"][1]["cards"] = ["coco", "hiro"]
        self.assertIn("艾玛毒素", poison_sources(game, game["cards"]["coco"]))
        game["night"] = {
            "actors": ["2"],
            "confirmed": ["2"],
            "locked": False,
            "reactions": [],
            "actions": [
                {
                    "seat_id": "2",
                    "card_id": "coco",
                    "ability": "knife",
                    "target_card": "millia",
                    "target_seat": "1",
                    "confirmed": True,
                }
            ],
        }
        with patch("backend.app.game.state.SystemRandom") as random:
            random.return_value.randrange.return_value = 1  # 即便骰到「无效」也不该消耗
            lock_night(game, [])
        self.assertTrue(game["night"]["actions"][0]["effective"])
        self.assertEqual([entry for entry in game["log"] if entry["kind"] == "poison"], [])
        deaths = {death["target_card"] for death in game["night"]["preview"]["deaths"]}
        self.assertIn("millia", deaths)

    def test_only_photo_still_rolls_the_poison_die(self):
        """效果类里只剩「赠送信物」吃中毒骰：信物仍会被判假，其他真实声明不受影响。"""
        game = arranged_game()
        game["seats"][1]["cards"] = ["coco", "hiro"]
        game["cards"]["coco"]["states"]["poisoned"] = True
        with patch("backend.app.game.state.SystemRandom") as random:
            random.return_value.randrange.return_value = 1  # 中毒骰值1：信物失效
            command(game, player(game, "2"), "day.skill", {"ability": "photo", "target": "1"})
        self.assertTrue(game["declarations"][-1]["fake"])
        self.assertFalse(game["photos"])

        other = arranged_game()
        other["seats"][0]["cards"] = ["emma", "millia"]
        other["cards"]["emma"]["states"]["poisoned"] = True
        command(other, player(other, "1"), "day.skill", {"ability": "interrupt", "target": "2"})
        self.assertFalse(other["declarations"][-1]["fake"])
        # 自由发言阶段没有「当前发言人」，打断只消耗当天次数，不抢占发言位。
        self.assertNotIn("interrupted_speaker", other["public"])
        self.assertEqual(other["cards"]["emma"]["uses"].get("interrupt_day"), other["day"])
        self.assertEqual([entry for entry in other["log"] if entry["kind"] == "poison"], [])

    def test_poisoned_night_actions_still_resolve(self):
        """夜间技能不再吃中毒骰：中毒的诺亚下雨照样生效，也不再写中毒日志。"""
        game = arranged_game("night", "night")
        game["cards"]["noah"]["states"]["poisoned"] = True
        game["night"] = {
            "actors": {"6": "noah"},
            "actions": [
                {
                    "card_id": "noah",
                    "seat_id": "6",
                    "ability": "rain",
                    "target_card": "millia",
                    "target_seat": "1",
                    "confirmed": True,
                }
            ],
            "confirmed": ["6"],
            "locked": False,
            "preview": None,
            "reactions": [],
        }
        lock_night(game, [])
        self.assertTrue(game["night"]["rain"])
        self.assertTrue(game["cards"]["noah"]["uses"]["rain"])
        self.assertEqual([entry for entry in game["log"] if entry["kind"] == "poison"], [])

    def test_status_projection_hides_poison_source_and_host_secrets(self):
        game = arranged_game()
        game["cards"]["noah"]["states"]["display_killer"] = "coco"
        player_view = game_view(game, player(game, "1"))
        self.assertNotIn(
            "poison", [item["id"] for item in player_view["self"]["statuses"]]
        )
        for card in player_view["self"]["cards"]:
            self.assertNotIn("poisoned", card["states"])
        # 其他席位的牌面明细本来就不下发给玩家。
        self.assertTrue(all("cards" not in seat for seat in player_view["seats"]))
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

    def test_challenging_a_fake_mass_brainwash_reverts_its_own_effects(self):
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
            game["spiritual"]["annan_penalty"]["6"]["declaration_id"], declaration["id"]
        )
        command(
            game,
            player(game, "2"),
            "day.challenge",
            {"declaration_id": declaration["id"]},
        )
        # 质疑成功只撤销这次声明自己的效果：处决名单与次日处罚一并撤回。
        self.assertNotIn("millia", game["execution"])
        self.assertNotIn("6", game["spiritual"]["annan_penalty"])

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
    def test_the_first_injury_only_marks_the_card(self):
        game = arranged_game("night_review", "night")
        preview = damage_preview(
            game,
            [{"target_card": "marg", "source_card": "arisa", "once_injury": True}],
        )
        self.assertTrue(preview["injured"]["marg"])
        self.assertFalse(preview["deaths"])

    def test_a_second_injury_always_kills(self):
        """负伤没有「只负伤一次、永不升级」的例外：已有负伤时再次负伤无条件出局。"""
        game = arranged_game("night_review", "night")
        game["cards"]["marg"]["injured"] = True
        preview = damage_preview(
            game,
            [{"target_card": "marg", "source_card": "arisa", "once_injury": True}],
        )
        self.assertEqual([death["target_card"] for death in preview["deaths"]], ["marg"])

    def test_marg_love_blocks_every_death_and_other_injury(self):
        """玛格的爱优先级最高：爱人只吃玛格每夜那一次负伤。"""
        game = arranged_game("night_review", "night")
        game["marg_love"] = {"seat_id": "2", "day": 2}
        game["cards"]["hiro"]["injured"] = True
        knife = damage_preview(
            game, [{"target_card": "hiro", "source_card": "coco", "cause": "knife"}]
        )
        self.assertFalse(knife["deaths"])
        preview, _ = night_damage(game)
        self.assertFalse(preview["deaths"])
        self.assertTrue(preview["injured"]["hiro"])

    def test_guardian_priorities_put_the_loved_card_before_millia_substitution(self):
        """玛格的爱 > 米莉亚替死：爱人在换血目标上时，攻击不会转给米莉亚。"""
        game = arranged_game("night_review", "night")
        game["marg_love"] = {"seat_id": "2", "day": 2}
        game["millia_swap"] = {"seat": "2", "day": 2}
        game["night"]["reactions"] = []
        preview = damage_preview(
            game, [{"target_card": "hiro", "source_card": "coco", "cause": "knife"}]
        )
        self.assertFalse(preview["deaths"])

    def test_protection_is_resolved_before_millia_substitution(self):
        """庇护 > 米莉亚替死：这一次伤害不至于出局时，不会触发替死。"""
        game = arranged_game("night_review", "night")
        game["millia_swap"] = {"seat": "2", "day": 2}
        game["night"]["reactions"] = []
        preview = damage_preview(
            game,
            [{"target_card": "hiro", "source_card": "coco", "cause": "knife"}],
            protection=["hiro"],
        )
        self.assertFalse(preview["deaths"])
        self.assertTrue(preview["injured"]["hiro"])

    def test_treasure_only_clears_its_own_seat_and_protects_today(self):
        game = arranged_game("night", "night")
        game["cards"]["millia"]["alive"] = False
        begin_night(game, [])
        # 别的席位先提交一条行动：寻宝只清本席，不能把别人的行动一起清掉。
        command(game, player(game, "3"), "night.submit", {"ability": "protect", "target": "2"})
        with patch("backend.app.game.engine.SystemRandom") as random:
            random.return_value.randrange.return_value = 1
            command(game, player(game, "1"), "night.submit", {"ability": "treasure"})
        self.assertFalse(game["night"]["locked"])
        self.assertEqual(game["phase"], "night")
        self.assertEqual(game["cards"]["emma"]["states"]["treasure_protected_day"], 2)
        submitted = {(action["seat_id"], action["ability"]) for action in game["night"]["actions"]}
        self.assertIn(("3", "protect"), submitted)
        self.assertIn(("1", "treasure"), submitted)

    def test_witch_emma_has_no_treasure_and_must_massacre(self):
        game = arranged_game("night", "night")
        game["cards"]["millia"]["alive"] = False
        game["cards"]["emma"]["witch"] = True
        begin_night(game, [])
        offered = [
            item["payload"]["ability"]
            for item in actions_for(game, player(game, "1"))
            if item["id"] == "night.submit"
        ]
        self.assertNotIn("treasure", offered)
        self.assertIn("massacre", offered)

    def test_treasure_cannot_be_resubmitted_to_reroll_the_mine(self):
        """寻宝提交后本夜定局：重交、清除、超时放弃都不能重掷地雷骰。"""
        game = arranged_game("night", "night")
        game["cards"]["millia"]["alive"] = False
        begin_night(game, [])
        with patch("backend.app.game.engine.SystemRandom") as random:
            random.return_value.randrange.return_value = 0  # 第一次就踩雷
            command(game, player(game, "1"), "night.submit", {"ability": "treasure"})
        entry = next(a for a in game["night"]["actions"] if a["ability"] == "treasure")
        self.assertTrue(entry["mine"])
        # 重交被拒：骰值不会被重掷成安全结果。
        with patch("backend.app.game.engine.SystemRandom") as random:
            random.return_value.randrange.return_value = 1
            with self.assertRaises(GameError):
                command(game, player(game, "1"), "night.submit", {"ability": "treasure"})
        # 清除被拒：不能私下看到地雷结果后弃单洗白。
        with self.assertRaises(GameError):
            command(game, player(game, "1"), "night.clear")
        entry = next(a for a in game["night"]["actions"] if a["ability"] == "treasure")
        self.assertTrue(entry["mine"])
        # 行动表不再提供修改、清除或放弃入口，只剩确认。
        offered = [item["id"] for item in actions_for(game, player(game, "1"))]
        self.assertNotIn("night.submit", offered)
        self.assertNotIn("night.clear", offered)
        self.assertIn("night.confirm", offered)
        # 超时强制推进只补确认，寻宝行动保留。
        self.assertTrue(timeout_seat(game, [], "1"))
        entry = next(a for a in game["night"]["actions"] if a["ability"] == "treasure")
        self.assertTrue(entry["mine"])
        self.assertIn("1", game["night"]["confirmed"])

    def test_treasure_without_mine_keeps_protection(self):
        """寻宝安全落地时保护照常生效，且换一天骰值重新掷。"""
        game = arranged_game("night", "night")
        game["cards"]["millia"]["alive"] = False
        begin_night(game, [])
        with patch("backend.app.game.engine.SystemRandom") as random:
            random.return_value.randrange.return_value = 1
            command(game, player(game, "1"), "night.submit", {"ability": "treasure"})
        self.assertEqual(game["cards"]["emma"]["states"]["treasure_protected_day"], 2)
        self.assertEqual(game["cards"]["emma"]["states"]["treasure_roll"]["day"], 2)

    def test_treasure_mine_resolves_in_the_night_batch(self):
        game = arranged_game("night", "night")
        game["cards"]["millia"]["alive"] = False
        begin_night(game, [])
        with patch("backend.app.game.engine.SystemRandom") as random:
            random.return_value.randrange.return_value = 0  # 触发地雷
            command(game, player(game, "1"), "night.submit", {"ability": "treasure"})
        self.assertNotIn("treasure_protected_day", game["cards"]["emma"]["states"])
        command(game, player(game, "1"), "night.confirm")
        game["night"]["confirmed"] = list(game["night"]["actors"])
        lock_night(game, [])
        deaths = {death["target_card"] for death in game["night"]["preview"]["deaths"]}
        self.assertEqual(deaths, {"emma"})

    def test_treasure_mine_is_never_substituted(self):
        game = arranged_game("night_review", "night")
        game["millia_swap"] = {"seat": "3", "day": 2}
        game["night"]["reactions"] = []
        attacks = [{"target_card": "meruru", "source_card": "emma", "cause": "treasure"}]
        preview = damage_preview(game, millia_substitute(game, attacks))
        self.assertEqual({death["target_card"] for death in preview["deaths"]}, {"meruru"})

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

    def test_nanoka_fires_all_six_bullets_re_picking_the_target_each_time(self):
        """临刑枪是连发：每枪重新选目标，命中率 1/6→6/6，打空即完成响应。"""
        game = arranged_game("execution")
        game["cards"]["emma"]["alive"] = False
        game["execution"] = ["nanoka"]
        game["execution_ready"] = []
        game["execution_shots"] = []
        with patch("backend.app.game.engine.SystemRandom") as random:
            random.return_value.randrange.return_value = 5  # 骰值恒为6：只有6/6那一枪命中
            for index in range(6):
                offered = [
                    item
                    for item in actions_for(game, player(game, "7"))
                    if item["id"] == "execution.shoot"
                ]
                self.assertEqual(len(offered), 1, f"第{index + 1}枪没有给出行动")
                # 每枪都重新选目标：目标席位在两席之间轮换。
                command(
                    game,
                    player(game, "7"),
                    "execution.shoot",
                    {"target": "2" if index % 2 else "3"},
                )
        self.assertEqual(
            [roll["threshold"] for roll in game["execution_rolls"]], [1, 2, 3, 4, 5, 6]
        )
        self.assertEqual(
            [roll["target_card"] for roll in game["execution_rolls"]],
            ["meruru", "hiro", "meruru", "hiro", "meruru", "hiro"],
        )
        self.assertEqual(len(game["execution_shots"]), 1)
        self.assertEqual(game["cards"]["nanoka"]["uses"], {"bullets": 0, "shot_misses": 0})
        # 打空即完成响应：不再有待办，也不再给出开枪或收手行动。
        self.assertIn("7", game["execution_ready"])
        self.assertNotIn("7", outstanding_seats(game))
        self.assertEqual(
            [
                item["id"]
                for item in actions_for(game, player(game, "7"))
                if item["id"].startswith("execution.")
            ],
            [],
        )

    def test_nanoka_may_stop_firing_early_and_a_hit_resets_the_ladder(self):
        game = arranged_game("execution")
        game["cards"]["emma"]["alive"] = False
        game["execution"] = ["nanoka"]
        game["execution_ready"] = []
        game["execution_shots"] = []
        with patch("backend.app.game.engine.SystemRandom") as random:
            random.return_value.randrange.return_value = 0  # 骰值1：1/6 也命中
            command(game, player(game, "7"), "execution.shoot", {"target": "3"})
            next_shot = next(
                item
                for item in actions_for(game, player(game, "7"))
                if item["id"] == "execution.shoot"
            )
            # 命中后重置：下一枪回到 1/6，并且行动说明要交代「每枪重新选目标」。
            self.assertIn("1/6", next_shot["label"])
            self.assertIn("重新选择目标", next_shot["description"])
            # 也可以收手：收手后不再有待办，已打出的枪照常结算。
            command(game, player(game, "7"), "execution.confirm", {})
        self.assertEqual(game["cards"]["nanoka"]["uses"], {"bullets": 5, "shot_misses": 0})
        self.assertIn("7", game["execution_ready"])
        self.assertNotIn("7", outstanding_seats(game))
        command(game, HOST, "host.advance", {})
        self.assertFalse(game["cards"]["meruru"]["alive"])
        self.assertFalse(game["cards"]["nanoka"]["alive"])

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

    def test_millia_only_takes_over_deaths_and_only_the_execution_gun(self):
        # 白天普通伤害不替死：主持人裁定直接打到换血对象身上。
        game = arranged_game("discussion", "day")
        game["millia_swap"] = {"seat": "3", "day": 1}
        game["seats"][2]["avatar_role_id"] = "meruru"
        death_batch(
            game,
            [],
            damage_preview(game, [{"target_card": "meruru", "source_card": "coco", "cause": "host"}]),
        )
        self.assertTrue(game["cards"]["millia"]["alive"])
        self.assertFalse(game["cards"]["meruru"]["alive"])

        # 处刑不替死：目标按处刑出局。
        game = arranged_game("execution", "day")
        game["millia_swap"] = {"seat": "3", "day": 2}
        preview = damage_preview(
            game, [{"target_card": "meruru", "source_card": None, "cause": "execution"}]
        )
        death_batch(game, [], preview)
        self.assertFalse(game["cards"]["meruru"]["alive"])
        self.assertTrue(game["cards"]["millia"]["alive"])

        # 临刑开枪是白天唯一会替死的伤害。
        game = arranged_game("execution", "day")
        game["millia_swap"] = {"seat": "3", "day": 2}
        attacks = millia_substitute(
            game, [{"target_card": "meruru", "source_card": "nanoka", "cause": "shoot"}]
        )
        death_batch(game, [], damage_preview(game, attacks))
        self.assertFalse(game["cards"]["millia"]["alive"])
        self.assertTrue(game["cards"]["meruru"]["alive"])

    def test_millia_only_substitutes_a_lethal_hit(self):
        # 非致死的负伤裁定不转移：负伤落到目标身上，米莉亚不受影响。
        game = arranged_game("discussion", "day")
        game["millia_swap"] = {"seat": "3", "day": 2}
        preview = damage_preview(
            game,
            millia_substitute(
                game, [{"target_card": "meruru", "source_card": None, "cause": "host", "injury": True}]
            ),
        )
        self.assertFalse(preview["deaths"])
        self.assertTrue(preview["injured"]["meruru"])
        self.assertFalse(preview["injured"]["millia"])

        # 目标已经负伤时，同一击会真的致死，这时才转移给米莉亚。
        game = arranged_game("discussion", "day")
        game["millia_swap"] = {"seat": "3", "day": 2}
        game["cards"]["meruru"]["injured"] = True
        preview = damage_preview(
            game,
            millia_substitute(
                game, [{"target_card": "meruru", "source_card": None, "cause": "host", "injury": True}]
            ),
        )
        self.assertEqual({death["target_card"] for death in preview["deaths"]}, {"millia"})
        self.assertTrue(game["cards"]["meruru"]["alive"])

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
        prepare_night_preview(game)
        self.assertFalse(any(item["kind"] == "millia" for item in game["pending"]))
        deaths = {death["target_card"] for death in game["night"]["preview"]["deaths"]}
        self.assertEqual(deaths, {"millia"})
        self.assertTrue(game["cards"]["meruru"]["alive"])

    def test_poisoned_millia_still_substitutes_without_poison_roll(self):
        # 米莉亚的换血与替死不吃中毒效果骰：与艾玛同席中毒时仍然替死，也不写中毒日志。
        game = arranged_game("night_review", "night")
        self.assertIn("艾玛毒素", poison_sources(game, game["cards"]["millia"]))
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
        with patch("backend.app.game.state.SystemRandom") as random:
            random.return_value.randrange.return_value = 1  # 即便骰到「无效」也不该消耗
            prepare_night_preview(game)
        self.assertEqual([entry for entry in game["log"] if entry["kind"] == "poison"], [])
        deaths = {death["target_card"] for death in game["night"]["preview"]["deaths"]}
        self.assertEqual(deaths, {"millia"})

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
        game["spiritual"]["annan_penalty"]["6"] = 3
        game["cards"]["hiro"]["witch"] = True
        game["information"].append(
            {"id": "memory", "title": "线索", "text": "保留记忆", "audience": ["p1"]}
        )
        rewind(game, snap["id"], [], mode="witch")
        self.assertEqual(game["cards"]["nanoka"]["uses"]["bullets"], 6)
        self.assertEqual(game["seats"][0]["occupant_id"], "substitute")
        self.assertTrue(game["spiritual"]["sherry_bound"])
        self.assertEqual(game["spiritual"]["annan_penalty"]["6"], 3)
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
        # 未提名或放弃的席位仍是待办：系统不会自动推进，等主持人处理。
        self.assertEqual(set(pending_nominators(game)), {"3", "5", "6", "7"})
        self.assertFalse(
            any(item["kind"] == "advance" and item["blocking"] for item in host_tasks(game))
        )
        for sid in ("3", "5", "6", "7"):
            command(game, player(game, sid), "vote.pass")
        command(game, HOST, "host.advance")
        votes = game_view(game, player(game, "1"))["public"]["votes"]
        self.assertEqual([item["seat_id"] for item in votes["candidates"]], ["3"])
        self.assertEqual(votes["total"], 1)

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

    def test_failed_challenge_seat_shows_no_duplicate_upper_avatar(self):
        """质疑失败整席出局：下层牌从未公示过，不得把上层牌当下牌标记重复显示。

        公开头像一直是上层牌（质疑失败不换头像），若仍下发 previous_role_id，
        状态页的双头像会渲染成两张一样的上层牌；下层牌只能显示中性占位。
        """
        game = arranged_game("discussion")
        # 走一次真实的开局：公开头像由开局锁定，之后质疑失败不换头像。
        # 开局进入的是第1夜魔女化阶段，这里把对局拨回第2天白天再质疑。
        game.update(status="lobby", phase="ordering", day=1, half="night")
        for seat in game["seats"]:
            seat["ready"] = True
        command(game, HOST, "host.start")
        game.update(status="playing", phase="discussion", half="day", day=2)
        game["seats"][0]["cards"] = ["emma", "millia"]
        command(game, player(game, "1"), "day.skill", {"ability": "interrupt", "target": "2"})
        declaration = game["declarations"][0]
        command(game, player(game, "3"), "day.challenge", {"declaration_id": declaration["id"]})
        seats = {seat["id"]: seat for seat in game_view(game, player(game, "1"))["seats"]}
        self.assertIsNone(seats["3"]["previous_role_id"])
        self.assertEqual(seats["3"]["avatar_role_id"], "meruru")
        self.assertFalse(seats["3"]["alive"])
        # 对照：正常的单牌出局（上层牌出局、下层登场）仍保留“上层→下层”两个名字。
        game2 = arranged_game()
        command(
            game2,
            HOST,
            "host.damage",
            {"targets": ["meruru"], "effect": "death", "source": "coco", "reason": "测试白天出局"},
        )
        seats2 = {seat["id"]: seat for seat in game_view(game2, player(game2, "1"))["seats"]}
        self.assertEqual(seats2["3"]["previous_role_id"], "meruru")
        self.assertEqual(seats2["3"]["avatar_role_id"], "hanna")

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

    def test_challengeable_claims_exclude_photo_love_and_gaze(self):
        game = arranged_game("discussion")
        game["seats"][0]["cards"] = ["emma", "millia"]
        command(game, player(game, "1"), "day.skill", {"ability": "interrupt", "target": "2"})
        game["seats"][2]["cards"] = ["annan", "meruru"]
        game["cards"]["annan"]["witch"] = True
        command(game, player(game, "3"), "day.skill", {"ability": "mass_brainwash", "target": "4"})
        game["seats"][3]["cards"] = ["marg", "sherry"]
        command(game, player(game, "4"), "day.skill", {"ability": "love", "target": "2"})
        game["seats"][6]["cards"] = ["honoka", "nanoka"]
        game["cards"]["honoka"]["states"]["disguise"] = "annan"
        command(game, player(game, "7"), "day.skill", {"ability": "mass_brainwash", "target": "5"})
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
                    ids["mass_brainwash(伪装)"],
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

    def test_honoka_bottom_disguise_waits_for_entry_and_locks_on_appearing(self):
        game = arranged_game()
        game.update(status="lobby", phase="ordering", day=1, half="night")
        game["seats"][6]["cards"] = ["nanoka", "honoka"]
        for seat in game["seats"]:
            seat["ready"] = True
        command(game, player(game, "7"), "honoka.disguise", {"role": "emma"})
        command(game, HOST, "host.start")
        # 未登场：选择先留着，别人看到的仍是上层牌，而且还能继续改。
        self.assertEqual(game_view(game, player(game, "1"))["seats"][6]["avatar_role_id"], "nanoka")
        self.assertEqual(game["cards"]["honoka"]["states"]["disguise"], "emma")
        command(game, player(game, "7"), "honoka.disguise", {"role": "noah"})
        self.assertEqual(game["cards"]["honoka"]["states"]["disguise"], "noah")
        game["half"] = "day"
        death_batch(
            game,
            [],
            damage_preview(
                game, [{"target_card": "nanoka", "cause": "host", "unconditional": True}]
            ),
        )
        # 登场瞬间按先前选择示人并锁定，之后不能再改。
        self.assertEqual(game_view(game, player(game, "1"))["seats"][6]["avatar_role_id"], "noah")
        self.assertTrue(game["cards"]["honoka"]["states"]["disguise_locked"])
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
        # 天亮只发一条汇总：夜终死讯按席位合并，不再逐条 + 角色名各发一遍。
        self.assertIn(
            f"第{game['day']}夜：3号玩家一张角色牌出局。",
            [item["text"] for item in events],
        )
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
    def test_peaceful_night_and_merged_death_summary(self):
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
        # 3号的梅露露是当夜唯一死者：逐条死讯与夜终汇总已合并成一条。
        self.assertIn(
            f"第{game['day']}夜：3号玩家一张角色牌出局。",
            [item["text"] for item in events],
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
        # 复活撤销死亡本身：记录、公告与半天出局都回滚。
        self.assertTrue(game["cards"]["millia"]["alive"])
        self.assertNotIn("millia", [item["target_card"] for item in game["deaths"]])
        self.assertNotIn(death["notice"], game["queued_notices"])
        # 目击看的是「被魔女刀指到」而不是「出局」：复活后名单照发，只把标题改成当事人还在场。
        kept = [item for item in game["pending"] if item.get("death_id") == death["id"]]
        self.assertEqual(len(kept), 1)
        self.assertIn("已被复活", kept[0]["title"])
        self.assertIn("照发", kept[0]["title"])
        # 傀儡化：该牌无投票权、无技能，且控制者是 3 号的梅露露。
        self.assertEqual(game["cards"]["millia"]["states"]["puppet"], "meruru")
        self.assertTrue(game["cards"]["millia"]["states"]["no_ability"])
        self.assertEqual(
            [panel["seat_id"] for panel in game_view(game, player(game, "3"))["self"]["puppet_controls"]],
            ["1"],
        )
        # 投票阶段：控制者能以该傀儡席投票，傀儡本身不产生第二个身份。
        game.update(day=2, phase="voting", half="day")
        candidate = current(game, game["seats"][2])["id"]
        game["nominations"] = [{"seat_id": "3", "card_id": candidate, "by": "2"}]
        game["ballots"] = {}
        game["public"]["votes"] = {
            "candidates": [{"seat_id": "3", "card_id": candidate}],
            "total": 1,
            "results": [],
        }
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


class KnifeWitnessAlways(unittest.TestCase):
    """目击的触发条件是「被魔女袭击指到」，不是「因此出局」：无论死没死都要有目击。

    庇护把魔女刀降级成负伤、玛格的爱免除这一击、米莉亚替死把致死一击转走，当事人
    都不是死者，但仍然看见了袭击，因此照发四人目击名单；真正出局的席位仍走普通
    死亡路径，不重复发。
    """

    def knife_night(self, target="4", *, protect=None, love=None, swap=None):
        game = arranged_game("night", "night")
        # 2号的当前牌是希罗：把它变成魔女，就有了独立的一刀。
        game["cards"]["hiro"]["witch"] = True
        if love:
            game["marg_love"] = {"seat_id": love, "day": 2}
        begin_night(game, [])
        if protect:
            command(game, player(game, "3"), "night.submit", {"ability": "protect", "target": protect})
            command(game, player(game, "3"), "night.confirm", {})
        if swap:
            command(game, player(game, "1"), "night.submit", {"ability": "swap", "target": swap})
            command(game, player(game, "1"), "night.confirm", {})
        command(game, player(game, "2"), "night.submit", {"ability": "knife", "target": target})
        command(game, player(game, "2"), "night.confirm", {})
        return game

    def suspects_pending(self, game, seat):
        return next(
            (
                item
                for item in game["pending"]
                if item["kind"] == "suspects" and item["seat_id"] == seat
            ),
            None,
        )

    def test_a_plain_knife_death_still_gets_exactly_one_list(self):
        game = self.knife_night(target="4")
        command(game, HOST, "host.advance")  # 锁夜并生成预结算
        preview = game["night"]["preview"]
        self.assertEqual({death["target_card"] for death in preview["deaths"]}, {"marg"})
        command(game, HOST, "host.advance")  # 发布夜间结果
        pendings = [item for item in game["pending"] if item["kind"] == "suspects"]
        # 4号死于这一刀：由死亡路径发名单，新的「未出局」路径不能重复发一份。
        self.assertEqual([item["seat_id"] for item in pendings], ["4"])

    def test_a_protected_knife_target_gets_a_list_without_dying(self):
        game = self.knife_night(target="4", protect="4")
        command(game, HOST, "host.advance")
        preview = game["night"]["preview"]
        self.assertEqual(preview["deaths"], [])
        self.assertTrue(preview["injured"]["marg"])
        command(game, HOST, "host.advance")
        self.assertEqual(game["deaths"], [])
        item = self.suspects_pending(game, "4")
        self.assertIsNotNone(item, "被庇护降级成负伤的人也是被刀指到的人")
        self.assertIn("未出局", item["title"])
        # 主持人照常填四人名单，真凶（2号希罗）必须在里面，名单只发给被袭击的这一席。
        command(
            game,
            HOST,
            "host.resolve",
            {"pending_id": item["id"], "suspects": ["hiro", "coco", "emma", "nanoka"]},
        )
        self.assertEqual(game["witness"]["seat_id"], "4")
        self.assertIn("希罗", game["witness"]["text"])
        audiences = [
            entry["audience"] for entry in game["information"] if entry["title"] == "夜间目击名单"
        ]
        self.assertEqual(audiences, [["p4"]])

    def test_an_immune_knife_target_gets_a_list_too(self):
        # 玛格的爱把这一刀完全挡下：当事人没有受伤，但仍然算「被魔女刀指到」。
        game = self.knife_night(target="3", love="3")
        command(game, HOST, "host.advance")
        self.assertEqual(game["night"]["preview"]["deaths"], [])
        command(game, HOST, "host.advance")
        self.assertEqual(game["deaths"], [])
        self.assertIsNotNone(self.suspects_pending(game, "3"))

    def test_millia_substitution_leaves_the_original_target_with_a_list(self):
        game = self.knife_night(target="4", swap="4")
        command(game, HOST, "host.advance")
        preview = game["night"]["preview"]
        self.assertEqual({death["target_card"] for death in preview["deaths"]}, {"millia"})
        command(game, HOST, "host.advance")
        self.assertTrue(game["cards"]["marg"]["alive"])
        # 顶替死亡的米莉亚按死亡路径拿名单，被刀指到的 4 号也拿一份。
        self.assertIsNotNone(self.suspects_pending(game, "1"))
        self.assertIsNotNone(self.suspects_pending(game, "4"))

    def test_the_host_default_form_is_ready_to_submit(self):
        """主持人拿到的「被袭击未出局」待办，表单默认值必须直接可提交。"""
        game = self.knife_night(target="4", protect="4")
        command(game, HOST, "host.advance")
        command(game, HOST, "host.advance")
        item = self.suspects_pending(game, "4")
        ruling = next(
            action
            for action in game_view(game, HOST)["actions"]
            if action["id"] == "host.resolve"
            and action["payload"]["pending_id"] == item["id"]
        )
        payload = {
            entry["name"]: entry.get("default")
            for entry in ruling["fields"]
            if entry.get("type") != "checkbox"
        }
        command(game, HOST, "host.resolve", {"pending_id": item["id"], **payload})
        self.assertEqual(game["witness"]["seat_id"], "4")

    def test_the_cause_scope_is_every_witch_attack_and_nothing_else(self):
        """魔女刀、额外攻击、全场攻击都算「魔女袭击」；13水与邻座负伤不是。"""
        game = arranged_game("night", "night")
        attacks = [
            {"target_card": "marg", "source_card": "emma", "cause": "knife"},
            {"target_card": "sherry", "source_card": "emma", "cause": "massacre"},
            {"target_card": "hiro", "source_card": "hanna", "cause": "extra_kill"},
            {"target_card": "meruru", "source_card": "emma", "cause": "massacre"},
            {"target_card": "leia", "source_card": "coco", "cause": "water"},
            {"target_card": "noah", "source_card": "arisa", "cause": "arisa_injure"},
        ]
        # 全场攻击会把上下两张牌都列出来：名单按席位发，victim 取该席当前牌。
        self.assertEqual(
            [(item["seat_id"], item["victim"], item["cause"]) for item in witch_witness_targets(game, attacks)],
            [("4", "marg", "knife"), ("2", "hiro", "extra_kill"), ("3", "meruru", "massacre")],
        )

    def test_water_is_not_a_knife_so_a_survivor_gets_nothing(self):
        """13水不是魔女袭击：被庇护挡下、没出局就没有目击（死亡时仍按原规则发）。"""
        game = arranged_game("night", "night")
        begin_night(game, [])
        command(game, HOST, "host.water", {"seat_id": "3"})
        command(game, player(game, "3"), "night.submit", {"ability": "protect", "target": "4"})
        command(game, player(game, "3"), "night.confirm", {})
        command(game, player(game, "3"), "water.use", {"target": "4"})
        command(game, HOST, "host.advance")
        self.assertEqual(game["deaths"], [])
        self.assertTrue(game["night"]["preview"]["injured"]["marg"])
        command(game, HOST, "host.advance")
        self.assertFalse(any(item["kind"] == "suspects" for item in game["pending"]))

    def test_reviving_a_water_victim_still_drops_its_witness(self):
        game = arranged_game("night", "night")
        game["cards"]["meruru"]["witch"] = True
        begin_night(game, [])
        # 先把米莉亚的换血钉死在2号：免得强制推进时随机换到4号，把毒杀转成替死。
        command(game, player(game, "1"), "night.submit", {"ability": "swap", "target": "2"})
        command(game, player(game, "1"), "night.confirm", {})
        command(game, HOST, "host.water", {"seat_id": "3"})
        command(game, player(game, "3"), "water.use", {"target": "4"})
        command(game, HOST, "host.advance")  # 锁夜 + 预结算
        command(game, HOST, "host.advance")  # 未隐藏死因：系统直接发固定四人目击
        death = next(item for item in game["deaths"] if item["target_card"] == "marg")
        self.assertEqual(game["witness"]["death_id"], death["id"])
        command(game, player(game, "3"), "meruru.revive", {"death_id": death["id"]})
        self.assertIsNone(game["witness"])
        self.assertFalse(any(item["kind"] == "suspects" for item in game["pending"]))


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

    def test_a_rewind_never_reveals_the_lower_cards_of_the_same_batch(self):
        """希罗被处决触发回溯：与希罗同时死亡的人也不能亮出下层牌。"""
        game = arranged_game()
        game.update(day=1, phase="discussion")
        save_snapshot(game)
        game.update(day=2, phase="execution", half="day")
        game["execution"] = ["millia", "hiro"]
        events = command(game, HOST, "host.advance", {})
        self.assertEqual(game["day"], 1)
        self.assertEqual(game["phase"], "discussion")
        self.assertTrue(game["spiritual"]["hiro_used"]["normal"])
        # 整批死亡随回溯作废：没有死讯、没有下层登场，头像也不切到下层牌。
        self.assertEqual(game["deaths"], [])
        self.assertTrue(game["cards"]["millia"]["alive"])
        self.assertTrue(game["cards"]["hiro"]["alive"])
        # seats 不随快照还原：头像保持出局前的公开形象，即上层米莉亚。
        self.assertEqual(game["seats"][0]["avatar_role_id"], "millia")
        self.assertFalse([event for event in events if "下层角色" in event["text"]])
        self.assertTrue(any("回溯" in event["text"] for event in events))

    def test_a_rewind_restores_the_avatar_of_a_recovered_upper_card(self):
        """回溯恢复上层牌后，公开头像要跟着改回上层，不能停在下层牌。"""
        game = arranged_game()
        game.update(day=1, phase="discussion")
        save_snapshot(game)
        game.update(day=2, phase="discussion")
        # 1号上层米莉亚白天出局：公开头像切到下层艾玛，随后希罗死亡触发回溯。
        game["cards"]["millia"]["alive"] = False
        game["seats"][0]["avatar_role_id"] = "emma"
        command(
            game,
            HOST,
            "host.damage",
            {"targets": ["hiro"], "effect": "death", "source": "coco", "reason": "测试回溯头像"},
        )
        self.assertEqual(game["day"], 1)
        self.assertTrue(game["cards"]["millia"]["alive"])
        # 当前牌恢复为米莉亚（上层）：头像不能再是下层艾玛。
        self.assertEqual(game["seats"][0]["avatar_role_id"], "millia")
        self.assertEqual(current(game, game["seats"][0])["role_id"], "millia")

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

    def test_a_night_preview_rewind_is_announced_to_the_table(self):
        # 夜间预结算触发的希罗回溯曾经把公告写进空事件列表：额度照扣、整夜被打回
        # 重来，但玩家和主持人都看不到「游戏时间已回溯」。
        game = arranged_game("night", "night")
        game.update(day=1, phase="night", half="night")
        save_snapshot(game)
        game["cards"]["meruru"]["alive"] = False  # 3号当前牌变成汉娜
        game["night"] = {
            "actors": {"3": "hanna"},
            "actions": [
                {
                    "id": "knife",
                    "seat_id": "3",
                    "card_id": "hanna",
                    "ability": "knife",
                    "target_seat": "2",
                    "target_card": "hiro",
                    "confirmed": True,
                    "effective": True,
                    "title": "3号 · 魔女刀",
                }
            ],
            "confirmed": ["3"],
            "locked": False,
            "preview": None,
            "reactions": [],
            "extra_attacks": [],
        }
        events = command(game, HOST, "host.advance", {})
        self.assertTrue(game["spiritual"]["hiro_used"]["normal"])
        self.assertTrue(game["cards"]["hiro"]["alive"])
        self.assertEqual(game["day"], 1)
        self.assertTrue(
            any(item["text"].startswith("游戏时间已回溯") for item in events),
            [item["text"] for item in events],
        )


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


class WitchEmmaMassacre(unittest.TestCase):
    """魔女化艾玛第三天必定杀光全场：不能「放弃并确认」。"""

    def witch_emma_night(self):
        game = arranged_game("night", "night")
        # 艾玛是1号的下层牌，只有米莉亚出局后它才是1号的当前牌。
        game["cards"]["millia"]["alive"] = False
        game["cards"]["emma"]["witch"] = True
        begin_night(game, [])
        return game

    def test_witch_emma_cannot_confirm_without_the_massacre(self):
        game = self.witch_emma_night()
        with self.assertRaises(GameError):
            command(game, player(game, "1"), "night.confirm", {})
        self.assertNotIn("1", game["night"]["confirmed"])

    def test_submitting_the_massacre_confirms_the_night(self):
        game = self.witch_emma_night()
        command(game, player(game, "1"), "night.submit", {"ability": "massacre"})
        command(game, player(game, "1"), "night.confirm", {})
        self.assertIn("1", game["night"]["confirmed"])
        self.assertIn(
            "massacre",
            [action["ability"] for action in game["night"]["actions"] if action["seat_id"] == "1"],
        )


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
        # 预提交发言不再发系统消息：内容留在队列里，轮到时以玩家发言公开。
        self.assertEqual(
            [item["text"] for item in events if item["text"].startswith("4号")], []
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
        # 进度不再逐人发系统消息：由公开字段驱动两端的进度条与 10 秒倒计时。
        self.assertEqual([e for e in events if e["kind"] != "chat"], [])
        deadline = game["public"]["auto_advance_at"]
        self.assertIsNotNone(deadline)
        run_auto_advance(game, deadline - 1)
        self.assertEqual(game["phase"], "discussion")
        run_auto_advance(game, deadline + 1)
        self.assertEqual(game["phase"], "nomination")
        self.assertEqual(game["discussion_end_requests"], [])
        # 同一席位不能重复提交。
        with self.assertRaises(GameError):
            command(game, player(game, "6"), "discussion.request_end", {})

    def test_everyone_left_ends_free_discussion_when_fewer_than_six_remain(self):
        game = arranged_game("discussion")
        # 1、2 号两张牌都已出局：在场只剩 5 名可行动席位，不必凑满六个。
        for cid in ("millia", "emma", "hiro", "coco"):
            game["cards"][cid]["alive"] = False
        offered = next(
            item for item in actions_for(game, player(game, "3")) if item["id"] == "discussion.request_end"
        )
        self.assertEqual(offered["label"], "请求结束自由发言（已有0/5人提交）")
        # 死透的席位没有结束请求按钮，也不会被算进「全员」。
        self.assertNotIn(
            "discussion.request_end",
            [item["id"] for item in actions_for(game, player(game, "1"))],
        )
        # 进度条的分母也随视图下发，客户端不再写死 6。
        view = game_view(game, player(game, "3"))
        self.assertEqual(view["public"]["discussion_end_required"], 5)
        for sid in ("3", "4", "5", "6"):
            command(game, player(game, sid), "discussion.request_end", {})
        self.assertNotIn("auto_advance_at", game["public"])
        command(game, player(game, "7"), "discussion.request_end", {})
        deadline = game["public"]["auto_advance_at"]
        self.assertIsNotNone(deadline)
        run_auto_advance(game, deadline + 1)
        self.assertEqual(game["phase"], "nomination")


class NominationFlow(unittest.TestCase):
    """提名可提前提交、重复提名不失败、提名人自动投同意票。"""

    def test_pre_nominations_confirm_themselves_when_the_phase_opens(self):
        game = arranged_game("discussion")
        command(game, player(game, "1"), "vote.nominate", {"target": "3"})
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
        candidate = nomination_rounds(game)[0]["card_id"]
        self.assertEqual(
            game["public"]["votes"]["candidates"],
            [{"seat_id": "3", "card_id": candidate}],
        )
        self.assertEqual(game["public"]["votes"]["total"], 1)
        # 提名过同一候选的两个席位都自动投同意票，不再出现在待投名单里。
        self.assertEqual(seat_choice(game, "1", candidate), "yes")
        self.assertEqual(seat_choice(game, "2", candidate), "yes")
        self.assertNotIn("vote.cast", [item["id"] for item in actions_for(game, player(game, "1"))])
        for sid in ["3", "4", "5", "6", "7"]:
            command(game, player(game, sid), "vote.cast", {candidate: "no"})
            self.assertTrue(ballot_complete(game, sid))
        command(game, HOST, "host.advance", {})
        self.assertEqual(len(game["vote_rounds"]), 1)
        self.assertEqual(game["phase"], "execution")

    def test_a_nominated_candidate_row_is_locked_to_agree(self):
        """提名过某候选的行只剩「同意」：自动同意票是规则，不是默认值。"""
        game = arranged_game("nomination")
        command(game, player(game, "1"), "vote.nominate", {"target": "3"})
        command(game, player(game, "2"), "vote.nominate", {"target": "4"})
        for sid in ("3", "4", "5", "6", "7"):
            command(game, player(game, sid), "vote.pass")
        command(game, HOST, "host.advance")
        rounds = [item["card_id"] for item in nomination_rounds(game)]
        descriptor = next(
            item
            for item in actions_for(game, player(game, "1"))
            if item["id"] == "vote.cast"
        )
        # 两个候选各一行：提名过的那个锁成同意，另一个正常三选一。
        self.assertEqual([item["name"] for item in descriptor["fields"]], rounds)
        locked = descriptor["fields"][0]
        self.assertEqual(locked["default"], "yes")
        self.assertEqual([option["value"] for option in locked["options"]], ["yes"])
        self.assertEqual(locked["note"], "提名自动同意")
        with self.assertRaises(GameError):
            command(game, player(game, "1"), "vote.cast", {rounds[0]: "no", rounds[1]: "no"})
        command(game, player(game, "1"), "vote.cast", {rounds[0]: "yes", rounds[1]: "abstain"})
        self.assertEqual(seat_choice(game, "1", rounds[0]), "yes")
        self.assertEqual(seat_choice(game, "1", rounds[1]), "abstain")

    def test_seat_options_show_the_role_card_in_game_and_the_nickname_before_it(self):
        """对局内选择界面按「座位号 · 角色名」标识席位，候场仍用玩家公开称呼。"""
        game = arranged_game("discussion")
        game["seats"][2]["name"] = "阿雪"
        game["seats"][2]["avatar_role_id"] = "emma"
        self.assertEqual(dict(seat_options(game))["3"], "3号 · 艾玛")
        # 穗乃香示人之后，选择界面跟着显示示人身份。
        game["seats"][2]["avatar_role_id"] = "noah"
        self.assertEqual(dict(seat_options(game))["3"], "3号 · 诺亚")
        # 发牌与调序阶段不公开角色：那里仍是公开称呼。
        game["seats"][2]["avatar_role_id"] = None
        game["status"] = "lobby"
        self.assertEqual(dict(seat_options(game))["3"], "3号 · 阿雪")

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


class LeiaDuel(unittest.TestCase):
    """蕾雅决斗：失去技能、两张牌强制候选、半数门槛、必须至少同意一张。"""

    ALL_SEATS = ("1", "2", "3", "4", "5", "6", "7")

    def duel_game(self, phase="nomination"):
        game = arranged_game(phase, "day")
        command(game, player(game, "5"), "day.skill", {"ability": "duel", "target": "4"})
        return game

    def pass_nominations(self, game, skip=()):
        for sid in self.ALL_SEATS:
            if sid not in skip:
                command(game, player(game, sid), "vote.pass", {})

    def test_the_duel_pairs_the_two_cards_and_locks_the_skill(self):
        game = self.duel_game()
        self.assertEqual(
            game["duel"], {"day": 2, "leia_card": "leia", "target_card": "marg"}
        )
        self.assertEqual(game["cards"]["leia"]["uses"]["duel_day"], 2)
        self.assertFalse(can_day_ability(game, game["cards"]["leia"], "duel"))

    def test_both_duel_cards_vote_first_and_pass_at_half(self):
        game = self.duel_game()
        # 1号整席出局，分母变成 6：半数门槛与严格过半这时才不同。
        game["cards"]["millia"]["alive"] = False
        game["cards"]["emma"]["alive"] = False
        self.pass_nominations(game, skip=("1",))
        command(game, HOST, "host.advance", {})
        self.assertEqual(game["phase"], "voting")
        rounds = [item["card_id"] for item in nomination_rounds(game)]
        self.assertEqual([item["seat_id"] for item in nomination_rounds(game)], ["5", "4"])
        self.assertEqual(game["public"]["votes"]["total"], 2)
        # 一次提交两张决斗牌：每人至少同意一张，随后一次推进把两轮一起结算。
        for sid, approved in {
            "2": "leia",
            "3": "leia",
            "4": "leia",
            "5": "marg",
            "6": "marg",
            "7": "marg",
        }.items():
            command(
                game,
                player(game, sid),
                "vote.cast",
                {card: ("yes" if card == approved else "no") for card in rounds},
            )
        command(game, HOST, "host.advance", {})
        self.assertEqual(
            game["vote_rounds"][0],
            {"candidate": "5", "yes": 3, "denominator": 6, "threshold": 3, "passed": True},
        )
        self.assertEqual(
            game["vote_rounds"][1],
            {"candidate": "4", "yes": 3, "denominator": 6, "threshold": 3, "passed": True},
        )
        self.assertIn("leia", game["execution"])
        self.assertIn("marg", game["execution"])

    def test_every_voter_must_agree_to_one_of_the_two_duel_cards(self):
        game = self.duel_game()
        self.pass_nominations(game)
        command(game, HOST, "host.advance", {})
        rounds = [item["card_id"] for item in nomination_rounds(game)]
        descriptor = next(
            item
            for item in actions_for(game, player(game, "1"))
            if item["id"] == "vote.cast"
        )
        # 两张决斗牌各占一行，都带 duel 标记；说明里写明必须至少同意一张。
        duel_rows = [item for item in descriptor["fields"] if item.get("duel")]
        self.assertEqual([item["name"] for item in duel_rows], rounds)
        self.assertIn("至少同意其中一张", descriptor["description"])
        # 两张都不同意：整份选票被拒绝。
        with self.assertRaises(GameError):
            command(game, player(game, "1"), "vote.cast", {card: "no" for card in rounds})
        # 只提交其中一张同意也合规，而且表态过的席位不再欠这张同意票。
        command(game, player(game, "1"), "vote.cast", {rounds[0]: "yes", rounds[1]: "no"})
        self.assertEqual(seat_choice(game, "1", rounds[0]), "yes")
        self.assertTrue(game["duel_approvals"]["1"])
        self.assertTrue(ballot_complete(game, "1"))
        # 必填是整份选票：只报其中一行会被字段校验拦下。
        with self.assertRaises(GameError):
            command(game, player(game, "2"), "vote.cast", {rounds[0]: "yes"})

    def test_a_duel_card_leaving_mid_vote_does_not_shift_the_rounds(self):
        """投票一旦开始，候选表就固定：决斗对象中途出局也不会让下一轮错位。"""
        game = self.duel_game()
        self.pass_nominations(game)
        command(game, HOST, "host.advance", {})
        rounds = [item["card_id"] for item in nomination_rounds(game)]
        command(game, player(game, "1"), "vote.cast", {rounds[0]: "yes", rounds[1]: "no"})
        command(
            game,
            HOST,
            "host.state",
            {
                "card_id": "marg",
                "state": "alive",
                "value": False,
                "reason": "测试：决斗对象中途出局",
            },
        )
        self.assertFalse(game["cards"]["marg"]["alive"])
        self.assertEqual(game["phase"], "voting")
        # 候选表不随出局变化，剩下的人仍按同一张表把两张都投完。
        self.assertEqual([item["seat_id"] for item in nomination_rounds(game)], ["5", "4"])
        self.assertEqual(game["public"]["votes"]["total"], 2)
        descriptor = next(
            item
            for item in actions_for(game, player(game, "2"))
            if item["id"] == "vote.cast"
        )
        self.assertEqual([item["name"] for item in descriptor["fields"]], rounds)

    def test_bound_sherry_may_abstain_when_hanna_is_the_duel_target(self):
        game = arranged_game("nomination", "day")
        game["seats"][2]["cards"] = ["hanna", "meruru"]
        game["seats"][3]["cards"] = ["sherry", "marg"]
        game["spiritual"]["sherry_bound"] = True
        command(game, player(game, "5"), "day.skill", {"ability": "duel", "target": "3"})
        self.pass_nominations(game)
        command(game, HOST, "host.advance", {})
        rounds = [item["card_id"] for item in nomination_rounds(game)]
        descriptor = next(
            item
            for item in actions_for(game, player(game, "4"))
            if item["id"] == "vote.cast"
        )
        hanna_row = next(item for item in descriptor["fields"] if item["name"] == "hanna")
        # 绑定的雪莉不能同意处决汉娜：这一行根本没有「同意」选项。
        self.assertEqual([option["value"] for option in hanna_row["options"]], ["no", "abstain"])
        self.assertIn("绑定汉娜", hanna_row["note"])
        self.assertIn("蕾雅决斗", hanna_row["note"])
        self.assertTrue(hanna_row["duel"])
        with self.assertRaises(GameError):
            command(game, player(game, "4"), "vote.cast", {rounds[0]: "yes", "hanna": "yes"})
        # 她也不必被迫去投蕾雅：两张都弃票同样合规。
        command(game, player(game, "4"), "vote.cast", {card: "abstain" for card in rounds})
        self.assertEqual(seat_choice(game, "4", "hanna"), "abstain")
        self.assertFalse(game["duel_approvals"].get("4"))
        for sid in ("1", "2", "3", "5", "6", "7"):
            command(game, player(game, sid), "vote.cast", {rounds[0]: "yes", "hanna": "no"})
        command(game, HOST, "host.advance", {})
        # 蕾雅拿到 6 票通过，汉娜没有票：绑定雪莉的弃票进入分母但不计入同意。
        self.assertEqual(
            game["vote_rounds"][0],
            {"candidate": "5", "yes": 6, "denominator": 7, "threshold": 4, "passed": True},
        )
        self.assertEqual(
            game["vote_rounds"][1],
            {"candidate": "3", "yes": 0, "denominator": 7, "threshold": 4, "passed": False},
        )


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

    def test_unfinished_player_actions_no_longer_block_the_advance(self):
        """未完成的玩家行动不再是阻塞项：主持人可以直接推进让它们立刻超时。"""
        game = arranged_game("voting")
        candidate = current(game, game["seats"][2])["id"]
        game["nominations"] = [{"seat_id": "3", "card_id": candidate, "by": None}]
        game["public"]["votes"] = {
            "candidates": [{"seat_id": "3", "card_id": candidate}],
            "total": 1,
            "results": [],
        }
        game["ballots"] = {}
        tasks = game_view(game, HOST)["host"]["tasks"]
        self.assertTrue(any(item["kind"] == "voting" for item in tasks))
        for task in tasks:
            if task["action"] == "host.warn":
                self.assertFalse(task["blocking"])
        advance = next(item for item in tasks if item["id"] == "advance")
        self.assertFalse(advance["blocking"])
        self.assertIn("按超时处理", advance["detail"])


class ForceAdvance(unittest.TestCase):
    """主持人推进就是强制推进：未完成的玩家行动立刻按超时（视为放弃）处理。"""

    def test_force_advance_skips_the_rest_of_the_speech_round(self):
        game = arranged_game("speech")
        command(game, HOST, "host.speech", {"start": "1", "direction": "asc"})
        command(game, player(game, "4"), "speech.speak", {"text": "我提前写好了"})
        events = command(game, HOST, "host.advance", {})
        self.assertEqual(game["phase"], "discussion")
        self.assertIsNone(game["public"]["speaker"])
        # 提前写好的内容不随强制推进丢失，仍以玩家消息公开。
        self.assertIn("我提前写好了", [item["text"] for item in events if item["kind"] == "chat"])
        self.assertTrue(any("强制推进" in item["text"] for item in game["log"]))
        # 被跳过的席位只收到私下提示，不对全场公告。
        for event in events:
            if "按超时处理" in event["text"]:
                self.assertIsNotNone(event["audience"])

    def test_force_advance_abstains_every_missing_vote(self):
        game = arranged_game("nomination")
        command(game, player(game, "2"), "vote.nominate", {"target": "3"})
        # 其余席位未提名或放弃：强制推进把它们按超时处理，直接进入投票。
        command(game, HOST, "host.advance", {})
        self.assertEqual(game["phase"], "voting")
        candidate = nomination_rounds(game)[0]["card_id"]
        command(game, player(game, "1"), "vote.cast", {candidate: "yes"})
        command(game, HOST, "host.advance", {})
        self.assertEqual(seat_choice(game, "1", candidate), "yes")
        self.assertEqual(seat_choice(game, "2", candidate), "yes")
        for sid in ("3", "4", "5", "6", "7"):
            # 强制推进＝视为放弃：没交卷的席位整份选票记弃票。
            self.assertEqual(seat_choice(game, sid, candidate), "abstain")
        self.assertEqual(game["vote_rounds"][0]["yes"], 2)
        self.assertEqual(game["phase"], "execution")

    def test_force_advance_confirms_given_up_night_actions(self):
        game = arranged_game("night", "night")
        begin_night(game, [])
        waiting = outstanding_seats(game)
        self.assertTrue(waiting)
        command(game, HOST, "host.advance", {})
        self.assertEqual(set(game["night"]["confirmed"]), set(game["night"]["actors"]))
        self.assertTrue(game["night"]["locked"])
        self.assertIsNotNone(game["night"]["preview"])
        self.assertEqual(game["phase"], "night_review")

    def test_force_advance_still_refuses_while_a_ruling_is_pending(self):
        """待裁定事项不是玩家行动：强制推进不会替主持人做裁定。"""
        game = arranged_game("discussion")
        item = pending(game, "evidence", "遗留证物", seat_id="1", text="一句话")
        with self.assertRaises(GameError):
            command(game, HOST, "host.advance", {})
        self.assertEqual(game["phase"], "discussion")
        self.assertEqual([entry["id"] for entry in game["pending"]], [item["id"]])

    def test_force_advance_lets_the_honoka_witness_choice_time_out(self):
        game = arranged_game("night_results", "night")
        pending(
            game,
            "honoka_witness",
            "穗乃香被列入目击：等待本人选择显示角色",
            seat_id="1",
            victim="millia",
            witness_seat="1",
            suspects=["honoka", "emma", "noah", "coco"],
        )
        command(game, HOST, "host.advance", {})
        self.assertEqual(game["pending"], [])
        self.assertEqual(game["witness"]["seat_id"], "1")
        self.assertIn("穗乃香", game["witness"]["text"])
        self.assertEqual(game["phase"], "speech")


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
        candidate = nomination_rounds(game)[0]["card_id"]
        self.assertEqual(
            game["public"]["votes"]["candidates"],
            [{"seat_id": "3", "card_id": candidate}],
        )
        action = next(
            item
            for item in actions_for(game, player(game, "4"))
            if item["id"] == "vote.cast"
        )
        # 一次性选票：每个候选一行，字段名是角色牌 id，行上带该席的座位号。
        self.assertEqual([item["name"] for item in action["fields"]], [candidate])
        row = action["fields"][0]
        self.assertEqual(row["type"], "select")
        self.assertEqual(row["seat_id"], "3")
        self.assertIn("3号", row["label"])
        self.assertEqual(
            [option["value"] for option in row["options"]], ["yes", "no", "abstain"]
        )
        self.assertIn("3号", action["label"])
        self.assertIn("3号", action["description"])
        self.assertIn("至少4票", action["description"])
        self.assertTrue(2 <= len(action["short_label"]) <= 4)

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


class RuleRevisions(unittest.TestCase):
    """第五版结算：庇护过期、爱当晚生效、处决无条件、强制换血、安安后果按席位、提名窗口。"""

    def test_execution_ignores_protection_and_the_gun_still_respects_it(self):
        game = arranged_game("execution", "day")
        game["cards"]["meruru"]["states"]["protected_day"] = game["day"]
        game["execution"] = ["meruru"]
        command(game, HOST, "host.advance")
        self.assertFalse(game["cards"]["meruru"]["alive"])

        gun = arranged_game("execution", "day")
        gun["cards"]["meruru"]["states"]["protected_day"] = gun["day"]
        gun["execution_shots"] = [
            {"target_card": "meruru", "source_card": "nanoka", "cause": "shoot"}
        ]
        command(gun, HOST, "host.advance")
        self.assertTrue(gun["cards"]["meruru"]["alive"])
        self.assertTrue(gun["cards"]["meruru"]["injured"])

    def test_love_only_starts_working_from_that_night(self):
        game = arranged_game("discussion", "day")
        command(game, player(game, "4"), "day.skill", {"ability": "love", "target": "2"})
        # 声明当天白天还不生效：爱人照样会被处决。
        self.assertIsNone(loved_card_id(game))
        preview = damage_preview(
            game, [{"target_card": "hiro", "cause": "execution", "unconditional": True}]
        )
        self.assertEqual({death["target_card"] for death in preview["deaths"]}, {"hiro"})
        # 当天夜里开始生效：免疫处决，并且每夜吃玛格那一次负伤。
        game["half"] = "night"
        self.assertEqual(loved_card_id(game), "hiro")
        preview = damage_preview(
            game, [{"target_card": "hiro", "cause": "execution", "unconditional": True}]
        )
        self.assertFalse(preview["deaths"])

    def test_protection_expires_at_the_next_night(self):
        game = arranged_game("discussion", "day")
        game["cards"]["meruru"]["states"]["protected_day"] = game["day"]
        self.assertTrue(protection_active(game, game["cards"]["meruru"]))
        game["half"] = "night"
        self.assertTrue(protection_active(game, game["cards"]["meruru"]))
        game["day"] += 1
        game["half"] = "day"
        self.assertTrue(protection_active(game, game["cards"]["meruru"]))
        game["half"] = "night"
        self.assertFalse(protection_active(game, game["cards"]["meruru"]))

    def test_millia_must_swap_before_confirming(self):
        game = arranged_game("night", "night")
        begin_night(game, [])
        with self.assertRaises(GameError):
            command(game, player(game, "1"), "night.confirm", {})
        command(game, player(game, "1"), "night.submit", {"ability": "swap", "target": "3"})
        command(game, player(game, "1"), "night.confirm", {})
        self.assertIn("1", game["night"]["confirmed"])

    def test_millia_can_confirm_when_no_target_is_left(self):
        game = arranged_game("night", "night")
        for seat in game["seats"]:
            if seat["id"] != "1":
                for cid in seat["cards"]:
                    game["cards"][cid]["alive"] = False
        begin_night(game, [])
        command(game, player(game, "1"), "night.confirm", {})
        self.assertIn("1", game["night"]["confirmed"])

    def test_locking_the_night_forces_a_random_swap(self):
        game = arranged_game("night", "night")
        begin_night(game, [])
        game["night"]["confirmed"] = list(game["night"]["actors"])
        lock_night(game, [])
        self.assertTrue(game["night"]["locked"])
        self.assertNotEqual(game["millia_swap"]["seat"], "1")
        self.assertTrue(
            any(
                action["ability"] == "swap" and action.get("forced")
                for action in game["night"]["actions"]
            )
        )

    def test_clearing_the_night_drops_the_standing_swap(self):
        game = arranged_game("night", "night")
        begin_night(game, [])
        command(game, player(game, "1"), "night.submit", {"ability": "swap", "target": "3"})
        self.assertEqual(game["millia_swap"]["seat"], "3")
        command(game, player(game, "1"), "night.clear", {})
        self.assertIsNone(game["millia_swap"])

    def test_annan_penalty_follows_the_seat_instead_of_the_card(self):
        game = arranged_game("nomination", "day")
        game["cards"]["noah"]["alive"] = False  # 安安成为6号席的当前牌
        game["spiritual"]["annan_penalty"]["6"] = {
            "day": game["day"],
            "declaration_id": "x",
        }
        self.assertNotIn("6", [seat["id"] for seat in eligible_voters(game)])
        open_vote(game, [])
        self.assertEqual(game["execution"], ["annan"])

    def test_only_witch_hiro_can_exit_voluntarily(self):
        game = arranged_game("discussion", "day")
        self.assertNotIn("hiro.exit", {item["id"] for item in actions_for(game, player(game, "2"))})
        game["cards"]["hiro"]["witch"] = True
        self.assertIn("hiro.exit", {item["id"] for item in actions_for(game, player(game, "2"))})

    def test_witch_exit_spends_the_witch_rewind_once(self):
        game = arranged_game("discussion", "day")
        game["cards"]["hiro"]["witch"] = True
        save_snapshot(game)
        command(game, player(game, "2"), "hiro.exit", {})
        self.assertTrue(game["cards"]["hiro"]["alive"])
        self.assertTrue(game["spiritual"]["hiro_used"]["witch"])
        self.assertEqual(game["public"]["rewinds"], 1)
        command(game, player(game, "2"), "hiro.exit", {})
        self.assertFalse(game["cards"]["hiro"]["alive"])

    def test_interrupt_takes_the_floor_only_in_speech_order(self):
        game = arranged_game("speech")
        game["public"]["speech_order"] = [seat["id"] for seat in game["seats"]]
        game["public"]["speaker"] = "2"
        command(
            game,
            player(game, "1"),
            "day.skill",
            {"ability": "interrupt", "target": "2", "card_id": "emma"},
        )
        self.assertEqual(game["public"]["speaker"], "1")
        self.assertEqual(game["public"]["interrupted_speaker"], "2")
        command(game, player(game, "1"), "speech.done", {})
        self.assertEqual(game["public"]["speaker"], "2")
        self.assertNotIn("interrupted_speaker", game["public"])

    def test_interrupt_marker_is_cleared_at_nightfall(self):
        game = arranged_game("speech")
        game["public"]["speech_order"] = [seat["id"] for seat in game["seats"]]
        game["public"]["speaker"] = "2"
        command(
            game,
            player(game, "1"),
            "day.skill",
            {"ability": "interrupt", "target": "2", "card_id": "emma"},
        )
        game["phase"] = "dusk"
        game["pending"] = []
        command(game, HOST, "host.advance")
        self.assertNotIn("interrupted_speaker", game["public"])

    def test_witness_form_does_not_require_an_absent_hanna(self):
        game = arranged_game("night_review", "night")
        game["seats"][2]["cards"] = ["meruru", "hanna"]  # 汉娜在下层，尚未登场
        item = pending(
            game, "suspects", "填写名单", seat_id="2", victim="meruru", source_card="coco"
        )
        command(
            game,
            HOST,
            "host.resolve",
            {"pending_id": item["id"], "suspects": ["coco", "emma", "leia", "marg"]},
        )
        self.assertIsNotNone(game["witness"])
        self.assertNotIn("汉娜", game["witness"]["text"])

    def test_witness_form_default_fill_prefers_present_roles(self):
        game = arranged_game("night_review", "night")
        # 第4席（玛格+雪莉）整席出局，汉娜沉在第3席下层：三名角色都不在场。
        for cid in ("marg", "sherry"):
            game["cards"][cid]["alive"] = False
        item = pending(
            game, "suspects", "填写名单", seat_id="2", victim="meruru", source_card="coco"
        )
        form = next(a for a in actions_for(game, HOST) if a["payload"].get("pending_id") == item["id"])
        default = form["fields"][0]["default"]
        self.assertEqual(len(default), 4)
        # 真凶必勾；补位只勾当前在场角色（按魔典顺序）：
        # 出局的玛格、雪莉与未登场的汉娜都不进默认勾选。
        self.assertEqual(default[0], "coco")
        for absent in ("marg", "sherry", "hanna"):
            self.assertNotIn(absent, default)

    def test_nominating_during_voting_refreshes_the_candidate_list(self):
        game = arranged_game("voting", "day")
        game["nominations"] = [{"seat_id": "3", "card_id": "meruru", "by": "2"}]
        game["public"]["votes"] = {
            "candidates": [{"seat_id": "3", "card_id": "meruru"}],
            "total": 1,
            "results": [],
        }
        command(game, player(game, "5"), "vote.nominate", {"target": "6"})
        # 投票中新增的提名立刻进候选表：还没交卷的席位要连它一起补齐。
        self.assertEqual(game["public"]["votes"]["total"], 2)
        self.assertEqual(
            [item["seat_id"] for item in game["public"]["votes"]["candidates"]],
            ["3", "6"],
        )
        pending_names = [
            item["name"]
            for item in next(
                action
                for action in actions_for(game, player(game, "1"))
                if action["id"] == "vote.cast"
            )["fields"]
        ]
        self.assertIn("meruru", pending_names)
        self.assertEqual(len(pending_names), 2)
        # 1号先把这两名候选一次投完；之后又有新提名时只补新候选，不能重投旧票。
        second = game["public"]["votes"]["candidates"][1]["card_id"]
        command(game, player(game, "1"), "vote.cast", {"meruru": "yes", second: "no"})
        command(game, player(game, "4"), "vote.nominate", {"target": "7"})
        self.assertEqual(game["public"]["votes"]["total"], 3)
        reopen = next(
            action
            for action in actions_for(game, player(game, "1"))
            if action["id"] == "vote.cast"
        )
        self.assertEqual([item["seat_id"] for item in reopen["fields"]], ["7"])
        third = reopen["fields"][0]["name"]
        self.assertIn("只列你还没表态的1名候选", reopen["description"])
        with self.assertRaises(GameError):
            command(game, player(game, "1"), "vote.cast", {"meruru": "no", third: "yes"})
        self.assertEqual(seat_choice(game, "1", "meruru"), "yes")

    def test_nomination_buttons_are_gone_after_the_vote_phase(self):
        for phase in ("execution", "dusk"):
            game = arranged_game(phase, "day")
            offered = {item["id"] for item in actions_for(game, player(game, "2"))}
            with self.subTest(phase=phase):
                self.assertNotIn("vote.nominate", offered)
                self.assertNotIn("vote.pass", offered)

    def test_honoka_can_pick_a_disguise_before_she_appears(self):
        game = arranged_game()
        game["seats"][6]["cards"] = ["nanoka", "honoka"]
        honoka = player(game, "7")
        self.assertIn("honoka.disguise", {item["id"] for item in actions_for(game, honoka)})
        command(game, honoka, "honoka.disguise", {"role": "emma"})
        self.assertEqual(game["cards"]["honoka"]["states"]["disguise"], "emma")
        self.assertNotIn("disguise_locked", game["cards"]["honoka"]["states"])
        # 示人之后，穗乃香才按「艾玛」的技能声明伪装技能。
        command(game, honoka, "honoka.disguise", {"role": "noah"})
        self.assertEqual(game["cards"]["honoka"]["states"]["disguise"], "noah")


if __name__ == "__main__":
    unittest.main()
