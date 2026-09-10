"""Cookie authentication and game-bound participant authorization."""

import hashlib
import json
import secrets
from urllib.parse import urlsplit

from fastapi import HTTPException

from . import storage

COOKIE = "seven_double_session"


def secret_hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def same_origin(connection):
    origin = connection.headers.get("origin")
    if connection.headers.get("sec-fetch-site") == "cross-site":
        return False
    if not origin:
        return connection.scope["type"] != "websocket"
    parsed = urlsplit(origin)
    scheme = {"ws": "http", "wss": "https"}.get(connection.url.scheme, connection.url.scheme)
    return (
        parsed.scheme == scheme
        and parsed.scheme in ("http", "https")
        and parsed.netloc.lower() == connection.headers.get("host", "").lower()
    )


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
    db.execute("UPDATE invites SET valid=0 WHERE participant_id=?", (participant_id,))


def me(actor):
    return {"actor": actor, "game_id": actor["game_id"] if actor else None}
