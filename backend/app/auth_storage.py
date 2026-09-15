"""Independent QQ account, login challenge, and persistent token storage."""

import hashlib
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from . import storage

TOKEN_DAYS = 180
CHALLENGE_MINUTES = 5


def now():
    return datetime.now(timezone.utc)


def now_text():
    return now().isoformat()


def secret_hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@contextmanager
def connect():
    db = sqlite3.connect(storage.DATA_DIR / "auth.sqlite3", timeout=15)
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
        CREATE TABLE IF NOT EXISTS accounts (
            id TEXT PRIMARY KEY, qq_id TEXT NOT NULL UNIQUE,
            nickname TEXT NOT NULL, avatar_url TEXT NOT NULL,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS login_challenges (
            id TEXT PRIMARY KEY, code_hash TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL, account_id TEXT,
            client_kind TEXT NOT NULL DEFAULT 'web',
            expires_at TEXT NOT NULL, consumed_at TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS challenge_status ON login_challenges(status, expires_at);
        CREATE TABLE IF NOT EXISTS login_tokens (
            token_hash TEXT PRIMARY KEY, account_id TEXT,
            kind TEXT NOT NULL, expires_at TEXT NOT NULL,
            valid INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS token_account ON login_tokens(account_id, valid);
        """)
        if "client_kind" not in {
            row["name"] for row in db.execute("PRAGMA table_info(login_challenges)")
        }:
            db.execute(
                "ALTER TABLE login_challenges ADD COLUMN client_kind TEXT NOT NULL DEFAULT 'web'"
            )
        db.commit()


def issue_token(db, kind, account_id=None):
    token = secrets.token_urlsafe(32)
    db.execute(
        "INSERT INTO login_tokens(token_hash,account_id,kind,expires_at,created_at) VALUES(?,?,?,?,?)",
        (
            secret_hash(token),
            account_id,
            kind,
            (now() + timedelta(days=TOKEN_DAYS)).isoformat(),
            now_text(),
        ),
    )
    return token


def token_row(hashed):
    if not hashed:
        return None
    with connect() as db:
        return db.execute(
            "SELECT * FROM login_tokens WHERE token_hash=? AND valid=1 AND expires_at>?",
            (hashed, now_text()),
        ).fetchone()


def revoke(hashed):
    if not hashed:
        return
    with transaction() as db:
        db.execute("UPDATE login_tokens SET valid=0 WHERE token_hash=?", (hashed,))


def account(account_id):
    with connect() as db:
        return db.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()


def create_challenge(client_kind="web"):
    with transaction() as db:
        for _ in range(20):
            code = f"{secrets.randbelow(1_000_000):06d}"
            if not db.execute(
                "SELECT 1 FROM login_challenges WHERE code_hash=? AND expires_at>?",
                (secret_hash(code), now_text()),
            ).fetchone():
                break
        else:
            raise RuntimeError("无法生成登录码")
        challenge_id = secrets.token_urlsafe(18)
        expires_at = (now() + timedelta(minutes=CHALLENGE_MINUTES)).isoformat()
        db.execute(
            "INSERT INTO login_challenges(id,code_hash,status,client_kind,expires_at,created_at) VALUES(?,?,'pending',?,?,?)",
            (challenge_id, secret_hash(code), client_kind, expires_at, now_text()),
        )
    return {"id": challenge_id, "code": code, "expires_at": expires_at, "status": "pending"}


def complete_challenge(code, qq_id, nickname, avatar_url):
    with transaction() as db:
        challenge = db.execute(
            "SELECT * FROM login_challenges WHERE code_hash=? AND status='pending' AND expires_at>?",
            (secret_hash(code), now_text()),
        ).fetchone()
        if not challenge:
            return None
        existing = db.execute("SELECT id FROM accounts WHERE qq_id=?", (qq_id,)).fetchone()
        account_id = existing["id"] if existing else secrets.token_urlsafe(18)
        stamp = now_text()
        db.execute(
            """INSERT INTO accounts(id,qq_id,nickname,avatar_url,created_at,updated_at)
               VALUES(?,?,?,?,?,?) ON CONFLICT(qq_id) DO UPDATE SET
               nickname=excluded.nickname,avatar_url=excluded.avatar_url,updated_at=excluded.updated_at""",
            (account_id, qq_id, nickname, avatar_url, stamp, stamp),
        )
        changed = db.execute(
            "UPDATE login_challenges SET status='completed',account_id=? WHERE id=? AND status='pending'",
            (account_id, challenge["id"]),
        ).rowcount
        return challenge["id"] if changed else None


def poll_challenge(challenge_id, client_kind):
    with transaction() as db:
        row = db.execute("SELECT * FROM login_challenges WHERE id=?", (challenge_id,)).fetchone()
        if not row or row["client_kind"] != client_kind:
            return None, "missing"
        if row["consumed_at"]:
            return None, "consumed"
        if row["expires_at"] <= now_text() and row["status"] == "pending":
            db.execute("UPDATE login_challenges SET status='expired' WHERE id=?", (challenge_id,))
            return None, "expired"
        if row["status"] != "completed":
            return {"id": row["id"], "status": row["status"], "expires_at": row["expires_at"]}, None
        token = issue_token(db, "player", row["account_id"])
        db.execute("UPDATE login_challenges SET consumed_at=? WHERE id=?", (now_text(), challenge_id))
        account_row = db.execute("SELECT * FROM accounts WHERE id=?", (row["account_id"],)).fetchone()
        return {
            "id": row["id"],
            "status": "completed",
            "account": account_view(account_row),
            "token": token,
        }, None


def account_view(row):
    return {key: row[key] for key in ("id", "qq_id", "nickname", "avatar_url")}


def sync_accounts(members):
    stamp = now_text()
    with transaction() as db:
        for member in members:
            existing = db.execute("SELECT id FROM accounts WHERE qq_id=?", (member.qq_id,)).fetchone()
            account_id = existing["id"] if existing else secrets.token_urlsafe(18)
            db.execute(
                """INSERT INTO accounts(id,qq_id,nickname,avatar_url,created_at,updated_at)
                   VALUES(?,?,?,?,?,?) ON CONFLICT(qq_id) DO UPDATE SET
                   nickname=excluded.nickname,avatar_url=excluded.avatar_url,updated_at=excluded.updated_at""",
                (account_id, member.qq_id, member.nickname, member.avatar_url or "", stamp, stamp),
            )
    return len(members)
