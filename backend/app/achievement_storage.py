"""Independent achievement definitions, grants, and player-owned display.

成就与七双对局规则无关，所以自成一个库（``data/achievements.sqlite3``）：主持人自定义
成就（名称 / 内容 / 稀有度 1-10），再把它授权给某个账号；玩家可独立选择一个成就
佩戴，以及最多五个优先展示的成就，摘要不足五个时按真实稀有度补齐。

独立的意义：建立新对局会清空对局库（``storage.purge``），但定义、授权、佩戴与优先展示
不会被牵动；账号库（``auth.sqlite3``）只用来给列表补充最新昵称与头像，缺了也能靠本库
里的昵称快照照常显示。
"""

import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, UTC

from . import storage

# 稀有度只有 1-10 十档，颜色由客户端按档位取。
MAX_RARITY = 10


def now_text():
    return datetime.now(UTC).isoformat()


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
            priority_position INTEGER,
            UNIQUE(account_id, achievement_id)
        );
        CREATE INDEX IF NOT EXISTS grant_account ON grants(account_id);
        CREATE INDEX IF NOT EXISTS grant_achievement ON grants(achievement_id);
        CREATE TABLE IF NOT EXISTS players (
            account_id TEXT PRIMARY KEY, nickname TEXT NOT NULL DEFAULT '',
            equipped_grant_id TEXT, last_played_at TEXT, updated_at TEXT NOT NULL
        );
        """)
        if "priority_position" not in {
            row["name"] for row in db.execute("PRAGMA table_info(grants)")
        }:
            db.execute("ALTER TABLE grants ADD COLUMN priority_position INTEGER")
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
        deleted = db.execute("DELETE FROM achievements WHERE id=?", (achievement_id,)).rowcount
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
        if not db.execute("SELECT 1 FROM achievements WHERE id=?", (achievement_id,)).fetchone():
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


def grant_by_id(grant_id):
    with connect() as db:
        row = _grant_row(db, grant_id)
        return grant_view(row) if row else None


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
    """优先选择在前，再按真实稀有度与获得时间补齐头像摘要。"""
    with connect() as db:
        rows = db.execute(
            """SELECT g.id,g.account_id,g.achievement_id,g.granted_at,a.name,a.detail,a.rarity
               FROM grants g JOIN achievements a ON a.id=g.achievement_id
               WHERE g.account_id=?
               ORDER BY g.priority_position IS NULL, g.priority_position,
                        a.rarity DESC, g.granted_at DESC LIMIT ?""",
            (account_id, limit),
        ).fetchall()
        return [grant_view(row) for row in rows]


def priority_grant_ids(account_id):
    """账号当前有效的优先展示授权，按玩家选择顺序返回。"""
    with connect() as db:
        return [
            row["id"]
            for row in db.execute(
                """SELECT g.id FROM grants g JOIN achievements a ON a.id=g.achievement_id
                   WHERE g.account_id=? AND g.priority_position IS NOT NULL
                   ORDER BY g.priority_position""",
                (account_id,),
            )
        ]


def set_priority_grants(account_id, grant_ids):
    """原子替换优先展示；先验证全部授权归属，失败时保留原选择。"""
    with transaction() as db:
        if grant_ids:
            placeholders = ",".join("?" for _ in grant_ids)
            owned = db.execute(
                f"""SELECT COUNT(*) FROM grants g JOIN achievements a ON a.id=g.achievement_id
                    WHERE g.account_id=? AND g.id IN ({placeholders})""",
                (account_id, *grant_ids),
            ).fetchone()[0]
            if owned != len(grant_ids):
                return False
        db.execute("UPDATE grants SET priority_position=NULL WHERE account_id=?", (account_id,))
        db.executemany(
            "UPDATE grants SET priority_position=? WHERE id=? AND account_id=?",
            ((position, grant_id, account_id) for position, grant_id in enumerate(grant_ids)),
        )
        return True


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
