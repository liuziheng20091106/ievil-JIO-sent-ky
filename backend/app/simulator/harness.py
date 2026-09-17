"""把传输层、登录、阵容与驱动拼成「可以跑一局」的现成入口。

检查里用 :func:`harness_for_test_client`；命令行跑批用 ``run-simulator.py``。
"""

from .client import ProtocolClient
from .driver import HostBrain, Roster, SeatActor, Simulation, SimulationResult
from .policy import HeuristicPolicy, ScriptedPolicy
from .transport import TestClientTransport

DEFAULT_CODEX_ROLES = [
    "emma",
    "hiro",
    "hanna",
    "meruru",
    "noah",
    "annan",
    "coco",
    "nanoka",
    "marg",
    "leia",
    "honoka",
]


def _authenticator_for_test_client(client, gateway_token="test-gateway-secret", group_id=123456):
    """回归检查里直接调 auth_storage 核销登录码，省掉一层 HTTP 网关。"""
    from backend.app import auth_storage

    def authenticate(code, qq_id, nickname, group):
        challenge_id = auth_storage.complete_challenge(
            code, qq_id, nickname, f"https://example.invalid/{qq_id}"
        )
        if not challenge_id:
            raise RuntimeError("登录码核销失败")

    return authenticate


def build_client(transport, label, origin="http://testserver"):
    return ProtocolClient(transport, label, origin=origin)


class Harness:
    """一局模拟的完整环境：主持人 + 七名虚拟玩家，可直接 run()。"""

    def __init__(
        self,
        client,
        *,
        gateway_token="test-gateway-secret",
        group_id=123456,
        codex=None,
        seed=0,
        policies=None,
        host_brain=True,
        verbose=False,
        io=None,
    ):
        self.client = client
        self.io = io
        self.log = []
        self._joined = False
        self.transport = TestClientTransport(client)
        self.authenticate = _authenticator_for_test_client(client, gateway_token, group_id)
        self.host = build_client(self.transport, "主持人")
        self.host.login_host()
        self.host.create_game(codex or DEFAULT_CODEX_ROLES)
        self.host.refresh()
        self.seats = self._seat_players(seed, policies)
        self.roster = Roster(self.seats, self.host, log=self.log)
        self.host_brain = HostBrain(self.log) if host_brain else None
        self.simulation = Simulation(
            self.roster,
            host_brain=self.host_brain,
            log=self.log,
            io=io,
            verbose=verbose,
        )

    def _seat_players(self, seed, policies):
        seats = []
        for index in range(7):
            qq_id = 900000 + index
            client = build_client(self.transport, f"虚拟玩家{index + 1}")
            client.login_player(
                str(qq_id),
                f"虚拟玩家{index + 1}",
                gateway_token=None,
                group_id=None,
                authenticator=self.authenticate,
            )
            client.game_id = self.host.game_id
            policy = (
                policies[index]
                if policies
                else HeuristicPolicy(seed=(seed or 0) * 100 + index)
            )
            seats.append(SeatActor(seat_id="?", client=client, policy=policy, nickname=f"虚拟玩家{index + 1}"))
        return seats

    def join(self):
        """进入对局并把席位号回填到每个虚拟玩家。"""
        self.host.refresh()
        self.host.open_join(True)
        for actor in self.seats:
            actor.client.join("player")
            actor.client.refresh()
        self.host.refresh()
        for actor in self.seats:
            actor.seat_id = actor.client.view["self"]["seat_id"]
        # 席位号是随机分配的，按席位排序让日志与断言稳定。
        self.seats.sort(key=lambda item: int(item.seat_id))
        self._joined = True
        return self

    def run(self, **kwargs) -> SimulationResult:
        if not self._joined:
            self.join()
        return self.simulation.run(**kwargs)


def harness_for_test_client(client, **kwargs):
    return Harness(client, **kwargs)


__all__ = [
    "DEFAULT_CODEX_ROLES",
    "Harness",
    "HeuristicPolicy",
    "ScriptedPolicy",
    "harness_for_test_client",
]
