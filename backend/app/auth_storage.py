"""Independent QQ account, login challenge, persistent token, and host authorization."""

import hashlib
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from . import storage

TOKEN_DAYS = 180
CHALLENGE_MINUTES = 5

# 过期登录码的宽限期：登录码本身只活 5 分钟，但「已经扫完码、客户端晚一点才来取令牌」
# 还会用到它，所以过期后先留一天再清，别让晚到的轮询拿到 410。
CHALLENGE_GRACE_HOURS = 24

# 主持等级：1 级只主持 1 局，5 级是系统管理员。等级本身由服务端判定，
# 客户端只按等级显示入口。
HOST_LEVEL_MIN = 1
HOST_LEVEL_MAX = 5

# 各级主持可授权/取消的最高等级；不在表里的等级没有授权他人的权限。
HOST_GRANT_LIMITS = {4: 3, 5: 5}

# 各级主持可定义与分发的成就最高稀有度（1-10）；1-2 级不能碰成就。
HOST_ACHIEVEMENT_LIMITS = {3: 3, 4: 4, 5: 10}


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
        CREATE TABLE IF NOT EXISTS host_authorizations (
            account_id TEXT PRIMARY KEY, level INTEGER NOT NULL,
            granted_by TEXT NOT NULL DEFAULT '', granted_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, hosted_game_id TEXT, consumed_at TEXT
        );
        """)
        if "client_kind" not in {
            row["name"] for row in db.execute("PRAGMA table_info(login_challenges)")
        }:
            db.execute(
                "ALTER TABLE login_challenges ADD COLUMN client_kind TEXT NOT NULL DEFAULT 'web'"
            )
        db.commit()
    cleanup()


def cleanup():
    """清掉不可能再被用到的登录码与令牌，返回各自删掉的行数。

    登录挑战和令牌从不失效删除，只有轮询到的那一条会顺手标成过期，所以时间一长
    库里全是死行。启动时清一次，只删三类确定无用的记录：已经换出过令牌的登录码
    （consumed_at 已置位，再轮询本来也只会得到 410）、过期超过宽限期的登录码、
    以及已撤销或已过期的令牌。未过期的令牌与宽限期内的登录码一律保留。
    """
    cutoff = (now() - timedelta(hours=CHALLENGE_GRACE_HOURS)).isoformat()
    with transaction() as db:
        challenges = db.execute(
            "DELETE FROM login_challenges WHERE consumed_at IS NOT NULL OR expires_at<=?",
            (cutoff,),
        ).rowcount
        tokens = db.execute(
            "DELETE FROM login_tokens WHERE valid=0 OR expires_at<=?", (now_text(),)
        ).rowcount
    return {"challenges": challenges, "tokens": tokens}


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


def account_by_qq(qq_id):
    if not qq_id:
        return None
    with connect() as db:
        return db.execute("SELECT * FROM accounts WHERE qq_id=?", (qq_id,)).fetchone()


def accounts_matching(query="", limit=30):
    """按昵称或 QQ 号搜索账号：主持授权页用它挑人（其余名单仍不含 QQ 号）。"""
    text = (query or "").strip()
    with connect() as db:
        if text:
            like = f"%{text}%"
            rows = db.execute(
                """SELECT * FROM accounts WHERE nickname LIKE ? OR qq_id LIKE ?
                   ORDER BY updated_at DESC LIMIT ?""",
                (like, like, limit),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM accounts ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]


def host_authorization(account_id):
    if not account_id:
        return None
    with connect() as db:
        row = db.execute(
            "SELECT * FROM host_authorizations WHERE account_id=?", (account_id,)
        ).fetchone()
        return dict(row) if row else None


def host_level(account_id):
    """授权表里的有效等级；1 级主持完一局（consumed_at 置位）后为 0。"""
    row = host_authorization(account_id)
    if not row or row["consumed_at"]:
        return 0
    return int(row["level"])


def host_authorizations():
    with connect() as db:
        return [dict(row) for row in db.execute("SELECT * FROM host_authorizations")]


def authorize_host(account_id, level, granted_by=""):
    """授权或改级；重新授权会清掉「一局已用完」，重新给一次机会。"""
    stamp = now_text()
    with transaction() as db:
        db.execute(
            """INSERT INTO host_authorizations
               (account_id,level,granted_by,granted_at,updated_at,hosted_game_id,consumed_at)
               VALUES(?,?,?,?,?,NULL,NULL)
               ON CONFLICT(account_id) DO UPDATE SET
               level=excluded.level, granted_by=excluded.granted_by,
               granted_at=excluded.granted_at, updated_at=excluded.updated_at,
               hosted_game_id=NULL, consumed_at=NULL""",
            (account_id, int(level), granted_by, stamp, stamp),
        )
    return host_authorization(account_id)


def revoke_host(account_id):
    with transaction() as db:
        removed = db.execute(
            "DELETE FROM host_authorizations WHERE account_id=?", (account_id,)
        ).rowcount
    return bool(removed)


def mark_hosted_game(account_id, game_id):
    """记下这一局由谁建立：1 级授权在他主持的这一局结束时作废。"""
    if not account_id:
        return
    with transaction() as db:
        db.execute(
            "UPDATE host_authorizations SET hosted_game_id=?, updated_at=? WHERE account_id=?",
            (game_id, now_text(), account_id),
        )


def consume_single_use_for_game(game_id):
    """局终（或对局被清空）时让该局的 1 级授权立即失效。"""
    if not game_id:
        return 0
    stamp = now_text()
    with transaction() as db:
        return db.execute(
            """UPDATE host_authorizations SET consumed_at=?, updated_at=?
               WHERE hosted_game_id=? AND level<? AND consumed_at IS NULL""",
            (stamp, stamp, game_id, 2),
        ).rowcount


def challenge_account(challenge_id):
    """挑战已绑定的账号 id；还没完成绑定时为 None。"""
    with connect() as db:
        row = db.execute(
            "SELECT account_id FROM login_challenges WHERE id=?", (challenge_id,)
        ).fetchone()
        return row["account_id"] if row else None


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


def poll_challenge(challenge_id, client_kind, kind="player"):
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
        token = issue_token(db, kind, row["account_id"])
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
