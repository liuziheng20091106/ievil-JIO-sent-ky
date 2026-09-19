"""HTTP transport, stable-account participation, channels, and command dispatch."""

import copy
import json
import os
import secrets
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response

from . import auth, auth_storage, evidence, realtime, schemas, storage, views
from .game import CATALOG, DEFAULT_CODEX, apply_command, clear_seat_actions, create_game

router = APIRouter(prefix="/api")


def require_game(db, game_id, mutable=False):
    game = storage.load_game(db, game_id)
    if not game:
        raise HTTPException(404, "对局不存在")
    game.setdefault("join_open", False)
    if mutable and game["status"] == "ended":
        raise HTTPException(409, "本局已经结束，只能查看获准的结算与历史")
    return game


def seat_for(game, seat_id):
    seat = next((seat for seat in game["seats"] if seat["id"] == seat_id), None)
    if not seat:
        raise HTTPException(422, "请选择有效席位")
    return seat


def impersonated_actor(db, game, seat_id):
    seat = seat_for(game, seat_id)
    occupant = seat["occupant_id"]
    if not occupant:
        raise HTTPException(422, "该席位当前无人操作")
    row = db.execute(
        "SELECT * FROM participants WHERE id=? AND game_id=? AND active=1 AND blocked=0",
        (occupant, game["id"]),
    ).fetchone()
    if not row:
        raise HTTPException(422, "该席位操作者已失效，请先安排替补")
    return {
        "id": row["id"],
        "account_id": row["account_id"],
        "kind": "player",
        "game_id": game["id"],
        "seat_id": seat["id"],
        "name": row["name"],
        "access_ids": json.loads(row["access_ids"]),
    }


def current_view(game_id, hashed):
    with storage.connect() as db:
        actor = auth.actor_for_token(db, hashed, game_id)
        if not actor:
            raise HTTPException(401, "登录已失效")
        return views.view(db, require_game(db, game_id), actor, realtime.online(game_id))


def session_for_token(token):
    with storage.connect() as db:
        return auth.me(auth.actor_for_token(db, auth.secret_hash(token)))


def revoke_current(request):
    auth_storage.revoke(auth.token_hash(request))


def refresh_connections():
    for game_id in {peer.game_id for peer in realtime.connections if peer.game_id}:
        realtime.publish(game_id)


def clear_connections(game_id=None):
    for peer in list(realtime.connections):
        if peer.kind == "host":
            peer.game_id = game_id
        else:
            realtime.detach(peer, 4401)


def require_gateway(request):
    if not auth.gateway_authorized(request):
        raise HTTPException(401, "网关认证失败")


def require_gateway_group(group_id):
    expected = os.environ.get("GAME_QQ_GROUP_ID", "")
    if not expected:
        raise HTTPException(503, "服务端尚未配置QQ群")
    if not secrets.compare_digest(str(group_id).encode(), expected.encode()):
        raise HTTPException(403, "QQ群不匹配")


def poll_login(challenge_id, client_kind):
    result, error = auth_storage.poll_challenge(challenge_id, client_kind)
    if error in {"missing", "consumed"}:
        raise HTTPException(410, "登录挑战不存在或已消费")
    if error == "expired":
        raise HTTPException(410, "登录挑战已过期")
    return result


@router.get("/health")
async def health():
    # 客户端版本标签：低于 latest 提示可更新，低于 minimum 必须更新；未配置则不下发。
    return {
        "ok": True,
        "client_latest": os.environ.get("GAME_CLIENT_LATEST") or None,
        "client_minimum": os.environ.get("GAME_CLIENT_MINIMUM") or None,
    }


@router.get("/catalog")
async def catalog():
    return {"roles": CATALOG, "default_codex": DEFAULT_CODEX}


@router.post("/auth/challenges")
async def web_challenge():
    return auth_storage.create_challenge("web")


@router.get("/auth/challenges/{challenge_id}")
async def web_challenge_status(challenge_id: str, request: Request, response: Response):
    result = poll_login(challenge_id, "web")
    if result["status"] != "completed":
        return result
    token = result.pop("token")
    auth.set_cookie(response, request, token)
    # 必须带上 status：客户端靠它判断登录完成。缺了它客户端会继续轮询，
    # 而挑战已经消费，下一次轮询就是 410，用户看到登录失败但账号其实已登录。
    return {"status": "completed", **session_for_token(token)}


@router.post("/native/auth/challenges")
async def native_challenge():
    return auth_storage.create_challenge("native")


@router.get("/native/auth/challenges/{challenge_id}")
async def native_challenge_status(challenge_id: str):
    result = poll_login(challenge_id, "native")
    if result["status"] != "completed":
        return result
    token = result.pop("token")
    # 同 web：status 必须随完成一起返回，否则客户端轮询到已消费的挑战会拿到 410。
    return {"status": "completed", "session_token": token, "session": session_for_token(token)}


@router.post("/internal/qq/login")
async def qq_login(body: schemas.QQLogin, request: Request):
    require_gateway(request)
    require_gateway_group(body.group_id)
    avatar = body.avatar_url or f"https://q1.qlogo.cn/g?b=qq&nk={body.qq_id}&s=100"
    challenge_id = auth_storage.complete_challenge(
        body.code, body.qq_id, body.nickname, avatar
    )
    if not challenge_id:
        raise HTTPException(409, "登录码无效、过期或已经使用")
    return {"ok": True}


@router.post("/internal/qq/members/sync")
async def qq_members(body: schemas.QQMemberSync, request: Request):
    require_gateway(request)
    require_gateway_group(body.group_id)
    valid = []
    for member in body.members:
        # 单条脏数据跳过即可，不该让整批同步 422：非法 QQ 号丢弃，空/超长昵称清洗后保留。
        if not (member.qq_id.isdigit() and 5 <= len(member.qq_id) <= 20):
            continue
        member.nickname = (member.nickname.strip() or member.qq_id)[:64]
        valid.append(member)
    return {"ok": True, "count": auth_storage.sync_accounts(valid), "skipped": len(body.members) - len(valid)}


@router.get("/me")
async def me(request: Request):
    with storage.connect() as db:
        return auth.me(auth.actor_for_token(db, auth.token_hash(request)))


def host_login_session(body, request):
    if not secrets.compare_digest(body.password.encode(), b"114514"):
        raise HTTPException(401, "主持人密码错误")
    revoke_current(request)
    token = auth.issue_session(None, "host")
    refresh_connections()
    return token, session_for_token(token)


@router.post("/host/login")
async def login(body: schemas.Login, request: Request, response: Response):
    async with realtime.lock:
        token, session = host_login_session(body, request)
        auth.set_cookie(response, request, token)
        return session


@router.post("/native/host/login")
async def native_host_login(body: schemas.Login, request: Request):
    async with realtime.lock:
        token, session = host_login_session(body, request)
        return {"session_token": token, "session": session}


@router.post("/logout")
async def logout(request: Request, response: Response):
    async with realtime.lock:
        revoke_current(request)
        response.delete_cookie(auth.COOKIE, path="/", httponly=True, samesite="lax")
        refresh_connections()
        return {"ok": True}


@router.get("/lobby")
async def lobby(request: Request):
    account = None
    try:
        account = auth.require_account(request)
    except HTTPException:
        with storage.connect() as db:
            host = auth.actor_for_token(db, auth.token_hash(request))
        if not host or host["kind"] != "host":
            raise
    with storage.connect() as db:
        game_id = storage.current_game_id(db)
        game = storage.load_game(db, game_id) if game_id else None
        if not game or game["status"] == "ended":
            return {"game": None, "participation": None}
        game.setdefault("join_open", False)
        available = sum(not seat["occupant_id"] for seat in game["seats"])
        participation = (
            auth.actor_for_token(db, auth.token_hash(request), game["id"]) if account else None
        )
        return {
            "game": {
                "id": game["id"],
                "status": game["status"],
                "phase": game["phase"],
                "join_open": bool(game["join_open"]),
                "player_seats_available": available,
                "can_join_player": bool(
                    game["join_open"] and game["phase"] == "lobby" and not game["cards"] and available
                ),
                "can_join_spectator": bool(game["join_open"]),
            },
            "participation": participation,
        }


@router.post("/reset")
async def reset(request: Request):
    async with realtime.lock:
        with storage.transaction() as db:
            auth.require_actor(db, request, host=True)
            storage.purge(db)
        clear_connections()
        with storage.connect() as db:
            return auth.me(auth.actor_for_token(db, auth.token_hash(request)))


@router.post("/games")
async def create(body: schemas.Create, request: Request):
    async with realtime.lock:
        with storage.transaction() as db:
            auth.require_actor(db, request, host=True)
            active = db.execute("SELECT id FROM games WHERE status != 'ended' LIMIT 1").fetchone()
            if active:
                raise HTTPException(409, "请先结束当前对局，再创建下一局")
            storage.purge(db)
            game = create_game(body.codex)
            db.execute(
                "INSERT INTO games(id,state,version,status,created_at) VALUES(?,?,?,?,?)",
                (
                    game["id"],
                    storage.dumps(game),
                    game["version"],
                    game["status"],
                    storage.now_text(),
                ),
            )
            row = storage.add_message(db, game["id"], text="新对局已创建，等待主持人开放参局")
        clear_connections(game["id"])
        realtime.publish(game["id"], [row])
        return current_view(game["id"], auth.token_hash(request))


@router.post("/games/{game_id}/participations")
async def participate(game_id: str, body: schemas.Participation, request: Request):
    account = auth.require_account(request)
    async with realtime.lock:
        with storage.transaction() as db:
            game = require_game(db, game_id, mutable=True)
            if not game.get("join_open"):
                raise HTTPException(409, "主持人尚未开放参局")
            previous = db.execute(
                "SELECT * FROM participants WHERE game_id=? AND account_id=?",
                (game_id, account["id"]),
            ).fetchone()
            if previous:
                if previous["blocked"]:
                    raise HTTPException(403, "该账号已在本局拉黑")
                if previous["kind"] != body.kind:
                    raise HTTPException(409, "同一账号不能更换本局参与方式")
                if previous["active"]:
                    return auth.me(auth.actor_for_token(db, auth.token_hash(request), game_id))
                if previous["kind"] == "player":
                    if game["status"] != "lobby":
                        # 开局后回席会继承角色牌与示人身份，必须由主持人走替换流程。
                        raise HTTPException(409, "对局已开始，回席需主持人安排观战者替补接管")
                    seat = seat_for(game, previous["seat_id"])
                    if seat["occupant_id"] not in (None, previous["id"]):
                        raise HTTPException(409, "原席位已由替补接管")
                    seat["occupant_id"], seat["name"] = previous["id"], previous["name"]
                db.execute("UPDATE participants SET active=1 WHERE id=?", (previous["id"],))
                participant_id = previous["id"]
            else:
                seat = None
                if body.kind == "player":
                    if game["phase"] != "lobby" or game["cards"]:
                        raise HTTPException(409, "已经发牌，只能选择观战")
                    available = [seat for seat in game["seats"] if not seat["occupant_id"]]
                    if not available:
                        raise HTTPException(409, "七个席位已满，可以选择观战")
                    seat = secrets.choice(available)
                participant_id = secrets.token_urlsafe(18)
                db.execute(
                    """INSERT INTO participants
                       (id,game_id,account_id,kind,seat_id,name,access_ids)
                       VALUES(?,?,?,?,?,?,?)""",
                    (
                        participant_id,
                        game_id,
                        account["id"],
                        body.kind,
                        seat["id"] if seat else None,
                        account["nickname"],
                        storage.dumps([participant_id]),
                    ),
                )
                if seat:
                    seat["occupant_id"], seat["name"] = participant_id, account["nickname"]
                    seat["ready"] = False
            game["version"] += 1
            storage.save_game(db, game)
            actor = auth.actor_for_token(db, auth.token_hash(request), game_id)
            label = (
                str(actor["seat_id"]) + "号玩家" if actor["kind"] == "player" else "观战者"
            ) + "【" + actor["name"] + "】"
            row = storage.add_message(db, game_id, text=label + "已加入对局")
        realtime.publish(game_id, [row])
        refresh_connections()
        return auth.me(actor)


@router.get("/games/{game_id}/state")
async def state(game_id: str, request: Request):
    async with realtime.lock:
        return current_view(game_id, auth.token_hash(request))


def room_command(db, game, actor, action_id, payload):
    if actor["kind"] != "host":
        raise HTTPException(403, "仅主持人可以管理房间")
    text = ""
    if action_id == "room.open_join":
        body = schemas.OpenJoin.model_validate(payload)
        game["join_open"] = body.open
        text = "主持人已开放账号主动参局" if body.open else "主持人已关闭账号主动参局"
    elif action_id == "room.kick":
        body = schemas.Kick.model_validate(payload)
        target = db.execute(
            "SELECT * FROM participants WHERE id=? AND game_id=? AND active=1 AND blocked=0",
            (body.participant_id, game["id"]),
        ).fetchone()
        if not target:
            raise HTTPException(422, "请选择本局有效参与者")
        seat = seat_for(game, target["seat_id"]) if target["kind"] == "player" else None
        if seat and seat["occupant_id"] != target["id"]:
            raise HTTPException(409, "该参与者已不再占据该席位")
        auth.revoke_participant(db, target["id"], block=body.block)
        if seat:
            seat["occupant_id"] = None
            if game["status"] == "lobby":
                seat["ready"] = False
        text = "【" + target["name"] + "】已被移出" + ("并在本局拉黑" if body.block else "")
    elif action_id == "room.replace":
        body = schemas.Replace.model_validate(payload)
        seat = seat_for(game, body.seat_id)
        if seat["occupant_id"]:
            raise HTTPException(409, "请先移出原玩家，再让观战者接管空席")
        substitute = db.execute(
            "SELECT * FROM participants WHERE id=? AND game_id=? AND kind='spectator' AND active=1 AND blocked=0",
            (body.participant_id, game["id"]),
        ).fetchone()
        if not substitute:
            raise HTTPException(422, "请选择本局有效观战者作为替补")
        old = db.execute(
            "SELECT * FROM participants WHERE game_id=? AND seat_id=? AND kind='player' ORDER BY rowid DESC LIMIT 1",
            (game["id"], seat["id"]),
        ).fetchone()
        access_ids = [substitute["id"]]
        if old:
            if body.share_history:
                access_ids = list(dict.fromkeys(access_ids + json.loads(old["access_ids"])))
            auth.revoke_participant(db, old["id"], block=bool(old["blocked"]))
        db.execute(
            "UPDATE participants SET kind='player',seat_id=?,access_ids=? WHERE id=?",
            (seat["id"], storage.dumps(access_ids), substitute["id"]),
        )
        seat["occupant_id"], seat["name"] = substitute["id"], substitute["name"]
        if game["status"] == "lobby":
            seat["ready"] = False
        if not body.keep_actions:
            clear_seat_actions(game, seat["id"])
        text = seat["id"] + "号席位已由【" + substitute["name"] + "】接管"
    elif action_id == "room.mute":
        body = schemas.Mute.model_validate(payload)
        target = db.execute(
            "SELECT * FROM participants WHERE id=? AND game_id=? AND active=1 AND blocked=0",
            (body.participant_id, game["id"]),
        ).fetchone()
        if not target:
            raise HTTPException(422, "请选择本局有效参与者")
        db.execute("UPDATE participants SET muted=? WHERE id=?", (int(body.muted), body.participant_id))
        text = "【" + target["name"] + "】已被禁言" if body.muted else "【" + target["name"] + "】已解除禁言"
    else:
        raise HTTPException(422, "未知房间管理操作")
    game["version"] += 1
    return [storage.add_message(db, game["id"], text=text)]


def channel_names(db, member_ids):
    names = {"host": "主持人"}
    if member_ids:
        placeholders = ",".join("?" for _ in member_ids)
        for row in db.execute(
            f"SELECT id,name FROM participants WHERE id IN ({placeholders})", member_ids
        ):
            names[row["id"]] = row["name"]
    return names


def channel_notice(db, game_id, row, ending=False):
    members = json.loads(row["participant_ids"])
    if len(members) == 2 and "host" in members:
        return None  # 主持人与玩家的双人私信不公告
    names = channel_names(db, [member for member in members if member != "host"])
    creator = names.get(row["creator_id"], "参与者")
    others = "、".join(names.get(member, "参与者") for member in members if member != row["creator_id"])
    text = creator + "与" + others + "已结束私信" if ending else creator + "正在与" + others + "私信"
    return storage.add_message(db, game_id, text=text)


def ensure_channel_available(db, game_id, member_ids, exclude=None):
    for member_id in member_ids:
        if member_id == "host":
            continue
        active = storage.active_private_channel(db, game_id, member_id)
        if active and active["id"] != exclude:
            raise HTTPException(409, "所选成员正在其他私信中")


def channel_command(db, game, actor, action_id, payload):
    rows = []
    if action_id == "channel.create":
        body = schemas.Channel.model_validate(payload)
        invited = list(dict.fromkeys(body.participant_ids))
        if actor["id"] in invited:
            raise HTTPException(422, "不能邀请自己")
        valid = {"host"}
        valid.update(
            row["id"]
            for row in db.execute(
                "SELECT id FROM participants WHERE game_id=? AND active=1 AND blocked=0", (game["id"],)
            )
        )
        if not invited or any(member not in valid for member in invited):
            raise HTTPException(422, "邀请成员必须是本局有效参与身份或主持人")
        members = [actor["id"], *invited]
        accepted = [actor["id"]] + (["host"] if "host" in invited else [])
        immediate = actor["kind"] == "host" or set(accepted) == set(members)
        if actor["kind"] == "host":
            accepted = list(members)
        if immediate:
            ensure_channel_available(db, game["id"], members)
        # 忽略自定义频道名，统一按成员生成：玩家用号位，主持人用「主持人」。
        seats = {row["participant_id"]: row["seat_id"] for row in db.execute(
            "SELECT id AS participant_id, seat_id FROM participants WHERE game_id=?", (game["id"],)
        )}
        title = "、".join(
            "主持人" if member == "host" else f"{seats.get(member) or '?'}号" for member in members
        )
        channel_id = "private:" + secrets.token_urlsafe(12)
        db.execute(
            """INSERT INTO channels
               (id,game_id,name,creator_id,status,participant_ids,invited_ids,accepted_ids,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (
                channel_id,
                game["id"],
                title,
                actor["id"],
                "active" if immediate else "pending",
                storage.dumps(members),
                storage.dumps(invited),
                storage.dumps(accepted),
                storage.now_text(),
            ),
        )
        if immediate:
            row = db.execute("SELECT * FROM channels WHERE id=?", (channel_id,)).fetchone()
            notice = channel_notice(db, game["id"], row)
            if notice:
                rows.append(notice)
    else:
        body = schemas.ChannelRef.model_validate(payload)
        row = db.execute(
            "SELECT * FROM channels WHERE id=? AND game_id=?", (body.channel_id, game["id"])
        ).fetchone()
        if not row:
            raise HTTPException(422, "私信频道不存在")
        members = json.loads(row["participant_ids"])
        invited = json.loads(row["invited_ids"])
        accepted = json.loads(row["accepted_ids"])
        if actor["kind"] != "host" and actor["id"] not in members:
            raise HTTPException(403, "你不是该私信成员")
        if action_id == "channel.accept":
            if row["status"] != "pending" or actor["id"] not in invited or actor["id"] in accepted:
                raise HTTPException(409, "该邀请不再等待你的同意")
            ensure_channel_available(db, game["id"], [actor["id"]])
            accepted.append(actor["id"])
            active = set(accepted) == set(members)
            if active:
                ensure_channel_available(db, game["id"], members, row["id"])
            db.execute(
                "UPDATE channels SET accepted_ids=?,status=? WHERE id=?",
                (storage.dumps(accepted), "active" if active else "pending", row["id"]),
            )
            if active:
                row = db.execute("SELECT * FROM channels WHERE id=?", (row["id"],)).fetchone()
                notice = channel_notice(db, game["id"], row)
                if notice:
                    rows.append(notice)
        elif action_id == "channel.reject":
            if row["status"] != "pending" or actor["id"] not in invited or actor["id"] in accepted:
                raise HTTPException(409, "该邀请不再等待你的回应")
            db.execute(
                "UPDATE channels SET status='ended',ended_at=? WHERE id=?",
                (storage.now_text(), row["id"]),
            )
            # 拒绝者此后不得再读频道里发过的图片：解除该频道消息的图片授权。
            db.execute("UPDATE messages SET image_id=NULL WHERE channel_id=?", (row["id"],))
        elif action_id == "channel.end":
            if row["status"] != "active":
                raise HTTPException(409, "该私信尚未开始或已经结束")
            db.execute(
                "UPDATE channels SET status='ended',ended_at=? WHERE id=?",
                (storage.now_text(), row["id"]),
            )
            db.execute("UPDATE messages SET image_id=NULL WHERE channel_id=?", (row["id"],))
            notice = channel_notice(db, game["id"], row, ending=True)
            if notice:
                rows.append(notice)
        else:
            raise HTTPException(422, "未知私信操作")
    game["version"] += 1
    return rows


def require_listed_action(db, game, actor, action_id, payload):
    projection = views.view(db, game, actor, realtime.online(game["id"]))
    candidates = [
        descriptor
        for descriptor in projection["actions"]
        if descriptor["id"] == action_id
        and all(payload.get(key) == value for key, value in descriptor["payload"].items())
    ]
    if not candidates:
        raise HTTPException(422, "此操作不可用，请刷新当前状态")
    descriptor = candidates[0]
    allowed = set(descriptor["payload"]) | {item["name"] for item in descriptor["fields"]}
    # channel.create 的自定义频道名已被忽略（服务端统一按成员命名），但旧客户端仍会带上。
    if action_id == "channel.create":
        allowed.add("name")
    if set(payload) - allowed:
        raise HTTPException(422, "操作包含未允许的字段")


@router.post("/games/{game_id}/commands")
async def command(game_id: str, body: schemas.Command, request: Request):
    async with realtime.lock:
        with storage.transaction() as db:
            actor = auth.require_actor(db, request, game_id)
            game = copy.deepcopy(require_game(db, game_id, mutable=True))
            if body.as_seat:
                if actor["kind"] != "host":
                    raise HTTPException(403, "仅主持人可以代玩家操作")
                actor = impersonated_actor(db, game, body.as_seat)
            if body.expected_version != game["version"]:
                raise HTTPException(409, "状态已变化，请刷新后检查并重新确认操作")
            payload = copy.deepcopy(body.payload)
            if actor["kind"] == "spectator" and not body.action.startswith("channel."):
                raise HTTPException(403, "观战者不能执行游戏或管理行动")
            if actor["kind"] != "host" and body.action.startswith("room."):
                raise HTTPException(403, "仅主持人可以管理房间")
            if (
                actor["kind"] != "host"
                and not body.action.startswith("channel.")
                and storage.active_private_channel(db, game_id, actor["id"])
            ):
                raise HTTPException(403, "私信期间不能执行游戏行动")
            if body.action == "marg.mimic":
                reason = storage.channel_send_reason(db, game, actor, "public")
                if reason:
                    raise HTTPException(403, reason)
            require_listed_action(db, game, actor, body.action, payload)
            if body.action.startswith("channel."):
                rows = channel_command(db, game, actor, body.action, payload)
            elif body.action.startswith("room."):
                rows = room_command(db, game, actor, body.action, payload)
            else:
                if "image" in payload:
                    image = payload.pop("image")
                    if image:
                        payload["image_id"] = evidence.create(db, game_id, actor, image=image)
                evidence.validate_references(db, game, actor, payload)
                events = apply_command(game, actor, body.action, payload, by_host=bool(body.as_seat))
                rows = storage.add_events(db, game_id, events)
            storage.save_game(db, game)
        realtime.publish(game_id, rows)
        return current_view(game_id, auth.token_hash(request))


@router.get("/games/{game_id}/seats/{seat_id}/view")
async def seat_view(game_id: str, seat_id: str, request: Request):
    async with realtime.lock:
        with storage.connect() as db:
            auth.require_actor(db, request, game_id, host=True)
            game = require_game(db, game_id)
            actor = impersonated_actor(db, game, seat_id)
            return {
                "seat_id": actor["seat_id"],
                "name": actor["name"],
                "view": views.view(db, game, actor, realtime.online(game_id)),
            }


@router.get("/games/{game_id}/messages")
async def get_messages(
    game_id: str,
    request: Request,
    before: int | None = Query(default=None, ge=1),
    after: int | None = Query(default=None, ge=0),
    channel_id: str | None = Query(default=None, max_length=100),
    scope: Literal["all", "public", "private", "system", "host"] = "all",
):
    if before is not None and after is not None:
        raise HTTPException(422, "不能同时使用前向和后向游标")
    async with realtime.lock:
        with storage.connect() as db:
            actor = auth.require_actor(db, request, game_id)
            require_game(db, game_id)
            return storage.messages(
                db,
                game_id,
                actor,
                before=before,
                after=after,
                channel_id=channel_id,
                scope=scope,
            )


@router.post("/games/{game_id}/messages")
async def send_message(game_id: str, body: schemas.Chat, request: Request):
    async with realtime.lock:
        with storage.transaction() as db:
            actor = auth.require_actor(db, request, game_id)
            game = require_game(db, game_id, mutable=True)
            permitted = views.view(db, game, actor, realtime.online(game_id))
            channel = next((item for item in permitted["channels"] if item["id"] == body.channel_id), None)
            if not channel:
                raise HTTPException(403, "你不能访问该频道")
            if not channel["can_send"]:
                raise HTTPException(403, channel.get("reason") or "当前不能在该频道发言")
            audience = None
            if body.channel_id != "public":
                channel_row = db.execute(
                    "SELECT * FROM channels WHERE id=? AND game_id=?", (body.channel_id, game_id)
                ).fetchone()
                if not channel_row or not storage.channel_visible(channel_row, actor):
                    raise HTTPException(403, "你不能访问该频道")
                audience = storage.channel_members(channel_row)
            seat = seat_for(game, actor["seat_id"]) if actor["seat_id"] else None
            row = storage.add_message(
                db,
                game_id,
                kind="chat",
                sender_id=actor["id"],
                sender_name=seat["name"] if seat else actor["name"],
                avatar_role_id=(seat["avatar_role_id"] if game["status"] != "lobby" else None)
                if seat
                else ("host" if actor["kind"] == "host" else None),
                channel_id=body.channel_id,
                text=body.text,
                audience=audience,
            )
        realtime.publish(game_id, [row], state=False)
        return storage.message_view(row, actor)


@router.post("/games/{game_id}/evidence")
async def upload_evidence(game_id: str, body: schemas.Evidence, request: Request):
    async with realtime.lock:
        with storage.transaction() as db:
            actor = auth.require_actor(db, request, game_id)
            require_game(db, game_id, mutable=True)
            if actor["kind"] == "spectator" or storage.active_private_channel(db, game_id, actor["id"]):
                raise HTTPException(403, "当前身份不能提交游戏证物")
            return {"id": evidence.create(db, game_id, actor, body.text, body.image)}


@router.get("/games/{game_id}/evidence/{evidence_id}")
async def get_evidence(game_id: str, evidence_id: str, request: Request):
    async with realtime.lock:
        with storage.connect() as db:
            actor = auth.require_actor(db, request, game_id)
            if actor["kind"] == "spectator":
                raise HTTPException(403, "观战者不能读取游戏证物")
            row = evidence.get_permitted(db, require_game(db, game_id), actor, evidence_id)
            headers = {
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'none'; sandbox",
            }
            if row["image"] is not None:
                return Response(content=row["image"], media_type=row["mime"], headers=headers)
            return Response(content=row["text"], media_type="text/plain; charset=utf-8", headers=headers)
