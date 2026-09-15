"""One permission projection shared by HTTP, WebSocket, chat, and evidence."""

import json

from . import storage
from .game import game_view
from .game.actions import action, field


def participant_rows(db, game_id):
    return list(db.execute("SELECT * FROM participants WHERE game_id=? ORDER BY rowid", (game_id,)))


def participant_summary(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "kind": row["kind"],
        "seat_id": row["seat_id"],
    }


def channel_actions(row, actor, invitation, current):
    fixed = {"channel_id": row["id"]}
    actions = []
    if row["status"] == "pending" and invitation == "pending":
        actions.extend(
            [
                action(
                    "channel.accept",
                    "同意加入私信",
                    payload=fixed,
                    group="私信",
                    short_label="同意",
                ),
                action(
                    "channel.reject",
                    "拒绝加入并取消本次私信",
                    payload=fixed,
                    group="私信",
                    short_label="拒绝",
                    danger=True,
                ),
            ]
        )
    if row["status"] == "active" and current:
        actions.append(
            action(
                "channel.end",
                "结束整个私信频道",
                payload=fixed,
                group="私信",
                short_label="结束私信",
                danger=True,
            )
        )
    return actions


def channels_for(db, game, actor, domain_view):
    ended = game["status"] == "ended"
    participants = participant_rows(db, game["id"])
    by_id = {row["id"]: row for row in participants}
    public_reason = storage.channel_send_reason(db, game, actor, "public") or domain_view.get(
        "chat_reason", ""
    )
    result = [
        {
            "id": "public",
            "label": "公开讨论",
            "status": "active",
            "creator_id": "host",
            "members": [],
            "invited_ids": [],
            "accepted_ids": [],
            "invitation": "none",
            "can_send": not public_reason and bool(domain_view.get("can_chat", False)),
            "reason": public_reason,
            "actions": [],
        }
    ]
    for row in db.execute("SELECT * FROM channels WHERE game_id=? ORDER BY rowid", (game["id"],)):
        members = json.loads(row["participant_ids"])
        if actor["kind"] != "host" and not set(actor["access_ids"]).intersection(members):
            continue
        invited = json.loads(row["invited_ids"])
        accepted = json.loads(row["accepted_ids"])
        current = actor["kind"] == "host" or actor["id"] in members
        invitation = (
            "accepted"
            if actor["id"] in accepted
            else "pending"
            if actor["id"] in invited
            else "none"
        )
        reason = storage.channel_send_reason(db, game, actor, row["id"])
        if row["status"] != "active":
            reason = "等待全部成员同意" if row["status"] == "pending" else "私信已经结束"
        elif not current:
            reason = "仅可查看获准继承的历史"
        summaries = []
        for member_id in members:
            if member_id == "host":
                summaries.append({"id": "host", "name": "主持人", "kind": "host", "seat_id": None})
            elif member_id in by_id:
                summaries.append(participant_summary(by_id[member_id]))
        actions = channel_actions(row, actor, invitation, current) if not ended else []
        result.append(
            {
                "id": row["id"],
                "label": "私密 · " + row["name"],
                "status": row["status"],
                "creator_id": row["creator_id"],
                "members": summaries,
                "invited_ids": invited,
                "accepted_ids": accepted,
                "invitation": invitation,
                "ended_at": row["ended_at"],
                "can_send": not reason and row["status"] == "active" and current,
                "reason": reason,
                "actions": actions,
            }
        )
    result.append(
        {
            "id": "system",
            "label": "系统与私密信息",
            "status": "active",
            "creator_id": "host",
            "members": [],
            "invited_ids": [],
            "accepted_ids": [],
            "invitation": "none",
            "can_send": False,
            "reason": "系统信息只用于告知，不能在此发言",
            "actions": [],
        }
    )
    return result




def channel_create_descriptor(db, game, actor, participants):
    if game["status"] == "ended" or storage.active_private_channel(db, game["id"], actor["id"]):
        return None
    options = []
    if actor["kind"] != "host":
        options.append(("host", "主持人"))
    options.extend(
        (row["id"], row["name"] + ("（观战）" if row["kind"] == "spectator" else ""))
        for row in participants
        if row["active"] and not row["blocked"] and row["id"] != actor["id"]
    )
    if not options:
        return None
    return action(
        "channel.create",
        "创建一对一或多人私信",
        [
            field("name", "频道名称"),
            field("participant_ids", "邀请成员", "multiselect", options, min=1, max=20),
        ],
        group="私信",
        short_label="建私信",
    )


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
    actions = [
        action(
            "room.open_join",
            "关闭开放参局" if game.get("join_open") else "开放账号主动参局",
            payload={"open": not game.get("join_open", False)},
            group="房间管理",
            short_label="关闭加入" if game.get("join_open") else "开放加入",
        ),
        action(
            "room.kick",
            "移出参与者 / 本局拉黑",
            [
                field("participant_id", "参与者", "select", [(p["value"], p["label"]) for p in people]),
                field("block", "同时在本局拉黑", "checkbox", required=False, default=False),
            ],
            group="房间管理",
            short_label="移出",
            danger=True,
        ),
    ]
    if substitutes and seats:
        actions.append(
            action(
                "room.replace",
                "观战者接管空席并保留该席角色牌、技能次数和裁定状态",
                [
                    field("seat_id", "席位", "select", [(s["value"], s["label"]) for s in seats]),
                    field(
                        "participant_id",
                        "替补观战者",
                        "select",
                        [(p["value"], p["label"]) for p in substitutes],
                    ),
                    field("share_history", "继承原操作者私密历史", "checkbox", required=False),
                    field("keep_actions", "保留该席已提交行动", "checkbox", required=False),
                ],
                group="房间管理",
                short_label="替补",
                danger=True,
            )
        )
    if people:
        actions.append(
            action(
                "room.mute",
                "设置或解除参与者禁言",
                [
                    field("participant_id", "参与者", "select", [(p["value"], p["label"]) for p in people]),
                    field("muted", "禁言（取消勾选为解除）", "checkbox", required=False, default=True),
                ],
                group="房间管理",
                short_label="禁言",
            )
        )
    return actions


def view(db, game, actor, online):
    result = game_view(game, actor)
    participants = participant_rows(db, game["id"])
    result["channels"] = channels_for(db, game, actor, result)
    result["can_chat"] = result["channels"][0]["can_send"]
    result["chat_reason"] = result["channels"][0]["reason"]
    occupancy = {seat["id"]: seat["occupant_id"] for seat in game["seats"]}
    for seat in result["seats"]:
        seat["online"] = occupancy.get(seat["id"]) in online
    if result.get("result"):
        people = {row["id"]: row for row in participants}
        result["result"]["personal_losses"] = [
            {"seat_id": people[pid]["seat_id"], "name": people[pid]["name"]}
            for pid in result["result"].get("personal_losses", [])
            if pid in people
        ]
    channel_actions = [item for channel in result["channels"] for item in channel["actions"]]
    active_private = storage.active_private_channel(db, game["id"], actor["id"])
    if active_private and actor["kind"] != "host":
        result["actions"] = channel_actions
    else:
        create_action = channel_create_descriptor(db, game, actor, participants)
        result["actions"].extend(([create_action] if create_action else []) + channel_actions)
    if actor["kind"] == "host":
        result.setdefault("host", {})["participants"] = [
            participant_summary(row)
            | {
                "active": bool(row["active"]),
                "blocked": bool(row["blocked"]),
                "muted": bool(row["muted"]),
                "online": row["id"] in online,
                "account_id": row["account_id"],
            }
            for row in participants
        ]
        if game["status"] != "ended":
            result["actions"].extend(runtime_actions(game, participants))
    return result
