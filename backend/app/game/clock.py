"""对局时钟：整局唯一的「现在」来源。

规则层（``engine``）与后台计时（``realtime``）都不再直接读墙钟，而是走 :func:`now`。
默认实现就是 ``time.time()``，与改造前各处分别调用的 ``time.time()`` 同源，因此线上
行为不变；检查与模拟可以装上 :class:`FakeClock`，把时间一次性推到倒计时终点，
不必真实等待那 5 秒 / 30 秒 / 10 秒。

用法（检查里）::

    clock = FakeClock()
    with clock.installed():
        run_auto_advance(game)                 # 到点前：不推进
        clock.expire(game["public"]["auto_advance_at"])
        run_auto_advance(game)                 # 到点后：立刻推进

显式传入的时间参数优先级永远最高：``run_auto_advance(game, now)`` 里的 ``now``
不会走时钟。
"""

import time
from contextlib import contextmanager


def _system_now():
    """默认实现：真实墙钟，与改造前直接调用的 ``time.time()`` 是同一个来源。"""
    return time.time()


_impl = _system_now


def now():
    """当前对局时间（秒，与 ``time.time()`` 同一口径）。"""
    return _impl()


def set_impl(impl):
    """替换时钟实现（传 ``None`` 恢复真实墙钟）；返回被替换掉的旧实现便于还原。"""
    global _impl
    previous = _impl
    _impl = _system_now if impl is None else impl
    return previous


class FakeClock:
    """测试时钟：不读墙钟，只在调用方显式推进时前进。

    ``now`` 可以当作 :func:`set_impl` 的实现直接使用；模拟器要的 ``sleep`` 也在这里：
    虚拟时钟下的「等待」就是把虚拟时间往前推，真实时间一点也不花。
    """

    def __init__(self, start=None):
        self.start = float(time.time() if start is None else start)
        self.value = self.start
        # 被推进的次数（模拟器的等待循环每转一圈算一次），只用于诊断。
        self.pushes = 0

    def now(self):
        return self.value

    def advance(self, seconds):
        """把虚拟时间往前推 ``seconds`` 秒；返回推进后的时刻。"""
        self.value += float(seconds)
        self.pushes += 1
        return self.value

    def advance_to(self, moment):
        """一次性把虚拟时间推到 ``moment``（倒计时终点）：只前进，不后退。"""
        if float(moment) > self.value:
            self.value = float(moment)
        self.pushes += 1
        return self.value

    def expire(self, deadline, seconds=1.0):
        """把虚拟时间推过某个截止时刻（``deadline + seconds``），让它立即到期。"""
        return self.advance_to(float(deadline) + float(seconds))

    def sleep(self, seconds):
        """模拟器等待循环要的接口：虚拟时钟下就是纯粹的时间跳跃，没有真实等待。"""
        return self.advance(seconds)

    def skipped(self):
        """相对起点走过的虚拟秒数，也就是这一局被跳过的总等待时长。"""
        return self.value - self.start

    @contextmanager
    def installed(self):
        """装上这块假时钟；退出时恢复原来的实现（通常是真实墙钟）。"""
        previous = set_impl(self.now)
        try:
            yield self
        finally:
            set_impl(previous)
