"""Independent achievement definitions, grants, and equipped display.

成就与七双对局规则无关，所以自成一个库（``data/achievements.sqlite3``）：主持人自定义
成就（名称 / 内容 / 稀有度 1-10），再把它授权给某个账号；玩家在自己获得的成就里挑一个
佩戴，对局内其他人才看得到。

独立的意义：建立新对局会清空对局库（``storage.purge``），但这里的定义、授权与佩戴记录
不会被牵动；账号库（``auth.sqlite3``）只用来给列表补充最新昵称与头像，缺了也能靠本库
里的昵称快照照常显示。
"""

import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from . import storage

# 稀有度只有 1-10 十档，颜色由客户端按档位取。
MAX_RARITY = 10


def now_text():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect():
    db = sqlite3.connect(storage.DATA_DIR / "achievements.sqlite3", timeout=15)
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
        CREATE TABLE IF NOT EXISTS achievements (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, detail TEXT NOT NULL,
            rarity INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS grants (
            id TEXT PRIMARY KEY,
            account_id TEXT NOT NULL,
            achievement_id TEXT NOT NULL REFERENCES achievements(id),
            granted_at TEXT NOT NULL,
            UNIQUE(account_id, achievement_id)
        );
        CREATE INDEX IF NOT EXISTS grant_account ON grants(account_id);
        CREATE INDEX IF NOT EXISTS grant_achievement ON grants(achievement_id);
        CREATE TABLE IF NOT EXISTS players (
            account_id TEXT PRIMARY KEY, nickname TEXT NOT NULL DEFAULT '',
            equipped_grant_id TEXT, last_played_at TEXT, updated_at TEXT NOT NULL
        );
        """)
        db.commit()


def definition_view(row, granted_count=0):
    return {
        "id": row["id"],
        "name": row["name"],
        "detail": row["detail"],
        "rarity": int(row["rarity"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "granted_count": granted_count,
    }


def grant_view(row):
    return {
        "id": row["id"],
        "account_id": row["account_id"],
        "achievement_id": row["achievement_id"],
        "name": row["name"],
        "detail": row["detail"],
        "rarity": int(row["rarity"]),
        "granted_at": row["granted_at"],
    }


def fitted(value, limit):
    """按字符数裁剪长文本：昵称快照超出上限时截断，不让列表接口失败。"""
    text = (value or "").strip()
    return text[:limit]


def definitions():
    """全部成就定义：稀有度高的在前，同档按创建时间新的在前。"""
    with connect() as db:
        counts = {
            row["achievement_id"]: row["n"]
            for row in db.execute(
                "SELECT achievement_id, COUNT(*) AS n FROM grants GROUP BY achievement_id"
            )
        }
        rows = db.execute(
            "SELECT * FROM achievements ORDER BY rarity DESC, created_at DESC"
        ).fetchall()
        return [definition_view(row, counts.get(row["id"], 0)) for row in rows]


def definition(achievement_id):
    with connect() as db:
        row = db.execute("SELECT * FROM achievements WHERE id=?", (achievement_id,)).fetchone()
        return definition_view(row) if row else None


def create_definition(name, detail, rarity):
    stamp = now_text()
    achievement_id = "ach-" + secrets.token_urlsafe(12)
    with transaction() as db:
        db.execute(
            """INSERT INTO achievements(id,name,detail,rarity,created_at,updated_at)
               VALUES(?,?,?,?,?,?)""",
            (achievement_id, name, detail, rarity, stamp, stamp),
        )
    return definition(achievement_id)


def update_definition(achievement_id, name, detail, rarity):
    with transaction() as db:
        changed = db.execute(
            """UPDATE achievements SET name=?,detail=?,rarity=?,updated_at=?
               WHERE id=?""",
            (name, detail, rarity, now_text(), achievement_id),
        ).rowcount
    return definition(achievement_id) if changed else None


def delete_definition(achievement_id):
    """删除定义：连同已授权记录一起删（界面会先提示已授予多少人）。"""
    with transaction() as db:
        removed = db.execute(
            "SELECT COUNT(*) AS n FROM grants WHERE achievement_id=?", (achievement_id,)
        ).fetchone()["n"]
        db.execute(
            """UPDATE players SET equipped_grant_id=NULL, updated_at=?
               WHERE equipped_grant_id IN (SELECT id FROM grants WHERE achievement_id=?)""",
            (now_text(), achievement_id),
        )
        db.execute("DELETE FROM grants WHERE achievement_id=?", (achievement_id,))
        deleted = db.execute(
            "DELETE FROM achievements WHERE id=?", (achievement_id,)
        ).rowcount
    return {"deleted": bool(deleted), "removed_grants": removed}


def ensure_player(db, account_id, nickname=""):
    stamp = now_text()
    db.execute(
        """INSERT INTO players(account_id,nickname,updated_at) VALUES(?,?,?)
           ON CONFLICT(account_id) DO UPDATE SET
           nickname=CASE WHEN excluded.nickname!='' THEN excluded.nickname ELSE players.nickname END,
           updated_at=excluded.updated_at""",
        (account_id, fitted(nickname, 64), stamp),
    )


def grant(account_id, achievement_id, nickname=""):
    """授权：同一玩家同一个成就只记一次；返回 None 表示定义不存在或已经获得过。"""
    stamp = now_text()
    grant_id = "grant-" + secrets.token_urlsafe(12)
    with transaction() as db:
        if not db.execute(
            "SELECT 1 FROM achievements WHERE id=?", (achievement_id,)
        ).fetchone():
            return None
        if db.execute(
            "SELECT 1 FROM grants WHERE account_id=? AND achievement_id=?",
            (account_id, achievement_id),
        ).fetchone():
            return None
        ensure_player(db, account_id, nickname)
        db.execute(
            "INSERT INTO grants(id,account_id,achievement_id,granted_at) VALUES(?,?,?,?)",
            (grant_id, account_id, achievement_id, stamp),
        )
        row = _grant_row(db, grant_id)
        return grant_view(row) if row else None


def _grant_row(db, grant_id):
    return db.execute(
        """SELECT g.id,g.account_id,g.achievement_id,g.granted_at,a.name,a.detail,a.rarity
           FROM grants g JOIN achievements a ON a.id=g.achievement_id WHERE g.id=?""",
        (grant_id,),
    ).fetchone()


def revoke(grant_id):
    with transaction() as db:
        row = db.execute("SELECT account_id FROM grants WHERE id=?", (grant_id,)).fetchone()
        if not row:
            return False
        db.execute(
            "UPDATE players SET equipped_grant_id=NULL, updated_at=? WHERE equipped_grant_id=?",
            (now_text(), grant_id),
        )
        db.execute("DELETE FROM grants WHERE id=?", (grant_id,))
        return True


def grants_for(account_id):
    """某账号获得的全部成就：稀有度高的在前，同档按获得时间新的在前。"""
    with connect() as db:
        rows = db.execute(
            """SELECT g.id,g.account_id,g.achievement_id,g.granted_at,a.name,a.detail,a.rarity
               FROM grants g JOIN achievements a ON a.id=g.achievement_id
               WHERE g.account_id=? ORDER BY a.rarity DESC, g.granted_at DESC""",
            (account_id,),
        ).fetchall()
        return [grant_view(row) for row in rows]


def top_grants(account_id, limit=5):
    """最稀有的前几个成就（头像摘要只给这一部分）。"""
    return grants_for(account_id)[:limit]


def equipped(account_id):
    """当前佩戴的成就；没佩戴或指向已撤销的记录时返回 None。"""
    if not account_id:
        return None
    with connect() as db:
        row = db.execute(
            """SELECT g.id,a.name,a.rarity FROM players p
               JOIN grants g ON g.id=p.equipped_grant_id
               JOIN achievements a ON a.id=g.achievement_id
               WHERE p.account_id=?""",
            (account_id,),
        ).fetchone()
        if not row:
            return None
        return {"id": row["id"], "name": row["name"], "rarity": int(row["rarity"])}


def equip(account_id, grant_id):
    """佩戴/取消佩戴；只能佩戴自己名下的记录，否则返回 False。"""
    with transaction() as db:
        ensure_player(db, account_id)
        if grant_id is None:
            db.execute(
                "UPDATE players SET equipped_grant_id=NULL, updated_at=? WHERE account_id=?",
                (now_text(), account_id),
            )
            return True
        owned = db.execute(
            "SELECT 1 FROM grants WHERE id=? AND account_id=?", (grant_id, account_id)
        ).fetchone()
        if not owned:
            return False
        db.execute(
            "UPDATE players SET equipped_grant_id=?, updated_at=? WHERE account_id=?",
            (grant_id, now_text(), account_id),
        )
        return True


def touch_played(account_id, nickname=""):
    """记一次参赛：玩家列表按这一列倒序排。"""
    if not account_id:
        return
    stamp = now_text()
    with transaction() as db:
        db.execute(
            """INSERT INTO players(account_id,nickname,last_played_at,updated_at)
               VALUES(?,?,?,?) ON CONFLICT(account_id) DO UPDATE SET
               nickname=CASE WHEN excluded.nickname!='' THEN excluded.nickname ELSE players.nickname END,
               last_played_at=excluded.last_played_at, updated_at=excluded.updated_at""",
            (account_id, fitted(nickname, 64), stamp, stamp),
        )


def player_rows():
    """账号 → 成就数、佩戴、最近参赛时间；只含参加过对局或获得过成就的账号。"""
    with connect() as db:
        rows = db.execute("SELECT * FROM players").fetchall()
        counts = {
            row["account_id"]: row["n"]
            for row in db.execute(
                "SELECT account_id, COUNT(*) AS n FROM grants GROUP BY account_id"
            )
        }
        equipped_map = {
            row["account_id"]: {
                "id": row["id"],
                "name": row["name"],
                "rarity": int(row["rarity"]),
            }
            for row in db.execute(
                """SELECT p.account_id,g.id,a.name,a.rarity FROM players p
                   JOIN grants g ON g.id=p.equipped_grant_id
                   JOIN achievements a ON a.id=g.achievement_id"""
            )
        }
    return [
        {
            "account_id": row["account_id"],
            "nickname": row["nickname"],
            "last_played_at": row["last_played_at"],
            "achievement_count": counts.get(row["account_id"], 0),
            "equipped": equipped_map.get(row["account_id"]),
        }
        for row in rows
    ]


def player_row(account_id):
    with connect() as db:
        row = db.execute("SELECT * FROM players WHERE account_id=?", (account_id,)).fetchone()
        return dict(row) if row else None
