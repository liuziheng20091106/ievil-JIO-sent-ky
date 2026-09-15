"""Bearer/cookie authentication and stable-account game authorization."""

import hashlib
import json
import os
import secrets
from urllib.parse import urlsplit

from fastapi import HTTPException

from . import auth_storage, storage

COOKIE = "seven_double_session"
DEFAULT_ALLOWED_ORIGINS = "super.tkcloud.online"


def secret_hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def allowed_origins():
    raw = os.environ.get("GAME_ALLOWED_ORIGINS", DEFAULT_ALLOWED_ORIGINS)
    return [
        urlsplit(item.strip().lower()).netloc or item.strip().lower()
        for item in raw.split(",")
        if item.strip()
    ]


def forwarded(connection, header):
    value = connection.headers.get(header)
    return value.split(",")[0].strip() if value else ""


def same_origin(connection):
    origin = connection.headers.get("origin")
    parsed = urlsplit(origin) if origin else None
    if parsed and parsed.hostname:
        allowed = allowed_origins()
        if parsed.netloc.lower() in allowed or parsed.hostname in allowed:
            return True
    site = connection.headers.get("sec-fetch-site")
    if site == "cross-site":
        return False
    if not origin:
        return connection.scope["type"] != "websocket"
    if site == "same-origin":
        return True
    if parsed.scheme not in ("http", "https"):
        return False
    scheme = forwarded(connection, "x-forwarded-proto") or {
        "ws": "http",
        "wss": "https",
    }.get(connection.url.scheme, connection.url.scheme)
    host = forwarded(connection, "x-forwarded-host") or connection.headers.get("host", "")
    return parsed.scheme == scheme and parsed.netloc.lower() == host.lower()


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


def bearer_hash(connection):
    authorization = connection.headers.get("authorization")
    if authorization is None:
        return None
    token = raw_token(connection)
    return secret_hash(token) if token else None


def token_hash(connection):
    token = raw_token(connection)
    return secret_hash(token) if token else None


def valid_bearer(connection):
    return bool(auth_storage.token_row(bearer_hash(connection)))


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
        "name": account["nickname"],
        "qq_id": account["qq_id"],
        "avatar_url": account["avatar_url"],
        "access_ids": [account["id"]],
    }


def actor_for_token(db, hashed, game_id=None):
    token = auth_storage.token_row(hashed)
    if not token:
        return None
    if token["kind"] == "host":
        return {
            "id": "host",
            "account_id": None,
            "kind": "host",
            "game_id": game_id or storage.current_game_id(db),
            "seat_id": None,
            "name": "主持人",
            "access_ids": ["host"],
        }
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
        **{key: participant[key] for key in ("id", "account_id", "kind", "game_id", "seat_id", "name")},
        "qq_id": account["qq_id"],
        "avatar_url": account["avatar_url"],
        "access_ids": json.loads(participant["access_ids"]),
    }


def require_actor(db, connection, game_id=None, host=False):
    actor = actor_for_token(db, token_hash(connection), game_id)
    if not actor:
        raise HTTPException(401, "登录已失效或尚未加入本局")
    if host and actor["kind"] != "host":
        raise HTTPException(403, "仅主持人可以进行此操作")
    return actor


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
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
        max_age=60 * 60 * 24 * auth_storage.TOKEN_DAYS,
    )


def revoke_participant(db, participant_id, *, block=False):
    db.execute(
        "UPDATE participants SET active=0,blocked=? WHERE id=?", (int(block), participant_id)
    )


def me(actor):
    return {"actor": actor, "game_id": actor["game_id"] if actor else None}
