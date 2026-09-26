"""Bearer/cookie authentication and stable-account game authorization."""

import hashlib
import json
import os
import secrets

from fastapi import HTTPException

from . import auth_storage, storage
from .game.state import display_player_name, host_capable, host_display_name

COOKIE = "seven_double_session"


def secret_hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def raw_token(connection):
    authorization = connection.headers.get("authorization")
    if authorization is not None:
        parts = authorization.split(" ")
        if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1] or any(
            char.isspace() for char in parts[1]
        ):
            return None
        return parts[1]
    return connection.cookies.get(COOKIE)


def token_hash(connection):
    token = raw_token(connection)
    return secret_hash(token) if token else None


def gateway_authorized(connection):
    expected = os.environ.get("GAME_GATEWAY_TOKEN", "")
    supplied = connection.headers.get("x-gateway-token", "")
    return bool(expected) and secrets.compare_digest(supplied.encode(), expected.encode())


def account_actor(account):
    return {
        "id": account["id"],
        "account_id": account["id"],
        "kind": "account",
        "game_id": None,
        "seat_id": None,
        "name": display_player_name(account["nickname"]),
        "qq_id": account["qq_id"],
        "avatar_url": account["avatar_url"],
        "access_ids": [account["id"]],
    }


def admin_qq_ids():
    """内置系统管理员的 QQ 号；用 GAME_ADMIN_QQ 配置，英文逗号分隔。"""
    return {item.strip() for item in os.environ.get("GAME_ADMIN_QQ", "").split(",") if item.strip()}


def host_level(account):
    """主持等级：内置管理员恒为 5 级，其余看授权表；被取消或用完一局后为 0。"""
    if account is None:
        return 0
    if account["qq_id"] in admin_qq_ids():
        return auth_storage.HOST_LEVEL_MAX
    return auth_storage.host_level(account["id"])


def host_actor(account, db, game_id=None, *, entered=True):
    """主持人身份。``entered`` 表示是否已确认进入本局管理界面。

    未确认时身份仍然是主持人（客户端要能识别出「我该去确认」），但访问名单为空、
    也不给主持级放行：具体判据见 :func:`backend.app.game.state.host_capable`。
    """
    return {
        "id": "host",
        "account_id": account["id"],
        "kind": "host",
        "game_id": game_id or storage.current_game_id(db),
        "seat_id": None,
        "name": host_display_name(account["nickname"]),
        # 等级与展示名之外，客户端只再需要 QQ 昵称本身（授权页与通告文案）。
        "nickname": display_player_name(account["nickname"]),
        "qq_id": account["qq_id"],
        "avatar_url": account["avatar_url"],
        "host_level": host_level(account),
        # 未确认进入就不属于本局任何频道：私聊与消息历史按空名单过滤。
        "access_ids": ["host"] if entered else [],
        "host_entered": bool(entered),
    }


def actor_for_token(db, hashed, game_id=None):
    token = auth_storage.token_row(hashed)
    if not token:
        return None
    if token["kind"] == "host":
        account = auth_storage.account(token["account_id"]) if token["account_id"] else None
        # 授权被取消或用完（1 级）之后，旧令牌立即不再有效。
        if not account or host_level(account) < auth_storage.HOST_LEVEL_MIN:
            return None
        target_game = game_id or storage.current_game_id(db)
        # 主持授权只说明「有资格主持」：进入某一局还要先确认一次，否则拿到的
        # 只是最窄的观察者投影，也不能执行任何管理操作。
        entered = not target_game or storage.host_entered(db, target_game, account["id"])
        return host_actor(account, db, game_id, entered=entered)
    account = auth_storage.account(token["account_id"])
    if not account:
        return None
    target_game = game_id or storage.current_game_id(db)
    participant = (
        db.execute(
            "SELECT * FROM participants WHERE game_id=? AND account_id=? AND active=1 AND blocked=0",
            (target_game, account["id"]),
        ).fetchone()
        if target_game
        else None
    )
    if not participant:
        return None if game_id else account_actor(account)
    game = storage.load_game(db, participant["game_id"])
    if not game:
        return None if game_id else account_actor(account)
    if participant["kind"] == "player" and not any(
        seat["id"] == participant["seat_id"] and seat["occupant_id"] == participant["id"]
        for seat in game["seats"]
    ):
        return None if game_id else account_actor(account)
    return {
        **{
            key: participant[key]
            for key in ("id", "account_id", "kind", "game_id", "seat_id")
        },
        "name": display_player_name(participant["name"]),
        "qq_id": account["qq_id"],
        "avatar_url": account["avatar_url"],
        "access_ids": json.loads(participant["access_ids"]),
    }


def require_actor(db, connection, game_id=None, host=False, level=1):
    """取当前身份；host=True 时要求主持权限，level 给出所需的最低主持等级。"""
    hashed = token_hash(connection)
    actor = actor_for_token(db, hashed, game_id)
    if not actor:
        # 令牌本身还在、只是主持授权被取消或用完：给出能看懂的原因。
        token = auth_storage.token_row(hashed)
        if token and token["kind"] == "host":
            raise HTTPException(403, "主持授权已失效或已被取消，请重新登录")
        raise HTTPException(401, "登录已失效或尚未加入本局")
    if host:
        if actor["kind"] != "host":
            raise HTTPException(403, "仅主持人可以进行此操作")
        # 「确认进入」只约束针对某一局的接口（如席位视角）：建局、一键初始化、
        # 主持授权、发布公告都是账号级功能，不该被某一局是否确认过挡住。
        if game_id and not host_capable(actor):
            raise HTTPException(403, "请先确认进入本局管理界面")
        if int(actor.get("host_level", 0)) < level:
            raise HTTPException(403, f"此操作需要 {level} 级主持权限")
    return actor


def require_host_capable(actor):
    """主持人必须先确认进入本局管理界面，才拥有主持级数据与操作。

    玩家、观战者不受影响；只有「有主持授权但还没确认进入」这一个状态被挡下。
    """
    if actor.get("kind") == "host" and not host_capable(actor):
        raise HTTPException(403, "请先确认进入本局管理界面")
    return actor


def require_host_level(db, connection, level, game_id=None):
    """主持专属功能的等级门槛：公告要 5 级，授权他人要 4 级等。"""
    return require_actor(db, connection, game_id, host=True, level=level)


def require_account(connection):
    token = auth_storage.token_row(token_hash(connection))
    if not token or token["kind"] != "player" or not token["account_id"]:
        raise HTTPException(401, "请先通过QQ群完成登录")
    account = auth_storage.account(token["account_id"])
    if not account:
        raise HTTPException(401, "登录已失效")
    return account


def issue_session(db, kind, account_id=None):
    with auth_storage.transaction() as auth_db:
        return auth_storage.issue_token(auth_db, kind, account_id)


def set_cookie(response, request, token):
    forwarded_proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        samesite="lax",
        # 代理终结 TLS 时 request.url.scheme 仍是 http，优先信转发协议头；
        # 代理没透传该头时只能按直连 scheme 下发，部署说明已要求透传。
        secure=forwarded_proto == "https" or request.url.scheme == "https",
        path="/",
        max_age=60 * 60 * 24 * auth_storage.TOKEN_DAYS,
    )


def revoke_participant(db, participant_id, *, block=False):
    db.execute(
        "UPDATE participants SET active=0,blocked=? WHERE id=?", (int(block), participant_id)
    )


def me(actor):
    return {"actor": actor, "game_id": actor["game_id"] if actor else None}
