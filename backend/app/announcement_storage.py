"""独立公告库：系统管理员发布的全服公告（markdown 正文）。

公告不属于任何一局，所以自成一个库（``data/announcements.sqlite3``）：建立新对局、
一键初始化、退出账号都不会影响它。发布与修改只有 5 级主持（系统管理员）能做。

客户端按每条公告的 sha256 在本地记录「已读」，服务端只负责给出稳定的哈希与一个
整体版本号；大厅轮询带上它们，客户端据此判断有没有更新。
"""

import hashlib
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from . import storage

TITLE_LIMIT = 60
BODY_LIMIT = 4000
# 一次下发多少条：公告是低频内容，取最新的一批即可。
LIST_LIMIT = 20


def now_text():
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connect():
    db = sqlite3.connect(storage.DATA_DIR / "announcements.sqlite3", timeout=15)
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
        CREATE TABLE IF NOT EXISTS announcements (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL,
            author_account_id TEXT NOT NULL DEFAULT '',
            author_name TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        """)
        db.commit()


def content_hash(announcement_id, title, body, updated_at):
    """客户端「已读」用的哈希：标题、正文或修改时间一变就算新内容。"""
    payload = f"{announcement_id}\n{title}\n{body}\n{updated_at}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def view(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "body": row["body"],
        "author_name": row["author_name"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "hash": content_hash(row["id"], row["title"], row["body"], row["updated_at"]),
    }


def announcements():
    """公告列表：最新发布的在前。"""
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM announcements ORDER BY created_at DESC"
        ).fetchall()
        return [view(row) for row in rows]


def announcement(announcement_id):
    with connect() as db:
        row = db.execute(
            "SELECT * FROM announcements WHERE id=?", (announcement_id,)
        ).fetchone()
        return view(row) if row else None


def create(title, body, author_account_id="", author_name=""):
    stamp = now_text()
    announcement_id = "note-" + secrets.token_urlsafe(12)
    with transaction() as db:
        db.execute(
            """INSERT INTO announcements
               (id,title,body,author_account_id,author_name,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?)""",
            (announcement_id, title, body, author_account_id, author_name, stamp, stamp),
        )
    return announcement(announcement_id)


def update(announcement_id, title, body):
    with transaction() as db:
        changed = db.execute(
            "UPDATE announcements SET title=?,body=?,updated_at=? WHERE id=?",
            (title, body, now_text(), announcement_id),
        ).rowcount
    return announcement(announcement_id) if changed else None


def delete(announcement_id):
    with transaction() as db:
        return bool(
            db.execute("DELETE FROM announcements WHERE id=?", (announcement_id,)).rowcount
        )


def version(items):
    """整体版本号：任一条公告新增、修改或删除都会变。"""
    payload = "\n".join(f"{item['id']}:{item['hash']}" for item in items)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def lobby_payload():
    """大厅轮询顺带下发的公告数据：最新的若干条 + 整体版本号。"""
    items = announcements()
    return {"announcements": items[:LIST_LIMIT], "announcements_version": version(items)}
