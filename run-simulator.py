"""模拟器命令行入口：跑 N 局虚拟玩家对局，用于回归与压测。

用法::

    .venv\\Scripts\\python.exe run-simulator.py --games 20
    .venv\\Scripts\\python.exe run-simulator.py --games 5 --seed 100 --verbose
    .venv\\Scripts\\python.exe run-simulator.py --games 3 --url http://127.0.0.1:8000

默认在临时目录里跑（每局一个独立的 ``GAME_DATA_DIR``），不会碰到 ``data/`` 中的真实对局。
"""

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

SUMMARY = "{:<6} {:<8} {:>4} {:>6} {:>8} {:<8} {}"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="七双虚拟玩家模拟器")
    parser.add_argument("--games", type=int, default=1, help="跑几局（默认1）")
    parser.add_argument("--seed", type=int, default=0, help="首个随机种子；第 n 局用 seed+n")
    parser.add_argument("--url", default="", help="对着已启动的服务跑；留空则进程内运行")
    parser.add_argument("--data-dir", default="", help="指定数据目录；默认每局一个临时目录")
    parser.add_argument("--verbose", action="store_true", help="打印每一步决策")
    parser.add_argument("--max-seconds", type=float, default=180.0, help="单局时间上限（秒）")
    parser.add_argument("--max-steps", type=int, default=4000, help="单局步数上限")
    parser.add_argument("--gateway-token", default=os.environ.get("GAME_GATEWAY_TOKEN", ""))
    parser.add_argument("--group-id", default=os.environ.get("GAME_QQ_GROUP_ID", "123456"))
    parser.add_argument("--quiet", action="store_true", help="只输出每局一行结果")
    return parser.parse_args(argv)


def build_environment(data_dir, gateway_token, group_id):
    """把本局的数据目录装进已经导入的模块里。

    ``storage.DATA_DIR`` / ``auth_storage`` 都在导入时解析 ``GAME_DATA_DIR``，
    所以只改环境变量不会生效；这里必须同时改写模块属性，且每一局都换一个目录，
    否则上一局未结束的对局会让 ``POST /api/games`` 返回 409。
    """
    os.environ["GAME_DATA_DIR"] = data_dir
    if gateway_token:
        os.environ["GAME_GATEWAY_TOKEN"] = gateway_token
    os.environ["GAME_QQ_GROUP_ID"] = str(group_id)
    os.environ.setdefault("GAME_ALLOWED_ORIGINS", "testserver")

    from backend.app import auth_storage, realtime, storage

    directory = Path(data_dir).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    storage.DATA_DIR = directory
    auth_storage.storage = storage
    # 每局是独立的库：清掉上一局留下的连接与在线记录。
    realtime.connections.clear()


def run_one(args, seed, directory, root):
    from backend.app.simulator.driver import HostBrain, Roster, SeatActor, Simulation
    from backend.app.simulator.policy import HeuristicPolicy

    if args.url:
        from backend.app.simulator.harness import DEFAULT_CODEX_ROLES
        from backend.app.simulator.client import ProtocolClient
        from backend.app.simulator.transport import HttpTransport, gateway_authenticator

        transport = HttpTransport(args.url)
        authenticate = gateway_authenticator(transport, args.gateway_token, args.group_id)
        host = ProtocolClient(transport, "主持人", origin=args.url)
        host.login_host()
        host.create_game(DEFAULT_CODEX_ROLES)
        host.refresh()
        seats = []
        for index in range(7):
            client = ProtocolClient(transport, f"虚拟玩家{index + 1}", origin=args.url)
            client.login_player(
                str(900000 + index),
                f"虚拟玩家{index + 1}",
                gateway_token=args.gateway_token,
                group_id=args.group_id,
                authenticator=authenticate,
            )
            client.game_id = host.game_id
            seats.append(
                SeatActor(
                    seat_id="?",
                    client=client,
                    policy=HeuristicPolicy(seed=seed * 100 + index),
                    nickname=f"虚拟玩家{index + 1}",
                )
            )
        roster = Roster(seats, host)
        host.open_join(True)
        for actor in seats:
            actor.client.join("player")
            actor.client.refresh()
        host.refresh()
        for actor in seats:
            actor.seat_id = actor.client.view["self"]["seat_id"]
        seats.sort(key=lambda item: int(item.seat_id))
        return Simulation(
            roster,
            host_brain=HostBrain(),
            io=sys.stdout,
            verbose=args.verbose,
            max_steps=args.max_steps,
            max_seconds=args.max_seconds,
        ).run()

    from fastapi.testclient import TestClient

    from backend.app.main import app
    from backend.app.simulator.harness import Harness

    with TestClient(
        app, base_url="http://testserver", headers={"Origin": "http://testserver"}
    ) as client:
        harness = Harness(client, seed=seed, verbose=args.verbose, io=sys.stdout)
        harness.simulation.max_steps = args.max_steps
        harness.simulation.max_seconds = args.max_seconds
        return harness.run()


def main(argv=None):
    args = parse_args(argv)
    if not args.quiet:
        print(SUMMARY.format("局", "结果", "天数", "步数", "耗时", "胜方", "原因"))
    failures = 0
    winners = {}
    started = time.monotonic()
    for index in range(args.games):
        seed = args.seed + index
        holder = None
        if args.data_dir:
            directory = str(Path(args.data_dir) / f"game{index}")
            Path(directory).mkdir(parents=True, exist_ok=True)
        else:
            holder = tempfile.TemporaryDirectory(prefix="qd-sim-")
            directory = holder.name
        build_environment(directory, args.gateway_token, args.group_id)
        try:
            result = run_one(args, seed, directory, Path(directory))
            winners[result.winner] = winners.get(result.winner, 0) + 1
            if not args.quiet:
                print(
                    SUMMARY.format(
                        seed,
                        result.status,
                        result.days,
                        result.steps,
                        f"{result.elapsed:.1f}s",
                        result.winner or "-",
                        (result.reason or "")[:40],
                    )
                )
        except Exception as error:
            failures += 1
            print(SUMMARY.format(seed, "FAILED", "-", "-", "-", "-", f"{type(error).__name__}: {error}"))
            if args.verbose:
                import traceback

                traceback.print_exc()
        finally:
            if holder is not None:
                holder.cleanup()
    total = time.monotonic() - started
    print(
        f"\n完成 {args.games - failures}/{args.games} 局，用时 {total:.1f}s，"
        f"胜方分布 {winners or '无'}"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
