"""Regression checks for rules that can silently spoil a hidden-role game."""

import unittest

from backend.app.game import DEFAULT_CODEX, GameError, apply_command, create_game, game_view
from backend.app.game.actions import actions_for
from backend.app.game.engine import sync_declarations
from backend.app.game.state import (
    DEAL_EXCLUDED_PAIRS,
    check_winner,
    deal_cards,
    seat_choice,
    upgrade_game,
)
from backend.app.views import action_prompt


HOST = {"id": "host", "kind": "host", "seat_id": None, "access_ids": ["host"]}

# 固定摆牌：1号是艾玛席（当前牌可可）、2号是另一个可转化席位，方便逐条核对
# 「艾玛优先 / 魔女阵营 A、B 补位 / 汉娜覆盖」三种第三天人选。
STAGED_PAIRS = [
    ["coco", "emma"],
    ["hiro", "millia"],
    ["leia", "arisa"],
    ["marg", "sherry"],
    ["meruru", "hanna"],
    ["noah", "annan"],
    ["nanoka", "honoka"],
]


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
    def test_dealing_never_duplicates_cards_or_pairs_excluded_roles(self):
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
                roles = {card["role_id"] for card in seat["cards"]}
                self.assertTrue(all(not {left, right}.issubset(roles) for left, right in DEAL_EXCLUDED_PAIRS))

    def test_upgrade_game_adds_the_new_rule_fields_without_replacing_history(self):
        game = create_game(DEFAULT_CODEX)
        deal_cards(game)
        game.pop("rules_revision")
        game["night"].pop("reactions")
        game.pop("marg_love")
        game.pop("duel")
        game.pop("duel_approvals")
        game.pop("ballots")
        game.pop("execution_shots")
        game.pop("execution_rolls")
        # 第六版以前的计票表：一次性投票改成 ballots 后这个字段整体作废。
        game["votes"] = {"1": "yes", "2": "no"}
        game["water"] = {"holder": "1", "used": False}
        game["pending"].append({"id": "stale", "kind": "lower_entry", "card_id": "honoka"})
        game["information"].append({"id": "kept"})
        # 第五版的旧局字段：布尔庇护改成日戳，安安后果从按牌改成按席位。
        game["cards"]["millia"]["states"]["protected"] = True
        game["spiritual"]["annan_penalty"]["annan"] = {"day": 3, "declaration_id": "old"}
        annan_seat = next(s["id"] for s in game["seats"] if "annan" in s["cards"])
        self.assertTrue(upgrade_game(game))
        self.assertEqual(game["rules_revision"], 6)
        self.assertEqual(game["night"]["reactions"], [])
        self.assertIsNone(game["marg_love"])
        self.assertIsNone(game["duel"])
        self.assertEqual(game["duel_approvals"], {})
        # 第六版：旧的轮次计票表换成整票 ballots；这一局不在投票阶段，不迁移内容。
        self.assertEqual(game["ballots"], {})
        self.assertNotIn("votes", game)
        # 处决阶段的临刑枪字段：旧局补齐为空，奈乃香开枪不再因缺键报错。
        self.assertEqual(game["execution_shots"], [])
        self.assertEqual(game["execution_rolls"], [])
        self.assertEqual(game["information"], [{"id": "kept"}])
        # 旧局的单瓶13水迁为一个未使用的持有席位；旧待办直接作废。
        self.assertEqual(game["water"], {"holders": ["1"]})
        self.assertEqual(game["pending"], [])
        self.assertNotIn("protected", game["cards"]["millia"]["states"])
        self.assertEqual(game["cards"]["millia"]["states"]["protected_day"], game["day"])
        self.assertEqual(
            game["spiritual"]["annan_penalty"][annan_seat],
            {"day": 3, "declaration_id": "old"},
        )
        self.assertFalse(upgrade_game(game))

    def test_a_legacy_save_stuck_in_the_execution_phase_can_still_fire_the_gun(self):
        """停在处决阶段的旧存档没有临刑枪字段：奈乃香开枪不能崩在写状态上。"""
        game = staged_game(day=2, half="day", phase="execution")
        game["execution"] = ["nanoka"]
        game["execution_ready"] = []
        del game["execution_shots"]
        game["rules_revision"] = 5
        self.assertTrue(upgrade_game(game))
        actor = {
            "id": game["seats"][6]["occupant_id"],
            "kind": "player",
            "game_id": game["id"],
            "seat_id": "7",
            "access_ids": [game["seats"][6]["occupant_id"]],
        }
        apply_command(game, actor, "execution.shoot", {"target": "3"})
        # 命中与否由骰子决定，只核对这一枪确实结算、扣了子弹，并且还能继续开枪。
        self.assertEqual(game["cards"]["nanoka"]["uses"]["bullets"], 5)
        self.assertEqual(len(game["execution_rolls"]), 1)
        self.assertLessEqual(len(game["execution_shots"]), 1)
        self.assertIn("execution.shoot", [item["id"] for item in actions_for(game, actor)])

    def test_upgrade_game_moves_a_mid_vote_save_into_the_ballot(self):
        """正停在投票阶段的旧存档：已经投出的当前轮选票要搬进 ballots，不逼玩家重投。"""
        game = staged_game(day=2, half="day", phase="voting")
        candidate = game["seats"][3]["cards"][0]
        game["nominations"] = [{"seat_id": "4", "card_id": candidate, "by": None}]
        game["votes"] = {"2": "no", "3": "yes"}
        del game["ballots"]
        self.assertTrue(upgrade_game(game))
        self.assertEqual(game["ballots"], {"2": {candidate: "no"}, "3": {candidate: "yes"}})
        self.assertNotIn("votes", game)
        self.assertEqual(seat_choice(game, "2", candidate), "no")
        self.assertEqual(seat_choice(game, "4", candidate), None)

    def test_upgrade_game_moves_a_removed_balloon_phase_to_nomination(self):
        """热气球整段移除后，停在旧阶段的存档不能因为查不到阶段名或技能名而崩溃。"""
        game = create_game(DEFAULT_CODEX)
        for actor in players(game):
            apply_command(game, actor, "lobby.ready", {})
        game["status"] = "playing"
        game["phase"] = "balloon"
        game["public"]["balloon"] = {
            "progress": 4,
            "participants": ["1"],
            "day": 1,
            "status": "collecting",
        }
        game["balloon_choices"] = {"1": "make"}
        game["balloon_proposal"] = {"by": "1", "participants": ["2"], "votes": {"1": True}}
        game["declarations"].append(
            {
                "id": "legacy-balloon",
                "day": game["day"],
                "seat_id": "1",
                "card_id": "legacy-card",
                "ability": "balloon",
                "fake": False,
                "by_host": False,
                "data": {"ability": "balloon", "participants": ["2"]},
                "status": "open",
                "executed": True,
            }
        )
        game["public"]["declarations"] = [
            {
                "id": "legacy-balloon",
                "seat_id": "1",
                "label": "组织热气球",
                "summary": "参与席位：2号",
                "status": "open",
            }
        ]
        self.assertTrue(upgrade_game(game))
        self.assertEqual(game["phase"], "nomination")
        self.assertNotIn("balloon", game["public"])
        self.assertNotIn("balloon_choices", game)
        self.assertNotIn("balloon_proposal", game)
        self.assertEqual(game["declarations"], [])
        self.assertEqual(game["public"]["declarations"], [])
        # 旧声明归档保留，而不是随玩法一起丢掉。
        self.assertEqual(
            [item["id"] for item in game["legacy_declarations"]], ["legacy-balloon"]
        )
        sync_declarations(game)
        visible = game_view(game, players(game)[0])
        self.assertEqual(visible["phase"], "nomination")
        self.assertNotIn("balloon", visible["public"])

    def test_player_views_hide_other_cards_while_spectator_gets_read_only_board(self):
        game = create_game(DEFAULT_CODEX)
        actors = players(game)
        for actor in actors:
            apply_command(game, actor, "lobby.ready", {})
        actor = actors[0]
        visible = game_view(game, actor)
        self.assertEqual(len(visible["self"]["cards"]), 2)
        self.assertFalse(visible.get("host"))
        # 魔女化命运只私下告知本人：公开视图里不能出现逐席布尔值，否则一眼看穿谁会魔女化。
        self.assertNotIn("witch_destiny", visible["public"])
        game["status"] = "playing"
        actor = actors[0]
        privately = game_view(game, actor)
        self.assertNotIn("witch_destiny", privately["public"])
        self.assertEqual(
            [s["id"] for s in privately["self"]["statuses"] if s["id"] == "witch_destiny"],
            ["witch_destiny"],
        )
        # 主持人仍看得到完整的命运表，才能核对与纠错。
        self.assertIn(
            "witch_destiny",
            game_view(game, {"id": "host", "kind": "host", "seat_id": None, "access_ids": ["host"]})[
                "public"
            ],
        )
        game["status"] = "lobby"
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
        # 候场/调序阶段不公开任何角色信息，观战替补入场前不得提前知情。
        self.assertTrue(all(not seat.get("cards") for seat in observer["seats"]))
        self.assertTrue(all("current_card_id" not in seat for seat in observer["seats"]))
        # 开局后观战者恢复只读棋盘。
        game["status"] = "playing"
        board = game_view(
            game,
            {
                "id": "observer",
                "kind": "spectator",
                "game_id": game["id"],
                "seat_id": None,
                "access_ids": ["observer"],
            },
        )
        self.assertTrue(all(len(seat["cards"]) == 2 for seat in board["seats"]))
        self.assertTrue(all(seat["current_card_id"] for seat in board["seats"]))

    def test_ready_progress_is_a_count_and_never_a_roster(self):
        game = create_game(DEFAULT_CODEX)
        actors = players(game)
        observer = {
            "id": "observer",
            "kind": "spectator",
            "game_id": game["id"],
            "seat_id": None,
            "access_ids": ["observer"],
        }
        apply_command(game, actors[0], "lobby.ready", {})
        self.assertTrue(game_view(game, actors[0])["seats"][0]["ready"])
        stranger = game_view(game, actors[1])
        self.assertEqual(stranger["ready_count"], 1)
        self.assertFalse(stranger["seats"][0]["ready"])
        self.assertTrue(
            all(seat["ready"] is None for seat in stranger["seats"] if seat["id"] != "2")
        )
        spectator = game_view(game, observer)
        self.assertEqual(spectator["ready_count"], 1)
        self.assertTrue(all(seat["ready"] is None for seat in spectator["seats"]))
        for actor in actors[1:]:
            apply_command(game, actor, "lobby.ready", {})
        self.assertEqual(game["phase"], "ordering")
        apply_command(game, actors[3], "lobby.ready", {})
        owner = game_view(game, actors[0])
        self.assertEqual(owner["ready_count"], 1)
        self.assertFalse(owner["seats"][0]["ready"])
        self.assertTrue(all(seat["ready"] is None for seat in owner["seats"] if seat["id"] != "1"))
        host = game_view(game, HOST)
        self.assertEqual(host["ready_count"], 1)
        self.assertTrue(host["seats"][3]["ready"])
        self.assertTrue(
            all(not seat["ready"] for index, seat in enumerate(host["seats"]) if index != 3)
        )

    def test_ready_action_stops_asking_once_the_player_is_ready(self):
        game = create_game(DEFAULT_CODEX)
        actors = players(game)

        def ready_action(actor):
            return next(item for item in actions_for(game, actor) if item["id"] == "lobby.ready")

        self.assertTrue(ready_action(actors[0])["blocking"])
        apply_command(game, actors[0], "lobby.ready", {})
        item = ready_action(actors[0])
        self.assertEqual(item["label"], "取消准备")
        self.assertFalse(item.get("blocking", False))
        self.assertTrue(ready_action(actors[1])["blocking"])

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
        apply_command(game, actors[0], "player.profile", {"name": "甲"})
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
        for actor in actors[:2]:
            own = game_view(game, actor)["self"]
            top = next(
                c["id"] for c in own["cards"] if c["role_id"] not in {"emma", "millia", "arisa"}
            )
            apply_command(game, actor, "lobby.order", {"top": top})
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
        pairs = [list(seat["cards"]) for seat in game["seats"]]
        own = game_view(game, actors[1])["self"]
        with self.assertRaises(GameError):
            apply_command(game, actors[1], "lobby.order", {"top": own["cards"][1]["id"]})
        with self.assertRaises(GameError):
            apply_command(game, actors[1], "lobby.ready", {})
        self.assertTrue(game["seats"][1]["ready"])
        self.assertEqual([seat["cards"] for seat in game["seats"]], pairs)
        self.assertEqual(game["phase"], "ordering")
        self.assertTrue(
            all(seat["avatar_role_id"] is None for seat in game_view(game, observer)["seats"])
        )
        apply_command(game, HOST, "host.start", {})
        self.assertEqual((game["status"], game["phase"]), ("playing", "witch"))
        self.assertEqual(
            [seat["avatar_role_id"] for seat in game_view(game, observer)["seats"]],
            [game["cards"][pair[0]]["role_id"] for pair in pairs],
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


def staged_game(day=3, half="night", phase="witch", faction=("1", "2")):
    """摆好一局可判定的中盘：固定牌面，并指定 A、B 两个魔女阵营席位。"""
    game = create_game(DEFAULT_CODEX)
    actors = players(game)
    for actor in actors:
        apply_command(game, actor, "lobby.ready", {})
    for actor in actors:
        apply_command(game, actor, "lobby.ready", {})
    apply_command(game, HOST, "host.start", {})
    for seat, pair in zip(game["seats"], STAGED_PAIRS):
        seat["cards"] = list(pair)
    for card in game["cards"].values():
        card["alive"] = True
        card["witch"] = False
    game.update(day=day, half=half, phase=phase, witch_checked_day=None, pending=[])
    game["public"]["witch_destiny"] = {
        "seats": [s["id"] in faction or "emma" in s["cards"] for s in game["seats"]],
        "first": list(faction),
    }
    return game


class WitchFactionRules(unittest.TestCase):
    """魔女阵营判定：开局告知、三天人选、汉娜魔化开关与好人胜利条件。"""

    def test_the_deal_tells_the_two_faction_seats_their_duty_day(self):
        game = create_game(DEFAULT_CODEX)
        actors = players(game)
        for actor in actors[:-1]:
            apply_command(game, actor, "lobby.ready", {})
        events = apply_command(game, actors[-1], "lobby.ready", {})
        faction = game["public"]["witch_destiny"]["first"]
        self.assertEqual(len(faction), 2)
        self.assertEqual(len(set(faction)), 2)
        notices = {
            e["audience"][0]: e["text"]
            for e in events
            if e.get("title") == "魔女化命运" and e.get("audience")
        }
        for index, seat_id in enumerate(faction):
            occupant = "participant-" + seat_id
            self.assertEqual(notices[occupant], f"你是魔女阵营：第{index + 1}天你的当前牌会魔女化。")
        # 非阵营席位照旧只知道自己会不会魔女化，不会看到「魔女阵营」这四个字。
        faction_occupants = {"participant-" + seat_id for seat_id in faction}
        others = [
            text for occupant, text in notices.items() if occupant not in faction_occupants
        ]
        self.assertTrue(others)
        self.assertTrue(all("魔女阵营" not in text for text in others))

    def test_third_night_is_emma_first_then_the_faction_pair(self):
        # 艾玛在场：以最高优先级成为当天魔女，即使 A 的当前牌也可转化。
        game = staged_game()
        apply_command(game, HOST, "host.advance", {})
        self.assertTrue(game["cards"]["emma"]["witch"])
        self.assertFalse(game["cards"]["coco"]["witch"])
        self.assertEqual(game["phase"], "night")

        # 艾玛已出局：由 A 的当前牌接替。
        game = staged_game()
        game["cards"]["emma"]["alive"] = False
        apply_command(game, HOST, "host.advance", {})
        self.assertTrue(game["cards"]["coco"]["witch"])
        self.assertFalse(game["cards"]["hiro"]["witch"])

        # A 的当前牌是不能魔女化的雪莉：轮到 B 的当前牌（B 席另一张不能是米莉亚/亚里沙）。
        game = staged_game(faction=("1", "6"))
        game["cards"]["emma"]["alive"] = False
        game["seats"][0]["cards"] = ["sherry", "emma"]
        game["seats"][3]["cards"] = ["marg", "coco"]
        apply_command(game, HOST, "host.advance", {})
        self.assertFalse(game["cards"]["sherry"]["witch"])
        self.assertTrue(game["cards"]["noah"]["witch"])

        # A、B 都已魔女化：不重复转化，也不报错。
        game = staged_game()
        game["cards"]["emma"]["alive"] = False
        game["cards"]["coco"]["witch"] = True
        game["cards"]["hiro"]["witch"] = True
        apply_command(game, HOST, "host.advance", {})
        self.assertEqual(game["phase"], "night")

    def test_the_third_night_fallback_never_witches_a_non_faction_seat(self):
        # A、B 的当前牌都不能魔女化时，第三天宁可当夜不产生新魔女，也不能退回魔典点别人。
        game = staged_game(faction=("1", "3"))
        game["cards"]["emma"]["alive"] = False
        game["seats"][0]["cards"] = ["sherry", "emma"]
        game["seats"][3]["cards"] = ["marg", "coco"]
        game["seats"][2]["cards"] = ["arisa", "leia"]
        apply_command(game, HOST, "host.advance", {})
        self.assertEqual([cid for cid, card in game["cards"].items() if card["witch"]], [])
        self.assertEqual(game["phase"], "night")

    def test_hanna_witch_switch_overrides_the_third_night_choice(self):
        def prepared():
            game = staged_game()
            game["cards"]["emma"]["alive"] = False
            game["cards"]["sherry"]["alive"] = False
            game["spiritual"]["sherry_bound"] = True
            game["seats"][4]["cards"] = ["hanna", "meruru"]
            return game

        # 开关关闭：按常规由 A 的当前牌魔女化。
        game = prepared()
        apply_command(game, HOST, "host.advance", {})
        self.assertTrue(game["cards"]["coco"]["witch"])
        self.assertFalse(game["cards"]["hanna"]["witch"])

        # 五条全部成立：汉娜覆盖当天人选。
        game = prepared()
        game["hanna_witch"] = True
        apply_command(game, HOST, "host.advance", {})
        self.assertTrue(game["cards"]["hanna"]["witch"])
        self.assertFalse(game["cards"]["coco"]["witch"])

        # 仍然是绑定状态（雪莉还在场）：不覆盖。
        game = prepared()
        game["hanna_witch"] = True
        game["cards"]["sherry"]["alive"] = True
        apply_command(game, HOST, "host.advance", {})
        self.assertFalse(game["cards"]["hanna"]["witch"])
        self.assertTrue(game["cards"]["coco"]["witch"])

        # 从未绑定过：不覆盖。
        game = prepared()
        game["hanna_witch"] = True
        game["spiritual"]["sherry_bound"] = False
        apply_command(game, HOST, "host.advance", {})
        self.assertFalse(game["cards"]["hanna"]["witch"])
        self.assertTrue(game["cards"]["coco"]["witch"])

        # 艾玛在场：艾玛的最高优先级高于汉娜。
        game = prepared()
        game["hanna_witch"] = True
        game["cards"]["emma"]["alive"] = True
        apply_command(game, HOST, "host.advance", {})
        self.assertTrue(game["cards"]["emma"]["witch"])
        self.assertFalse(game["cards"]["hanna"]["witch"])

    def test_hanna_witch_switch_is_off_by_default_host_only_and_before_night_three(self):
        self.assertFalse(create_game(DEFAULT_CODEX)["hanna_witch"])

        game = staged_game(day=2, half="day", phase="discussion")
        for actor in players(game):
            self.assertNotIn(
                "host.hanna_witch", [item["id"] for item in actions_for(game, actor)]
            )
        toggle = next(
            item for item in actions_for(game, HOST) if item["id"] == "host.hanna_witch"
        )
        self.assertEqual(toggle["label"], "汉娜魔化：已关闭")
        self.assertEqual(toggle["fields"][0]["default"], "off")
        events = apply_command(game, HOST, "host.hanna_witch", {"value": "on"})
        self.assertTrue(game["hanna_witch"])
        self.assertEqual([e["audience"] for e in events if e["title"] == "规则调整"], [[]])
        self.assertEqual(
            next(item for item in actions_for(game, HOST) if item["id"] == "host.hanna_witch")[
                "label"
            ],
            "汉娜魔化：已开启",
        )
        apply_command(game, HOST, "host.hanna_witch", {"value": "off"})
        self.assertFalse(game["hanna_witch"])

        # 第三天夜里（入夜后的夜间行动）不再允许改开关。
        game = staged_game(day=3, half="night", phase="night")
        self.assertNotIn(
            "host.hanna_witch", [item["id"] for item in actions_for(game, HOST)]
        )
        with self.assertRaises(GameError):
            apply_command(game, HOST, "host.hanna_witch", {"value": "on"})

    def test_good_wins_only_when_both_faction_seats_are_out(self):
        game = staged_game(day=1, half="day", phase="discussion")
        game["cards"]["coco"]["witch"] = True
        # 魔女牌（A 的当前牌）出局但 A 席还有牌：不算好人胜利。
        game["cards"]["coco"]["alive"] = False
        check_winner(game)
        self.assertIsNone(game["winner_candidate"])
        # A 席整席出局、B 席还在：仍然不算。
        game["cards"]["emma"]["alive"] = False
        check_winner(game)
        self.assertIsNone(game["winner_candidate"])
        # A、B 两席都出局：好人胜利，理由点名魔女阵营。
        game["cards"]["hiro"]["alive"] = False
        game["cards"]["millia"]["alive"] = False
        check_winner(game)
        self.assertEqual(game["winner_candidate"]["winner"], "good")
        self.assertEqual(game["winner_candidate"]["reason"], "魔女阵营A、B两席出局")


class PhaseBannerRules(unittest.TestCase):
    """全场横幅：当前轮到谁、还在等谁、还是只等主持人。

    横幅走客户端已有的 action_prompt 通道，因此这里直接核对服务端下发的文案：
    夜间只说「仍有玩家未完成行动」，列出席位等于公开谁有夜间技能。
    """

    @staticmethod
    def prompt(game, seat_id, active_private=False):
        actor = next(item for item in players(game) if item["seat_id"] == seat_id)
        return action_prompt(game, actor, active_private)

    def test_speech_phase_tells_everyone_whose_turn_it_is(self):
        game = staged_game(day=2, half="day", phase="speech")
        game["public"]["speaker"] = "3"
        # 轮到的席位仍是本人催办，其他席位看到全场通报。
        self.assertEqual(self.prompt(game, "3")["title"], "轮到你顺序发言")
        self.assertEqual(self.prompt(game, "5")["title"], "当前轮到3号玩家发言")
        self.assertEqual(self.prompt(game, "5")["text"], "")

    def test_nomination_and_voting_list_who_is_still_expected(self):
        game = staged_game(day=2, half="day", phase="nomination")
        game["nomination_done"] = ["1", "2"]
        self.assertEqual(
            self.prompt(game, "1")["title"], "正在等待3号、4号、5号、6号、7号玩家提名"
        )
        self.assertEqual(self.prompt(game, "3")["title"], "请提交提名或放弃")

        game = staged_game(day=2, half="day", phase="voting")
        # 一次性投票：候选是4号席的当前牌，1号提名过它（自动同意），2号已投不同意。
        candidate = game["seats"][3]["cards"][0]
        game["nominations"] = [{"seat_id": "4", "card_id": candidate, "by": "1"}]
        game["ballots"] = {"2": {candidate: "no"}}
        self.assertEqual(
            self.prompt(game, "1")["title"], "正在等待3号、4号、5号、6号、7号玩家投票"
        )
        self.assertEqual(self.prompt(game, "3")["title"], "请投票")
        # 全场横幅只通报进度：私聊里的「先结束私聊」提示只挂在本人待办上。
        self.assertIsNone(self.prompt(game, "1", active_private=True)["hint"])
        self.assertIn("私聊", self.prompt(game, "3", active_private=True)["hint"])

    def test_night_banner_never_names_the_seats_that_are_still_acting(self):
        game = staged_game(day=3, half="night", phase="night")
        game["night"]["actors"] = {
            seat_id: game["seats"][int(seat_id) - 1]["cards"][0] for seat_id in ("2", "3")
        }
        game["night"]["confirmed"] = []
        self.assertEqual(self.prompt(game, "2")["title"], "请完成本夜行动")
        for seat_id in ("1", "5", "7"):
            title = self.prompt(game, seat_id)["title"]
            self.assertEqual(title, "仍有玩家未完成行动")
            self.assertNotIn("号", title)
        # 少一个人待办也必须是同一条文案：不能从文案变化里推出谁完成了行动。
        game["night"]["confirmed"] = ["2"]
        self.assertEqual(self.prompt(game, "1")["title"], "仍有玩家未完成行动")
        # 夜里还有玩家待办（如穗乃香选显示角色）时也只报「还有玩家」，不提示等主持人。
        game = staged_game(day=3, half="night", phase="night_review")
        game["night"]["preview"] = {"deaths": []}
        game["pending"] = [
            {"id": "w1", "kind": "honoka_witness", "seat_id": "7", "title": "等待选择"}
        ]
        self.assertEqual(self.prompt(game, "4")["title"], "仍有玩家未完成行动")
        self.assertNotIn("7", self.prompt(game, "4")["title"])

    def test_host_blocked_phases_ask_the_table_to_wait_for_the_host(self):
        game = staged_game(day=3, half="night", phase="night_review")
        game["night"]["preview"] = {"deaths": []}
        self.assertEqual(self.prompt(game, "4")["title"], "等待主持人进行操作")
        self.assertEqual(
            self.prompt(staged_game(day=3, half="night", phase="night_results"), "4")["title"],
            "等待主持人进行操作",
        )
        self.assertEqual(
            self.prompt(staged_game(day=3, half="day", phase="dusk"), "4")["title"],
            "等待主持人进行操作",
        )
        # 自动推进被主持人暂停时也只能等他；恢复后不再提示。
        game = staged_game(day=3, half="day", phase="nomination")
        game["nomination_done"] = [seat["id"] for seat in game["seats"]]
        game["public"]["auto_advance_off"] = True
        self.assertEqual(self.prompt(game, "4")["title"], "等待主持人进行操作")
        game["public"].pop("auto_advance_off")
        self.assertIsNone(self.prompt(game, "4"))

    def test_free_discussion_never_blames_the_host(self):
        game = staged_game(day=2, half="day", phase="discussion")
        game["public"]["auto_advance_off"] = True
        self.assertIsNone(self.prompt(game, "4"))


if __name__ == "__main__":
    unittest.main()
