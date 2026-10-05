"""独立历史对局库：结束或清空终止后，公开完整游戏记录。

历史独立于对局库；清空前必须快照频道、原受众、证物和主持人日志。
进行中的对局不会由历史查询或结束补录公开。撤回消息只保留占位。
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, UTC

from . import storage
from .game.catalog import ABILITY_NAMES, NIGHT_ABILITIES, PHASES, ROLES
from .game import plugins
from .game.state import display_player_name, host_label

# 列表接口一页最多几条。
PAGE_LIMIT = 50
DEFAULT_PAGE = 20


def now_text():
    return datetime.now(UTC).isoformat()


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
        additions = {
            "matches": {
                "host_log": "TEXT NOT NULL DEFAULT '[]'",
                "export_text": "TEXT NOT NULL DEFAULT ''",
                "archive_complete": "INTEGER NOT NULL DEFAULT 0",
            },
            "match_events": {
                "channel_name": "TEXT NOT NULL DEFAULT '历史公开频道'",
                "audience_names": "TEXT",
                "image_id": "TEXT",
                "recalled_at": "TEXT",
            },
        }
        for table, columns in additions.items():
            existing = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
            for column, declaration in columns.items():
                if column not in existing:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
        db.commit()


def _dumps(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _loads(value, fallback):
    try:
        return json.loads(value) if value else fallback
    except TypeError, ValueError:
        return fallback


def role_name(role_id):
    return ROLES.get(role_id, {}).get("name", str(role_id or "未发牌"))


def readable_message(event):
    """把已有播报卡与聊天引用变为文字，不把图片或动画数据塞进 TXT。"""
    lines = [event.get("text") or ""]
    if event.get("image_id"):
        lines.append("[附证物图片；TXT 不含图像]")
    payload = _loads(event.get("payload"), {})
    if not isinstance(payload, dict):
        return "\n".join(filter(None, lines))
    kind = payload.get("type")
    if kind == "skill":
        lines.append("技能：" + str(payload.get("ability_name") or payload.get("ability") or ""))
        if payload.get("intro"):
            lines.append("技能介绍：" + str(payload["intro"]))
        if payload.get("target") is not None:
            lines.append("目标：" + str(payload["target"]) + "号")
        if payload.get("effect"):
            lines.append("效果：" + str(payload["effect"]))
        if payload.get("fake"):
            lines.append("主持人记录：伪装声明")
    elif kind == "references":
        if payload.get("image"):
            lines.append("[附聊天图片；TXT 不含图像]")
        for item in payload.get("items", []):
            if not isinstance(item, dict):
                continue
            lines.append("引用：" + str(item.get("label") or "消息/证物"))
            if item.get("text"):
                lines.append(str(item["text"]))
            if item.get("image_id"):
                lines.append("[引用含图片；TXT 不含图像]")
    elif kind == "death":
        for death in payload.get("deaths", []):
            if isinstance(death, dict):
                lines.append(
                    f"出局：{death.get('seat_id', '?')}号 · {death.get('player_name', '')} · "
                    + str(death.get("role_name") or role_name(death.get("avatar_role_id")))
                    + (" · 13水毒杀" if death.get("water") else "")
                )
    elif kind == "sticker":
        lines.append("[表情图片；TXT 不含图像]")
    return "\n".join(filter(None, lines))


# 游戏记录字段的中文名称；只格式化下方显式选出的机械状态，不遍历整份存档。
RULE_LABELS = {
    "day": "游戏日",
    "half": "昼夜",
    "phase": "阶段",
    "kind": "类型",
    "seat": "席位",
    "seat_id": "席位",
    "target_seat": "目标席位",
    "card_id": "角色牌",
    "target_card": "目标牌",
    "source_card": "来源牌",
    "role_id": "角色",
    "original_role_id": "原角色",
    "target": "目标",
    "source": "来源",
    "source_seat": "来源席位",
    "victim": "受害者",
    "true_source": "实际真凶",
    "display_source": "显示真凶",
    "cause": "原因",
    "text": "正文",
    "title": "说明",
    "ability": "技能",
    "fake": "伪装",
    "data": "声明内容",
    "effects": "生效内容",
    "challenge": "质疑",
    "challenger": "质疑者",
    "challengeable": "可质疑",
    "resolved": "已裁定",
    "confirmed": "已确认",
    "effective": "生效",
    "cancelled": "已取消",
    "revoked": "已撤销",
    "allowed": "获准",
    "locked": "已锁定",
    "roll": "骰值",
    "threshold": "阈值",
    "hit": "命中",
    "mine": "触发地雷",
    "bullets": "剩余子弹",
    "shot_misses": "连续未命中次数",
    "interrupt_day": "打断使用日",
    "duel_day": "决斗使用日",
    "love_day": "爱人使用日",
    "gaze_day": "查看魔女状态使用日",
    "extra_kill": "额外攻击已使用",
    "revive": "复活已使用",
    "mass_brainwash": "全员洗脑已使用",
    "rain": "下雨",
    "scapegoat": "替罪凶手",
    "poisoned": "中毒",
    "protected_day": "庇护起始日",
    "treasure_protected_day": "寻宝保护日",
    "treasure_roll": "寻宝骰",
    "no_vote": "失去投票权",
    "no_ability": "失去技能",
    "puppet": "傀儡主人牌",
    "display_killer": "显示凶手",
    "disguise": "示人角色",
    "disguise_locked": "示人已锁定",
    "evidence_allowed": "允许遗留证物",
    "evidence_used": "证物已提交",
    "entry_allowed": "允许行动",
    "normal": "普通",
    "witch": "魔女化",
    "hiro_used": "希罗回溯已用",
    "hiro_exception": "希罗例外",
    "sherry_bound": "雪莉绑定",
    "annan_penalty": "安安后果日",
    "personal_losses": "个人失败",
    "persistent_states": "回溯保留裁定状态",
    "speaker": "当前发言者",
    "speech_order": "发言顺序",
    "votes": "投票结算",
    "declarations": "技能声明",
    "rewinds": "回溯次数",
    "witch_destiny": "魔女化命运",
    "seats": "各席命运",
    "first": "首两日当值魔女席位",
    "holders": "持有者",
    "actors": "夜间行动者",
    "actions": "夜间行动",
    "reactions": "响应行动",
    "extra_attacks": "额外伤害",
    "revive_declined": "已放弃复活",
    "preview": "夜间预结算",
    "nomination": "提名",
    "nominator": "提名者",
    "candidate": "候选",
    "candidates": "候选牌",
    "voters": "投票者",
    "yes": "同意",
    "no": "不同意",
    "abstain": "弃票",
    "denominator": "投票分母",
    "count": "票数",
    "passed": "已通过",
    "executed": "已处决",
    "required": "所需票数",
    "leia_card": "蕾雅牌",
    "water": "13水",
    "guess": "猜测角色",
    "suspects": "疑似凶手",
    "killer": "凶手",
    "owner_id": "持有者",
    "recipient": "接收者",
    "recipients": "接收者",
    "to": "接收者",
    "from": "发出者",
    "given": "已赠送",
    "used": "已使用",
    "authorized": "已授权",
    "truth": "真实信息",
    "false_text": "虚假信息",
    "alive": "存活",
    "injured": "负伤",
    "witches": "魔女",
    "reason": "裁定说明",
    "winner": "胜方",
    "damage": "伤害",
    "deaths": "死亡记录",
}


def rule_text(value, names, key=""):
    """游戏机械记录的缩进文本；身份凭证和运行计时字段不属于游戏导出。"""
    if isinstance(value, dict):
        lines = []
        for field, item in value.items():
            if (
                field
                in {
                    "id",
                    "account_id",
                    "qq_id",
                    "access_ids",
                    "token",
                    "token_hash",
                    "session_token",
                    "invite_code",
                    "host_entries",
                    "image",
                    "_animation",
                }
                or "deadline" in field
                or field.endswith("_at")
            ):
                continue
            if field == "image_id":
                if item:
                    lines.append("图片：存在（TXT 不含图像）")
                continue
            label = RULE_LABELS.get(field, names.get(field, role_name(field)))
            content = rule_text(item, names, field)
            lines.append(f"{label}：{content}".replace("\n", "\n  "))
        return "\n".join(lines) or "无"
    if isinstance(value, list):
        return (
            "\n".join(f"{i + 1}. {rule_text(item, names, key)}" for i, item in enumerate(value))
            or "无"
        )
    if value is None:
        return "无"
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if key == "half":
        return {"day": "白天", "night": "夜晚"}.get(text, text)
    if key == "phase":
        return PHASES.get(text, text)
    if key == "ability":
        return ABILITY_NAMES.get(text, NIGHT_ABILITIES.get(text, (None, text))[1])
    if key == "winner":
        return {
            "good": "好人阵营",
            "witch": "魔女阵营",
            "emma": "艾玛单胜",
            "aborted": "终止对局",
        }.get(text, text)
    return names.get(
        text,
        ROLES.get(text, {}).get(
            "name",
            {
                "good": "好人阵营",
                "witch": "魔女阵营",
                "emma": "艾玛单胜",
                "aborted": "终止对局",
                "yes": "同意",
                "no": "不同意",
                "abstain": "弃票",
            }.get(text, text),
        ),
    )


def readable_export(game, snap, ended_at, source, complete):
    players = snap.get("players", [])
    names = {row["id"]: display_player_name(row["name"]) for row in players}
    host_name = game.get("host_name") or host_label(game)
    names["host"] = host_name
    names.update(
        {
            s["id"]: f"{s['id']}号（{display_player_name(s.get('name', ''))}）"
            for s in game.get("seats", [])
        }
    )
    result = game.get("result") or {}
    lines = [
        "七双历史对局",
        f"对局：{game.get('id', '')}",
        f"归档时间：{ended_at}",
        "归档方式：" + ("结束裁定" if source == "ended" else "清空终止（未宣判）"),
        f"主持人：{host_name}",
        f"最后进度：第{game.get('day', 0)}天 · "
        + {"day": "白天", "night": "夜晚"}.get(game.get("half"), "")
        + " · "
        + PHASES.get(game.get("phase"), game.get("phase", "")),
        "胜方：" + rule_text(result.get("winner"), names, "winner"),
        "裁定：" + str(result.get("reason") or "未宣判"),
        "个人失败：" + rule_text(result.get("personal_losses", []), names),
    ]
    if not complete:
        lines.append(
            "归档不完整：旧版未保存私聊、定向情报、完整日志与规则状态；"
            "仅补回仍然存在的资料，已丢失内容无法恢复，旧日志可能已截断。"
        )
    lines.extend(
        [
            "",
            "【规则与模块】",
            f"规则修订：{game.get('rules_revision', '未知')}",
            "魔典：" + ("、".join(role_name(r) for r in game.get("codex", [])) or "未保存"),
            "汉娜魔化："
            + (
                "未保存" if "hanna_witch" not in game else "开启" if game["hanna_witch"] else "关闭"
            ),
        ]
    )
    modules = {module.ID: plugins.info(module) for module in plugins.REGISTRY}
    names.update({module_id: module["name"] for module_id, module in modules.items()})
    for entry in game.get("rule_plugins", []):
        module = modules.get(entry["id"], {})
        lines.append(f"模块：{module.get('name', entry['id'])}，版本{entry.get('version', '')}")
        if module.get("description"):
            lines.append(module["description"])
    lines.extend(["", "【参与者与最终上下牌】"])
    for row in players:
        lines.append(
            f"{display_player_name(row['name'])} · "
            + {"player": "玩家", "spectator": "观战者", "host": "主持人"}.get(
                row["kind"], row["kind"]
            )
            + (f" · {row['seat_id']}号" if row.get("seat_id") else " · 未入座")
            + (" · 已离场" if not row.get("active", True) else "")
            + (" · 已移除" if row.get("blocked") else "")
        )
    for seat in game.get("seats", []):
        lines.append(f"{seat['id']}号 · {display_player_name(seat.get('name', ''))}")
        for index, card_id in enumerate(seat.get("cards", [])):
            card = game.get("cards", {}).get(card_id, {})
            lines.append(
                ("上牌" if index == 0 else "下牌")
                + "："
                + role_name(card.get("role_id", card_id))
                + (
                    "（未保存状态）"
                    if not card
                    else " · "
                    + ("存活" if card.get("alive") else "死亡")
                    + " · "
                    + ("魔女化" if card.get("witch") else "未魔女化")
                    + " · "
                    + ("负伤" if card.get("injured") else "未负伤")
                )
            )
            if card.get("original_role_id") != card.get("role_id"):
                lines.append("原角色：" + role_name(card.get("original_role_id")))
            lines.append("技能使用：" + rule_text(card.get("uses", {}), names))
            lines.append("角色状态：" + rule_text(card.get("states", {}), names))
    lines.extend(["", "【最终有效规则状态】"])
    sections = {
        "public": "公开进度与魔女命运",
        "night": "夜间行动与预结算",
        "pending": "待裁定事件",
        "deaths": "死亡记录",
        "spiritual": "灵界与永久裁定",
        "nominations": "提名",
        "ballots": "各席选票",
        "vote_rounds": "投票轮次",
        "vote_freeze": "冻结投票分母",
        "execution": "处决名单",
        "execution_ready": "临刑已确认席位",
        "execution_shots": "临刑射击",
        "execution_rolls": "射击骰",
        "water": "13水",
        "millia_swap": "米莉亚换血",
        "photos": "可可照片",
        "marg_love": "玛格爱人",
        "duel": "蕾雅决斗",
        "duel_approvals": "决斗同意票",
        "declarations": "技能声明与质疑",
        "witness": "目击名单",
        "surrenders": "交牌申请",
        "generated_witches": "产生过魔女的席位",
        "half_exits": "席位离场时段",
        "nomination_done": "已完成提名席位",
        "speech_passed": "已完成发言席位",
        "discussion_end_requests": "结束自由发言申请",
        "day_binding": "当天绑定",
        "witch_checked_day": "最后魔女检测日",
        "winner_candidate": "待确认胜负",
        "plugin_state": "模块规则状态",
    }
    for key, title in sections.items():
        if game.get(key) not in (None, [], {}):
            lines.extend([title + "：", rule_text(game[key], names)])
    lines.extend(["", "【证物】"])
    for item in snap.get("evidence", []):
        lines.append(f"{item['created_at']} · {names.get(item['owner_id'], '已离场参与者')}")
        lines.append(item.get("text") or "（无文字）")
        if item.get("has_image"):
            lines.append("[附证物图片；TXT 不含图像]")
    lines.extend(["", "【主持人日志：有效操作与裁定】"])
    for entry in game.get("log", []):
        lines.append(
            f"第{entry.get('day', 0)}天 · "
            + {"day": "白天", "night": "夜晚"}.get(entry.get("half"), "")
            + " · "
            + PHASES.get(entry.get("phase"), entry.get("phase", ""))
            + " · "
            + {"action": "操作", "host": "主持裁定", "roll": "掷骰", "system": "系统"}.get(
                entry.get("kind"), "记录"
            )
            + "："
            + str(entry.get("text") or "")
        )
    lines.extend(["", "【完整消息时间线】" if complete else "【消息时间线（旧档现存资料）】"])
    for event in snap.get("events", []):
        recipients = event.get("audience_names")
        audience = "全场" if recipients is None else "、".join(recipients) or "无接收者"
        lines.append(
            f"{event['created_at']} · {event.get('channel_name', '历史公开频道')} · "
            f"{display_player_name(event['sender_name'])} · 接收：{audience}"
        )
        lines.append("[消息已撤回]" if event.get("recalled_at") else event["text"])
        if event.get("recalled_at"):
            lines.append("撤回时间：" + event["recalled_at"])
    return "\n".join(lines) + "\n"


def archived_events(db, game_id, names=None):
    """保留所有有效消息与发送时的受众；撤回正文和图片不能复活。"""
    names = names or {}
    channels = {
        row["id"]: dict(row)
        for row in db.execute("SELECT * FROM channels WHERE game_id=?", (game_id,))
    }
    events = []
    for row in db.execute(
        "SELECT * FROM messages WHERE game_id=? AND kind!='presence' ORDER BY id", (game_id,)
    ):
        event = dict(row)
        audience = _loads(event["audience"], None)
        event["audience_names"] = (
            None if audience is None else [names.get(member, "已离场参与者") for member in audience]
        )
        channel_id = event["channel_id"]
        channel = channels.get(channel_id)
        channel_seats = _loads(event.get("channel_seat_ids"), None)
        if channel_seats is not None:
            event["channel_name"] = (
                "私信" + "".join(channel_seats) + "：" + "、".join(event["audience_names"] or [])
            )
        elif channel:
            members = _loads(channel["participant_ids"], [])
            event["channel_name"] = "私聊：" + "、".join(
                names.get(member, "已离场参与者") for member in members
            )
        else:
            event["channel_name"] = {
                "public": "公屏",
                "information": "定向情报" if audience is not None else "全场公告",
                "spectator": "观战频道",
            }.get(channel_id, "私聊：" + "、".join(event["audience_names"] or []))
        if event["recalled_at"]:
            event["text"] = "[消息已撤回]"
            event["image_id"] = None
        else:
            event["text"] = readable_message(event)
        events.append(event)
    return events


def snapshot(game_db, game_id):
    """清空对局库之前，脱离连接保存参与身份、消息和证物文字。"""
    players = [
        dict(row)
        for row in game_db.execute(
            "SELECT * FROM participants WHERE game_id=? ORDER BY rowid", (game_id,)
        )
    ]
    stored = game_db.execute("SELECT state FROM games WHERE id=?", (game_id,)).fetchone()
    game = _loads(stored["state"], {}) if stored else {}
    names = {row["id"]: display_player_name(row["name"]) for row in players}
    names["host"] = host_label(game)
    return {
        "players": players,
        "events": archived_events(game_db, game_id, names),
        "evidence": [
            dict(row)
            for row in game_db.execute(
                "SELECT id,owner_id,text,mime,created_at,image IS NOT NULL AS has_image "
                "FROM evidence WHERE game_id=? ORDER BY rowid",
                (game_id,),
            )
        ],
    }


def record(game, source, snap=None):
    """新局完整留档；旧局仅在原结束局还在时补齐，保留原结束时间。"""
    match_id = game.get("id")
    if not match_id or (source != "aborted" and game.get("status") != "ended"):
        return False
    snap = snap or {"players": [], "events": []}
    result = game.get("result") or {}
    stamp = now_text()
    seats = {seat["id"]: seat for seat in game.get("seats", [])}
    host_log = [
        {key: row.get(key, "") for key in ("day", "half", "phase", "kind", "text")}
        for row in game.get("log", [])
    ]
    with transaction() as db:
        existing = db.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
        if existing and (
            existing["archive_complete"] or existing["export_text"] or game.get("status") != "ended"
        ):
            return False
        if existing:
            # 补录只能补资料，不能因原库部分缺失而删除旧档中仍然存在的记录。
            events = list(snap.get("events", []))
            known = {(event["kind"], event["sender_name"], event["created_at"]) for event in events}
            for item in db.execute(
                "SELECT * FROM match_events WHERE match_id=? ORDER BY seq", (match_id,)
            ):
                if (item["kind"], item["sender_name"], item["created_at"]) not in known:
                    event = dict(item)
                    event["audience_names"] = _loads(event["audience_names"], None)
                    events.append(event)
            events.sort(key=lambda event: event["created_at"])
            players = list(snap.get("players", []))
            player_ids = {player["id"] for player in players}
            for item in db.execute(
                "SELECT * FROM match_players WHERE match_id=? ORDER BY rowid", (match_id,)
            ):
                if item["participant_id"] not in player_ids:
                    players.append({**dict(item), "id": item["participant_id"]})
            snap = {**snap, "events": events, "players": players}
        # 旧版本日志可能曾被环形截断，补回现存资料也不能宣称历史从未丢失。
        complete = existing is None
        ended_at = existing["ended_at"] if existing else stamp
        source = existing["source"] if existing else source
        export_text = readable_export(game, snap, ended_at, source, complete)
        db.execute(
            """INSERT INTO matches
               (id,ended_at,recorded_at,day,half,phase,winner,reason,source,host_name,
                personal_losses,host_log,export_text,archive_complete)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                recorded_at=excluded.recorded_at,day=excluded.day,half=excluded.half,
                phase=excluded.phase,winner=excluded.winner,reason=excluded.reason,
                host_name=excluded.host_name,personal_losses=excluded.personal_losses,
                host_log=excluded.host_log,export_text=excluded.export_text,
                archive_complete=excluded.archive_complete""",
            (
                match_id,
                ended_at,
                stamp,
                int(game.get("day") or 0),
                str(game.get("half") or ""),
                str(game.get("phase") or ""),
                str(result.get("winner") or ""),
                str(result.get("reason") or ""),
                source,
                host_label(game),
                _dumps(result.get("personal_losses") or []),
                _dumps(host_log),
                export_text,
                int(complete),
            ),
        )
        db.execute("DELETE FROM match_players WHERE match_id=?", (match_id,))
        db.execute("DELETE FROM match_events WHERE match_id=?", (match_id,))
        for row in snap.get("players", []):
            seat = seats.get(row["seat_id"]) if row["seat_id"] else None
            db.execute(
                """INSERT INTO match_players
                   (match_id,participant_id,account_id,name,kind,seat_id,role_ids,active,blocked)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    match_id,
                    row["id"],
                    row["account_id"],
                    row["name"],
                    row["kind"],
                    row["seat_id"],
                    _dumps(
                        list(seat.get("cards") or []) if seat else _loads(row.get("role_ids"), [])
                    ),
                    int(row["active"]),
                    int(row["blocked"]),
                ),
            )
        for seq, row in enumerate(snap.get("events", [])):
            recalled = row.get("recalled_at")
            db.execute(
                """INSERT INTO match_events
                   (match_id,seq,kind,sender_name,avatar_role_id,text,created_at,
                    channel_name,audience_names,image_id,recalled_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    match_id,
                    seq,
                    row["kind"],
                    row["sender_name"],
                    row["avatar_role_id"],
                    "[消息已撤回]" if recalled else row["text"],
                    row["created_at"],
                    row.get("channel_name", "公屏"),
                    None if row.get("audience_names") is None else _dumps(row["audience_names"]),
                    None if recalled else row.get("image_id"),
                    recalled,
                ),
            )
    return True


def record_known(game_db, game_ids, *, allow_aborted=False):
    """结束补录不会公开进行中对局；清空前的调用必须显式允许终止留档。"""
    recorded = 0
    for game_id in game_ids:
        game = storage.load_game(game_db, game_id)
        if not game or (game.get("status") != "ended" and not allow_aborted):
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
        game_db, [row["id"] for row in game_db.execute("SELECT id FROM games")], allow_aborted=True
    )


def delete(match_id):
    """删除一条历史对局（连同参与身份与完整记录）。不存在时返回 False。

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
        "archive_complete": bool(row["archive_complete"]),
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
            f"SELECT id,ended_at,day,winner,reason,source,host_name,personal_losses,archive_complete "
            f"FROM matches{where} ORDER BY ended_at DESC, rowid DESC LIMIT ?",
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
    """单局全量公开详情；只补已有旧归档且仍存在的结束局。"""
    with connect() as db:
        row = db.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
    if not row:
        return None
    if (
        not row["archive_complete"]
        and not row["export_text"]
        and row["source"] == "ended"
        and (storage.DATA_DIR / "seven-double.sqlite3").is_file()
    ):
        with storage.connect() as source:
            stored = source.execute(
                "SELECT state FROM games WHERE id=? AND status='ended'", (match_id,)
            ).fetchone()
            game = _loads(stored["state"], {}) if stored else None
            if game and game.get("status") == "ended":
                record(game, "ended", snapshot(source, match_id))
                with connect() as db:
                    row = db.execute("SELECT * FROM matches WHERE id=?", (match_id,)).fetchone()
    with connect() as db:
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
                "text": "[消息已撤回]" if item["recalled_at"] else item["text"],
                "created_at": item["created_at"],
                "channel_name": item["channel_name"],
                "audience_names": _loads(item["audience_names"], None),
                "image_id": None if item["recalled_at"] else item["image_id"],
                "recalled_at": item["recalled_at"],
            }
            for item in db.execute(
                "SELECT * FROM match_events WHERE match_id=? ORDER BY seq", (match_id,)
            )
        ]
    detail["host_log"] = _loads(row["host_log"], [])
    detail["export_text"] = row["export_text"]
    if not detail["export_text"]:
        # 清空过的旧历史只能导出已有公开记录，不能虚构其私聊与最终机械状态。
        legacy_game = {
            "id": match_id,
            "day": row["day"],
            "half": row["half"],
            "phase": row["phase"],
            "host_name": detail["host_name"],
            "result": {key: detail[key] for key in ("winner", "reason", "personal_losses")},
        }
        legacy_players = [
            {**player, "id": player["participant_id"]} for player in detail["players"]
        ]
        legacy_game["seats"] = [
            {"id": player["seat_id"], "name": player["name"], "cards": player["role_ids"]}
            for player in legacy_players
            if player["seat_id"]
        ]
        detail["export_text"] = readable_export(
            legacy_game,
            {"players": legacy_players, "events": detail["events"]},
            row["ended_at"],
            row["source"],
            False,
        )
    return detail
