"""虚拟玩家的决策策略：只依据服务端裁剪后的视图做合法选择。

策略刻意保持「愚蠢但合法」：它要测试的是规则与流程，不是 AI 战术。
每个决策点都从视图的 ``actions``/``fields`` 里读候选值，因此永远不会提交
服务端没开放的组合——一旦服务端少给了合法选项，模拟器就会立刻卡住并报错。
"""

import random
from dataclasses import dataclass, field, replace



@dataclass
class Decision:
    """一次决策：行动 id 与载荷；``note`` 只用于日志。

    ``as_seat`` 用于傀儡代操作：控制者以该席位身份提交，与人类客户端一致。
    """

    action: str
    payload: dict = field(default_factory=dict)
    note: str = ""
    as_seat: str | None = None

    def __repr__(self):
        detail = ",".join(f"{k}={v}" for k, v in self.payload.items())
        target = f"@{self.as_seat}" if self.as_seat else ""
        return f"{self.action}{target}({detail})"


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


def puppet_view(view, panel):
    """把控制者视图裁剪成「以傀儡席位身份看到的视图」。

    傀儡面板里的 ``actions`` 已经是该席此刻仍可提交的全部行动（服务端已剔除
    已用掉的夜间技能与已提交的阶段行动），因此这里只替换行动与自身身份，
    让同一套决策逻辑原样复用；``public`` 等公共信息保持不变。
    """
    if "self" not in view:
        return view
    return {
        **view,
        "actions": panel["actions"],
        "self": {
            **view["self"],
            "seat_id": panel["seat_id"],
            # 夜间已确认与否不参与判断：面板有 night.confirm 才会被选中。
            "night_confirmed": False,
            "night_actions": [],
        },
    }


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
            self._night,
            self._day_skill,
            self._speech,
            self._nomination,
            self._voting,
            self._execution,
            self._misc,
            self._puppet,
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
            # 艾玛、米莉亚、亚里沙必须放下层，上层只能从另一牌里选。
            fixed_lower = {"emma", "millia", "arisa"}
            top = next(
                (card["id"] for card in view["self"]["cards"] if card["role_id"] not in fixed_lower),
                self_card_ids[0],
            )
            return Decision("lobby.order", {"top": top}, "选上层")
        if view["phase"] == "lobby" and self_seat is not None and self_seat.get("ready"):
            # 首次准备阶段的 ``lobby.ready`` 是开关：已准备时再点一次等于「取消准备」。
            # 七个席位全部入座并准备后才会发牌，重复提交会让准备状态一直闪烁，
            # 也会让真人对局永远凑不齐「全员准备」（``ordering`` 阶段的该行动才是单向的）。
            return None
        return Decision("lobby.ready", {}, "准备")

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
        ballot = client.action("vote.cast")
        if ballot is None:
            return None
        # 一次性选票：每个候选一行，只投服务端给出的选项。提名自动同意行只有
        # 「同意」；决斗日带有 duel 标记的行至少要有一张同意，否则整份选票会被拒。
        payload = {}
        duel_rows = []
        for item in ballot["fields"]:
            options = [option["value"] for option in item.get("options", [])]
            if not options:
                return None
            default = item.get("default")
            payload[item["name"]] = default if default in options else self.random.choice(options)
            if item.get("duel"):
                duel_rows.append(item["name"])
        if duel_rows and not any(payload.get(name) == "yes" for name in duel_rows):
            payload[duel_rows[0]] = "yes"
        return Decision("vote.cast", payload, f"投票（{len(payload)} 名候选）")

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

    # ------------------------------------------------------------------ 傀儡

    def _puppet(self, client):
        """按控制者身份代操作傀儡席。

        傀儡席自己没有行动（服务端只把行动放进控制者的 ``puppet_controls``），
        因此模拟器必须像真人控制者那样代提交，否则整局会卡在该席的待办上。
        傀儡面板里的行动列表本来就是「该席此刻仍可提交的部分」，所以直接复用
        同一个决策流程，只需把身份换成傀儡席位并在提交时带上 ``as_seat``。
        """
        for panel in client.view["self"].get("puppet_controls", []):
            real = client.view
            try:
                client.view = puppet_view(real, panel)
                decision = self._puppet_decision(client)
            finally:
                client.view = real
            if decision is not None:
                return replace(decision, as_seat=panel["seat_id"], note=f"傀儡{panel['seat_id']}号 {decision.note}")
        return None

    def _puppet_decision(self, client):
        for chooser in (
            self._night,
            self._day_skill,
            self._speech,
            self._nomination,
            self._voting,
            self._execution,
        ):
            decision = chooser(client)
            if decision is not None:
                return decision
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
        # 决斗强制票这一轮服务端只给「同意」，固定偏好也不能把它投成非法值。
        options = option_values(cast, "choice")
        choice = self.votes if not options or self.votes in options else options[0]
        return Decision("vote.cast", {"choice": choice}, "投票")

    def _night_payload(self, client, descriptor, ability):
        payload = super()._night_payload(client, descriptor, ability)
        if payload and self.night_target and "target" in payload:
            options = option_values(descriptor, "target")
            if self.night_target in options:
                payload["target"] = self.night_target
        return payload
