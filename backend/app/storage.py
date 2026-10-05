"""SQLite state and audience-scoped message history."""

import json
import logging
import os
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, UTC
from pathlib import Path

from .game.catalog import night_half
from .game.state import display_player_name, host_capable, participant_eliminated

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("GAME_DATA_DIR", PROJECT_ROOT / "data")).resolve()

logger = logging.getLogger(__name__)


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
            audience TEXT, image_id TEXT, payload TEXT, recalled_at TEXT,
            reference_title TEXT, mention_ids TEXT NOT NULL DEFAULT '[]', channel_seat_ids TEXT
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
        message_columns = {row["name"] for row in db.execute("PRAGMA table_info(messages)")}
        if message_columns and "payload" not in message_columns:
            # 结构化播报（技能名/目标/介绍）存在这一列里：旧库补列，读取时按可见范围裁剪。
            db.execute("ALTER TABLE messages ADD COLUMN payload TEXT")
        if "recalled_at" not in message_columns:
            db.execute("ALTER TABLE messages ADD COLUMN recalled_at TEXT")
        if "mention_ids" not in message_columns:
            db.execute("ALTER TABLE messages ADD COLUMN mention_ids TEXT NOT NULL DEFAULT '[]'")
        if "reference_title" not in message_columns:
            db.execute("ALTER TABLE messages ADD COLUMN reference_title TEXT")
        if "channel_seat_ids" not in message_columns:
            db.execute("ALTER TABLE messages ADD COLUMN channel_seat_ids TEXT")
            for row in db.execute(
                "SELECT m.id,m.game_id,COALESCE(m.audience,c.participant_ids) AS members "
                "FROM messages m LEFT JOIN channels c ON c.id=m.channel_id AND c.game_id=m.game_id "
                "WHERE m.kind='chat' AND m.channel_id NOT IN ('public','spectator','information','system')"
            ).fetchall():
                db.execute(
                    "UPDATE messages SET channel_seat_ids=? WHERE id=?",
                    (
                        dumps(
                            _channel_seat_ids(
                                db, row["game_id"], json.loads(row["members"] or "[]")
                            )
                        ),
                        row["id"],
                    ),
                )
        # 原游戏没有成就设计：清掉历史对局里残留的占位字段，免得状态查看器继续显示它。
        for row in db.execute("SELECT id,state FROM games").fetchall():
            state = json.loads(row["state"])
            public = state.get("public")
            if isinstance(public, dict) and "achievements_enabled" in public:
                public.pop("achievements_enabled")
                db.execute("UPDATE games SET state=? WHERE id=?", (dumps(state), row["id"]))
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
    return datetime.now(UTC).isoformat()


def load_game(db, game_id):
    row = db.execute("SELECT state FROM games WHERE id=?", (game_id,)).fetchone()
    if not row:
        return None
    game = json.loads(row["state"])
    from .game.state import upgrade_game
    from .game.plugins import require_compatible

    missing_phase_start = "phase_started_at" not in game.get("public", {})
    upgrade_game(game)
    require_compatible(game)
    if missing_phase_start:
        # 普通读取也要持久化旧局的安全起点；已有写事务交给调用方统一提交。
        in_transaction = db.in_transaction
        save_game(db, game)
        if not in_transaction:
            db.commit()
    return game


def current_game_id(db):
    row = db.execute("SELECT id FROM games ORDER BY rowid DESC LIMIT 1").fetchone()
    return row["id"] if row else None


def host_entered(db, game_id, account_id):
    """该账号是否已确认进入这一局的管理界面。

    未确认的主持人只拿到最窄的观察者投影（主持级判据见
    :func:`backend.app.game.state.host_capable`），所以每个请求都要核一次。
    """
    if not game_id or not account_id:
        return False
    game = load_game(db, game_id)
    return bool(game) and account_id in set(game.get("host_entries") or [])


def save_game(db, game):
    db.execute(
        "UPDATE games SET state=?,version=?,status=? WHERE id=?",
        (dumps(game), game["version"], game["status"], game["id"]),
    )


def purge(db):
    """Clear game data without touching global accounts or login tokens."""
    # 对局行、参与身份与消息删掉就再也还原不出来：删之前先交给独立的历史库留档。
    # 历史是另一个 SQLite 文件，写失败只记日志，不能因此挡住「一键初始化 / 开启下一局」。
    from .history_storage import archive_pending

    try:
        archive_pending(db)
    except Exception:
        logger.exception("清空对局库前留档失败；继续清空")
    for table in ("messages", "evidence", "channels", "participants", "invites", "games"):
        db.execute(f"DELETE FROM {table}")


INVITE_MINUTES = 10


def invite_cutoff():
    """待处理邀请的有效下界；过期不写库，读取时按时间过滤。"""
    return (datetime.now(UTC) - timedelta(minutes=INVITE_MINUTES)).isoformat()


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


def _channel_seat_ids(db, game_id, members):
    """只保留发送时参与玩家的固定席位，主持人不占席位。"""
    members = set(members)
    return sorted(
        {
            row["seat_id"]
            for row in db.execute(
                "SELECT id,seat_id FROM participants WHERE game_id=? AND kind='player'", (game_id,)
            )
            if row["id"] in members and row["seat_id"] in {"1", "2", "3", "4", "5", "6", "7"}
        }
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
    payload=None,
    mention_ids=None,
    reference_title=None,
):
    created_at = now_text()
    channel_seat_ids = (
        _channel_seat_ids(db, game_id, audience or [])
        if kind == "chat" and channel_id not in {"public", "spectator", "information", "system"}
        else None
    )
    cursor = db.execute(
        """INSERT INTO messages(game_id,kind,sender_id,sender_name,avatar_role_id,
           channel_id,text,created_at,audience,image_id,payload,mention_ids,reference_title,channel_seat_ids)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
            None if payload is None else dumps(payload),
            dumps(mention_ids or []),
            reference_title,
            None if channel_seat_ids is None else dumps(channel_seat_ids),
        ),
    )
    return dict(db.execute("SELECT * FROM messages WHERE id=?", (cursor.lastrowid,)).fetchone())


def recall_message(db, row):
    db.execute(
        """UPDATE messages SET recalled_at=?,text='',mention_ids='[]',image_id=NULL,payload=NULL
           WHERE id=?""",
        (now_text(), row["id"]),
    )
    return dict(db.execute("SELECT * FROM messages WHERE id=?", (row["id"],)).fetchone())


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
                payload=event.get("payload"),
                reference_title=event.get("reference_title") if audience is None else None,
                channel_id=event.get("channel_id", "public" if audience is None else "information"),
                sender_id=event.get("sender_id", "host"),
                sender_name=event.get("sender_name", "主持人"),
                avatar_role_id=event.get("avatar_role_id", "host"),
            )
        )
    return rows


def reference_events(db, game_id, message_id=None):
    """公开事件目录和发送校验共用的同一条来源判据。"""
    rows = db.execute(
        """SELECT id, text, image_id, reference_title, kind, payload FROM messages
           WHERE game_id=? AND audience IS NULL AND kind!='chat'
           AND (reference_title IS NOT NULL OR (kind='alert' AND
               (text GLOB '第[0-9]*夜[：是]*' OR
                (json_valid(payload) AND json_extract(payload,'$.type')='death'))))
           AND (? IS NULL OR id=?) ORDER BY id""",
        (game_id, message_id, message_id),
    ).fetchall()
    result = []
    for row in rows:
        title = row["reference_title"]
        if not title:
            if row["kind"] != "alert":
                continue
            if re.match(r"^第[0-9]+夜[：是]", row["text"]):
                title = "夜终公告"
            elif row["payload"] and json.loads(row["payload"]).get("type") == "death":
                title = "出局公告"
            else:
                continue
        item = {
            "type": "event",
            "id": str(row["id"]),
            "label": f"{title}·{row['text'][:40].replace(chr(10), ' ')}·{row['id']}",
            "text": row["text"],
        }
        if row["image_id"]:
            item["image_id"] = row["image_id"]
        result.append(item)
    return result


def visible_message(row, actor):
    if host_capable(actor) or actor.get("kind") == "spectator":
        return True
    if row["channel_id"] == SPECTATOR_CHANNEL and row["kind"] == "chat":
        # 观战频道聊天对玩家与其它非主持人身份一律不可见（历史与实时推送共用）。
        return False
    return row["audience"] is None or bool(
        set(actor["access_ids"]).intersection(json.loads(row["audience"]))
    )


def message_view(row, actor):
    result = {
        key: row[key]
        for key in (
            "id",
            "game_id",
            "kind",
            "sender_id",
            "sender_name",
            "avatar_role_id",
            "channel_id",
            "text",
            "created_at",
        )
    }
    # sqlite3.Row 没有 __contains__：`x in row` 走迭代、比的是「值」而不是列名，所以
    # 这里必须保留 .keys()——SIM118 的简化建议在这个类型上是错的（会静默丢掉撤回与播报）。
    recalled = bool(row["recalled_at"]) if "recalled_at" in row.keys() else False  # noqa: SIM118
    result["recalled"] = recalled
    result["channel_seat_ids"] = (
        json.loads(row["channel_seat_ids"])
        if "channel_seat_ids" in row.keys() and row["channel_seat_ids"] is not None  # noqa: SIM118
        else []
    )
    result["mention_ids"] = (
        json.loads(row["mention_ids"])
        if not recalled and "mention_ids" in row.keys()  # noqa: SIM118 - 同上，不能用 `in row`
        else []
    )
    if recalled:
        result["text"] = ""
        result["sender_name"] = display_player_name(result["sender_name"])
        return result
    if (
        row["kind"] == "information"
        and (host_capable(actor) or actor.get("kind") == "spectator")
        and "audience" in row.keys()  # noqa: SIM118 - sqlite3.Row 的成员判断比较值
        and row["audience"] is not None
    ):
        result["audience"] = json.loads(row["audience"])
    if row["image_id"]:
        result["image_id"] = row["image_id"]
    # 昵称展示统一走展示名：消息留档里存的是完整昵称，只有下发时按 16 半角宽度截断。
    result["sender_name"] = display_player_name(result["sender_name"])
    # 结构化播报按收件人裁剪：同一行消息，不同的人拿到的细节不同。
    if "payload" in row.keys() and row["payload"]:  # noqa: SIM118 - 同上，不能用 `in row`
        projected = project_message_payload(row["payload"], actor, row["kind"])
        if projected:
            result["payload"] = projected
            if projected.get("type") == "sticker":
                result["sticker_md5"] = projected["md5"]
    return result


def project_message_payload(raw, actor, kind=None):
    """把消息里的结构化载荷裁剪成该身份可见的细节。

    技能播报（主动与被动）与角色卡死亡两类载荷走这里。技能名与介绍是公开规则，
    任何能看到这条消息的人都能拿到；目标是否下发由技能决定（``PUBLIC_TARGET_ABILITIES``），
    私密目标只有声明者本人（按 ``access_ids``，与其它「挂在自己名下的私密情报」同一判据）
    与主持人能看到；被动技能的结果同理由 ``effect_public`` 决定；``fake``（伪装声明）
    与牌 id 只给主持人——伪装声明在其他人眼里必须与真声明完全一致，判据只能在服务端。
    动画使用消息创建时的 ``_animation`` 快照：本人/已确认主持人拿 owner 分支，其他人
    只拿 public 分支；私密被动与不公开目标的 information 即使直接调用投影也不下发动画。

    死亡卡片是另一回事：载荷由 ``state.death_card_entry`` 按白名单构造，里面本来就只有
    公开信息（席位、展示名、公开头像、是否13水），因此对每个收件人原样下发；
    这张卡片本身发给谁，仍由 ``notify`` 的 audience 决定。
    """
    try:
        payload = json.loads(raw) if isinstance(raw, str) else raw
    except TypeError, ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("type") == "sticker":
        md5 = payload.get("md5")
        if kind != "chat" or not isinstance(md5, str) or not re.fullmatch(r"[0-9a-f]{32}", md5):
            return None
        return {"type": "sticker", "md5": md5}
    if payload.get("type") == "references":
        if kind != "chat" or not isinstance(payload.get("items"), list):
            return None
        fields = ("start", "end", "type", "id", "label", "text", "image_id")
        return {
            "type": "references",
            **({"image": payload["image"]} if isinstance(payload.get("image"), str) else {}),
            "items": [
                {key: item[key] for key in fields if key in item}
                for item in payload["items"]
                if isinstance(item, dict)
            ],
        }

    if kind == "speech_turn" and payload.get("type") == "speech_turn":
        return {
            key: payload[key]
            for key in ("type", "day", "seat_id", "avatar_role_id", "animation")
            if key in payload
        }
    if payload.get("type") == "death":
        return {key: payload[key] for key in ("type", "day", "half", "deaths") if key in payload}
    if payload.get("type") == "plugin":
        return {
            key: payload[key]
            for key in ("type", "id", "name", "version", "description", "category")
            if key in payload
        }
    if payload.get("type") == "intelligence":
        return {
            key: payload[key]
            for key in ("type", "day", "seat_id", "actor_name", "text")
            if key in payload
        }
    if payload.get("type") == "animation":
        if kind == "alert" and payload.get("public") is True:
            privileged = host_capable(actor) or payload.get("actor_participant_id") in (
                actor.get("access_ids") or []
            )
            return {
                "type": "animation",
                "animation": payload["_animation"]["owner" if privileged else "public"],
            }
        if kind == "information" and (
            host_capable(actor)
            or payload.get("actor_participant_id") in (actor.get("access_ids") or [])
        ):
            return {"type": "animation", "animation": payload["_animation"]["owner"]}
        return None
    if payload.get("type") != "skill":
        return payload if host_capable(actor) else None
    host = host_capable(actor)
    access = set(actor.get("access_ids") or [])
    privileged = host or payload.get("actor_participant_id") in access
    result = {
        key: payload[key]
        for key in (
            "type",
            "mode",
            "declaration_id",
            "ability",
            "ability_name",
            "role_id",
            "role_name",
            "intro",
            "seat_id",
            "actor_participant_id",
            "actor_name",
            "challengeable",
            "target_public",
            "effect_public",
        )
        if key in payload
    }
    if result.get("target_public") or privileged:
        result["target"] = payload.get("target")
    if result.get("effect_public") or privileged:
        result["effect"] = payload.get("effect")
    private_animation = (payload.get("mode") == "passive" and not payload.get("effect_public")) or (
        kind == "information" and not payload.get("target_public")
    )
    if "_animation" in payload and (privileged or not private_animation):
        result["animation"] = payload["_animation"]["owner" if privileged else "public"]
    if host:
        result["fake"] = bool(payload.get("fake"))
        result["card_id"] = payload.get("card_id")
    return result


def active_private_channel(db, game, participant_id):
    """该参与身份当前生效的私聊频道；夜间只承认含主持人的私聊。"""
    if participant_id == "host":
        return None
    clauses = [
        "c.game_id=?",
        "c.status='active'",
        "EXISTS (SELECT 1 FROM json_each(c.participant_ids) WHERE value=?)",
    ]
    args = [game["id"], participant_id]
    if night_half(game):
        clauses.append("EXISTS (SELECT 1 FROM json_each(c.participant_ids) WHERE value='host')")
    return db.execute(
        "SELECT * FROM channels c WHERE " + " AND ".join(clauses) + " ORDER BY c.rowid LIMIT 1",
        args,
    ).fetchone()


def channel_members(row):
    return json.loads(row["participant_ids"])


def channel_visible(row, actor):
    return (
        host_capable(actor)
        or actor.get("kind") == "spectator"
        or actor["id"] in channel_members(row)
    )


def typing_visible(db, game_id, actor, channel_id):
    """输入状态（「正在输入」）对某个身份是否可见。

    公屏全体可见；观战者只读全部频道，玩家私信仍只给成员与已确认主持人。
    system 频道不存在输入状态，已结束的私信不再广播输入状态。
    """
    if actor.get("kind") == "host" and not host_capable(actor):
        # 未确认进入本局管理界面的主持人连消息都发不出去，也不该广播「正在输入」。
        return False
    if channel_id == "public":
        return True
    if channel_id == SPECTATOR_CHANNEL:
        return actor.get("kind") == "spectator" or host_capable(actor)
    if channel_id == "system":
        return False
    row = db.execute(
        "SELECT * FROM channels WHERE id=? AND game_id=?", (channel_id, game_id)
    ).fetchone()
    if not row or row["status"] != "active":
        return False
    return channel_visible(row, actor)


SPECTATOR_CHANNEL = "spectator"


def channel_send_reason(db, game, actor, channel_id):
    if actor.get("kind") == "spectator":
        return "观战者只能只读查看频道"
    if game["status"] == "ended":
        return "本局已经结束"
    participant = db.execute("SELECT muted FROM participants WHERE id=?", (actor["id"],)).fetchone()
    if participant and participant["muted"]:
        return "主持人已将你禁言"
    if actor.get("kind") == "player" and channel_id == SPECTATOR_CHANNEL:
        return "观战频道仅观战者可见"
    if (
        not host_capable(actor)
        and channel_id not in {"public", "information"}
        and (night_half(game) or participant_eliminated(game, actor.get("id")))
    ):
        # 夜间与整席出局都只允许与主持人私聊：不含主持人的频道（旧数据或异常路径
        # 遗留）一律不能再发言。出局按当前牌现场求值，回溯或复活后自动解除。
        row = db.execute(
            "SELECT participant_ids FROM channels WHERE id=?", (channel_id,)
        ).fetchone()
        if row and "host" not in json.loads(row["participant_ids"]):
            return "夜间只能与主持人私聊" if night_half(game) else "出局后只能与主持人私信"
    active = active_private_channel(db, game, actor["id"])
    if not host_capable(actor) and active and channel_id != active["id"]:
        return "私信期间只能在当前私信频道发言"
    return ""


def messages(
    db, game_id, actor, *, before=None, after=None, channel_id=None, scope="all", channel_ids=None
):
    clauses, args = ["m.game_id=?"], [game_id]
    if channel_ids is not None:
        # 傀儡代读：只放行该席位所在的聊天频道历史，不放行面向个人的系统情报。
        placeholders = ",".join("?" for _ in channel_ids)
        clauses.append(f"m.kind='chat' AND m.channel_id IN ({placeholders})")
        args.extend(channel_ids)
    elif not host_capable(actor) and actor.get("kind") != "spectator":
        ids = actor["access_ids"]
        if ids:
            placeholders = ",".join("?" for _ in ids)
            clauses.append(
                f"(m.audience IS NULL OR EXISTS (SELECT 1 FROM json_each(m.audience) WHERE value IN ({placeholders})))"
            )
            args.extend(ids)
        else:
            # 访问名单为空的身份（例如还没确认进入本局的主持人）只能看公开消息。
            clauses.append("m.audience IS NULL")
    if not host_capable(actor) and actor.get("kind") != "spectator" and scope != "system":
        # 观战频道聊天只允许观战者与已确认主持人读取。
        clauses.append("(m.kind!='chat' OR m.channel_id!='spectator')")
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
        clauses.append("m.kind IN ('chat','speech_turn') AND m.channel_id='public'")
    elif scope == "private":
        clauses.append("m.kind='chat' AND m.channel_id NOT IN ('public','information','spectator')")
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
