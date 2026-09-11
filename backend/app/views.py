"""One permission projection shared by HTTP, WebSocket, and chat."""

import json

from .game import game_view


def participant_rows(db, game_id):
    return list(db.execute("SELECT * FROM participants WHERE game_id=? ORDER BY rowid", (game_id,)))


def channels_for(db, game, actor, domain_view):
    host = actor["kind"] == "host"
    ended = game["status"] == "ended"
    participant = db.execute("SELECT muted FROM participants WHERE id=?", (actor["id"],)).fetchone()
    muted = bool(participant and participant["muted"])
    reason = "本局已经结束" if ended else "主持人已将你禁言" if muted else ""
    public_reason = reason or domain_view.get("chat_reason", "")
    result = [
        {
            "id": "public",
            "label": "公开讨论",
            "can_send": not reason and bool(domain_view.get("can_chat", False)),
            "reason": public_reason,
        }
    ]
    participants = participant_rows(db, game["id"])
    for row in participants:
        if row["kind"] != "player":
            continue
        if host or row["id"] in actor["access_ids"]:
            current = bool(row["active"]) and (host or row["id"] == actor["id"])
            result.append(
                {
                    "id": "host:" + row["id"],
                    "label": "私密 · " + row["name"] + " ↔ 主持人",
                    "can_send": not reason and current,
                    "reason": reason or ("仅可查看获准继承的历史" if not current else ""),
                }
            )
    for row in db.execute("SELECT * FROM channels WHERE game_id=? ORDER BY rowid", (game["id"],)):
        members = json.loads(row["participant_ids"])
        if host or set(actor["access_ids"]).intersection(members):
            current = host or actor["id"] in members
            result.append(
                {
                    "id": row["id"],
                    "label": "私密 · " + row["name"],
                    "can_send": not reason and current,
                    "reason": reason or ("仅可查看获准继承的历史" if not current else ""),
                }
            )
    return result


def runtime_actions(game, participants):
    seats = [
        {"value": seat["id"], "label": seat["id"] + "号 · " + (seat["name"] or "空席")}
        for seat in game["seats"]
        if not seat["occupant_id"]
    ]
    active = [row for row in participants if row["active"] and not row["blocked"]]
    people = [
        {
            "value": row["id"],
            "label": row["name"]
            + ("（观战）" if row["kind"] == "spectator" else "（" + str(row["seat_id"]) + "号）"),
        }
        for row in active
    ]
    substitutes = [option for option, row in zip(people, active) if row["kind"] == "spectator"]
    select_seat = {
        "name": "seat_id",
        "label": "席位",
        "type": "select",
        "required": True,
        "options": seats,
    }
    actions = [
        {
            "id": "room.kick",
            "label": "移出参与者 / 本局拉黑",
            "group": "房间管理",
            "danger": True,
            "description": "撤销玩家或观战者的全部会话，不改变角色与技能状态。统一邀请码不受影响；发牌后空席只能由主持人安排观战者接管。",
            "fields": [
                {
                    "name": "participant_id",
                    "label": "参与者",
                    "type": "select",
                    "required": True,
                    "options": people,
                },
                {
                    "name": "block",
                    "label": "同时将该参与身份在本局拉黑",
                    "type": "checkbox",
                    "default": False,
                },
            ],
        }
    ]
    if substitutes and seats:
        actions.append(
            {
                "id": "room.replace",
                "label": "观战者接管席位",
                "group": "房间管理",
                "danger": True,
                "description": "先移出原玩家，再接管空席；保留该席双牌、状态与剩余次数。请先在主持人牌表查看状态和已提交行动；勾选后才继承原私密历史或保留行动。",
                "fields": [
                    select_seat,
                    {
                        "name": "participant_id",
                        "label": "替补观战者",
                        "type": "select",
                        "required": True,
                        "options": substitutes,
                    },
                    {
                        "name": "share_history",
                        "label": "允许继承原操作者获准的全部私密历史",
                        "type": "checkbox",
                        "default": False,
                    },
                    {
                        "name": "keep_actions",
                        "label": "保留该席已提交 / 确认的行动",
                        "type": "checkbox",
                        "default": False,
                    },
                ],
            }
        )
    if people:
        actions.extend(
            [
                {
                    "id": "room.channel",
                    "label": "创建私密频道",
                    "group": "房间管理",
                    "description": "仅所选参与者与主持人可查看及发言，不会自动公开旧信息。",
                    "fields": [
                        {"name": "name", "label": "频道名称", "type": "text", "required": True},
                        {
                            "name": "participant_ids",
                            "label": "参与者",
                            "type": "multiselect",
                            "required": True,
                            "options": people,
                        },
                    ],
                },
                {
                    "id": "room.mute",
                    "label": "设置禁言",
                    "group": "房间管理",
                    "fields": [
                        {
                            "name": "participant_id",
                            "label": "参与者",
                            "type": "select",
                            "required": True,
                            "options": people,
                        },
                        {
                            "name": "muted",
                            "label": "禁言（取消勾选为解除）",
                            "type": "checkbox",
                            "default": True,
                        },
                    ],
                },
            ]
        )
    actions.append(
        {
            "id": "room.revoke_invite",
            "label": "撤销统一邀请码",
            "group": "房间管理",
            "danger": True,
            "fields": [
                {
                    "name": "kind",
                    "label": "邀请码范围",
                    "type": "select",
                    "required": True,
                    "options": [
                        {"value": "player", "label": "统一玩家邀请码"},
                        {"value": "spectator", "label": "统一观战邀请码"},
                    ],
                }
            ],
        }
    )
    return actions


def view(db, game, actor, online):
    result = game_view(game, actor)
    result["channels"] = channels_for(db, game, actor, result)
    result["can_chat"] = result["channels"][0]["can_send"]
    result["chat_reason"] = result["channels"][0].get("reason", "")
    occupancy = {seat["id"]: seat["occupant_id"] for seat in game["seats"]}
    for seat in result["seats"]:
        seat["online"] = occupancy.get(seat["id"]) in online
    if result.get("result"):
        people = {row["id"]: row for row in participant_rows(db, game["id"])}
        result["result"]["personal_losses"] = [
            {"seat_id": people[pid]["seat_id"], "name": people[pid]["name"]}
            for pid in result["result"].get("personal_losses", [])
            if pid in people
        ]
    if actor["kind"] == "host":
        rows = participant_rows(db, game["id"])
        result.setdefault("host", {})["participants"] = [
            {key: row[key] for key in ("id", "kind", "seat_id", "name")}
            | {
                "active": bool(row["active"]),
                "blocked": bool(row["blocked"]),
                "muted": bool(row["muted"]),
                "online": row["id"] in online,
            }
            for row in rows
        ]
        if game["status"] != "ended":
            result["actions"].extend(runtime_actions(game, rows))
    return result
