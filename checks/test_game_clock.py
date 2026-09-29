"""对局时钟注入：倒计时到点由时钟说了算，检查与模拟不必真实等待。

规则层（``engine``）与后台计时（``realtime``）都读同一个 ``backend.app.game.clock``；
这里装上 :class:`FakeClock`，把 5 秒自动推进、30 秒顺序发言、10 秒讨论结束与主持人
的 30 秒警告一次性推到期，最后用假时钟驱动一局完整模拟，证明：

* 对局照常走到 ``ended``（时钟换掉不改变任何规则语义）；
* 整个模拟的真实耗时远小于被跳过的等待时长（等待确实被跳过了，而不是被绕过）。

检查自己不做任何真实等待：没有 ``time.sleep``，时间只在虚拟时钟上往前推。
"""

import os
import tempfile
import time
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app import realtime, storage
from backend.app.game import DEFAULT_CODEX, apply_command, create_game
from backend.app.game import clock as game_clock
from backend.app.game.catalog import (
    AUTO_ADVANCE_DELAY,
    DISCUSSION_END_DELAY,
    SPEECH_TURN_SECONDS,
)
from backend.app.game.engine import (
    expire_warnings,
    run_auto_advance,
    run_speech_timer,
)
from backend.app.game.views import host_tasks
from backend.app.main import app
from backend.app.simulator.driver import HostBrain
from backend.app.simulator.harness import Harness
from backend.app.simulator.policy import HeuristicPolicy

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
    """与 checks/test_resolution.py 同口径的最小对局夹具（这里独立写一份）。"""
    game = create_game(DEFAULT_CODEX)
    for seat in game["seats"]:
        seat["occupant_id"] = "p" + seat["id"]
    for seat in game["seats"]:
        apply_command(game, player(game, seat["id"]), "lobby.ready", {})
    game.update(status="playing", phase=phase, half=half, day=2)
    for seat, pair in zip(game["seats"], PAIRS, strict=True):
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
    """与 checks/test_resolution.py 同口径：apply_command 改的是副本，改完再换回去。"""
    changed = deepcopy(game)
    events = apply_command(changed, actor, action, payload or {})
    game.clear()
    game.update(changed)
    return events


async def idle_clock():
    """把后台每秒一次的计时循环停掉：检查自己驱动 run_timers，避免两个线程抢同一局。"""
    return


class SilentSpeechPolicy(HeuristicPolicy):
    """发言阶段整场不提交：让服务端的 30 秒公开计时把每个发言人依次顺延。

    真人玩家既不点「结束发言」也不预提交时，规则就是由时钟换人
    （见 engine.run_speech_timer：到点自动轮到下一位）。整局模拟走这条路径，
    跳过的正是那 30 秒一轮的等待。
    """

    def _speech(self, client):
        return None


class CountdownHostBrain(HostBrain):
    """真人节奏的主持人：不替系统点「推进」，让倒计时自己到期。

    默认的 :class:`HostBrain` 一见可推进就立刻推，5/10 秒倒计时永远不会到期；
    这个检查要覆盖的正是那条系统自动推进的路径，所以这里只在没有别的阻塞待办时
    让开一步（待裁定事项、宣判、交牌审阅照旧由脚本主持人处理）。
    """

    def act(self, host):
        view = host.view
        if view.get("public", {}).get("auto_advance_at") is not None:
            tasks = view.get("host", {}).get("tasks", [])
            others = [t for t in tasks if t.get("blocking") and t["kind"] != "advance"]
            if not others:
                return None
        return super().act(host)


class GameSimClock(game_clock.FakeClock):
    """整局模拟用的虚拟时钟。

    * 服务端读它：``engine`` 的倒计时全部挂在虚拟时间上；
    * 模拟器读它：``driver`` 的等待循环走 ``sleep``，不再真实空转；
    * ``sleep`` 不一小步一小步地磨：直接把虚拟时间跳到场上最近的倒计时终点，再跑一遍
      :func:`realtime.run_timers`（与后台每秒一次的计时循环同一条代码路径）。
      所以跳过的时长正好是那些倒计时真的要等的时长，没有被放大。
    """

    def __init__(self, start=None):
        super().__init__(start)
        self.ticks = 0

    def next_deadline(self):
        """场上最近的倒计时终点：顺序发言、自动推进与主持人警告。"""
        with storage.connect() as db:
            ids = [
                row["id"]
                for row in db.execute("SELECT id FROM games WHERE status != 'ended'")
            ]
        moments = []
        for game_id in ids:
            with storage.connect() as db:
                game = storage.load_game(db, game_id)
            if not game:
                continue
            public = game.get("public", {})
            for key in ("speech_deadline", "auto_advance_at"):
                value = public.get(key)
                if value:
                    moments.append(float(value))
            moments.extend(float(value) for value in (game.get("warnings") or {}).values())
        return min(moments) if moments else None

    def sleep(self, seconds):
        target = self.next_deadline()
        moment = self.advance_to(target) if target is not None else self.advance(seconds)
        realtime.run_timers(moment)
        self.ticks += 1
        return moment


class CountdownClock(unittest.TestCase):
    """单独看倒计时：装上假时钟后，时间参数优先，其次才是时钟。"""

    def test_speech_timer_expires_on_the_installed_clock(self):
        fake = game_clock.FakeClock()
        with fake.installed():
            game = arranged_game("speech")
            command(game, HOST, "host.speech", {"start": "1", "direction": "asc"})
            speaker = game["public"]["speaker"]
            deadline = game["public"]["speech_deadline"]
            self.assertAlmostEqual(deadline, fake.now() + SPEECH_TURN_SECONDS, delta=0.001)
            # 未到点：倒计时到点前不换人。
            run_speech_timer(game)
            self.assertEqual(game["public"]["speaker"], speaker)
            # 一次性推到期：发言权立刻顺延，并重新计时。
            fake.expire(deadline)
            run_speech_timer(game)
            self.assertNotEqual(game["public"]["speaker"], speaker)
            self.assertGreater(
                game["public"]["speech_deadline"], fake.now() + SPEECH_TURN_SECONDS - 1
            )

    def test_auto_advance_expires_on_the_installed_clock(self):
        fake = game_clock.FakeClock()
        with fake.installed():
            game = arranged_game("speech")
            command(game, HOST, "host.speech", {"start": "1", "direction": "asc"})
            for sid in list(game["public"]["speech_order"]):
                command(game, player(game, sid), "speech.done", {})
            deadline = game["public"]["auto_advance_at"]
            self.assertAlmostEqual(deadline, fake.now() + AUTO_ADVANCE_DELAY, delta=0.001)
            self.assertIn("advance", [t["kind"] for t in host_tasks(game)])
            run_auto_advance(game)
            self.assertEqual(game["phase"], "speech", "倒计时没到点就不该推进")
            fake.expire(deadline)
            run_auto_advance(game)
            self.assertEqual(game["phase"], "discussion")
            self.assertNotIn("auto_advance_at", game["public"])

    def test_discussion_end_expires_on_the_installed_clock(self):
        fake = game_clock.FakeClock()
        with fake.installed():
            game = arranged_game("discussion")
            for sid in ("1", "2", "3", "4", "5"):
                command(game, player(game, sid), "discussion.request_end", {})
            self.assertNotIn("auto_advance_at", game["public"])
            command(game, player(game, "6"), "discussion.request_end", {})
            deadline = game["public"]["auto_advance_at"]
            self.assertAlmostEqual(deadline, fake.now() + DISCUSSION_END_DELAY, delta=0.001)
            run_auto_advance(game)
            self.assertEqual(game["phase"], "discussion")
            fake.expire(deadline)
            run_auto_advance(game)
            self.assertEqual(game["phase"], "nomination")

    def test_warning_timeout_expires_on_the_installed_clock(self):
        fake = game_clock.FakeClock()
        with fake.installed():
            game = arranged_game("speech")
            command(game, HOST, "host.speech", {"start": "1", "direction": "asc"})
            target = game["public"]["speaker"]
            command(game, HOST, "host.warn", {"seat_id": target})
            deadline = game["warnings"][target]
            self.assertAlmostEqual(deadline, fake.now() + 30, delta=0.001)
            expire_warnings(game)
            self.assertIn(target, game["warnings"], "警告没到点就不该按放弃处理")
            fake.expire(deadline)
            expire_warnings(game)
            self.assertNotIn(target, game["warnings"])
            self.assertNotEqual(game["public"]["speaker"], target, "警告到点就该顺延发言")

    def test_explicit_now_still_wins_over_the_clock(self):
        """函数上的 now 参数优先级最高：装了假时钟也不影响显式传参的既有语义。"""
        fake = game_clock.FakeClock()
        with fake.installed():
            game = arranged_game("speech")
            command(game, HOST, "host.speech", {"start": "1", "direction": "asc"})
            for sid in list(game["public"]["speech_order"]):
                command(game, player(game, sid), "speech.done", {})
            deadline = game["public"]["auto_advance_at"]
            # 假时钟已经越过截止时刻，但显式传进来的时刻还没到：不推进。
            fake.expire(deadline)
            run_auto_advance(game, deadline - 1)
            self.assertEqual(game["phase"], "speech")
            # 显式传进来的时刻到了：照常推进。
            run_auto_advance(game, deadline + 1)
            self.assertEqual(game["phase"], "discussion")


class WholeGameOnTheClock(unittest.TestCase):
    """整局模拟：假时钟驱动，真实耗时远小于被跳过的等待时长。"""

    SEED = 3

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

    def test_a_whole_game_finishes_without_waiting_for_the_clock(self):
        virtual = GameSimClock()
        # 关掉后台计时循环：检查自己用虚拟时钟驱动同一条计时路径。
        with patch.object(realtime, "clock", idle_clock), virtual.installed(), TestClient(
            app, base_url="http://testserver", headers={"Origin": "http://testserver"}
        ) as client:
            harness = Harness(
                client,
                seed=self.SEED,
                clock=virtual,
                fast_forward=False,
                policies=[
                    SilentSpeechPolicy(seed=self.SEED * 100 + index) for index in range(7)
                ],
            )
            harness.simulation.host_brain = CountdownHostBrain(harness.log)
            started = time.monotonic()
            result = harness.run()
            real_seconds = time.monotonic() - started
            skipped = virtual.skipped()

        self.assertEqual(result.status, "ended", "\n".join(result.log[-20:]))
        self.assertTrue(result.reason)
        detail = (
            f"真实 {real_seconds:.1f}s / 跳过 {skipped:.1f}s / 计时 {virtual.ticks} 次 / "
            f"{result.days} 天 {result.steps} 步"
        )
        # 通过时也留下一行数字：下面的阈值就是照着实测比值（9~13 倍）定的。
        print("整局虚拟时钟模拟：" + detail)
        # 整局确实等过倒计时：发言 30 秒、自动推进 5/10 秒、讨论结束 10 秒都从时钟上跳过去了。
        self.assertGreater(skipped, 120.0, f"虚拟时间没跳过等待：{detail}")
        self.assertGreater(virtual.ticks, 1, f"服务端计时没跑过：{detail}")
        # 真实耗时远小于被跳过的等待：等待被跳过，而不是被绕过（实测比值 9~13 倍）。
        self.assertLess(real_seconds * 3, skipped, f"跳过的不够多：{detail}")


if __name__ == "__main__":
    unittest.main()
