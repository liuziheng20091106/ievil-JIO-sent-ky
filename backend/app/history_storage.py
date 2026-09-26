"""独立历史对局库：已结束（或未结束就被清空）的对局留档。

历史不属于任何一局，所以自成一个库（``data/history.sqlite3``）：建立新对局、一键初始化
都会清空对局库（``storage.purge``），但这里的记录不会被牵动。存的是**公开记录**：
胜负与裁定说明、七个席位的两张角色牌、参与身份，以及公屏聊天与全场公告的时间线。
私信频道的对话、只发给个人的情报（``audience`` 定向）与证物图片都不入库——设计稿
要求「不默认披露全部私聊」。

写入是尽力而为：它发生在对局事务提交**之后**（两个 SQLite 文件之间没有跨库事务），
失败只丢这一条历史，不阻断任何游戏命令；清空对局前的补录（见 ``api.reset`` /
``api.create``）会按 ``matches.id`` 幂等地把它补上。
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from . import storage
from .game.state import display_player_name, host_label

# 一局最多归档多少条公开消息：只取最近的一批，长对局不会无限膨胀。
EVENT_LIMIT = 400
# 列表接口一页最多几条。
PAGE_LIMIT = 50
DEFAULT_PAGE = 20


def now_text():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect():
    db = sqlite3.connect(storage.DATA_DIR / "history.sqlite3", timeout=15)
    db.row_factory = sqlite3.Row
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


def initialize():
    storage.DATA_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS matches (
            id TEXT PRIMARY KEY, ended_at TEXT NOT NULL, recorded_at TEXT NOT NULL,
            day INTEGER NOT NULL, half TEXT NOT NULL DEFAULT '', phase TEXT NOT NULL DEFAULT '',
            winner TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL, host_name TEXT NOT NULL DEFAULT '',
            personal_losses TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE IF NOT EXISTS match_players (
            match_id TEXT NOT NULL REFERENCES matches(id), participant_id TEXT NOT NULL,
            account_id TEXT, name TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'player',
            seat_id TEXT, role_ids TEXT NOT NULL DEFAULT '[]',
            active INTEGER NOT NULL DEFAULT 1, blocked INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (match_id, participant_id)
        );
        CREATE TABLE IF NOT EXISTS match_events (
            match_id TEXT NOT NULL REFERENCES matches(id), seq INTEGER NOT NULL,
            kind TEXT NOT NULL, sender_name TEXT NOT NULL DEFAULT '', avatar_role_id TEXT,
            text TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
            PRIMARY KEY (match_id, seq)
        );
        """)
        db.commit()


def _dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(value, fallback):
    try:
        return json.loads(value) if value else fallback
    except (TypeError, ValueError):
        return fallback


def archived_events(db, game_id):
    """从对局库挑出可以留档的公开消息：公屏聊天 + 全场公告。

    只放行 ``kind='chat' AND channel_id='public'`` 与 ``audience IS NULL`` 的非聊天消息，
    因此私信、观战频道、``audience`` 定向的私密情报与连接状态都不会进来。
    """
    rows = db.execute(
        """SELECT kind,sender_name,avatar_role_id,text,created_at FROM messages
           WHERE game_id=? AND kind!='presence'
             AND ((kind='chat' AND channel_id='public')
                  OR (kind!='chat' AND audience IS NULL))
           ORDER BY id DESC LIMIT ?""",
        (game_id, EVENT_LIMIT),
    ).fetchall()
    return [dict(row) for row in reversed(rows)]


def snapshot(game_db, game_id):
    """在对局事务内取一份脱离连接的快照：参与身份 + 可留档的公开消息。

    留档本身要等对局事务提交之后才写（两个 SQLite 文件没有跨库事务），而清空对局
    （``storage.purge``）会把参与身份与消息一起删掉，所以必须先在事务里快照下来。
    """
    rows = game_db.execute(
        "SELECT * FROM participants WHERE game_id=? ORDER BY rowid", (game_id,)
    ).fetchall()
    return {
        "players": [dict(row) for row in rows],
        "events": archived_events(game_db, game_id),
    }


def record(game, source, snap=None):
    """把一个对局写入历史；同一对局重复调用不会产生第二条。返回是否新写入。"""
    match_id = game.get("id")
    if not match_id:
        return False
    snap = snap or {"players": [], "events": []}
    result = game.get("result") or {}
    stamp = now_text()
    seats = {seat["id"]: seat for seat in game.get("seats", [])}
    with transaction() as db:
        inserted = db.execute(
            """INSERT OR IGNORE INTO matches
               (id,ended_at,recorded_at,day,half,phase,winner,reason,source,host_name,personal_losses)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (
                match_id,
                stamp,
                stamp,
                int(game.get("day") or 0),
                str(game.get("half") or ""),
                str(game.get("phase") or ""),
                str(result.get("winner") or ""),
                str(result.get("reason") or ""),
                source,
                host_label(game),
                _dumps(result.get("personal_losses") or []),
            ),
        ).rowcount
        if not inserted:
            return False
        for row in snap.get("players", []):
            seat = seats.get(row["seat_id"]) if row["seat_id"] else None
            db.execute(
                """INSERT OR REPLACE INTO match_players
                   (match_id,participant_id,account_id,name,kind,seat_id,role_ids,active,blocked)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    match_id,
                    row["id"],
                    row["account_id"],
                    row["name"],
                    row["kind"],
                    row["seat_id"],
                    _dumps(list((seat or {}).get("cards") or [])),
                    int(row["active"]),
                    int(row["blocked"]),
                ),
            )
        for seq, row in enumerate(snap.get("events", [])):
            db.execute(
                """INSERT OR REPLACE INTO match_events
                   (match_id,seq,kind,sender_name,avatar_role_id,text,created_at)
                   VALUES(?,?,?,?,?,?,?)""",
                (
                    match_id,
                    seq,
                    row["kind"],
                    row["sender_name"],
                    row["avatar_role_id"],
                    row["text"],
                    row["created_at"],
                ),
            )
    return True


def record_known(game_db, game_ids):
    """按对局 id 留档：对局与参与身份还在库里时调用。

    结束对局的补写（api.command）走这里；已经清空的对局查不到，直接跳过——那种情况
    由 :func:`archive_pending` 在删除之前兜住。
    """
    recorded = 0
    for game_id in game_ids:
        game = storage.load_game(game_db, game_id)
        if not game:
            continue
        source = "ended" if game.get("status") == "ended" else "aborted"
        if record(game, source, snapshot(game_db, game_id)):
            recorded += 1
    return recorded


def archive_pending(game_db):
    """清空对局库之前的兜底：把库里还没留档的对局先记进历史。

    ``storage.purge`` 会删掉 games / participants / messages，删掉之后谁也还原不出来，
    所以留档必须在删除之前完成。历史是独立文件，这里立即提交；对局 id 幂等，已经
    记过的局不会产生第二条。
    """
    return record_known(
        game_db, [row["id"] for row in game_db.execute("SELECT id FROM games")]
    )


def delete(match_id):
    """删除一条历史对局（连同参与身份与公开时间线）。不存在时返回 False。

    4 级及以上主持人的维护操作：历史是独立库，删除只动这里的三张表，与对局库无关。
    """
    with transaction() as db:
        deleted = db.execute("DELETE FROM matches WHERE id=?", (match_id,)).rowcount
        if not deleted:
            return False
        db.execute("DELETE FROM match_players WHERE match_id=?", (match_id,))
        db.execute("DELETE FROM match_events WHERE match_id=?", (match_id,))
    return True


def _match_row(row):
    return {
        "id": row["id"],
        "ended_at": row["ended_at"],
        "day": int(row["day"]),
        "winner": row["winner"],
        "reason": row["reason"],
        "source": row["source"],
        "host_name": display_player_name(row["host_name"]),
        "personal_losses": _loads(row["personal_losses"], []),
    }


def matches(limit=DEFAULT_PAGE, before=None):
    """已归档的对局：最近结束的在前，``before`` 是上一页最后一条的 ended_at。"""
    limit = max(1, min(int(limit), PAGE_LIMIT))
    clauses, args = [], []
    if before:
        clauses.append("ended_at < ?")
        args.append(before)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with connect() as db:
        rows = db.execute(
            f"SELECT * FROM matches{where} ORDER BY ended_at DESC, rowid DESC LIMIT ?",
            (*args, limit + 1),
        ).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        players = players_by_match(db, [row["id"] for row in rows])
    listed = []
    for row in rows:
        item = _match_row(row)
        item["players"] = players.get(row["id"], [])
        item["player_count"] = len(item["players"])
        listed.append(item)
    return {"matches": listed, "has_more": has_more}


def players_by_match(db, match_ids):
    if not match_ids:
        return {}
    placeholders = ",".join("?" for _ in match_ids)
    grouped = {}
    for row in db.execute(
        f"SELECT * FROM match_players WHERE match_id IN ({placeholders}) ORDER BY rowid",
        match_ids,
    ):
        grouped.setdefault(row["match_id"], []).append(_player_row(row))
    return grouped


def _player_row(row):
    return {
        "participant_id": row["participant_id"],
        "account_id": row["account_id"],
        "name": display_player_name(row["name"]),
        "kind": row["kind"],
        "seat_id": row["seat_id"],
        "role_ids": _loads(row["role_ids"], []),
        "active": bool(row["active"]),
        "blocked": bool(row["blocked"]),
    }


def match(match_id):
    """单局详情：结算、参与身份与公开时间线；不存在时返回 None。"""
    with connect() as db:
        row = db.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
        if not row:
            return None
        detail = _match_row(row)
        detail["players"] = [
            _player_row(item)
            for item in db.execute(
                "SELECT * FROM match_players WHERE match_id=? ORDER BY rowid", (match_id,)
            )
        ]
        detail["events"] = [
            {
                "seq": int(item["seq"]),
                "kind": item["kind"],
                "sender_name": display_player_name(item["sender_name"]),
                "avatar_role_id": item["avatar_role_id"],
                "text": item["text"],
                "created_at": item["created_at"],
            }
            for item in db.execute(
                "SELECT * FROM match_events WHERE match_id=? ORDER BY seq", (match_id,)
            )
        ]
    return detail
