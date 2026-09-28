"""被动技能卡片与角色卡死亡卡片：载荷内容与「谁能看到多少」的服务端边界。

被动技能（处决幻视、时间回溯、替死、爱人庇护、转爱自己）复用主动技能的播报卡片，
只换边框颜色与措辞。卡片本身不判断可见性：载荷里的结果多半是私密情报，收件人由
``notify`` 的 audience 决定，投影再按 ``effect_public`` 裁一刀。死亡卡片是另一回事：
它的载荷按白名单构造，只有公开信息，人人都能看，但真实牌与死因一个字都不许进。
"""

import unittest
from copy import deepcopy
from unittest.mock import patch

from backend.app import storage
from backend.app.game import DEFAULT_CODEX, apply_command, create_game
from backend.app.game.engine import enter_execution
from backend.app.game.resolution import damage_preview, millia_substitute

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
# 死亡卡片允许出现在载荷里的字段：多一个都算泄漏，少一个客户端就画不出来。
DEATH_ENTRY_KEYS = {"seat_id", "player_name", "avatar_role_id", "role_name", "water"}


def arranged_game(phase="discussion", half="day"):
    game = create_game(DEFAULT_CODEX)
    for seat in game["seats"]:
        seat["occupant_id"] = "p" + seat["id"]
    for seat in game["seats"]:
        apply_command(game, player(game, seat["id"]), "lobby.ready", {})
    game.update(status="playing", phase=phase, half=half, day=2)
    for seat, pair in zip(game["seats"], PAIRS):
        seat.update(cards=list(pair), occupant_id="p" + seat["id"], ready=True)
    # 公开头像按当前牌补齐：真实对局在开局时统一写过一遍。
    for seat in game["seats"]:
        seat["avatar_role_id"] = seat["cards"][0]
    return game


def player(game, sid):
    return {
        "id": "p" + sid,
        "kind": "player",
        "seat_id": sid,
        "game_id": game["id"],
        "access_ids": ["p" + sid],
    }


def stranger(sid="1"):
    return {"id": "p" + sid, "kind": "player", "access_ids": ["p" + sid]}


def command(game, actor, action, payload=None):
    changed = deepcopy(game)
    events = apply_command(changed, actor, action, payload or {})
    game.clear()
    game.update(changed)
    return events


def skill_cards(events):
    return [event for event in events if event.get("payload", {}).get("type") == "skill"]


def death_cards(events):
    return [event for event in events if event.get("payload", {}).get("type") == "death"]


class PassiveGazeCard(unittest.TestCase):
    def gaze_game(self):
        game = arranged_game("voting")
        # 默认发牌里艾玛在1号席，与7号席的奈乃香环形相邻，先移除这个毒源。
        game["cards"]["emma"]["alive"] = False
        game["execution"] = ["millia"]
        return game

    def test_gaze_is_a_private_passive_card(self):
        game = self.gaze_game()
        events = []
        enter_execution(game, events)
        event = next(event for event in skill_cards(events) if event["payload"]["ability"] == "gaze")
        # 只发给奈乃香本人：其余玩家连这条消息都收不到。
        self.assertEqual(event["kind"], "information")
        self.assertEqual(event["audience"], ["p7"])
        payload = event["payload"]
        self.assertEqual(payload["mode"], "passive")
        self.assertEqual(payload["ability_name"], "处决幻视")
        self.assertEqual(payload["role_id"], "nanoka")
        self.assertEqual(payload["actor_participant_id"], "p7")
        self.assertFalse(payload["challengeable"])
        self.assertFalse(payload["target_public"])
        self.assertIsNone(payload["target"])
        # 卡片上的结果必须与发给她的文本同源，同真同假。
        self.assertEqual(payload["effect"], event["text"])
        self.assertEqual(payload["effect"], "本日处决名单不含魔女。")
        # 结果不是公开情报：非本人即使拿到这条消息也不下发 effect。
        self.assertFalse(payload["effect_public"])

    def test_the_result_never_reaches_another_reader(self):
        game = self.gaze_game()
        events = []
        enter_execution(game, events)
        payload = next(event for event in skill_cards(events))["payload"]
        other = storage.project_message_payload(payload, stranger())
        # 技能名与介绍是公开规则，结果不是。
        self.assertEqual(other["ability_name"], "处决幻视")
        self.assertNotIn("effect", other)
        self.assertNotIn("card_id", other)
        self.assertNotIn("fake", other)
        owner = storage.project_message_payload(payload, player(game, "7"))
        self.assertEqual(owner["effect"], "本日处决名单不含魔女。")
        host = storage.project_message_payload(payload, HOST)
        self.assertEqual(host["effect"], "本日处决名单不含魔女。")

    def test_a_poisoned_gaze_card_shows_exactly_what_she_received(self):
        for roll, expected in ((0, "本日处决名单含有魔女。"), (1, "本日处决名单不含魔女。")):
            game = self.gaze_game()
            game["cards"]["nanoka"]["states"]["poisoned"] = True
            game["cards"]["hanna"]["witch"] = True
            game["execution"] = ["hanna"]
            with patch("backend.app.game.state.SystemRandom") as random:
                random.return_value.randrange.return_value = roll
                events = []
                enter_execution(game, events)
            event = next(event for event in skill_cards(events))
            self.assertEqual(event["text"], expected)
            self.assertEqual(event["payload"]["effect"], expected)


class DeathCard(unittest.TestCase):
    def test_day_death_card_carries_only_public_fields(self):
        game = arranged_game("discussion", "day")
        game["seats"][2]["avatar_role_id"] = "meruru"
        events = command(
            game,
            HOST,
            "host.damage",
            {"targets": ["meruru"], "effect": "death", "source": "coco", "reason": "测试白天出局"},
        )
        event = next(event for event in death_cards(events))
        # 全场公示：死亡公告本来就是公开事件。
        self.assertEqual(event["kind"], "alert")
        self.assertIsNone(event["audience"])
        entry = event["payload"]["deaths"][0]
        self.assertEqual(set(entry), DEATH_ENTRY_KEYS)
        self.assertEqual(entry["seat_id"], "3")
        self.assertEqual(entry["avatar_role_id"], "meruru")
        self.assertEqual(entry["role_name"], "梅露露")
        self.assertFalse(entry["water"])
        # 死因与真实牌 id 不进卡片：主持人视图另有完整记录。
        self.assertNotIn("cause", entry)
        self.assertNotIn("card_id", entry)
        self.assertNotIn("source_card", entry)

    def test_a_water_death_marks_the_card_unless_the_cause_is_hidden(self):
        from backend.app.game.resolution import death_batch

        for hidden, water in ((False, True), (True, False)):
            game = arranged_game("discussion", "day")
            events = []
            death_batch(
                game,
                events,
                damage_preview(
                    game,
                    [
                        {
                            "target_card": "meruru",
                            "source_card": "coco",
                            "cause": "water",
                            "hide_cause": hidden,
                        }
                    ],
                ),
            )
            entry = next(event for event in death_cards(events))["payload"]["deaths"][0]
            self.assertEqual(entry["water"], water)
            # 隐藏死因时连「13水」这三个字都不出现：卡片与公告文本同一口径。
            self.assertEqual(set(entry), DEATH_ENTRY_KEYS)

    def test_a_disguised_honoka_keeps_her_shown_role_on_the_card(self):
        game = arranged_game("discussion", "day")
        game["seats"][6]["cards"] = ["honoka", "nanoka"]
        game["seats"][6]["avatar_role_id"] = "noah"
        events = command(
            game,
            HOST,
            "host.damage",
            {"targets": ["honoka"], "effect": "death", "source": "coco", "reason": "测试"},
        )
        card = next(event for event in death_cards(events))
        entry = card["payload"]["deaths"][0]
        # 卡片按公开头像取角色名：不能顺着真实牌把示人身份说破。
        self.assertEqual(entry["avatar_role_id"], "noah")
        self.assertEqual(entry["role_name"], "诺亚")
        self.assertNotIn("穗乃香", str(entry))
        # 同一时刻的公告文本与卡片同一口径：真实牌名一个字都不许出现在文本里，
        # 否则卡片藏住了示人身份、公告文本又把它说出去。
        self.assertEqual(card["text"], "7号 · 诺亚一张角色牌出局。")
        self.assertNotIn("穗乃香", card["text"])

    def test_night_deaths_are_merged_into_one_card_at_dawn(self):
        game = arranged_game("night_review", "night")
        game["night"]["reactions"] = []
        game["night"]["preview"] = damage_preview(
            game,
            [
                {"target_card": "meruru", "source_card": "emma", "cause": "knife"},
                {"target_card": "leia", "source_card": "emma", "cause": "knife"},
            ],
        )
        # 预结算这一步只排队，不发卡片：夜间出局一律压到天亮。
        events = command(game, HOST, "host.advance")
        self.assertFalse(death_cards(events))
        self.assertEqual(len(game["queued_deaths"]), 2)
        game["pending"] = []
        events = command(game, HOST, "host.advance")
        card = next(event for event in death_cards(events))
        self.assertEqual(card["payload"]["half"], "night")
        self.assertEqual({entry["seat_id"] for entry in card["payload"]["deaths"]}, {"3", "5"})
        self.assertEqual(game["queued_deaths"], [])
        self.assertEqual(game["queued_notices"], [])

    def test_the_death_payload_is_visible_to_everyone_unchanged(self):
        game = arranged_game("discussion", "day")
        events = command(
            game,
            HOST,
            "host.damage",
            {"targets": ["meruru"], "effect": "death", "source": "coco", "reason": "测试"},
        )
        payload = next(event for event in death_cards(events))["payload"]
        other = storage.project_message_payload(payload, stranger())
        self.assertEqual(other, payload)
        self.assertEqual(
            set(other["deaths"][0]),
            DEATH_ENTRY_KEYS,
        )


class PassiveNightCards(unittest.TestCase):
    def test_substitution_card_is_private_and_waits_for_dawn(self):
        game = arranged_game("night_review", "night")
        game["millia_swap"] = {"seat": "3", "day": 2}
        game["night"]["reactions"] = []
        game["night"]["preview"] = damage_preview(
            game,
            millia_substitute(
                game, [{"target_card": "meruru", "source_card": "emma", "cause": "knife"}]
            ),
        )
        # 预结算只试算：替死的那一击落在米莉亚身上，此刻还没写进生死。
        self.assertEqual(
            [death["target_card"] for death in game["night"]["preview"]["deaths"]], ["millia"]
        )
        self.assertEqual(game["night"]["preview"]["deaths"][0]["substituted_from"], "meruru")
        # 预结算阶段一条被动卡都不许发：夜里提示替死就等于提前公布夜里的结算。
        events = command(game, HOST, "host.advance")
        self.assertFalse([item for item in skill_cards(events) if item["payload"]["mode"] == "passive"])
        self.assertFalse(game["cards"]["millia"]["alive"])
        self.assertTrue(game["cards"]["meruru"]["alive"])
        self.assertEqual(game["deaths"][-1].get("substituted_from"), "meruru")
        game["pending"] = []
        events = command(game, HOST, "host.advance")
        card = next(
            item for item in skill_cards(events) if item["payload"]["ability"] == "substitute"
        )
        # 换血对象是私密情报：只发给1号席的米莉亚（主持人另有旁路）。
        self.assertEqual(card["audience"], ["p1"])
        self.assertEqual(card["payload"]["role_id"], "millia")
        self.assertEqual(card["payload"]["mode"], "passive")
        self.assertIn("3号", card["payload"]["effect"])
        self.assertFalse(card["payload"]["effect_public"])
        other = storage.project_message_payload(card["payload"], stranger("2"))
        self.assertNotIn("effect", other)
        self.assertEqual(
            storage.project_message_payload(card["payload"], player(game, "1"))["effect"],
            card["payload"]["effect"],
        )

    def test_love_block_card_is_private_to_marg(self):
        game = arranged_game("night_review", "night")
        game["marg_love"] = {"seat_id": "2", "card_id": "hiro", "day": 2}
        game["night"]["reactions"] = []
        game["night"]["preview"] = damage_preview(
            game, [{"target_card": "hiro", "source_card": "coco", "cause": "knife"}]
        )
        self.assertEqual(game["night"]["preview"]["love_blocked"], ["hiro"])
        self.assertFalse(game["night"]["preview"]["deaths"])
        events = command(game, HOST, "host.advance")
        self.assertFalse(skill_cards(events))
        events = command(game, HOST, "host.advance")
        card = next(item for item in skill_cards(events) if item["payload"]["ability"] == "love")
        # 被爱的牌是私密情报（爱上/移情的目标不公开），只发给4号席的玛格。
        self.assertEqual(card["audience"], ["p4"])
        self.assertEqual(card["payload"]["role_id"], "marg")
        self.assertIn("2号", card["payload"]["effect"])
        self.assertNotIn("effect", storage.project_message_payload(card["payload"], stranger()))

    def test_transfer_to_self_is_announced_once_and_only_to_marg(self):
        from backend.app.game.resolution import publish_love_self

        game = arranged_game("night_review", "night")
        game["marg_love"] = {"seat_id": "3", "card_id": "meruru", "day": 2}
        game["night"]["reactions"] = []
        # 玛格自己每夜那一发（cause="love"）不触发爱人的免疫，被爱的人会真的出局。
        game["night"]["preview"] = damage_preview(
            game, [{"target_card": "meruru", "source_card": "marg", "cause": "love"}]
        )
        self.assertEqual(
            [death["target_card"] for death in game["night"]["preview"]["deaths"]], ["meruru"]
        )
        events = command(game, HOST, "host.advance")
        self.assertFalse([item for item in skill_cards(events) if item["payload"]["mode"] == "passive"])
        self.assertFalse(game["cards"]["meruru"]["alive"])
        game["pending"] = []
        events = command(game, HOST, "host.advance")
        cards = [item for item in skill_cards(events) if item["payload"]["ability"] == "love_self"]
        self.assertEqual(len(cards), 1)
        # 被爱的那张牌是谁，只有玛格自己需要知道。
        self.assertEqual(cards[0]["audience"], ["p4"])
        self.assertTrue(game["marg_love"]["self_notified"])
        # 已经通知过一次就不再重复。
        again = []
        publish_love_self(game, again)
        self.assertFalse(again)


if __name__ == "__main__":
    unittest.main()
