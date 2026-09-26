"""虚拟玩家模拟器的回归检查：一局完整对局必须能从开局走到合法收尾。

这些检查保护的是真实的规则与流程边界：阶段推进、行动授权、以及「服务端列出的
行动一定可以提交」这条不变式。虚拟玩家只依据服务端裁剪后的视图决策，
因此一旦某个阶段少给了出口，或者某条行动列出后又被拒绝，这里就会失败。
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import storage
from backend.app.game.catalog import ROLES
from backend.app.main import app
from backend.app.simulator.client import ProtocolClient
from backend.app.simulator.harness import Harness
from backend.app.simulator.policy import field_spec, option_values
from backend.app.simulator.transport import TestClientTransport, gateway_authenticator

# 一局完整对局要走完魔女化、夜间、顺序发言、提名、投票与处决，
# 同时等待系统自己 5 秒的自动推进，因此给足时间但保持有界。
# 弱机器上单局可能跑到数分钟（实测最长约 400 秒），预算必须留够，
# 否则超时会被误报成「走不到结局」。
GAME_SECONDS = 600
GAME_STEPS = 4000


class SimulatorCase(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.data_patch = patch.object(storage, "DATA_DIR", Path(self.directory.name))
        self.data_patch.start()
        self.addCleanup(self.data_patch.stop)
        self.env_patch = patch.dict(
            os.environ,
            {
                "GAME_GATEWAY_TOKEN": "test-gateway-secret",
                "GAME_QQ_GROUP_ID": "123456",
                "GAME_ADMIN_QQ": "10001",
                "GAME_ALLOWED_ORIGINS": "testserver",
            },
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)

    def test_harness_seats_all_seven_players_and_deals(self):
        """入场与发牌：七个虚拟玩家各自拿到随机席位，无人重复。"""
        with self.client() as client:
            harness = Harness(client, seed=7)
            harness.join()
            seats = [actor.seat_id for actor in harness.seats]
            self.assertEqual(len(seats), 7)
            self.assertEqual(sorted(seats), [str(i + 1) for i in range(7)])
            harness.simulation.prepare()
            view = harness.host.view
            self.assertEqual(view["status"], "playing")
            self.assertEqual(len({s["participant_id"] for s in view["seats"]}), 7)
            for seat in view["seats"]:
                self.assertTrue(seat["occupied"])
                self.assertEqual(len(seat["cards"]), 2)

    def test_full_game_reaches_a_winner(self):
        """整局模拟：必须走到 ended，并给出胜利方与理由。"""
        with self.client() as client:
            harness = Harness(client, seed=3)
            harness.simulation.max_seconds = GAME_SECONDS
            harness.simulation.max_steps = GAME_STEPS
            result = harness.run()
            self.assertEqual(result.status, "ended", "\n".join(result.log[-20:]))
            self.assertIn(result.winner, {"good", "witch", "aborted"})
            self.assertTrue(result.reason)
            self.assertGreater(result.days, 0)

    def test_simulated_game_keeps_rules_consistent(self):
        """收尾状态不变式：出局牌不自相矛盾，胜负理由与存活魔女一致。"""
        with self.client() as client:
            harness = Harness(client, seed=5)
            harness.simulation.max_seconds = GAME_SECONDS
            result = harness.run()
            self.assertEqual(result.status, "ended")
            view = harness.host.view
            cards = {
                card["id"]: card
                for seat in view["seats"]
                for card in seat.get("cards", [])
            }
            self.assertEqual(len(cards), 14)
            # 每个席位同时只有一张「当前」牌：两张牌都在场会让上下层机制失效。
            # 下层牌本身仍是 alive 的，所以这里看 current_card_id 而不是 alive 数量。
            for seat in view["seats"]:
                current = seat["current_card_id"]
                if current is None:
                    # 整席出局（质疑失败）：两张牌都不该存活。
                    self.assertFalse(
                        [card["id"] for card in seat["cards"] if card["alive"]],
                        f"{seat['id']}号已无当前牌却仍有存活牌",
                    )
                else:
                    self.assertTrue(cards[current]["alive"])
            if view["result"]["winner"] == "witch":
                self.assertFalse(cards["millia"]["alive"] and cards["arisa"]["alive"])

    def test_every_listed_action_is_submittable(self):
        """不变式：视图列出的行动必须真的可以提交，否则玩家会被卡死。"""
        with self.client() as client:
            harness = Harness(client, seed=11)
            harness.join()
            harness.simulation.prepare()
            harness.simulation.roster.host.submit("host.advance", {})
            actors = harness.roster.seats
            for actor in actors:
                actor.client.refresh()
                self.assertEqual(actor.client.view["status"], "playing")
            # 至少有一个席位在夜间拿到了 night.submit，并且提交后不被拒绝。
            submits = [
                (actor, descriptor)
                for actor in actors
                for descriptor in actor.client.available("night.submit")
            ]
            self.assertTrue(submits, "首夜没有任何席位获得夜间行动")
            actor, descriptor = submits[0]
            actor.client.refresh()
            decision = actor.policy.decide(actor.client)
            self.assertIsNotNone(decision, f"{actor.seat_id}号拿到行动却无法决策")
            actor.client.submit(decision.action, decision.payload)
            self.assertTrue(actor.client.view["self"]["night_actions"])

    def test_night_targets_respect_offered_options(self):
        """夜间目标只能取自服务端给出的候选，且按角色卡标识席位。"""
        with self.client() as client:
            harness = Harness(client, seed=13)
            harness.join()
            harness.simulation.prepare()
            harness.roster.host.submit("host.advance", {})
            checked = 0
            for actor in harness.roster.seats:
                actor.client.refresh()
                seats = {seat["id"]: seat for seat in actor.client.view["seats"]}
                for descriptor in actor.client.available("night.submit"):
                    ability = descriptor["payload"]["ability"]
                    self.assertIn("ability", descriptor["payload"])
                    if ability not in {"knife", "protect", "shoot", "spear", "swap"}:
                        continue
                    targets = option_values(descriptor, "target")
                    self.assertTrue(targets, f"{ability} 没有任何可选目标")
                    # 对局内的选择界面不显示玩家昵称：标签是「N号 · 当前展示角色名」。
                    target_field = field_spec(descriptor, "target")
                    self.assertEqual(target_field.get("options_kind"), "seat")
                    for option in target_field["options"]:
                        seat = seats.get(option["value"])
                        role_id = seat and seat.get("avatar_role_id")
                        if role_id:
                            self.assertIn(
                                ROLES[role_id]["name"],
                                option["label"],
                                f"{ability} 的目标标签不是角色卡：{option['label']}",
                            )
                    decision = actor.policy.decide(actor.client)
                    if decision and decision.action == "night.submit":
                        if decision.payload.get("ability") != ability:
                            continue
                        self.assertIn(decision.payload["target"], targets)
                        checked += 1
            self.assertGreater(checked, 0, "首夜没有可校验的带目标夜间行动")

    def test_players_never_see_other_players_cards(self):
        """可见性裁剪：虚拟玩家的视图不能泄露他人的角色牌。"""
        with self.client() as client:
            harness = Harness(client, seed=17)
            harness.join()
            harness.simulation.prepare()
            for actor in harness.roster.seats:
                actor.client.refresh()
                own = actor.client.view["self"]["seat_id"]
                for seat in actor.client.view["seats"]:
                    if seat["id"] == own:
                        continue
                    self.assertNotIn("cards", seat, f"{seat['id']}号的角色牌泄露给了{own}号")
                self.assertEqual(len(actor.client.view["self"]["cards"]), 2)

    def test_policy_avoids_repeating_lobby_order(self):
        """准备阶段：排牌只做一次，否则会在「排牌→未准备」之间死循环。"""
        with self.client() as client:
            harness = Harness(client, seed=19)
            harness.join()
            simulation = harness.simulation
            # 用策略自己走完准备阶段：必须先排牌再准备，不能反复排牌。
            simulation._drive_until(simulation._dealt, "发牌")
            self.assertEqual(harness.host.view["phase"], "ordering")
            simulation._drive_until(simulation._ordered, "再次准备")
            self.assertTrue(all(seat["ready"] for seat in harness.host.view["seats"]))
            orders = [line for line in harness.log if "lobby.order" in line]
            readies = [line for line in harness.log if "lobby.ready" in line]
            # 每个席位最多排一次牌：7 次排牌之后必须进入准备，而不是无限重排。
            self.assertLessEqual(len(orders), 14, "\n".join(orders))
            self.assertGreaterEqual(len(readies), 7, "\n".join(readies))

    def test_millia_substitute_stays_idempotent_across_repeated_preview(self):
        """米莉亚替死在反复重算预结算下保持稳定：只转移一次致命攻击。

        ``prepare_night_preview`` 会在主持人改动状态、警告超时等时机被反复调用。
        替死把指向换血对象的攻击改写为米莉亚牌后，重算不能叠加、不能漂移。
        """
        from backend.app.game import DEFAULT_CODEX, create_game
        from backend.app.game.resolution import begin_night, prepare_night_preview
        from backend.app.game.state import current, deal_cards, owner

        game = create_game(DEFAULT_CODEX)
        for seat in game["seats"]:
            seat["occupant_id"] = f"p{seat['id']}"
        deal_cards(game)
        millia_seat = owner(game, "millia")
        millia_seat["cards"] = ["millia"] + [c for c in millia_seat["cards"] if c != "millia"]
        game["status"] = "playing"
        game["phase"] = "ordering"
        begin_night(game, [])
        target_seat = next(
            s for s in game["seats"] if s["id"] != millia_seat["id"] and current(game, s)
        )
        target_card = current(game, target_seat)
        game["night"]["actions"] = [
            {
                "id": "swap-action",
                "seat_id": millia_seat["id"],
                "card_id": "millia",
                "ability": "swap",
                "target_seat": target_seat["id"],
                "target_card": target_card["id"],
                "effective": True,
                "confirmed": True,
            }
        ]
        game["night"]["extra_attacks"] = [
            {"target_card": target_card["id"], "cause": "host", "unconditional": True}
        ]
        game["millia_swap"] = {"seat": target_seat["id"], "day": 1}
        # 米莉亚的替死不掷中毒骰：与艾玛同席中毒时也必须稳定替死，重算不得漂移。
        prepare_night_preview(game)
        deaths = {death["target_card"] for death in game["night"]["preview"]["deaths"]}
        self.assertIn("millia", deaths, "换血对象的致命攻击没有转移到米莉亚牌")
        self.assertNotIn(target_card["id"], deaths, "换血对象仍在预结算中出局")

        for _ in range(3):
            prepare_night_preview(game)
            deaths = {death["target_card"] for death in game["night"]["preview"]["deaths"]}
            self.assertIn("millia", deaths, "重算后预结算漂移")
            self.assertNotIn(target_card["id"], deaths, "重算后预结算漂移")

    def test_gateway_authenticator_sends_a_numeric_group(self):
        """网关核销的群号必须是整数：schema 是 StrictInt，命令行传进来的是字符串或群列表。"""
        with self.client() as client:
            with patch.dict(os.environ, {"GAME_QQ_GROUP_ID": "1105925736,775621176"}):
                transport = TestClientTransport(client)
                authenticate = gateway_authenticator(
                    transport, "test-gateway-secret", "1105925736,775621176"
                )
                player = ProtocolClient(transport, "虚拟玩家1", origin="http://testserver")
                player.login_player(
                    "900001",
                    "虚拟玩家1",
                    gateway_token="test-gateway-secret",
                    group_id="1105925736,775621176",
                    authenticator=authenticate,
                )
            self.assertTrue(player.token, "网关核销失败时拿不到玩家令牌")

    def test_policy_never_un_readies_itself_in_the_lobby(self):
        """首次准备阶段不能重复点「准备」：该行动在 lobby 阶段是开关，重复提交等于取消准备。"""
        with self.client() as client:
            harness = Harness(client, seed=23)
            harness.join()
            actor = harness.roster.seats[0]
            actor.client.refresh()
            self.assertEqual(actor.client.view["phase"], "lobby")
            actor.client.submit("lobby.ready", {})
            actor.client.refresh()
            decision = actor.policy.decide(actor.client)
            self.assertNotEqual(
                decision and decision.action, "lobby.ready", "已准备的席位被策略再次提交准备"
            )
            if decision is not None:
                actor.client.submit(decision.action, decision.payload)
            actor.client.refresh()
            seat = next(item for item in actor.client.view["seats"] if item["id"] == actor.seat_id)
            self.assertTrue(seat["ready"], "策略把自己的准备状态取消了")

    def test_policy_drives_puppet_panels_through_as_seat(self):
        """傀儡席没有自主行动，策略必须像真人控制者那样用 as_seat 代提交。

        否则梅露露复活出傀儡后，该席既没有行动又占着待办，整局会永远卡住。
        """
        from backend.app.simulator.policy import HeuristicPolicy

        panel_actions = [
            {
                "id": "speech.done",
                "label": "*结束本次发言",
                "short_label": "结束",
                "payload": {},
                "fields": [],
                "group": "流程",
                "as_seat": "2",
            }
        ]
        view = {
            "status": "playing",
            "phase": "speech",
            "half": "day",
            "day": 2,
            "public": {"speaker": "2", "speech_order": ["2", "3"]},
            "self": {
                "seat_id": "5",
                "puppet_controls": [{"seat_id": "2", "name": "虚拟玩家2", "actions": panel_actions}],
            },
            "actions": [],
        }

        class FakeClient:
            def __init__(self, view):
                self.view = view

            def action(self, action_id):
                return next((d for d in self.view["actions"] if d["id"] == action_id), None)

            def available(self, action_id):
                return [d for d in self.view["actions"] if d["id"] == action_id]

        client = FakeClient(view)
        decision = HeuristicPolicy(seed=1).decide(client)
        self.assertIsNotNone(decision, "控制者没有为傀儡席做出任何决策")
        self.assertEqual(decision.action, "speech.done")
        self.assertEqual(decision.as_seat, "2", "傀儡决策没有带上 as_seat")
        # 决策结束后必须还原控制者自己的视图，不能把傀儡面板留在 client.view 上。
        self.assertEqual(client.view, view)

    def client(self):
        client = TestClient(
            app, base_url="http://testserver", headers={"Origin": "http://testserver"}
        )
        return client


if __name__ == "__main__":
    unittest.main()
