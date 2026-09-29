"""模拟器傀儡席的夜间行动回归检查。

傀儡由梅露露的魔女技能复活产生（牌的 ``states["no_ability"]``）。规则规定傀儡不能
发动角色技能，只剩魔女刀，因此一张傀儡牌每夜最多只有一个 ``night.submit`` 条目
（见 ``actions.night_abilities`` 对 ``no_ability`` 的提前返回）。

傀儡席自己没有视图：服务端只把 ``actions`` 放进控制者的 ``puppet_controls``。
模拟器把面板当成傀儡的视图复用（``policy.puppet_view``），而 ``policy._night`` 靠
``self.night_actions`` 判断哪些技能已经提交过。面板里没有这个字段，于是策略会认为
「什么都没提交」，反复重投同一条 ``night.submit``，对局永远走不到确认。

真实事故：``checks/test_simulator.py`` 的 seed 3 一局烧满 600 秒预算仍停在 ``playing``，
日志尾部是同一席位反复 ``night.submit``。
"""

import unittest

from backend.app.game.actions import night_abilities
from backend.app.game.catalog import ROLES
from backend.app.simulator.policy import HeuristicPolicy


class FakeClient:
    """只提供策略真正用到的三件事：视图、按 id 取行动、列出某 id 的全部行动。"""

    def __init__(self, view):
        self.view = view

    def action(self, action_id):
        return next((d for d in self.view["actions"] if d["id"] == action_id), None)

    def available(self, action_id):
        return [d for d in self.view["actions"] if d["id"] == action_id]


def puppet_panel(*, submitted):
    """还原服务端给控制者的傀儡夜间面板。

    ``submitted=False`` 是「这一夜还什么都没提交」：只有 ``night.submit`` 与
    ``night.confirm``。``submitted=True`` 是已经交过刀：服务端会额外给出
    ``night.clear``，并把 ``night.submit`` 的标题从「选择」改成「修改」
    （见 ``actions.actions_for`` 的夜间分支）。
    """
    panel = [
        {
            "id": "night.submit",
            "label": ("*修改" if submitted else "*选择") + "魔女刀",
            "short_label": "夜行",
            "payload": {"ability": "knife"},
            "fields": [
                {
                    "name": "target",
                    "label": "目标",
                    "kind": "select",
                    "required": True,
                    "options": [
                        {"value": "1", "label": "1号"},
                        {"value": "4", "label": "4号"},
                    ],
                }
            ],
            "group": "夜间",
            "as_seat": "2",
        }
    ]
    if submitted:
        panel.append(
            {
                "id": "night.clear",
                "label": "*清除未确认夜间选择",
                "short_label": "清除",
                "payload": {},
                "fields": [],
                "group": "夜间",
                "as_seat": "2",
            }
        )
    panel.append(
        {
            "id": "night.confirm",
            "label": "*确认已选行动（未选视为放弃）",
            "short_label": "确认",
            "payload": {},
            "fields": [],
            "group": "夜间",
            "as_seat": "2",
        }
    )
    return panel


def controller_view(*, submitted, seat_id="5", puppet_seat="2"):
    """控制者（魔女梅露露）自己的视图，傀儡面板挂在 ``puppet_controls`` 上。"""
    return {
        "status": "playing",
        "phase": "night",
        "half": "night",
        "day": 2,
        "public": {},
        "self": {
            "seat_id": seat_id,
            "night_confirmed": False,
            "puppet_controls": [
                {
                    "seat_id": puppet_seat,
                    "name": f"虚拟玩家{puppet_seat}",
                    "actions": puppet_panel(submitted=submitted),
                }
            ],
        },
        "actions": [],
    }


class PuppetNightDecision(unittest.TestCase):
    def decide(self, *, submitted):
        view = controller_view(submitted=submitted)
        client = FakeClient(view)
        decision = HeuristicPolicy(seed=1).decide(client)
        # 决策结束后必须还原控制者自己的视图，不能把傀儡面板留在 client.view 上。
        self.assertEqual(client.view, view, "控制者视图没有还原")
        return decision

    def test_puppet_submits_the_knife_when_nothing_was_submitted(self):
        """本夜尚未提交时，控制者要为傀儡席交出那一刀。"""
        decision = self.decide(submitted=False)
        self.assertIsNotNone(decision, "控制者没有为傀儡席做出任何决策")
        self.assertEqual(decision.action, "night.submit")
        self.assertEqual(decision.as_seat, "2", "傀儡决策没有带上 as_seat")
        self.assertEqual(decision.payload["ability"], "knife")

    def test_puppet_confirms_instead_of_resubmitting_an_already_submitted_knife(self):
        """刀已经交过时必须转去确认夜间，不能无限重投同一条 night.submit。

        这是本次修复的核心：面板给出 ``night.clear`` 就等于「该席本夜已有提交」，
        策略要据此认定那一刀已经交过。
        """
        decision = self.decide(submitted=True)
        self.assertIsNotNone(decision, "已提交后控制者不再为傀儡席做任何决策")
        self.assertEqual(
            decision.action,
            "night.confirm",
            "傀儡席已提交过魔女刀，控制者仍在重投（活锁）",
        )
        self.assertEqual(decision.as_seat, "2")


class PuppetAbilityInvariant(unittest.TestCase):
    def test_a_puppet_card_offers_at_most_one_night_action(self):
        """面板回填依赖「傀儡牌每夜至多一个技能」这条不变式。

        它一旦被放宽，本文件上一条断言就会以「静默漏掉技能」的方式失效，
        所以这里先失败，提示回填逻辑需要改成能区分具体技能的形式。
        """
        for role in ROLES:
            for witch in (False, True):
                card = {
                    "role_id": role,
                    "witch": witch,
                    "uses": {},
                    "states": {"no_ability": True},
                }
                self.assertLessEqual(
                    len(night_abilities({}, card)),
                    1,
                    f"{role}（witch={witch}）的傀儡牌给出了多个夜间行动",
                )


if __name__ == "__main__":
    unittest.main()
