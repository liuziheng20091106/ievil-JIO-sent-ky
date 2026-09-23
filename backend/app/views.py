"""One permission projection shared by HTTP, WebSocket, chat, and evidence."""

import json

from . import storage
from .game import game_view
from .game.actions import action, field
from .game.views import seat_chat


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


def puppet_channel_view(db, game, seat):
    """受控傀儡席的频道视角：公开讨论与本人已有私信，标签带 *，条目携带 as_seat。

    频道 id 仍是真实 id（发送时用 as_seat 区分身份），草稿隔离由客户端的 asSeat 承担。
    禁言与私信占用按傀儡席自身身份判定，不因控制者是梅露露而放宽。
    """
    occupant = seat["occupant_id"]
    identity = {"id": occupant, "kind": "player"} if occupant else None
    result = []
    can_send, chat_reason = seat_chat(game, seat)
    blocked = (
        storage.channel_send_reason(db, game, identity, "public") if identity else "该席位当前无人操作"
    ) or chat_reason
    result.append(
        {
            "id": "public",
            "as_seat": seat["id"],
            "label": f"*公开讨论（{seat['id']}号）",
            "status": "active",
            "creator_id": "host",
            "members": [],
            "invited_ids": [],
            "accepted_ids": [],
            "invitation": "none",
            "can_send": not blocked and can_send,
            "reason": blocked,
            "actions": [],
        }
    )
    if not occupant:
        return result
    for row in db.execute("SELECT * FROM channels WHERE game_id=? ORDER BY rowid", (game["id"],)):
        members = json.loads(row["participant_ids"])
        if occupant not in members:
            continue
        reason = storage.channel_send_reason(db, game, identity, row["id"])
        if row["status"] != "active":
            reason = "等待全部成员同意" if row["status"] == "pending" else "私信已经结束"
        accepted = json.loads(row["accepted_ids"])
        result.append(
            {
                "id": row["id"],
                "as_seat": seat["id"],
                "label": f"*私密 · {puppet_channel_title(db, members)}",
                "status": row["status"],
                "creator_id": row["creator_id"],
                "members": [
                    {"id": member, "name": channel_names(db, [member]).get(member, "参与者"), "kind": "player"}
                    for member in members
                ],
                "invited_ids": json.loads(row["invited_ids"]),
                "accepted_ids": accepted,
                "invitation": "accepted" if occupant in accepted else "none",
                "can_send": not reason and row["status"] == "active",
                "reason": reason,
                "actions": [],
            }
        )
    return result


def channel_names(db, member_ids):
    """频道显示用的参与者称呼（views 自己的实现，避免与 api 层循环依赖）。"""
    names = {"host": "主持人"}
    if member_ids:
        placeholders = ",".join("?" for _ in member_ids)
        for row in db.execute(
            f"SELECT id,name FROM participants WHERE id IN ({placeholders})", member_ids
        ):
            names[row["id"]] = row["name"]
    return names


def puppet_channel_title(db, members):
    names = channel_names(db, [member for member in members if member != "host"])
    return "、".join("主持人" if member == "host" else names.get(member, "参与者") for member in members)


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
        # 频道名统一按成员生成：玩家用号位，主持人用「主持人」；观战者与未知身份回退名字。
        title = "、".join(
            "主持人"
            if member["kind"] == "host"
            else f"{member['seat_id']}号"
            if member["kind"] == "player" and member["seat_id"]
            else member["name"]
            for member in summaries
        )
        actions = channel_actions(row, actor, invitation, current) if not ended else []
        result.append(
            {
                "id": row["id"],
                "label": "私密 · " + title,
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
            description=(
                "关闭后除了你定向邀请的账号，其他账号不能再主动参局。"
                if game.get("join_open")
                else "开放后在线账号可以在大厅直接加入本局；席位随机分配。"
            ),
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
    # 受控傀儡席：把该席的频道视角挂在对应面板上，发送时用 as_seat 区分身份。
    controlled = (result.get("self") or {}).get("puppet_controls") or []
    ended = game["status"] == "ended"
    for panel in controlled:
        seat = next((s for s in game["seats"] if s["id"] == panel["seat_id"]), None)
        if not seat:
            panel["channels"] = []
            continue
        panel["channels"] = puppet_channel_view(db, game, seat)
        occupant = seat["occupant_id"]
        if not occupant:
            continue
        identity = {"id": occupant, "kind": "player"}
        puppet_actions = []
        if not ended and not storage.active_private_channel(db, game["id"], occupant):
            create = channel_create_descriptor(db, game, identity, participants)
            if create:
                puppet_actions.append(create)
        for row in db.execute(
            "SELECT * FROM channels WHERE game_id=? ORDER BY rowid", (game["id"],)
        ):
            members = json.loads(row["participant_ids"])
            if occupant not in members or row["status"] != "pending":
                continue
            if occupant not in json.loads(row["invited_ids"]):
                continue
            if occupant in json.loads(row["accepted_ids"]):
                continue
            puppet_actions.extend(channel_actions(row, identity, "pending", True))
        for descriptor in puppet_actions:
            # 同 :func:`puppet_action_panels`：星号只进 label，short_label 保持协议长度。
            descriptor["label"] = f"*{descriptor['label']}"
            descriptor["as_seat"] = seat["id"]
            descriptor["description"] = (
                f"傀儡视角 · {seat['id']}号；以该席位的公开身份建立或回应私信。"
            )
        panel["actions"].extend(puppet_actions)
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
    collected_channel_actions = [item for channel in result["channels"] for item in channel["actions"]]
    active_private = storage.active_private_channel(db, game["id"], actor["id"])
    if active_private and actor["kind"] != "host":
        result["actions"] = collected_channel_actions
    else:
        create_action = channel_create_descriptor(db, game, actor, participants)
        result["actions"].extend(
            ([create_action] if create_action else []) + collected_channel_actions
        )
    if (result.get("self") or {}).get("puppet_spectator"):
        # 傀儡席由控制者代操作：原玩家只读旁观，连私信类行动也不下发。
        result["actions"] = []
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
