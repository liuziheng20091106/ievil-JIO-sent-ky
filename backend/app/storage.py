"""SQLite state and immutable, audience-scoped message history."""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("GAME_DATA_DIR", PROJECT_ROOT / "data")).resolve()


def dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def initialize():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS games (
            id TEXT PRIMARY KEY, state TEXT NOT NULL, version INTEGER NOT NULL,
            status TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS participants (
            id TEXT PRIMARY KEY, game_id TEXT NOT NULL REFERENCES games(id),
            kind TEXT NOT NULL, seat_id TEXT, name TEXT NOT NULL,
            access_ids TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
            blocked INTEGER NOT NULL DEFAULT 0, muted INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY, participant_id TEXT,
            kind TEXT NOT NULL, valid INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS invites (
            code_hash TEXT PRIMARY KEY, game_id TEXT NOT NULL REFERENCES games(id),
            kind TEXT NOT NULL, valid INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS channels (
            id TEXT PRIMARY KEY, game_id TEXT NOT NULL REFERENCES games(id),
            name TEXT NOT NULL, participant_ids TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT NOT NULL REFERENCES games(id), kind TEXT NOT NULL,
            sender_id TEXT NOT NULL, sender_name TEXT NOT NULL, avatar_role_id TEXT,
            channel_id TEXT NOT NULL, text TEXT NOT NULL, created_at TEXT NOT NULL,
            audience TEXT, image_id TEXT
        );
        CREATE INDEX IF NOT EXISTS message_game_id ON messages(game_id, id);
        CREATE TABLE IF NOT EXISTS evidence (
            id TEXT PRIMARY KEY, game_id TEXT NOT NULL REFERENCES games(id),
            owner_id TEXT NOT NULL, text TEXT NOT NULL, mime TEXT,
            image BLOB, created_at TEXT NOT NULL
        );
        """)
    with transaction() as db:
        if "seat_id" in {row["name"] for row in db.execute("PRAGMA table_info(invites)")}:
            db.execute("UPDATE invites SET valid=0")
            for column in ("seat_id", "participant_id", "redeemed_by"):
                db.execute(f"ALTER TABLE invites DROP COLUMN {column}")
        for row in db.execute("SELECT state FROM games WHERE status='lobby'").fetchall():
            game = json.loads(row["state"])
            if game["phase"] == "lobby" and game["cards"]:
                game["phase"] = "ordering"
                game["version"] += 1
                game["snapshots"] = []
                for seat in game["seats"]:
                    seat["ready"] = False
                save_game(db, game)
                db.execute(
                    "UPDATE messages SET avatar_role_id=NULL "
                    "WHERE game_id=? AND kind='chat' AND sender_id!='host'",
                    (game["id"],),
                )


@contextmanager
def connect():
    db = sqlite3.connect(DATA_DIR / "seven-double.sqlite3", timeout=15)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
    finally:
        db.close()


@contextmanager
def transaction():
    with connect() as db:
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise


def now_text():
    return datetime.now(timezone.utc).isoformat()


def load_game(db, game_id):
    row = db.execute("SELECT state FROM games WHERE id=?", (game_id,)).fetchone()
    return json.loads(row["state"]) if row else None


def current_game_id(db):
    row = db.execute("SELECT id FROM games ORDER BY rowid DESC LIMIT 1").fetchone()
    return row["id"] if row else None


def save_game(db, game):
    db.execute(
        "UPDATE games SET state=?,version=?,status=? WHERE id=?",
        (dumps(game), game["version"], game["status"], game["id"]),
    )
    if game["status"] == "ended":
        db.execute("UPDATE invites SET valid=0 WHERE game_id=?", (game["id"],))


def purge(db):
    """清空全部对局数据（含邀请码、参与身份、进度、聊天与证物）；主持人会话保留。"""
    for table in ("messages", "evidence", "channels", "invites", "participants", "games"):
        db.execute(f"DELETE FROM {table}")
    db.execute("DELETE FROM sessions WHERE kind != 'host'")


def add_message(
    db,
    game_id,
    *,
    kind="notice",
    sender_id="host",
    sender_name="主持人",
    avatar_role_id="host",
    channel_id="public",
    text="",
    audience=None,
    image_id=None,
):
    created_at = now_text()
    cursor = db.execute(
        """INSERT INTO messages(game_id,kind,sender_id,sender_name,avatar_role_id,
           channel_id,text,created_at,audience,image_id) VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (
            game_id,
            kind,
            sender_id,
            sender_name,
            avatar_role_id,
            channel_id,
            text,
            created_at,
            None if audience is None else dumps(audience),
            image_id,
        ),
    )
    return dict(db.execute("SELECT * FROM messages WHERE id=?", (cursor.lastrowid,)).fetchone())


def add_events(db, game_id, events):
    rows = []
    for event in events:
        audience = event.get("audience")
        rows.append(
            add_message(
                db,
                game_id,
                kind=event.get("kind", "notice"),
                text=event.get("text", ""),
                audience=audience,
                image_id=event.get("image_id"),
                channel_id="public" if audience is None else "information",
            )
        )
    return rows


def visible_message(row, actor):
    return (
        actor["kind"] == "host"
        or row["audience"] is None
        or bool(set(actor["access_ids"]).intersection(json.loads(row["audience"])))
    )


def message_view(row):
    result = {
        key: row[key]
        for key in (
            "id",
            "kind",
            "sender_id",
            "sender_name",
            "avatar_role_id",
            "channel_id",
            "text",
            "created_at",
        )
    }
    if row["image_id"]:
        result["image_id"] = row["image_id"]
    return result


def messages(db, game_id, actor, *, before=None, after=None, channel_id=None):
    clauses, args = ["m.game_id=?"], [game_id]
    if actor["kind"] != "host":
        ids = actor["access_ids"]
        placeholders = ",".join("?" for _ in ids)
        clauses.append(
            f"(m.audience IS NULL OR EXISTS (SELECT 1 FROM json_each(m.audience) WHERE value IN ({placeholders})))"
        )
        args.extend(ids)
    if before is not None:
        clauses.append("m.id < ?")
        args.append(before)
    if after is not None:
        clauses.append("m.id > ?")
        args.append(after)
    if channel_id is not None:
        if channel_id == "system":
            clauses.append("m.channel_id='information'")
        else:
            clauses.append("m.channel_id=?")
            args.append(channel_id)
    order = "ASC" if after is not None else "DESC"
    rows = list(
        db.execute(
            "SELECT m.* FROM messages m WHERE "
            + " AND ".join(clauses)
            + f" ORDER BY m.id {order} LIMIT 101",
            args,
        )
    )
    more = len(rows) > 100
    rows = rows[:100]
    if order == "DESC":
        rows.reverse()
    return {"messages": [message_view(row) for row in rows], "has_more": more}
