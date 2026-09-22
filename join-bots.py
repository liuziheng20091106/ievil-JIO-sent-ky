"""派 N 个虚拟玩家加入正在运行的服务上的对局。

用法::

    .venv\\Scripts\\python.exe join-bots.py 3
    .venv\\Scripts\\python.exe join-bots.py 4 --url http://127.0.0.1:8000 --wait 600

走真实协议（登录码核销 → 入场 → 命令提交），只驱动玩家席位，绝不提交主持人动作。
主持人还没开放参局时脚本会等，开放后立刻把席位填上；席位少于请求数量时报出实际入场数。

脚本放在临时目录（不落仓库），靠 ROOT 常量指向本仓库。
"""

import argparse
import os
import sys
import time

ROOT = r"C:\Users\Nahida\Documents\ievil JIO sent-ky"
sys.path.insert(0, ROOT)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 本地 live 服务的网关密钥来自 start.cmd.local.cmd；优先取环境变量。
DEFAULT_TOKEN = os.environ.get("GAME_GATEWAY_TOKEN") or (
    "FWJTuJrtfhgygcqa39S80XLplEjIlCLtgy8AtNm37XAKGaNHvTsl0cLQcJBriDv"
)

from backend.app.simulator.client import ProtocolClient, ProtocolError, VersionConflict
from backend.app.simulator.driver import SeatActor
from backend.app.simulator.policy import HeuristicPolicy
from backend.app.simulator.transport import HttpTransport, gateway_authenticator


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="派虚拟玩家加入已有对局")
    parser.add_argument("count", type=int, help="要派出的虚拟玩家数量")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="服务地址")
    parser.add_argument("--token", default=DEFAULT_TOKEN, help="网关密钥（默认取 GAME_GATEWAY_TOKEN）")
    parser.add_argument("--group", default="1105925736", help="群号；逗号分隔时取第一个")
    parser.add_argument("--wait", type=float, default=300.0, help="等待主持人开放参局的秒数")
    parser.add_argument("--poll", type=float, default=2.0, help="轮询间隔秒数")
    parser.add_argument("--verbose", action="store_true", help="打印每一步决策")
    return parser.parse_args(argv)


def log(text):
    print(text, flush=True)


def leave_reason(game):
    if game is None:
        return "当前没有未结束的对局"
    if not game["join_open"]:
        return "主持人尚未开放参局"
    if game["phase"] != "lobby" or not game["player_seats_available"]:
        return f"已发牌或席位已满（阶段 {game['phase']}，空席 {game['player_seats_available']}）"
    return "可以入场"


def login_bots(args):
    transport = HttpTransport(args.url)
    authenticate = gateway_authenticator(transport, args.token, args.group)
    clients = []
    for index in range(args.count):
        name = f"虚拟玩家{index + 1}"
        client = ProtocolClient(transport, name, origin=args.url)
        client.login_player(
            str(900000 + index),
            name,
            gateway_token=args.token,
            group_id=args.group,
            authenticator=authenticate,
        )
        clients.append(client)
    log(f"已取得 {len(clients)} 个玩家令牌（{args.url}）")
    return clients


def wait_for_open_game(clients, args):
    deadline = time.monotonic() + args.wait
    reported = None
    while True:
        game = clients[0].lobby().get("game")
        reason = leave_reason(game)
        if game is not None and game["can_join_player"]:
            return game["id"]
        if reason != reported:
            reported = reason
            log(f"暂不能入场：{reason}；每 {args.poll:g} 秒重试，最多等 {args.wait:g} 秒")
        if time.monotonic() >= deadline:
            raise SystemExit(f"等待超时：{reason}")
        time.sleep(args.poll)


def seat_bots(clients, game_id):
    actors = []
    for index, client in enumerate(clients):
        name = f"虚拟玩家{index + 1}"
        client.game_id = game_id
        try:
            client.join("player")
        except ProtocolError as error:
            log(f"{name} 入场失败：{error.detail}")
            continue
        client.refresh()
        seat_id = client.view["self"]["seat_id"]
        log(f"{name} 已入座 {seat_id} 号")
        actors.append(
            SeatActor(
                seat_id=seat_id,
                client=client,
                policy=HeuristicPolicy(seed=index),
                nickname=name,
            )
        )
    if not actors:
        raise SystemExit("没有任何虚拟玩家成功入场")
    return actors


def drive(actors, args):
    while True:
        try:
            for actor in actors:
                for _ in range(6):
                    actor.client.refresh()
                    view = actor.client.view
                    if view["status"] == "ended":
                        raise SystemExit("对局已结束，虚拟玩家退出")
                    decision = actor.policy.decide(actor.client)
                    if decision is None:
                        break
                    if decision.action == "lobby.ready" and view["phase"] == "lobby":
                        seat = next(
                            (item for item in view["seats"] if item["id"] == actor.seat_id), None
                        )
                        if seat and seat.get("ready"):
                            # 首次准备阶段里 lobby.ready 是开关，再点一次等于取消准备。
                            break
                    try:
                        actor.client.submit(decision.action, decision.payload)
                    except VersionConflict:
                        continue
                    except ProtocolError as error:
                        log(f"{actor.seat_id}号 {decision.action} 被拒：{error.detail}")
                        break
                    if args.verbose:
                        log(f"{actor.seat_id}号 {decision}  [{view['phase']}]")
                    break
            time.sleep(args.poll)
        except KeyboardInterrupt:
            log("收到中断，虚拟玩家退出")
            return
        except ProtocolError as error:
            log(f"通信失败：{error}（{args.poll:g} 秒后继续）")
            time.sleep(args.poll)


def main(argv=None):
    args = parse_args(argv)
    if args.count < 1:
        raise SystemExit("数量必须大于 0")
    clients = login_bots(args)
    game_id = wait_for_open_game(clients, args)
    log(f"目标对局：{game_id}")
    actors = seat_bots(clients, game_id)
    log(f"已入场 {len(actors)} 个虚拟玩家：{', '.join(a.seat_id + '号' for a in actors)}")
    drive(actors, args)


if __name__ == "__main__":
    main()
