"""Single-worker room synchronization and per-connection heartbeats."""

import asyncio
import logging
import time
from dataclasses import dataclass, field

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from . import auth, storage, views
from .game import expire_warnings, run_auto_advance
from .game.views import seat_chat

logger = logging.getLogger(__name__)
# ponytail: one room and one worker; use per-room locks if concurrent games are added.
lock = asyncio.Lock()
connections = set()

# 账号级在线：大厅里的账号没有 WebSocket，靠轮询 /api/lobby、/api/online 续期；
# 对局内的连接由 pong 续期。窗口与连接心跳一致（60 秒）。
# 在线状态只投影到 seats[].online 与 /api/online，不再产生「已连接 / 已掉线」系统消息。
PRESENCE_SECONDS = 60
presence: dict[str, float] = {}


def touch(key):
    """刷新某个身份的在线时间；key 是账号 id，主持人固定密码登录用 "host"。"""
    if key:
        presence[key] = time.monotonic()


def online_keys():
    """返回在线窗口内的身份集合，并顺手清掉过期条目。"""
    stamp = time.monotonic()
    for key, seen in list(presence.items()):
        if stamp - seen >= PRESENCE_SECONDS:
            presence.pop(key, None)
    return set(presence)


@dataclass(eq=False)
class Connection:
    socket: WebSocket
    token_hash: str
    game_id: str
    participant_id: str
    name: str
    kind: str
    seat_id: str | None
    account_id: str | None
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=256))
    last_pong: float = field(default_factory=time.monotonic)
    last_ping: float = field(default_factory=time.monotonic)
    # 输入状态（「正在输入」）节流：同一连接 1 秒内只中继一帧，防刷。
    # 默认 0：连接刚建立的第一帧不能被节流吃掉。
    last_typing: float = 0.0


def online(game_id):
    return {peer.participant_id for peer in connections if peer.game_id == game_id}


def enqueue(peer, message):
    try:
        peer.queue.put_nowait(message)
    except asyncio.QueueFull:
        # A slow client reconnects to durable state/history instead of losing ordered events.
        while not peer.queue.empty():
            peer.queue.get_nowait()
        peer.queue.put_nowait({"type": "_close", "code": 1013})


def detach(peer, code=4401):
    if peer not in connections:
        return False
    connections.remove(peer)
    while not peer.queue.empty():
        peer.queue.get_nowait()
    enqueue(peer, {"type": "_close", "code": code})
    return peer.participant_id not in online(peer.game_id)


def publish(game_id, new_messages=(), state=True):
    """Called under lock, only after mutation transaction has committed."""
    notices = list(new_messages)
    with storage.transaction() as db:
        for peer in list(connections):
            if peer.game_id != game_id:
                continue
            actor = auth.actor_for_token(db, peer.token_hash, game_id)
            if not actor:
                detach(peer)
            else:
                peer.participant_id, peer.kind = actor["id"], actor["kind"]
                peer.name, peer.seat_id = actor["name"], actor["seat_id"]
    with storage.connect() as db:
        game = storage.load_game(db, game_id)
        if not game:
            return
        for peer in list(connections):
            if peer.game_id != game_id:
                continue
            actor = auth.actor_for_token(db, peer.token_hash, game_id)
            if not actor:
                continue
            for row in notices:
                if storage.visible_message(row, actor):
                    enqueue(peer, {"type": "message", "message": storage.message_view(row, actor)})
            if state:
                enqueue(
                    peer, {"type": "state", "state": views.view(db, game, actor, online(game_id))}
                )


async def writer(peer):
    while True:
        message = await peer.queue.get()
        if message["type"] == "_close":
            await peer.socket.close(code=message["code"])
            return
        await asyncio.wait_for(peer.socket.send_json(message), timeout=10)


async def receiver(peer):
    while True:
        data = await peer.socket.receive_json()
        if isinstance(data, dict) and data.get("type") == "pong":
            peer.last_pong = time.monotonic()
            touch(peer.account_id or "host")
        elif isinstance(data, dict) and data.get("type") == "typing":
            await handle_typing(peer, data)


TYPING_RELAY_SECONDS = 1.0


def typing_sender(game, actor):
    """输入状态的展示信息：与发消息的署名规则一致（席位名与公开头像）。"""
    seat = next((s for s in game["seats"] if s["id"] == actor["seat_id"]), None)
    if actor["kind"] == "host":
        return {"kind": "host", "seat_id": None, "name": actor["name"], "avatar_role_id": "host"}
    if actor["kind"] == "spectator":
        return {"kind": "spectator", "seat_id": None, "name": actor["name"], "avatar_role_id": None}
    return {
        "kind": "player",
        "seat_id": actor["seat_id"],
        "name": seat["name"] if seat else actor["name"],
        "avatar_role_id": seat["avatar_role_id"] if game["status"] != "lobby" and seat else None,
    }


async def handle_typing(peer, data):
    """中继「正在输入」：校验发言权与可见性后转发给能看见该频道的连接。

    输入状态是纯内存瞬态：不落库、不进消息历史、不推状态帧。发送权判定与
    发消息一致（channel_send_reason），可见性判定与聊天消息一致（typing_visible）。
    """
    channel_id = data.get("channel_id")
    if not isinstance(channel_id, str) or not channel_id:
        return
    active = data.get("active") is not False
    stamp = time.monotonic()
    if active and stamp - peer.last_typing < TYPING_RELAY_SECONDS:
        return
    async with lock:
        with storage.connect() as db:
            game = storage.load_game(db, peer.game_id)
            if not game or game["status"] == "ended":
                return
            actor = auth.actor_for_token(db, peer.token_hash, peer.game_id)
            if not actor or actor["game_id"] != peer.game_id:
                return
            if not storage.typing_visible(db, peer.game_id, actor, channel_id):
                return
            reason = storage.channel_send_reason(db, game, actor, channel_id)
            if reason:
                return
            # 公屏的发言权还有一层 phase 判定（顺序发言等待/夜间关闭），
            # 由 can_chat/seat_chat 给出：与频道投影里的 can_send 同一来源。
            if channel_id == "public" and actor.get("kind") == "player":
                seat = next(
                    (s for s in game["seats"] if s["id"] == actor["seat_id"]), None
                )
                if seat is None or not seat_chat(game, seat)[0]:
                    return
            sender = typing_sender(game, actor)
            for other in list(connections):
                if other.game_id != peer.game_id or other.participant_id == actor["id"]:
                    continue
                theirs = auth.actor_for_token(db, other.token_hash, peer.game_id)
                if not theirs or not storage.typing_visible(
                    db, peer.game_id, theirs, channel_id
                ):
                    continue
                enqueue(
                    other,
                    {
                        "type": "typing",
                        "channel_id": channel_id,
                        "participant_id": actor["id"],
                        "active": active,
                        **sender,
                    },
                )
        peer.last_typing = stamp


async def live(socket):
    # 不再校验握手来源：原生客户端不发 Origin，Flutter Web 的 Origin 随端口变化。
    # 鉴权在下面用会话令牌完成。
    #
    # 必须先 accept 再关闭：Starlette 里 accept 之前调用 close 会拒绝整个握手，
    # uvicorn 直接回 HTTP 403（不是 4401），客户端只看到「连不上」而拿不到原因。
    peer = None
    tasks = []
    try:
        await socket.accept()
        async with lock:
            with storage.connect() as db:
                actor = auth.actor_for_token(db, auth.token_hash(socket))
                if not actor or not actor["game_id"]:
                    await socket.close(code=4401)
                    return
                game = storage.load_game(db, actor["game_id"])
                if not game:
                    await socket.close(code=4401)
                    return
            peer = Connection(
                socket,
                auth.token_hash(socket),
                actor["game_id"],
                actor["id"],
                actor["name"],
                actor["kind"],
                actor["seat_id"],
                actor["account_id"],
            )
            connections.add(peer)
            touch(peer.account_id or "host")
            with storage.connect() as db:
                enqueue(
                    peer,
                    {
                        "type": "sync",
                        "state": views.view(db, game, actor, online(game["id"])),
                        "messages": storage.messages(db, game["id"], actor)["messages"],
                    },
                )
            publish(game["id"])
        tasks = [asyncio.create_task(writer(peer)), asyncio.create_task(receiver(peer))]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except WebSocketDisconnect, RuntimeError, ValueError, asyncio.TimeoutError:
        pass
    finally:
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if peer:
            async with lock:
                was_registered = peer in connections
                detach(peer, 1000)
                if was_registered:
                    publish(peer.game_id)
            if (
                socket.application_state is WebSocketState.CONNECTED
                and socket.client_state is WebSocketState.CONNECTED
            ):
                try:
                    await asyncio.wait_for(socket.close(code=1000), timeout=2)
                except WebSocketDisconnect, RuntimeError, OSError, asyncio.TimeoutError:
                    pass


async def clock():
    while True:
        await asyncio.sleep(1)
        try:
            async with lock:
                stamp = time.monotonic()
                dropped = set()
                for peer in list(connections):
                    if stamp - peer.last_pong >= 60:
                        if detach(peer, 4408):
                            dropped.add(peer.game_id)
                    elif stamp - peer.last_ping >= 20:
                        enqueue(peer, {"type": "ping"})
                        peer.last_ping = stamp
                for game_id in dropped:
                    publish(game_id)
                with storage.connect() as db:
                    ids = [
                        row["id"]
                        for row in db.execute("SELECT id FROM games WHERE status != 'ended'")
                    ]
                for game_id in ids:
                    with storage.transaction() as db:
                        game = storage.load_game(db, game_id)
                        previous = game["version"]
                        events = expire_warnings(game, time.time())
                        events += run_auto_advance(game, time.time())
                        changed = game["version"] != previous
                        if changed:
                            storage.save_game(db, game)
                            rows = storage.add_events(db, game_id, events)
                    if changed:
                        publish(game_id, rows)
        except Exception:
            logger.exception("计时任务失败；保留原状态并在下次检查重试")
