"""HTTP transport, room administration, and atomic domain command dispatch."""

import copy
import secrets

from fastapi import APIRouter, HTTPException, Query, Request, Response

from . import auth, evidence, realtime, schemas, storage, views
from .game import CATALOG, DEFAULT_CODEX, apply_command, clear_seat_actions, create_game

router = APIRouter(prefix="/api")


def require_game(db, game_id, mutable=False):
    game = storage.load_game(db, game_id)
    if not game:
        raise HTTPException(404, "对局不存在")
    if mutable and game["status"] == "ended":
        raise HTTPException(409, "本局已经结束，只能查看获准的结算与历史")
    return game


def seat_for(game, seat_id):
    seat = next((seat for seat in game["seats"] if seat["id"] == seat_id), None)
    if not seat:
        raise HTTPException(422, "请选择有效席位")
    return seat


def current_view(game_id, hashed):
    with storage.connect() as db:
        actor = auth.actor_for_token(db, hashed, game_id)
        if not actor:
            raise HTTPException(401, "登录已失效")
        return views.view(db, require_game(db, game_id), actor, realtime.online(game_id))


def revoke_current_cookie(db, request):
    hashed = auth.token_hash(request)
    if hashed:
        db.execute("UPDATE sessions SET valid=0 WHERE token_hash=?", (hashed,))


def refresh_connections():
    for game_id in {peer.game_id for peer in realtime.connections}:
        realtime.publish(game_id)


@router.get("/health")
async def health():
    return {"ok": True}


@router.get("/catalog")
async def catalog():
    return {"roles": CATALOG, "default_codex": DEFAULT_CODEX}


@router.get("/me")
async def me(request: Request):
    async with realtime.lock:
        with storage.connect() as db:
            return auth.me(auth.actor_for_token(db, auth.token_hash(request)))


@router.post("/host/login")
async def login(body: schemas.Login, request: Request, response: Response):
    if not secrets.compare_digest(body.password.encode(), b"114514"):
        raise HTTPException(401, "主持人密码错误")
    async with realtime.lock:
        with storage.transaction() as db:
            revoke_current_cookie(db, request)
            token = auth.issue_session(db, "host")
            actor = auth.actor_for_token(db, auth.secret_hash(token))
        auth.set_cookie(response, request, token)
        refresh_connections()
        return auth.me(actor)


@router.post("/logout")
async def logout(request: Request, response: Response):
    async with realtime.lock:
        with storage.transaction() as db:
            revoke_current_cookie(db, request)
        response.delete_cookie(auth.COOKIE, path="/", httponly=True, samesite="lax")
        refresh_connections()
        return {"ok": True}


@router.post("/games")
async def create(body: schemas.Create, request: Request):
    async with realtime.lock:
        with storage.transaction() as db:
            auth.require_actor(db, request, host=True)
            active = db.execute("SELECT id FROM games WHERE status != 'ended' LIMIT 1").fetchone()
            if active:
                raise HTTPException(409, "请先结束当前对局，再创建下一局")
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
            db.execute("UPDATE invites SET valid=0 WHERE game_id != ?", (game["id"],))
            row = storage.add_message(db, game["id"], text="新对局已创建，等待七位玩家凭邀请码入席")
        for peer in realtime.connections:
            if peer.kind == "host":
                peer.game_id = game["id"]
        realtime.publish(game["id"], [row])
        return current_view(game["id"], auth.token_hash(request))


@router.post("/games/{game_id}/invites")
async def invite(game_id: str, body: schemas.Invite, request: Request):
    async with realtime.lock:
        with storage.transaction() as db:
            auth.require_actor(db, request, game_id, host=True)
            game = require_game(db, game_id, mutable=True)
            if body.kind == "player":
                seat = seat_for(game, body.seat_id)
                participant_id = seat["occupant_id"]
            else:
                if body.seat_id is not None:
                    raise HTTPException(422, "观战邀请码不对应玩家席位")
                participant_id = None
            db.execute(
                "UPDATE invites SET valid=0 WHERE game_id=? AND kind=? AND seat_id IS ?",
                (game_id, body.kind, body.seat_id),
            )
            code = secrets.token_urlsafe(12)
            db.execute(
                "INSERT INTO invites(code_hash,game_id,seat_id,kind,participant_id) VALUES(?,?,?,?,?)",
                (auth.secret_hash(code), game_id, body.seat_id, body.kind, participant_id),
            )
        return {"code": code, "seat_id": body.seat_id, "kind": body.kind}


@router.post("/join")
async def join(body: schemas.Join, request: Request, response: Response):
    async with realtime.lock:
        with storage.transaction() as db:
            invitation = db.execute(
                "SELECT * FROM invites WHERE code_hash=? AND valid=1 AND redeemed_by IS NULL",
                (auth.secret_hash(body.code),),
            ).fetchone()
            if not invitation:
                raise HTTPException(403, "邀请码无效、已使用或已被撤销")
            game = require_game(db, invitation["game_id"], mutable=True)
            previous = auth.actor_for_token(db, auth.token_hash(request))
            if previous and previous["kind"] == "host":
                raise HTTPException(409, "主持人请使用另一个浏览器身份加入，或先退出主持人")
            seat = seat_for(game, invitation["seat_id"]) if invitation["kind"] == "player" else None
            participant_id = invitation["participant_id"] or secrets.token_urlsafe(18)
            if (
                previous
                and previous["game_id"] == game["id"]
                and previous["kind"] == "player"
                and previous["id"] != participant_id
            ):
                raise HTTPException(409, "你已占据本局席位，请由主持人处理替补或移出")
            if seat and seat["occupant_id"] and seat["occupant_id"] != invitation["participant_id"]:
                raise HTTPException(409, "该席位已被占用，请联系主持人")
            if invitation["participant_id"]:
                participant = db.execute(
                    "SELECT * FROM participants WHERE id=? AND active=1 AND blocked=0",
                    (participant_id,),
                ).fetchone()
                if not participant:
                    raise HTTPException(403, "该参与身份已撤销，请联系主持人重新发码")
                db.execute("UPDATE sessions SET valid=0 WHERE participant_id=?", (participant_id,))
                db.execute("UPDATE participants SET name=? WHERE id=?", (body.name, participant_id))
            else:
                db.execute(
                    "INSERT INTO participants(id,game_id,kind,seat_id,name,access_ids) VALUES(?,?,?,?,?,?)",
                    (
                        participant_id,
                        game["id"],
                        invitation["kind"],
                        invitation["seat_id"],
                        body.name,
                        storage.dumps([participant_id]),
                    ),
                )
            revoke_current_cookie(db, request)
            if seat:
                seat["occupant_id"], seat["name"] = participant_id, body.name
                if game["status"] == "lobby" and not invitation["participant_id"]:
                    seat["ready"] = False
            db.execute(
                "UPDATE invites SET valid=0,redeemed_by=? WHERE code_hash=?",
                (participant_id, invitation["code_hash"]),
            )
            token = auth.issue_session(db, invitation["kind"], participant_id)
            game["version"] += 1
            storage.save_game(db, game)
            label = (str(seat["id"]) + "号玩家" if seat else "观战者") + "【" + body.name + "】"
            row = storage.add_message(db, game["id"], text=label + "已加入对局")
            actor = auth.actor_for_token(db, auth.secret_hash(token))
        auth.set_cookie(response, request, token)
        realtime.publish(game["id"], [row])
        refresh_connections()
        return auth.me(actor)


@router.get("/games/{game_id}/state")
async def state(game_id: str, request: Request):
    async with realtime.lock:
        return current_view(game_id, auth.token_hash(request))


def room_command(db, game, actor, action, payload):
    if actor["kind"] != "host":
        raise HTTPException(403, "仅主持人可以管理房间")
    text = ""
    if action == "room.kick":
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
            db.execute(
                "UPDATE invites SET valid=0 WHERE game_id=? AND seat_id=?", (game["id"], seat["id"])
            )
            seat["occupant_id"] = None
            if game["status"] == "lobby":
                seat["ready"] = False
        text = "【" + target["name"] + "】已被移出" + ("并在本局拉黑" if body.block else "")
    elif action == "room.replace":
        body = schemas.Replace.model_validate(payload)
        seat = seat_for(game, body.seat_id)
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
                import json

                access_ids = list(dict.fromkeys(access_ids + json.loads(old["access_ids"])))
            auth.revoke_participant(db, old["id"], block=bool(old["blocked"]))
        db.execute(
            "UPDATE invites SET valid=0 WHERE game_id=? AND seat_id=?", (game["id"], seat["id"])
        )
        db.execute(
            "UPDATE participants SET kind='player',seat_id=?,access_ids=? WHERE id=?",
            (seat["id"], storage.dumps(access_ids), substitute["id"]),
        )
        db.execute(
            "UPDATE sessions SET kind='player' WHERE participant_id=? AND valid=1",
            (substitute["id"],),
        )
        seat["occupant_id"], seat["name"] = substitute["id"], substitute["name"]
        if not body.keep_actions:
            clear_seat_actions(game, seat["id"])
        text = seat["id"] + "号席位已由【" + substitute["name"] + "】接管"
        private_notice = storage.add_message(
            db,
            game["id"],
            kind="information",
            audience=[substitute["id"]],
            channel_id="host:" + substitute["id"],
            text="主持人已让你接管"
            + seat["id"]
            + "号席位。"
            + ("允许继承原操作者私密历史。" if body.share_history else "不继承原操作者私密历史。")
            + (
                "保留该席已提交行动。"
                if body.keep_actions
                else "该席待处理和已确认行动已清除，请按阶段重新操作。"
            ),
        )
        game["version"] += 1
        return [private_notice, storage.add_message(db, game["id"], text=text)]
    elif action == "room.channel":
        body = schemas.Channel.model_validate(payload)
        members = list(dict.fromkeys(body.participant_ids))
        for participant_id in members:
            if not db.execute(
                "SELECT 1 FROM participants WHERE id=? AND game_id=? AND active=1 AND blocked=0",
                (participant_id, game["id"]),
            ).fetchone():
                raise HTTPException(422, "频道成员必须是本局有效参与者")
        channel_id = "group:" + secrets.token_urlsafe(12)
        db.execute(
            "INSERT INTO channels(id,game_id,name,participant_ids) VALUES(?,?,?,?)",
            (channel_id, game["id"], body.name, storage.dumps(members)),
        )
        game["version"] += 1
        return [
            storage.add_message(
                db,
                game["id"],
                text="主持人已开启私密频道【" + body.name + "】",
                audience=members,
                channel_id=channel_id,
            )
        ]
    elif action == "room.mute":
        body = schemas.Mute.model_validate(payload)
        target = db.execute(
            "SELECT * FROM participants WHERE id=? AND game_id=? AND active=1 AND blocked=0",
            (body.participant_id, game["id"]),
        ).fetchone()
        if not target:
            raise HTTPException(422, "请选择本局有效参与者")
        db.execute(
            "UPDATE participants SET muted=? WHERE id=?", (int(body.muted), body.participant_id)
        )
        text = (
            "【" + target["name"] + "】已被禁言"
            if body.muted
            else "【" + target["name"] + "】已解除禁言"
        )
    elif action == "room.revoke_invite":
        if set(payload) != {"seat_id"}:
            raise HTTPException(422, "请选择邀请码范围")
        seat_id = payload["seat_id"]
        if seat_id != "spectator":
            seat_for(game, seat_id)
        db.execute(
            "UPDATE invites SET valid=0 WHERE game_id=? AND seat_id IS ?",
            (game["id"], None if seat_id == "spectator" else seat_id),
        )
        game["version"] += 1
        return [
            storage.add_message(
                db,
                game["id"],
                text="所选未使用邀请码已撤销",
                audience=["host"],
                channel_id="information",
            )
        ]
    else:
        raise HTTPException(422, "未知房间管理操作")
    game["version"] += 1
    return [storage.add_message(db, game["id"], text=text)]


@router.post("/games/{game_id}/commands")
async def command(game_id: str, body: schemas.Command, request: Request):
    async with realtime.lock:
        with storage.transaction() as db:
            actor = auth.require_actor(db, request, game_id)
            game = copy.deepcopy(require_game(db, game_id, mutable=True))
            if body.expected_version != game["version"]:
                raise HTTPException(409, "状态已变化，请刷新后检查并重新确认操作")
            payload = copy.deepcopy(body.payload)
            if "image" in payload:
                image = payload.pop("image")
                if image:
                    payload["image_id"] = evidence.create(db, game_id, actor, image=image)
            evidence.validate_references(db, game, actor, payload)
            if body.action.startswith("room."):
                rows = room_command(db, game, actor, body.action, payload)
            else:
                events = apply_command(game, actor, body.action, payload)
                rows = storage.add_events(db, game_id, events)
            storage.save_game(db, game)
        realtime.publish(game_id, rows)
        return current_view(game_id, auth.token_hash(request))


@router.get("/games/{game_id}/messages")
async def get_messages(
    game_id: str,
    request: Request,
    before: int | None = Query(default=None, ge=1),
    after: int | None = Query(default=None, ge=0),
    channel_id: str | None = Query(default=None, max_length=100),
):
    if before is not None and after is not None:
        raise HTTPException(422, "不能同时使用前向和后向游标")
    async with realtime.lock:
        with storage.connect() as db:
            actor = auth.require_actor(db, request, game_id)
            require_game(db, game_id)
            return storage.messages(
                db, game_id, actor, before=before, after=after, channel_id=channel_id
            )


@router.post("/games/{game_id}/messages")
async def send_message(game_id: str, body: schemas.Chat, request: Request):
    async with realtime.lock:
        with storage.transaction() as db:
            actor = auth.require_actor(db, request, game_id)
            game = require_game(db, game_id, mutable=True)
            permitted = views.view(db, game, actor, realtime.online(game_id))
            channel = next(
                (item for item in permitted["channels"] if item["id"] == body.channel_id), None
            )
            if not channel:
                raise HTTPException(403, "你不能访问该频道")
            if not channel["can_send"]:
                raise HTTPException(403, channel.get("reason") or "当前不能在该频道发言")
            audience = None
            if body.channel_id.startswith("host:"):
                audience = [body.channel_id[5:]]
            elif body.channel_id != "public":
                import json

                channel_row = db.execute(
                    "SELECT participant_ids FROM channels WHERE id=? AND game_id=?",
                    (body.channel_id, game_id),
                ).fetchone()
                audience = json.loads(channel_row["participant_ids"])
            seat = seat_for(game, actor["seat_id"]) if actor["seat_id"] else None
            row = storage.add_message(
                db,
                game_id,
                kind="chat",
                sender_id=actor["id"],
                sender_name=seat["name"] if seat else actor["name"],
                avatar_role_id=seat["avatar_role_id"]
                if seat
                else ("host" if actor["kind"] == "host" else None),
                channel_id=body.channel_id,
                text=body.text,
                audience=audience,
            )
        realtime.publish(game_id, [row], state=False)
        return storage.message_view(row)


@router.post("/games/{game_id}/evidence")
async def upload_evidence(game_id: str, body: schemas.Evidence, request: Request):
    async with realtime.lock:
        with storage.transaction() as db:
            actor = auth.require_actor(db, request, game_id)
            require_game(db, game_id, mutable=True)
            if actor["kind"] == "spectator":
                raise HTTPException(403, "观战者不能提交游戏证物")
            return {"id": evidence.create(db, game_id, actor, body.text, body.image)}


@router.get("/games/{game_id}/evidence/{evidence_id}")
async def get_evidence(game_id: str, evidence_id: str, request: Request):
    async with realtime.lock:
        with storage.connect() as db:
            actor = auth.require_actor(db, request, game_id)
            row = evidence.get_permitted(db, require_game(db, game_id), actor, evidence_id)
            headers = {
                "Cache-Control": "private, no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'none'; sandbox",
            }
            if row["image"] is not None:
                return Response(content=row["image"], media_type=row["mime"], headers=headers)
            return Response(
                content=row["text"], media_type="text/plain; charset=utf-8", headers=headers
            )
