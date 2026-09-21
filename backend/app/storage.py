"""SQLite state and immutable, audience-scoped message history."""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
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
            account_id TEXT, kind TEXT NOT NULL, seat_id TEXT, name TEXT NOT NULL,
            access_ids TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
            blocked INTEGER NOT NULL DEFAULT 0, muted INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS channels (
            id TEXT PRIMARY KEY, game_id TEXT NOT NULL REFERENCES games(id),
            name TEXT NOT NULL, creator_id TEXT NOT NULL,
            status TEXT NOT NULL, participant_ids TEXT NOT NULL,
            invited_ids TEXT NOT NULL, accepted_ids TEXT NOT NULL,
            created_at TEXT NOT NULL, ended_at TEXT
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
        participant_columns = {row["name"] for row in db.execute("PRAGMA table_info(participants)")}
        if "account_id" not in participant_columns:
            db.execute("ALTER TABLE participants ADD COLUMN account_id TEXT")
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS participant_account "
            "ON participants(game_id,account_id) WHERE account_id IS NOT NULL"
        )
        channel_columns = {row["name"] for row in db.execute("PRAGMA table_info(channels)")}
        legacy_channels = "creator_id" not in channel_columns
        additions = {
            "creator_id": "TEXT NOT NULL DEFAULT 'host'",
            "status": "TEXT NOT NULL DEFAULT 'active'",
            "invited_ids": "TEXT NOT NULL DEFAULT '[]'",
            "accepted_ids": "TEXT NOT NULL DEFAULT '[]'",
            "created_at": "TEXT NOT NULL DEFAULT ''",
            "ended_at": "TEXT",
        }
        for column, declaration in additions.items():
            if column not in channel_columns:
                db.execute(f"ALTER TABLE channels ADD COLUMN {column} {declaration}")
        if legacy_channels:
            for row in db.execute("SELECT id,participant_ids,created_at FROM channels").fetchall():
                db.execute(
                    "UPDATE channels SET invited_ids=?,accepted_ids=?,created_at=? WHERE id=?",
                    (
                        row["participant_ids"],
                        row["participant_ids"],
                        row["created_at"] or now_text(),
                        row["id"],
                    ),
                )
        db.execute("DROP TABLE IF EXISTS sessions")
        # 旧的 invites 是已删除的邀请码模型，形状不同；只有旧形状才重建。
        invite_columns = {row["name"] for row in db.execute("PRAGMA table_info(invites)")}
        if invite_columns and "account_id" not in invite_columns:
            db.execute("DROP TABLE IF EXISTS invites")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS invites (
            id TEXT PRIMARY KEY, game_id TEXT NOT NULL REFERENCES games(id),
            account_id TEXT NOT NULL, inviter_id TEXT NOT NULL,
            inviter_name TEXT NOT NULL, status TEXT NOT NULL,
            created_at TEXT NOT NULL, responded_at TEXT
        );
        CREATE UNIQUE INDEX IF NOT EXISTS invite_pending
            ON invites(game_id,account_id) WHERE status='pending';
        CREATE INDEX IF NOT EXISTS invite_account ON invites(account_id,status);
        """)


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
    if not row:
        return None
    game = json.loads(row["state"])
    from .game.state import upgrade_game

    upgrade_game(game)
    return game

def current_game_id(db):
    row = db.execute("SELECT id FROM games ORDER BY rowid DESC LIMIT 1").fetchone()
    return row["id"] if row else None


def save_game(db, game):
    db.execute(
        "UPDATE games SET state=?,version=?,status=? WHERE id=?",
        (dumps(game), game["version"], game["status"], game["id"]),
    )

def purge(db):
    """Clear game data without touching global accounts or login tokens."""
    for table in ("messages", "evidence", "channels", "participants", "invites", "games"):
        db.execute(f"DELETE FROM {table}")


INVITE_MINUTES = 10


def invite_cutoff():
    """待处理邀请的有效下界；过期不写库，读取时按时间过滤。"""
    return (datetime.now(timezone.utc) - timedelta(minutes=INVITE_MINUTES)).isoformat()


def pending_invites(db, account_id):
    """该账号的待处理邀请，附带对局状态；对局已结束的邀请直接作废。"""
    return list(
        db.execute(
            """SELECT i.* FROM invites i JOIN games g ON g.id=i.game_id
               WHERE i.account_id=? AND i.status='pending' AND i.created_at>=?
                 AND g.status!='ended' ORDER BY i.created_at""",
            (account_id, invite_cutoff()),
        )
    )

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
                channel_id=event.get("channel_id", "public" if audience is None else "information"),
                sender_id=event.get("sender_id", "host"),
                sender_name=event.get("sender_name", "主持人"),
                avatar_role_id=event.get("avatar_role_id", "host"),
            )
        )
    return rows


def visible_message(row, actor):
    return (
        actor["kind"] == "host"
        or row["audience"] is None
        or bool(set(actor["access_ids"]).intersection(json.loads(row["audience"])))
    )


def message_view(row, actor):
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


def active_private_channel(db, game_id, participant_id):
    if participant_id == "host":
        return None
    return db.execute(
        """SELECT * FROM channels c WHERE c.game_id=? AND c.status='active'
           AND EXISTS (SELECT 1 FROM json_each(c.participant_ids) WHERE value=?)
           ORDER BY c.rowid LIMIT 1""",
        (game_id, participant_id),
    ).fetchone()


def channel_members(row):
    return json.loads(row["participant_ids"])


def channel_visible(row, actor):
    return actor["kind"] == "host" or actor["id"] in channel_members(row)


def channel_send_reason(db, game, actor, channel_id):
    if game["status"] == "ended":
        return "本局已经结束"
    participant = db.execute("SELECT muted FROM participants WHERE id=?", (actor["id"],)).fetchone()
    if participant and participant["muted"]:
        return "主持人已将你禁言"
    active = active_private_channel(db, game["id"], actor["id"])
    if actor["kind"] != "host" and active and channel_id != active["id"]:
        return "私信期间只能在当前私信频道发言"
    return ""


def messages(db, game_id, actor, *, before=None, after=None, channel_id=None, scope="all"):
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
        clauses.append("m.channel_id=?")
        args.append("information" if channel_id == "system" else channel_id)
    if scope == "public":
        clauses.append("m.kind='chat' AND m.channel_id='public'")
    elif scope == "private":
        clauses.append("m.kind='chat' AND m.channel_id!='public' AND m.channel_id!='information'")
    elif scope == "system":
        clauses.append("m.kind!='chat'")
    elif scope == "host":
        clauses.append(
            "m.kind='chat' AND m.channel_id!='public' AND EXISTS ("
            "SELECT 1 FROM channels c, json_each(c.participant_ids) e "
            "WHERE c.id=m.channel_id AND e.value='host')"
        )
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
    return {"messages": [message_view(row, actor) for row in rows], "has_more": more}
