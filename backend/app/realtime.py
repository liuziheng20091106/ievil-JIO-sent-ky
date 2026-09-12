"""Single-worker room synchronization and per-connection heartbeats."""

import asyncio
import logging
import time
from dataclasses import dataclass, field

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from . import auth, storage, views
from .game import expire_warnings

logger = logging.getLogger(__name__)
# ponytail: one room and one worker; use per-room locks if concurrent games are added.
lock = asyncio.Lock()
connections = set()


@dataclass(eq=False)
class Connection:
    socket: WebSocket
    token_hash: str
    game_id: str
    participant_id: str
    name: str
    kind: str
    seat_id: str | None
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=256))
    last_pong: float = field(default_factory=time.monotonic)
    last_ping: float = field(default_factory=time.monotonic)


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


def presence_text(peer, connected):
    label = (
        "主持人"
        if peer.kind == "host"
        else (f"{peer.seat_id}号玩家【{peer.name}】" if peer.seat_id else f"观战者【{peer.name}】")
    )
    return label + ("已连接 / 重新连接" if connected else "已掉线")


def publish(game_id, new_messages=(), state=True):
    """Called under lock, only after mutation transaction has committed."""
    notices = list(new_messages)
    with storage.transaction() as db:
        for peer in list(connections):
            if peer.game_id != game_id:
                continue
            actor = auth.actor_for_token(db, peer.token_hash, game_id)
            if not actor:
                if detach(peer):
                    notices.append(
                        storage.add_message(
                            db, game_id, kind="presence", text=presence_text(peer, False)
                        )
                    )
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
                    enqueue(peer, {"type": "message", "message": storage.message_view(row)})
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


async def live(socket):
    if not auth.same_origin(socket):
        await socket.close(code=4403)
        return
    peer = None
    tasks = []
    try:
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
            await socket.accept()
            peer = Connection(
                socket,
                auth.token_hash(socket),
                actor["game_id"],
                actor["id"],
                actor["name"],
                actor["kind"],
                actor["seat_id"],
            )
            first = actor["id"] not in online(game["id"])
            connections.add(peer)
            notices = []
            with storage.transaction() as db:
                if first:
                    notices.append(
                        storage.add_message(
                            db, game["id"], kind="presence", text=presence_text(peer, True)
                        )
                    )
            with storage.connect() as db:
                enqueue(
                    peer,
                    {
                        "type": "sync",
                        "state": views.view(db, game, actor, online(game["id"])),
                        "messages": storage.messages(db, game["id"], actor)["messages"],
                    },
                )
            publish(game["id"], notices)
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
                last = detach(peer, 1000)
                if last:
                    with storage.transaction() as db:
                        notice = storage.add_message(
                            db, peer.game_id, kind="presence", text=presence_text(peer, False)
                        )
                    publish(peer.game_id, [notice])
                elif was_registered:
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
                disconnected = {}
                for peer in list(connections):
                    if stamp - peer.last_pong >= 60:
                        if detach(peer, 4408):
                            disconnected.setdefault(peer.game_id, []).append(peer)
                    elif stamp - peer.last_ping >= 20:
                        enqueue(peer, {"type": "ping"})
                        peer.last_ping = stamp
                for game_id, peers in disconnected.items():
                    with storage.transaction() as db:
                        # 初始化会删除全部对局；已消失的对局不再补写在线记录。
                        if not game_id or not storage.load_game(db, game_id):
                            continue
                        rows = [
                            storage.add_message(
                                db, game_id, kind="presence", text=presence_text(peer, False)
                            )
                            for peer in peers
                        ]
                    publish(game_id, rows)
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
                        changed = game["version"] != previous
                        if changed:
                            storage.save_game(db, game)
                            rows = storage.add_events(db, game_id, events)
                    if changed:
                        publish(game_id, rows)
        except Exception:
            logger.exception("计时任务失败；保留原状态并在下次检查重试")
