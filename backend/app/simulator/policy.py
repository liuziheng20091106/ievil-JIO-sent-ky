"""虚拟玩家的决策策略：只依据服务端裁剪后的视图做合法选择。

策略刻意保持「愚蠢但合法」：它要测试的是规则与流程，不是 AI 战术。
每个决策点都从视图的 ``actions``/``fields`` 里读候选值，因此永远不会提交
服务端没开放的组合——一旦服务端少给了合法选项，模拟器就会立刻卡住并报错。
"""

import random
from dataclasses import dataclass, field



@dataclass
class Decision:
    """一次决策：行动 id 与载荷；``note`` 只用于日志。"""

    action: str
    payload: dict = field(default_factory=dict)
    note: str = ""

    def __repr__(self):
        detail = ",".join(f"{k}={v}" for k, v in self.payload.items())
        return f"{self.action}({detail})"


def option_values(descriptor, name):
    for item in descriptor["fields"]:
        if item["name"] == name:
            return [option["value"] for option in item.get("options", [])]
    return []


def field_default(descriptor, name, fallback=None):
    for item in descriptor["fields"]:
        if item["name"] == name:
            default = item.get("default")
            return fallback if default is None else default
    return fallback


def field_spec(descriptor, name):
    return next((item for item in descriptor["fields"] if item["name"] == name), None)


class HeuristicPolicy:
    """按阶段优先级挑一个行动，并只填视图允许的字段。

    策略的职责边界很硬：**绝不猜测合法性**。任何无法从视图推出的选择一律放弃
    （放弃本身也是服务端明确提供的行动），从而把「服务端没给出口」变成显式失败。
    """

    def __init__(self, seed=None, *, speak=True, nominate=True, aggression=0.5):
        self.random = random.Random(seed)
        self.speak = speak
        self.nominate = nominate
        self.aggression = aggression
        # 记住已经做过的「一次就好」决策，避免重复触发把状态来回改。
        self._ordered = set()
        self._filled_night = set()
        self._answered_photos = set()
        self._evidence_submitted = set()
        self._used_water = False
        self._revived = False

    # ------------------------------------------------------------------ 入口

    def decide(self, client):
        """返回下一个 :class:`Decision`，或 None 表示当前没有该做的事。"""
        view = client.view
        if view["status"] == "ended":
            return None
        for chooser in (
            self._lobby,
            self._hiro,
            self._night,
            self._day_skill,
            self._speech,
            self._nomination,
            self._voting,
            self._execution,
            self._balloon,
            self._misc,
        ):
            decision = chooser(client)
            if decision is not None:
                return decision
        return None

    # ------------------------------------------------------------------ 准备

    def _lobby(self, client):
        view = client.view
        if view["status"] != "lobby":
            return None
        ready = client.action("lobby.ready")
        if ready is None:
            return None
        self_seat = next((s for s in view["seats"] if s["id"] == view["self"]["seat_id"]), None)
        self_card_ids = [card["id"] for card in view["self"]["cards"]]
        order = client.action("lobby.order")
        # ``lobby.order`` 会把 ready 置回 False，所以每个阶段只排一次牌，
        # 否则会永远在「排牌 → 未准备 → 再排牌」之间打转。
        marker = (view["day"], view["phase"], bool(self_seat and self_seat.get("ready")))
        if order is not None and marker not in self._ordered:
            self._ordered.add(marker)
            top = self.random.choice(self_card_ids)
            return Decision("lobby.order", {"top": top}, "选上层")
        return Decision("lobby.ready", {}, "准备")

    def _hiro(self, client):
        """希罗回溯：默认按预结算继续，避免把模拟器卡在人为判定点上。"""
        decline = client.action("hiro.decline")
        if decline is not None:
            return Decision("hiro.decline", {}, "不回溯")
        return None

    # ------------------------------------------------------------------ 夜间

    def _night(self, client):
        view = client.view
        if view["phase"] not in {"night", "night_coco"}:
            return None
        if view["self"].get("night_confirmed"):
            return None
        submitted = {item["ability"] for item in view["self"].get("night_actions", [])}
        for descriptor in client.available("night.submit"):
            ability = descriptor["payload"]["ability"]
            if ability in submitted:
                continue
            payload = self._night_payload(client, descriptor, ability)
            if payload is None:
                continue
            # ``payload['ability']`` 是服务端用来区分同一 id 多条行动的关键字段，
            # 必须原样带上，否则 require_listed_action 匹配不到任何行动。
            payload = {**descriptor["payload"], **payload}
            return Decision("night.submit", payload, f"夜行 {ability}")
        confirm = client.action("night.confirm")
        if confirm is not None:
            return Decision("night.confirm", {}, "确认夜间")
        return None

    def _night_payload(self, client, descriptor, ability):
        for name in ("target", "target_card"):
            target = field_spec(descriptor, name)
            if target is None:
                continue
            options = option_values(descriptor, name)
            if not options:
                return None
            return {name: self.random.choice(options)}
        return {}

    # ------------------------------------------------------------------ 白天技能

    def _day_skill(self, client):
        view = client.view
        if view["half"] != "day":
            return None
        # 保命优先：被处决在即时，先处理临刑响应之外的紧急项由各自分支负责。
        for descriptor in client.available("day.skill"):
            if descriptor.get("group") == "私密伪装选择":
                # 伪装会被主持人裁定，模拟器默认不主动制造判定点。
                continue
            filled = self._fill(descriptor, {})
            if filled is None:
                continue
            if self._constrain_day_skill(client, filled) is None:
                continue
            if self.random.random() > self.aggression:
                continue
            return Decision("day.skill", filled, f"白天技能 {filled['ability']}")
        return None

    def _constrain_day_skill(self, client, payload):
        """修正已授权但语义受限的目标；返回 None 表示这次不该发动。

        ``day.skill`` 的目标在服务端还有额外约束（例如「打断发言」只能指向当前
        发言者），字段候选不会体现这一点，因此这里按规则收敛。
        """
        ability = payload.get("ability")
        if ability == "interrupt":
            # 「打断发言」只能在顺序发言阶段指向当前发言者本人；候选由服务端的
            # target 字段给出，但「必须是当前发言者」只有规则知道，必须在这里收敛，
            # 否则会一直提交一个服务端必然拒绝的目标。
            view = client.view
            if view["phase"] != "speech":
                return None
            speaker = view["public"].get("speaker")
            if not speaker or speaker == view["self"]["seat_id"]:
                return None
            payload["target"] = speaker
        elif ability == "last_speaker":
            payload.pop("target", None)
        elif ability == "photo":
            # 赠照片：不能送给自己，且必须有真实内容或画面，否则服务端拒收。
            mine = client.view["self"]["seat_id"]
            target = payload.get("target")
            if target == mine:
                return None
            payload.setdefault("text", "这是给你的照片。")
        return payload

    def _fill(self, descriptor, payload):
        """按字段定义补齐必填项；无法合法补齐时返回 None。

        以 ``descriptor['payload']`` 为基底：服务端用它区分同一 id 的多条行动
        （例如 ``night.submit`` 的 ability、``day.skill`` 的 ability），
        丢掉这些固定字段会让命令匹配不到任何已授权行动。
        """
        result = {**descriptor.get("payload", {}), **payload}
        for item in descriptor["fields"]:
            name, kind = item["name"], item["type"]
            if name in result:
                continue
            if kind in {"text", "textarea"}:
                if item.get("required"):
                    result[name] = item.get("default") or "模拟发言内容"
                continue
            if kind == "number":
                result[name] = item.get("default", item.get("min", 1))
                continue
            if kind == "checkbox":
                if item.get("required"):
                    result[name] = bool(item.get("default", True))
            if kind == "drawing":
                if item.get("required"):
                    return None
                continue
            options = option_values(descriptor, name)
            if not options:
                if item.get("required"):
                    return None
                continue
            if kind == "select":
                result[name] = item.get("default") or self.random.choice(options)
            else:
                low = item.get("min", 1 if item.get("required") else 0)
                high = min(item.get("max", len(options)), len(options))
                if low > high:
                    return None
                count = self.random.randint(low, high) if high else 0
                result[name] = self.random.sample(options, count)
        return result

    # ------------------------------------------------------------------ 发言

    def _speech(self, client):
        view = client.view
        if view["phase"] != "speech":
            return None
        speaker = view["public"].get("speaker")
        mine = view["self"]["seat_id"]
        if speaker == mine:
            done = client.action("speech.done")
            if done is not None and self.speak:
                return Decision("speech.done", {}, "结束发言")
            return Decision("speech.done", {}, "结束发言") if done else None
        if speaker is None:
            return None
        if mine in view["public"].get("speech_order", []):
            if self.speak:
                hint = client.action("speech.speak")
                if hint is not None:
                    return Decision("speech.speak", {"text": self._speech_text(client)}, "预提交发言")
            skip = client.action("speech.done")
            if skip is not None:
                return Decision("speech.done", {}, "本轮不发言")
        return None

    def _speech_text(self, client):
        view = client.view
        dead = [s["id"] for s in view["seats"] if not s["alive"]]
        lead = f"第{view['day']}天我的看法："
        if dead:
            return lead + "、".join(f"{sid}号" for sid in dead) + "号的角色牌已经出局，先听后续发言。"
        return lead + "目前没有确定的线索，先按顺序听完再做判断。"

    # ------------------------------------------------------------------ 提名

    def _nomination(self, client):
        view = client.view
        if view["phase"] != "nomination":
            return None
        nominate = client.action("vote.nominate")
        pass_action = client.action("vote.pass")
        if nominate is None and pass_action is None:
            return None
        if not self.nominate or self.random.random() < 0.5:
            if pass_action is not None:
                return Decision("vote.pass", {}, "放弃提名")
        if nominate is None:
            return Decision("vote.pass", {}, "放弃提名") if pass_action else None
        options = option_values(nominate, "target")
        if not options:
            return Decision("vote.pass", {}, "无可提名目标") if pass_action else None
        return Decision("vote.nominate", {"target": self.random.choice(options)}, "提名")

    # ------------------------------------------------------------------ 投票

    def _voting(self, client):
        view = client.view
        if view["phase"] != "voting":
            return None
        cast = client.action("vote.cast")
        if cast is None:
            return None
        choice = self.random.choice(["yes", "no", "abstain"])
        return Decision("vote.cast", {"choice": choice}, "投票")

    # ------------------------------------------------------------------ 处决

    def _execution(self, client):
        view = client.view
        if view["phase"] != "execution":
            return None
        confirm = client.action("execution.confirm")
        if confirm is not None:
            return Decision("execution.confirm", {}, "放弃临刑行动")
        shoot = client.action("execution.shoot")
        if shoot is not None:
            options = option_values(shoot, "target")
            if options:
                return Decision("execution.shoot", {"target": self.random.choice(options)}, "临刑开枪")
        return None

    # ------------------------------------------------------------------ 热气球

    def _balloon(self, client):
        choose = client.action("balloon.choose")
        if choose is not None:
            options = option_values(choose, "choice")
            pick = "make" if self.random.random() < 0.7 else "skip"
            if pick not in options:
                pick = options[0] if options else None
            if pick:
                return Decision("balloon.choose", {"choice": pick}, "热气球选择")
        agree = client.action("balloon.agree")
        decline = client.action("balloon.decline")
        if agree is not None or decline is not None:
            if self.random.random() < 0.6 and agree is not None:
                return Decision("balloon.agree", {}, "同意名单")
            if decline is not None:
                return Decision("balloon.decline", {}, "拒绝名单")
        propose = client.action("balloon.propose")
        if propose is not None and self.random.random() < 0.3:
            filled = self._fill(propose, {})
            if filled is not None:
                return Decision("balloon.propose", filled, "提议名单")
        return None

    # ------------------------------------------------------------------ 其它

    def _misc(self, client):
        """照片授权、13水、复活、遗留证物等低频行动。"""
        for descriptor in client.view.get("actions", []):
            action_id = descriptor["id"]
            if action_id == "honoka.witness":
                roles = option_values(descriptor, "role")
                if roles:
                    return Decision(
                        action_id,
                        {**descriptor["payload"], "role": self.random.choice(roles)},
                        "选择目击显示身份",
                    )
            if action_id == "photo.permission":
                photo_id = descriptor["payload"]["photo_id"]
                # 授权可以反复改，但重复提交同一状态没有意义，会让对局原地打转。
                if photo_id in self._answered_photos:
                    continue
                self._answered_photos.add(photo_id)
                return Decision(action_id, {"photo_id": photo_id, "allow": True}, "照片授权")
            if action_id == "water.use":
                if self._used_water:
                    continue
                options = option_values(descriptor, "target")
                if options and self.random.random() < 0.25:
                    self._used_water = True
                    return Decision(action_id, {"target": self.random.choice(options)}, "使用13水")
            if action_id == "meruru.revive":
                if self._revived:
                    continue
                options = option_values(descriptor, "death_id")
                if options:
                    self._revived = True
                    return Decision(action_id, {"death_id": options[-1]}, "复活傀儡")
            if action_id == "evidence.submit":
                card_id = descriptor["payload"]["card_id"]
                if card_id in self._evidence_submitted:
                    continue
                self._evidence_submitted.add(card_id)
                return Decision(
                    action_id, {"card_id": card_id, "text": "模拟遗留证物"}, "提交证物"
                )
            if action_id == "hiro.exit":
                return None
        return None


class ScriptedPolicy(HeuristicPolicy):
    """可注入固定偏好的策略，便于回归检查复现特定分支。"""

    def __init__(self, seed=None, *, votes="yes", night_target=None, **kwargs):
        super().__init__(seed, **kwargs)
        self.votes = votes
        self.night_target = night_target

    def _voting(self, client):
        cast = client.action("vote.cast")
        if cast is None:
            return None
        return Decision("vote.cast", {"choice": self.votes}, "投票")

    def _night_payload(self, client, descriptor, ability):
        payload = super()._night_payload(client, descriptor, ability)
        if payload and self.night_target and "target" in payload:
            options = option_values(descriptor, "target")
            if self.night_target in options:
                payload["target"] = self.night_target
        return payload
