"""One permission projection shared by HTTP, WebSocket, chat, and evidence."""

import json

from . import storage
from .game import game_view
from .game.actions import action, field, outstanding_seats
from .game.catalog import AUTO_PHASES, night_half
from .game.state import (
    actor_eliminated,
    display_player_name,
    host_capable,
    host_label,
    seat_eliminated,
)
from .game.views import SPEECH_WAIT_REASON, seat_chat
from .storage import SPECTATOR_CHANNEL


# 「请求操作」催办：自己的行动正卡住流程时的标题与说明，由服务端决定何时显示、显示什么。
BLOCKING_PROMPTS = {
    "night": ("请完成本夜行动", "选择行动后确认；也可以放弃并确认。"),
    "night_coco": ("请完成最后的夜间行动", "其余人的夜间行动已锁定，只等你提交。"),
    "speech": ("轮到你顺序发言", "发言、打断，或点「本轮不发言」跳过你的顺序。"),
    "nomination": ("请提交提名或放弃", "同一人可以被多人提名；提交即生效。"),
    "voting": ("请投票", "严格超过有投票权存活玩家的一半才会处决。"),
    "execution": ("请完成临刑响应", "有临刑开枪机会时先选目标开枪；每枪都要重新选目标，子弹没打完前可以接着开，也可以随时收手并确认。"),
}


def seat_number_list(seats):
    """「3号、4号」：横幅里按座位号顺序列出等待中的席位。

    outstanding_seats 按发言顺序（而不是编号）返回，直接拼接会出现
    「正在等待7号、6号、5号玩家提名」这种读不通的排列。
    """
    return "、".join(f"{seat}号" for seat in sorted(seats, key=int))


def host_blocking(game):
    """流程是不是卡在主持人身上：玩家都做完了，却还得等主持人动手。

    只算真正让流程停住的阻塞——待裁定事项、胜负宣判、必须由主持人推进的阶段
    （预结算发布、夜间结果、天黑结算），以及被主持人暂停的自动推进。交牌申请
    只是主持人的待办，不挡流程，因此不算。
    """
    if game["status"] != "playing" or outstanding_seats(game):
        return False
    if any(item["kind"] != "honoka_witness" for item in game["pending"]):
        return True
    if game["winner_candidate"]:
        return True
    if game["phase"] == "night_review":
        return game["night"]["preview"] is not None
    if game["phase"] not in AUTO_PHASES:
        return True
    return bool(game["public"].get("auto_advance_off"))


def public_notice(game):
    """全场横幅：当前轮到谁发言、还在等谁动手、是不是只等主持人。

    与个人催办框同一份文案来源，但内容对全场一致，且绝不泄露夜间进度：
    夜间只报「仍有玩家未完成行动」——列出席位等于当众公开谁有夜间技能。
    没有值得公示的进度时返回 None。
    """
    if game["status"] != "playing":
        return None
    phase = game["phase"]
    waiting = outstanding_seats(game)
    if phase == "speech":
        # 轮到的席位本人另有「轮到你顺序发言」的个人催办，这里通报给其他人。
        speaker = game["public"].get("speaker")
        if speaker:
            return f"当前轮到{speaker}号玩家发言"
    elif phase in {"nomination", "voting"} and waiting:
        action = "提名" if phase == "nomination" else "投票"
        return f"正在等待{seat_number_list(waiting)}玩家{action}"
    if waiting and night_half(game):
        # 整个夜间只报「还有玩家没做完」：列出席位等于公开谁有夜间技能。
        return "仍有玩家未完成行动"
    if phase == "discussion":
        # 自由发言由「已有 n/所需人数 人请求结束」的进度条表示，不在这里提示等主持人。
        return None
    if host_blocking(game):
        return "等待主持人进行操作"
    return None


def action_prompt(game, actor, active_private):
    """客户端顶部常驻的横幅：先是卡在本人身上的操作，其次才是全场进度。

    返回 None 表示当前没有要给这名玩家看的内容。内容与时机都由服务端判定，
    客户端只负责醒目地展示；玩家在私聊里时额外说明要先结束私聊。
    """
    if actor["kind"] != "player" or game["status"] == "ended":
        return None
    seat = next((s for s in game["seats"] if s["occupant_id"] == actor["id"]), None)
    if not seat:
        return None
    blocking = True
    if game["status"] == "lobby":
        if seat["ready"]:
            return None
        if game["phase"] == "ordering":
            title, text = "请确认上下牌并再次准备", "七名玩家再次准备后，主持人才会开局。"
        else:
            title, text = "请点击文本框下发的*准备*按钮", "七名玩家全部准备后，系统才会发牌。"
    elif seat["id"] in outstanding_seats(game):
        title, text = BLOCKING_PROMPTS.get(
            game["phase"], ("请在行动区域完成当前操作", "你的操作正在阻塞流程推进。")
        )
    else:
        notice = public_notice(game)
        if notice is None:
            return None
        # 全场横幅只是通报进度，不提示「先结束私聊才能行动」。
        blocking, title, text = False, notice, ""
    return {
        "title": title,
        "text": text,
        "hint": "你正在私聊中：先结束私聊，才能执行上面的操作。"
        if blocking and active_private
        else None,
    }


def result_title(result):
    """结算标题：终止对局不再显示成一个阵营获胜（与客户端 _resultTitle 同文案）。"""
    winner = (result or {}).get("winner") or ""
    if winner == "good":
        return "本局已结束 · 好人获胜"
    if winner == "witch":
        return "本局已结束 · 魔女获胜"
    if winner == "aborted":
        return "本局已终止"
    return "本局已结束"


def dialogs(game, actor, domain_view):
    """对局内悬浮对话框：结束信息 / 私聊申请 / 当日目击名单，列表顺序即优先级。

    什么时候弹什么由服务端决定（客户端只渲染）：结束信息取本局结算，私聊申请取
    频道投影里「等我回应」的那几条，目击名单取服务端已经按身份裁剪过的 ``witness``。
    同意/拒绝直接复用频道投影里那份 channel.accept/channel.reject 动作描述，提交时
    仍走 ``require_listed_action`` 的同一套校验，服务端不放宽任何权限。
    """
    items = []
    result = game.get("result")
    if result:
        items.append(
            {
                "id": f"result:{game['id']}",
                "kind": "result",
                "title": result_title(result),
                "text": result.get("reason", ""),
                "dismissible": True,
                "actions": [],
                "match_id": game["id"],
            }
        )
    if game["status"] != "ended":
        for channel in domain_view.get("channels", []):
            if channel.get("invitation") != "pending":
                continue
            creator = next(
                (
                    member
                    for member in channel.get("members", [])
                    if member.get("id") == channel.get("creator_id")
                ),
                None,
            )
            who = (creator or {}).get("name") or "其他人"
            seat = (creator or {}).get("seat_id")
            items.append(
                {
                    "id": f"channel:{channel['id']}",
                    "kind": "channel_invite",
                    "title": "私聊申请",
                    "text": f"{seat}号 {who} 邀请你加入私信；同意后双方才能发言。"
                    if seat
                    else f"{who} 邀请你加入私信；同意后双方才能发言。",
                    "dismissible": True,
                    "actions": list(channel.get("actions") or []),
                }
            )
    witness = domain_view.get("witness")
    if witness:
        items.append(
            {
                "id": f"witness:{game['id']}:{witness.get('day')}",
                "kind": "witness",
                "title": "当日目击名单",
                "text": witness.get("text", ""),
                "dismissible": True,
                "actions": [],
            }
        )
    return items


def participant_rows(db, game_id):
    return list(db.execute("SELECT * FROM participants WHERE game_id=? ORDER BY rowid", (game_id,)))


def participant_summary(row):
    return {
        "id": row["id"],
        "name": display_player_name(row["name"]),
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
    can_send, chat_reason, chat_transient = seat_chat(game, seat)
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
            "blocked_transient": blocked == chat_reason and chat_transient,
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
                "label": f"*私密 · {puppet_channel_title(db, members, host_label(game))}",
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


def channel_names(db, member_ids, host_name="主持人"):
    """频道显示用的参与者称呼（views 自己的实现，避免与 api 层循环依赖）。"""
    names = {"host": host_name}
    if member_ids:
        placeholders = ",".join("?" for _ in member_ids)
        for row in db.execute(
            f"SELECT id,name FROM participants WHERE id IN ({placeholders})", member_ids
        ):
            names[row["id"]] = display_player_name(row["name"])
    return names


def puppet_channel_title(db, members, host_name="主持人"):
    names = channel_names(db, [member for member in members if member != "host"], host_name)
    return "、".join(host_name if member == "host" else names.get(member, "参与者") for member in members)


def channels_for(db, game, actor, domain_view):
    ended = game["status"] == "ended"
    participants = participant_rows(db, game["id"])
    by_id = {row["id"]: row for row in participants}
    # 对局内的「主持人」一律带上本局主持人的昵称，玩家才分得清是谁在主持。
    host_name = host_label(game)
    if actor.get("kind") == "spectator":
        # 观战者独享观战频道：只下发观战频道与系统频道，没有公屏与私信。
        reason = storage.channel_send_reason(db, game, actor, SPECTATOR_CHANNEL)
        return [
            {
                "id": SPECTATOR_CHANNEL,
                "label": "观战频道",
                "status": "active",
                "creator_id": "host",
                "members": [],
                "invited_ids": [],
                "accepted_ids": [],
                "invitation": "none",
                "can_send": not ended and not reason,
                "reason": reason or ("本局已经结束" if ended else ""),
                "actions": [],
            },
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
            },
        ]
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
            # 频道级失效（夜间关闭、出局等）才触发客户端的「自动切换到可用频道」；
            # 顺序发言的「等待你的发言顺序」是临时等待，标记出来让客户端跳过。
            "blocked_transient": public_reason == SPEECH_WAIT_REASON
            and not domain_view.get("can_chat", False),
            "actions": [],
        }
    ]
    for row in db.execute("SELECT * FROM channels WHERE game_id=? ORDER BY rowid", (game["id"],)):
        members = json.loads(row["participant_ids"])
        if not host_capable(actor) and not set(actor["access_ids"]).intersection(members):
            continue
        invited = json.loads(row["invited_ids"])
        accepted = json.loads(row["accepted_ids"])
        current = host_capable(actor) or actor["id"] in members
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
                summaries.append({"id": "host", "name": host_name, "kind": "host", "seat_id": None})
            elif member_id in by_id:
                summaries.append(participant_summary(by_id[member_id]))
        # 频道名统一按成员生成：玩家用号位，主持人用「主持人(昵称)」；观战者与未知身份回退名字。
        title = "、".join(
            host_name
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
    if host_capable(actor):
        # 观战频道对主持人开放：可见、可发言（玩家永远看不到它）。
        spectator_reason = storage.channel_send_reason(db, game, actor, SPECTATOR_CHANNEL)
        result.append(
            {
                "id": SPECTATOR_CHANNEL,
                "label": "观战频道",
                "status": "active",
                "creator_id": "host",
                "members": [],
                "invited_ids": [],
                "accepted_ids": [],
                "invitation": "none",
                "can_send": not ended and not spectator_reason,
                "reason": spectator_reason or ("本局已经结束" if ended else ""),
                "actions": [],
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
    if game["status"] == "ended" or storage.active_private_channel(db, game, actor["id"]):
        return None
    if actor.get("kind") == "spectator":
        # 观战者独享观战频道，不能发起任何私信。
        return None
    host = host_capable(actor)
    night = night_half(game)
    # 夜间与「整席出局」都只允许与主持人私聊：两者对玩家是同一个独占限制，
    # 出局判定按当前牌现场求值，回溯或复活后自动恢复多人私信。
    exclusive = not host and (night or actor_eliminated(game, actor))
    options = []
    if not host:
        options.append(("host", host_label(game)))
    if host or not exclusive:
        for row in participants:
            # 观战者已收拢进观战频道：私信邀请名单不再出现他们。
            if not row["active"] or row["blocked"] or row["id"] == actor["id"]:
                continue
            if row["kind"] == "spectator":
                continue
            # 已出局的玩家除了主持人谁都不该再私信，因此也不再出现在邀请名单里。
            if not host and seat_eliminated(game, row["seat_id"]):
                continue
            options.append((row["id"], display_player_name(row["name"])))
    if not options:
        return None
    if exclusive and not night:
        extra = {"description": "已整席出局：只能与主持人私信；复活后恢复多人私信。"}
    elif exclusive:
        extra = {"description": "夜间只能与主持人建立私聊；天黑时全部私信频道已结束。"}
    else:
        extra = {}
    return action(
        "channel.create",
        "创建与主持人的私聊" if exclusive else "创建一对一或多人私信",
        [
            field(
                "participant_ids",
                "邀请成员",
                "multiselect",
                options,
                min=1,
                max=1 if exclusive else 20,
            ),
        ],
        group="私信",
        short_label="建私信",
        **extra,
    )


def runtime_actions(game, participants):
    seats = [
        {
            "value": seat["id"],
            "label": seat["id"]
            + "号 · "
            + (display_player_name(seat["name"]) or "空席"),
        }
        for seat in game["seats"]
        if not seat["occupant_id"]
    ]
    active = [row for row in participants if row["active"] and not row["blocked"]]
    people = [
        {
            "value": row["id"],
            "label": display_player_name(row["name"])
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
        if not ended and not storage.active_private_channel(db, game, occupant):
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
            {
                "seat_id": people[pid]["seat_id"],
                "name": display_player_name(people[pid]["name"]),
            }
            for pid in result["result"].get("personal_losses", [])
            if pid in people
        ]
    collected_channel_actions = [item for channel in result["channels"] for item in channel["actions"]]
    active_private = storage.active_private_channel(db, game, actor["id"])
    if actor.get("kind") == "spectator":
        # 观战者没有私信：不下发任何 channel.* 行动。
        result["actions"] = []
    elif active_private and not host_capable(actor):
        result["actions"] = collected_channel_actions
    else:
        create_action = channel_create_descriptor(db, game, actor, participants)
        result["actions"].extend(
            ([create_action] if create_action else []) + collected_channel_actions
        )
    puppet_spectator = bool((result.get("self") or {}).get("puppet_spectator"))
    if puppet_spectator:
        # 傀儡席由控制者代操作：原玩家只读旁观，连私信类行动也不下发。
        result["actions"] = []
    if not puppet_spectator:
        prompt = action_prompt(game, actor, bool(active_private) and not host_capable(actor))
        if prompt:
            result["action_prompt"] = prompt
    if host_capable(actor):
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
    if actor.get("kind") == "host" and not host_capable(actor):
        # 未确认进入本局管理界面：连私信入口都不给，主持人这一步只能去确认。
        # 客户端的确认页也不依赖这些行动，所以清空不会挡住进入流程。
        result["actions"] = []
    # 悬浮对话框：服务端决定「什么时候弹什么」，客户端只负责渲染与交互。
    result["dialogs"] = dialogs(game, actor, result)
    return result
