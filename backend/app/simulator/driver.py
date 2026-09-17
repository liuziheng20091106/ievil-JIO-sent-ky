"""模拟器驱动：组建阵容、自动主持、推进整局直到结束。

主持人由脚本扮演（``HostBrain``），只处理「必须由主持人宣布或裁定」的事项，
系统自己能算完的阶段交给 5 秒自动推进；因此一局模拟会真实走过全部阶段。

参考「真人操作」用法时，把 ``Simulation(host_brain=None)`` 留空，``step`` 只驱动
玩家，主持人动作由外部按 :meth:`Simulation.host_tasks` 决定。
"""

import time
from dataclasses import dataclass, field

from .client import ProtocolError, ProtocolClient, VersionConflict
from .policy import Decision, HeuristicPolicy

MAX_STEPS = 4000
MAX_SECONDS = 300.0


@dataclass
class SeatActor:
    seat_id: str
    client: ProtocolClient
    policy: HeuristicPolicy
    nickname: str = ""
    player: dict = field(default_factory=dict)

    def __repr__(self):
        return f"<Seat {self.seat_id} {self.nickname}>"


@dataclass
class SimulationResult:
    game_id: str
    status: str
    days: int
    steps: int
    elapsed: float
    winner: str | None
    reason: str | None
    seats: list[str]
    log: list[str] = field(default_factory=list)
    host_actions: int = 0

    @property
    def finished(self):
        return self.status == "ended"


class HostBrain:
    """脚本主持人：只做裁定与宣布，把系统能自算的部分留给自动推进。"""

    def __init__(self, log=None, *, resolve_defaults=True, max_days=12):
        self.log = log if log is not None else []
        self.resolve_defaults = resolve_defaults
        self.max_days = max_days

    def act(self, host: ProtocolClient) -> str | None:
        """返回本次做掉的行动 id；None 表示主持人不该动、交给自动推进。"""
        view = host.view
        if view["status"] == "ended":
            return None
        if view["status"] == "lobby":
            return self._lobby(host)
        tasks = view.get("host", {}).get("tasks", [])

        # 有阻塞待办时先处理：待裁定事项、宣判、交牌。
        pending = [t for t in tasks if t["kind"] == "pending" and t.get("blocking")]
        if pending and self.resolve_defaults:
            outcome = self._resolve(host, pending[0])
            # "refresh" 表示裁定与别的席位撞车；刷新后下一轮会重新取待办。
            return "refresh" if outcome == "refresh" else outcome
        winner = next((t for t in tasks if t["kind"] == "winner"), None)
        if winner:
            return self._confirm_winner(host)
        if view["day"] > self.max_days:
            return self._abort(host, f"模拟超过{self.max_days}天仍未结束")
        if pending:
            return None

        # 审阅预结算并发布夜间结果是主持人的职责，系统不会自动完成。
        review = next((t for t in tasks if t["kind"] == "review" and t.get("blocking")), None)
        if review:
            return self._advance(host)
        advance = next((t for t in tasks if t["kind"] == "advance" and t.get("blocking")), None)
        if advance:
            return self._advance(host)
        return None

    # ------------------------------------------------------------------ 细节

    def _lobby(self, host):
        # 全员已准备时优先开局；否则才考虑开放参局。
        # 注意 ``join_open`` 不在任何视图里，只能靠 ``room.open_join`` 是否列出反推。
        start = host.action("host.start")
        if start is not None:
            try:
                host.submit("host.start", {})
                return "host.start"
            except ProtocolError as error:
                self.log.append(f"开局被拒：{error.detail}")
                return None
        if host.action("room.open_join", {"open": True}) is not None:
            try:
                host.open_join(True)
                return "room.open_join"
            except (VersionConflict, ProtocolError):
                return None
        return None

    def _advance(self, host):
        try:
            host.submit("host.advance", {})
            return "host.advance"
        except VersionConflict:
            return None
        except ProtocolError as error:
            self.log.append(f"主持人推进被拒：{error.detail}")
            return None

    def _confirm_winner(self, host):
        print_v = host.action("host.confirm_winner")
        if print_v is None:
            return None
        try:
            host.submit("host.confirm_winner", {"confirm": True})
            return "host.confirm_winner"
        except ProtocolError as error:
            self.log.append(f"宣判被拒：{error.detail}")
            return None

    def _abort(self, host, reason):
        try:
            host.submit("host.end", {"winner": "aborted", "reason": reason})
            return "host.end"
        except ProtocolError:
            return None

    def _resolve(self, host, task):
        """对一条待裁定事项给出「按规则默认值」的裁定。

        默认值全部取行动描述里的 ``default``，也就是主持人界面上预填的那一项；
        这样做不是「自动通过」，而是复现主持人点确认时最省事的那条路径。
        个别字段的默认值在服务端并不总是合法（疑似凶手名单必须同时包含真凶与
        汉娜，且「不列入蕾雅」只在蕾雅是魔女时才成立），这里显式改成满足约束的值。
        """
        action_id = task["action"]
        payload = dict(task["payload"])
        descriptor = next(
            (
                item
                for item in host.view["actions"]
                if item["id"] == action_id
                and all(item["payload"].get(k) == v for k, v in payload.items())
            ),
            None,
        )
        if descriptor is None:
            return None
        for item in descriptor["fields"]:
            if item["name"] in payload:
                continue
            default = item.get("default")
            kind = item["type"]
            if kind == "checkbox":
                payload[item["name"]] = bool(default) if default is not None else True
            elif default is not None:
                payload[item["name"]] = default
            elif kind in {"text", "textarea"} and item.get("required"):
                payload[item["name"]] = "模拟主持人裁定"
            elif kind == "select" and item.get("options"):
                payload[item["name"]] = item["options"][0]["value"]
            elif kind == "multiselect" and item.get("required"):
                options = [o["value"] for o in item["options"]]
                want = item.get("min", 1)
                if len(options) < want:
                    return None
                payload[item["name"]] = options[:want]
        self._fix_suspects(payload)
        return self._submit_resolution(host, action_id, payload)

    def _fix_suspects(self, payload):
        """把疑似凶手名单修正为必然合法的三人：真凶 + 汉娜 + 任意第三人。

        ``omit_leia`` 只在蕾雅确实是魔女时可勾选；模拟器无法从视图确认这一点，
        因此一律不勾，并在名单里保留蕾雅（若她被规则要求出现）。
        """
        suspects = payload.get("suspects")
        if not isinstance(suspects, list):
            return
        if payload.get("omit_leia"):
            payload["omit_leia"] = False
        suspects = list(dict.fromkeys(suspects))
        if "hanna" not in suspects:
            suspects = [*suspects, "hanna"]
        payload["suspects"] = suspects[:3]

    def _submit_resolution(self, host, action_id, payload):
        try:
            host.submit(action_id, payload)
            return action_id
        except VersionConflict:
            # 别的席位刚刚改过状态：刷新后由调用方重新取一次待办再裁定。
            self.log.append(f"裁定冲突 {action_id}：状态已变化，刷新后重试")
            return "refresh"
        except ProtocolError as error:
            self.log.append(f"裁定被拒 {action_id}: {error.detail}")
            return self._repair(host, action_id, payload, error)

    def _repair(self, host, action_id, payload, error):
        """裁定被拒时按服务端文案做最小修正，再试一次。

        服务的裁定默认值并不总是合法（例如「裁定魔女蕾雅不入名单」只在蕾雅确实
        是魔女时才能勾选；名单要求同时包含真凶与汉娜）。这里只处理已知的、
        可判定的冲突，其余仍然报错，避免把真正的规则缺陷掩盖成「自动重试」。
        """
        detail = error.detail or ""
        if action_id != "host.resolve":
            return None
        if payload.get("omit_leia") and "蕾雅" in detail:
            fixed = {**payload, "omit_leia": False}
            suspects = fixed.get("suspects")
            if isinstance(suspects, list) and "leia" not in suspects:
                # 取消「不列入蕾雅」后，名单必须把蕾雅补回去。
                suspects = [*suspects[:2], "leia"] if len(suspects) >= 3 else [*suspects, "leia"]
                fixed["suspects"] = suspects[:3]
            return self._submit_resolution(host, action_id, fixed)
        if "名单必须包含" in detail:
            for required in ("hanna", "leia"):
                if required in detail and payload.get("suspects"):
                    suspects = list(payload["suspects"])
                    if required not in suspects:
                        suspects = suspects[:2] + [required]
                        return self._submit_resolution(
                            host, action_id, {**payload, "suspects": suspects[:3]}
                        )
        return None


class Roster:
    """一组虚拟玩家；负责登录、入场、发牌前准备与逐回合驱动。"""

    def __init__(self, seats, host, *, log=None):
        self.seats = seats
        self.host = host
        self.log = log if log is not None else []

    def __len__(self):
        return len(self.seats)

    def seat(self, seat_id):
        return next((s for s in self.seats if s.seat_id == seat_id), None)

    def alive_clients(self):
        return [s for s in self.seats if s.client.view and s.client.view["status"] != "ended"]


class Simulation:
    """一整局的编排器：准备 → 循环决策 → 结束校验。"""

    def __init__(
        self,
        roster: Roster,
        *,
        host_brain=None,
        log=None,
        io=None,
        max_steps=MAX_STEPS,
        max_seconds=MAX_SECONDS,
        verbose=False,
        fast_forward=True,
    ):
        self.roster = roster
        self.host_brain = host_brain
        self.log = log if log is not None else []
        self.io = io
        self.max_steps = max_steps
        self.max_seconds = max_seconds
        self.verbose = verbose
        self.fast_forward = fast_forward
        self.steps = 0
        self.host_actions = 0

    def note(self, text):
        self.log.append(text)
        if self.verbose and self.io is not None:
            print(text, file=self.io)

    # ------------------------------------------------------------------ 准备

    def prepare(self):
        """开放参局 → 全员入场 → 首次准备发牌 → 排序后再次准备 → 主持人开局。"""
        self.roster.host.refresh()
        self.roster.host.open_join(True)
        for actor in self.roster.seats:
            actor.client.game_id = self.roster.host.game_id
        self._drive_until(lambda: self._all_seated(), "全员入场")
        self._drive_until(lambda: self._dealt(), "首次准备发牌")
        self._drive_until(lambda: self._ordered(), "上下牌与再次准备")
        # 全员再次准备后由主持人开局：这一步必须真的发生，否则对局会停在 ordering。
        self.roster.host.refresh()
        if self.roster.host.view["phase"] == "ordering":
            if self.host_brain is not None:
                self.host_brain.act(self.roster.host)
            self.roster.host.refresh()
        if self.roster.host.view["status"] == "lobby":
            raise RuntimeError(f"主持人未能开局，仍停在 {self.roster.host.view['phase']}")

    def _all_seated(self):
        view = self.roster.host.view
        return all(seat["occupied"] for seat in view["seats"])

    def _dealt(self):
        return self.roster.host.view["phase"] == "ordering"

    def _ordered(self):
        view = self.roster.host.view
        return view["phase"] == "ordering" and all(seat["ready"] for seat in view["seats"])

    def _drive_until(self, done, label, limit=400):
        for _ in range(limit):
            self.roster.host.refresh()
            if done():
                return
            progressed = self._players_once()
            if not progressed:
                self.roster.host.refresh()
                if done():
                    return
                raise RuntimeError(f"{label}阶段没有玩家可行动作，流程卡住：{self._summary()}")
        raise RuntimeError(f"{label}阶段超过步数上限")

    # ------------------------------------------------------------------ 主循环

    def run(self) -> SimulationResult:
        started = time.monotonic()
        self.prepare()
        self.note(f"对局开始：{self.roster.host.game_id}")
        while self.steps < self.max_steps:
            if time.monotonic() - started > self.max_seconds:
                self.note("模拟超时")
                break
            self.roster.host.refresh()
            before = self.roster.host.view["version"]
            if self.roster.host.view["status"] == "ended":
                break
            self._players_once()
            if self.host_brain is not None:
                host_action = self.host_brain.act(self.roster.host)
                if host_action:
                    self.host_actions += 1
                    self.note(f"主持人：{host_action}")
            self.roster.host.refresh()
            if self.roster.host.view["status"] == "ended":
                break
            if self.roster.host.view["version"] != before:
                continue
            if self._await_auto_advance():
                continue
            view = self.roster.host.view
            raise RuntimeError(
                f"对局停在第{view['day']}天 {view['phase']}：无人可行动\n{self._summary()}"
            )
        self.roster.host.refresh()
        view = self.roster.host.view
        result = view["result"] or {}
        return SimulationResult(
            game_id=view["id"],
            status=view["status"],
            days=view["day"],
            steps=self.steps,
            elapsed=time.monotonic() - started,
            winner=result.get("winner"),
            reason=result.get("reason"),
            seats=[s.seat_id for s in self.roster.seats],
            log=self.log,
            host_actions=self.host_actions,
        )

    def _players_once(self):
        progressed = False
        for actor in self.roster.seats:
            try:
                if self._step_actor(actor):
                    progressed = True
            except VersionConflict:
                progressed = True
        return progressed

    def _step_actor(self, actor):
        """让一个虚拟玩家做一步；返回是否推进了状态。

        其它玩家并发提交会让本地的 ``actions`` 列表过期，服务端会以 422
        「此操作不可用」拒绝。真实客户端此时要刷新后让人重新确认；模拟器把
        「重新确认」实现为重新决策一次，因此这里刷新后重试一轮而不是直接失败。
        """
        client = actor.client
        for _ in range(3):
            client.refresh()
            view = client.view
            if view["status"] == "ended":
                return False
            decision = actor.policy.decide(client)
            if decision is None:
                return False
            self.steps += 1
            self.note(f"{actor.seat_id}号：{decision.action} {decision.payload}")
            try:
                client.submit(decision.action, decision.payload)
                return True
            except VersionConflict:
                continue
            except ProtocolError as error:
                if error.status != 422:
                    raise
                self.note(f"{actor.seat_id}号：{decision.action} 被拒（{error.detail}），刷新后重试")
                continue
        raise RuntimeError(f"{actor.seat_id}号连续提交被拒：{decision}")

    def _await_auto_advance(self):
        """系统自己在 5 秒内推进的阶段，等它一下而不是报卡死。

        这是真实规则的等待：``AUTO_PHASES`` 里无人待办时由系统倒计时推进。
        模拟器可以选择等（更贴近真实节奏）或直接由主持人推进（更快），
        ``fast_forward`` 控制后者，跑批时用它把单局时间从分钟级压到秒级。
        """
        self.roster.host.refresh()
        view = self.roster.host.view
        if view["status"] != "playing":
            return False
        tasks = view.get("host", {}).get("tasks", [])
        advance = next((t for t in tasks if t["kind"] == "advance"), None)
        if self.fast_forward and advance is not None and advance.get("blocking"):
            # 待办说「可以推进」时直接推：不必等系统那 5 秒倒计时。
            # night_coco 等阶段系统不会自己计时，只能由主持人推进。
            return self._advance_now()
        ready_at = view["public"].get("auto_advance_at")
        if ready_at is None and not any(t["kind"] == "advance" for t in tasks):
            return False
        deadline = time.monotonic() + 8.0
        while time.monotonic() < deadline:
            time.sleep(0.2)
            self.roster.host.refresh()
            if self.roster.host.view["version"] != view["version"]:
                return True
            if self.roster.host.view["status"] == "ended":
                return True
        return False

    def _advance_now(self):
        """由主持人替系统推进本阶段；被拒说明条件其实不成立，交给上层报卡死。"""
        self.roster.host.refresh()
        if self.roster.host.action("host.advance") is None:
            return False
        try:
            self.roster.host.submit("host.advance", {})
        except ProtocolError as error:
            self.log.append(f"快速推进被拒：{error.detail}")
            return False
        self.host_actions += 1
        return True

    # ------------------------------------------------------------------ 诊断

    def _summary(self):
        view = self.roster.host.view
        lines = [f"阶段 {view['phase']}（第{view['day']}天·{view['half']}）"]
        for task in view.get("host", {}).get("tasks", []):
            lines.append(f"  主持待办：{task['kind']} {task['title']}")
        for actor in self.roster.seats:
            pending = [d["id"] for d in actor.client.view.get("actions", [])]
            lines.append(f"  {actor.seat_id}号：{pending or '无行动'}")
        return "\n".join(lines)

    def host_tasks(self):
        """主持人待办列表：交给真人主持人时用它决定下一步。"""
        self.roster.host.refresh()
        return self.roster.host.view.get("host", {}).get("tasks", [])


def run_simulation(
    roster: Roster,
    *,
    host_brain=None,
    log=None,
    io=None,
    max_steps=MAX_STEPS,
    max_seconds=MAX_SECONDS,
    verbose=False,
) -> SimulationResult:
    simulation = Simulation(
        roster,
        host_brain=host_brain,
        log=log,
        io=io,
        max_steps=max_steps,
        max_seconds=max_seconds,
        verbose=verbose,
    )
    return simulation.run()


__all__ = [
    "Decision",
    "HostBrain",
    "Roster",
    "SeatActor",
    "Simulation",
    "SimulationResult",
    "run_simulation",
]
