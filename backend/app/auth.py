"""Cookie authentication and game-bound participant authorization."""

import hashlib
import json
import os
import secrets
from urllib.parse import urlsplit

from fastapi import HTTPException

from . import storage

COOKIE = "seven_double_session"
DEFAULT_ALLOWED_ORIGINS = "super.tkcloud.online"


def secret_hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def allowed_origins():
    """显式放行的来源，写 host 或 host:port（贴整条 URL 也可以）；用 GAME_ALLOWED_ORIGINS 覆盖。"""
    raw = os.environ.get("GAME_ALLOWED_ORIGINS", DEFAULT_ALLOWED_ORIGINS)
    hosts = []
    for item in raw.split(","):
        item = item.strip().lower()
        if item:
            hosts.append(urlsplit(item).netloc or item)
    return hosts


def forwarded(connection, header):
    """反向代理可能改写 Host/scheme，取 X-Forwarded-* 的第一个值当作对外值。"""
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
        # 浏览器自己判定为同源，代理改写 Host 或终结 TLS 都不影响。
        return True
    if parsed.scheme not in ("http", "https"):
        return False
    scheme = forwarded(connection, "x-forwarded-proto") or {
        "ws": "http",
        "wss": "https",
    }.get(connection.url.scheme, connection.url.scheme)
    host = forwarded(connection, "x-forwarded-host") or connection.headers.get("host", "")
    return parsed.scheme == scheme and parsed.netloc.lower() == host.lower()


def token_hash(connection):
    token = connection.cookies.get(COOKIE)
    return secret_hash(token) if token else None


def actor_for_token(db, hashed, game_id=None):
    if not hashed:
        return None
    session = db.execute(
        "SELECT * FROM sessions WHERE token_hash=? AND valid=1", (hashed,)
    ).fetchone()
    if not session:
        return None
    if session["kind"] == "host":
        return {
            "id": "host",
            "kind": "host",
            "game_id": game_id or storage.current_game_id(db),
            "seat_id": None,
            "name": "主持人",
            "access_ids": ["host"],
        }
    participant = db.execute(
        "SELECT * FROM participants WHERE id=? AND active=1 AND blocked=0",
        (session["participant_id"],),
    ).fetchone()
    if not participant or (game_id and participant["game_id"] != game_id):
        return None
    game = storage.load_game(db, participant["game_id"])
    if not game:
        return None
    if participant["kind"] == "player" and not any(
        seat["id"] == participant["seat_id"] and seat["occupant_id"] == participant["id"]
        for seat in game["seats"]
    ):
        return None
    return {key: participant[key] for key in ("id", "kind", "game_id", "seat_id", "name")} | {
        "access_ids": json.loads(participant["access_ids"])
    }


def require_actor(db, connection, game_id=None, host=False):
    actor = actor_for_token(db, token_hash(connection), game_id)
    if not actor:
        raise HTTPException(401, "登录已失效，请重新加入或联系主持人")
    if host and actor["kind"] != "host":
        raise HTTPException(403, "仅主持人可以进行此操作")
    return actor


def issue_session(db, kind, participant_id=None):
    token = secrets.token_urlsafe(32)
    db.execute(
        "INSERT INTO sessions(token_hash,participant_id,kind,created_at) VALUES(?,?,?,?)",
        (secret_hash(token), participant_id, kind, storage.now_text()),
    )
    return token


def set_cookie(response, request, token):
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
        max_age=60 * 60 * 24 * 30,
    )


def revoke_participant(db, participant_id, *, block=False):
    db.execute(
        "UPDATE participants SET active=0,blocked=? WHERE id=?", (int(block), participant_id)
    )
    db.execute("UPDATE sessions SET valid=0 WHERE participant_id=?", (participant_id,))


def me(actor):
    return {"actor": actor, "game_id": actor["game_id"] if actor else None}
