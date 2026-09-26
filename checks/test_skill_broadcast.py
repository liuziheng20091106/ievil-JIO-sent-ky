"""技能播报：结构化载荷的内容与「谁能看到多少」的服务端裁剪。

播报是全场消息，但细节分档：技能名与介绍人人可见，目标只有技能本身公开（打断、决斗、
全场洗脑）或收件人就是声明者/主持人才给，伪装标记只有主持人看得到——伪装声明在其他
玩家眼里必须与真声明完全一致。
"""

import unittest
from copy import deepcopy

from backend.app import storage
from backend.app.game import DEFAULT_CODEX, apply_command, create_game

HOST = {"id": "host", "kind": "host", "host_entered": True, "access_ids": ["host"]}
PAIRS = [
    ["millia", "emma"],
    ["hiro", "coco"],
    ["meruru", "hanna"],
    ["marg", "sherry"],
    ["leia", "arisa"],
    ["noah", "annan"],
    ["nanoka", "honoka"],
]


def arranged_game():
    game = create_game(DEFAULT_CODEX)
    for seat in game["seats"]:
        seat["occupant_id"] = "p" + seat["id"]
    for seat in game["seats"]:
        apply_command(game, player(game, seat["id"]), "lobby.ready", {})
    game.update(status="playing", phase="discussion", half="day", day=2)
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


def broadcast(game, actor, ability, payload):
    """声明一次白天技能并返回那条播报事件。"""
    events = command(game, actor, "day.skill", {"ability": ability, **payload})
    return next(event for event in events if event.get("payload", {}).get("type") == "skill")


class SkillBroadcastPayload(unittest.TestCase):
    def test_love_broadcast_carries_skill_name_intro_and_secret_target(self):
        game = arranged_game()
        event = broadcast(game, player(game, "4"), "love", {"target": "5"})
        payload = event["payload"]
        self.assertEqual(event["kind"], "alert")
        self.assertEqual(payload["ability"], "love")
        self.assertEqual(payload["ability_name"], "爱上/移情")
        self.assertEqual(payload["role_id"], "marg")
        self.assertEqual(payload["role_name"], "玛格")
        self.assertIn("移情", payload["intro"])
        self.assertEqual(payload["seat_id"], "4")
        self.assertEqual(payload["actor_participant_id"], "p4")
        self.assertFalse(payload["challengeable"])
        self.assertFalse(payload["target_public"])
        self.assertEqual(payload["target"], {"seat_id": "5", "name": "5号玩家"})
        self.assertFalse(payload["fake"])
        # 旧客户端与历史搜索仍能读到原来的整句文本。
        self.assertIn("声明发动", event["text"])

    def test_duel_target_is_public_and_challengeable(self):
        game = arranged_game()
        event = broadcast(game, player(game, "5"), "duel", {"target": "3"})
        payload = event["payload"]
        self.assertEqual(payload["ability_name"], "决斗")
        self.assertTrue(payload["target_public"])
        self.assertTrue(payload["challengeable"])

    def test_disguised_declaration_is_marked_for_the_host_only_in_payload(self):
        game = arranged_game()
        # 7 号是穗乃香（示人身份玛格）：可以把「爱上/移情」伪装成自己示人的技能。
        game["seats"][6]["cards"] = ["honoka", "nanoka"]
        game["cards"]["honoka"]["states"]["disguise"] = "marg"
        event = broadcast(game, player(game, "7"), "love", {"target": "2"})
        self.assertTrue(event["payload"]["fake"])
        self.assertEqual(event["payload"]["role_id"], "marg")
        self.assertFalse(event["payload"]["target_public"])


class PayloadProjection(unittest.TestCase):
    """同一条消息按收件人裁剪：目标与伪装标记不能泄漏给不该看到的人。"""

    def setUp(self):
        self.payload = {
            "type": "skill",
            "ability": "love",
            "ability_name": "爱上/移情",
            "role_id": "marg",
            "role_name": "玛格",
            "intro": "白天可宣布爱上一人或移情。",
            "seat_id": "4",
            "actor_participant_id": "p4",
            "actor_name": "kiwi",
            "challengeable": False,
            "target_public": False,
            "target": {"seat_id": "5", "name": "庭雨"},
            "fake": True,
            "card_id": "c-marg",
        }
        self.other = {"id": "p5", "kind": "player", "access_ids": ["p5"]}
        self.declarer = {"id": "p4", "kind": "player", "access_ids": ["p4"]}

    def test_other_players_get_the_skill_but_not_the_secret_target_or_fake(self):
        view = storage.project_message_payload(self.payload, self.other)
        self.assertEqual(view["ability_name"], "爱上/移情")
        self.assertEqual(view["intro"], "白天可宣布爱上一人或移情。")
        self.assertNotIn("target", view)
        self.assertNotIn("fake", view)
        self.assertNotIn("card_id", view)

    def test_declarer_sees_the_target_but_not_the_fake_flag(self):
        view = storage.project_message_payload(self.payload, self.declarer)
        self.assertEqual(view["target"], {"seat_id": "5", "name": "庭雨"})
        self.assertNotIn("fake", view)

    def test_host_sees_everything(self):
        view = storage.project_message_payload(self.payload, HOST)
        self.assertEqual(view["target"], {"seat_id": "5", "name": "庭雨"})
        self.assertTrue(view["fake"])
        self.assertEqual(view["card_id"], "c-marg")

    def test_public_target_is_sent_to_everyone(self):
        payload = {**self.payload, "target_public": True}
        view = storage.project_message_payload(payload, self.other)
        self.assertEqual(view["target"], {"seat_id": "5", "name": "庭雨"})

    def test_unknown_payload_types_are_host_only(self):
        payload = {"type": "future", "secret": "只有主持人该看到"}
        self.assertIsNone(storage.project_message_payload(payload, self.other))
        self.assertEqual(
            storage.project_message_payload(payload, HOST), payload
        )

    def test_message_view_only_attaches_payload_when_present(self):
        row = {
            "id": 1,
            "kind": "alert",
            "sender_id": "host",
            "sender_name": "主持人",
            "avatar_role_id": "host",
            "channel_id": "public",
            "text": "4号声明发动「宣布爱上或移情」，该技能不可质疑。",
            "created_at": "2026-09-26T02:00:00+00:00",
            "image_id": None,
            "keys": lambda: ["id", "payload"],
            "payload": storage.dumps(self.payload),
        }
        view = storage.message_view(row, self.other)
        self.assertNotIn("target", view["payload"])
        self.assertNotIn("payload", storage.message_view({**row, "payload": None}, self.other))
