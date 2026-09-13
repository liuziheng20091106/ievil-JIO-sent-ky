"""Allow-list projections: secrets never leave through the public view."""

from copy import deepcopy

from .actions import actions_for
from .catalog import PHASES
from .resolution import coco_seat
from .state import (
    can_use_card,
    current,
    eligible_voters,
    pending_nominators,
    owner,
    player_seat,
    require,
    role_card,
)


def host_tasks(game):
    """Ordered to-do list for the host: every item is either blocking or a reminder."""
    tasks = []
    for item in game["pending"]:
        tasks.append(
            {
                "id": item["id"],
                "kind": "pending",
                "title": item["title"],
                "detail": item.get("text", ""),
                "seats": [item["seat_id"]] if item.get("seat_id") else [],
                "action": "host.resolve",
                "payload": {"pending_id": item["id"]},
                "blocking": True,
            }
        )
    if game["status"] != "playing":
        return tasks

    def warn_task(kind, seat_id, title):
        tasks.append(
            {
                "id": f"{kind}:{seat_id}" if seat_id else kind,
                "kind": kind,
                "title": title,
                "detail": "",
                "seats": [seat_id] if seat_id else [],
                "action": "host.warn",
                "payload": {"seat_id": seat_id} if seat_id else {},
                "blocking": True,
            }
        )

    phase = game["phase"]
    if phase in {"night", "night_coco"}:
        coco = coco_seat(game) if phase == "night" else None
        for sid in game["night"]["actors"]:
            if sid in game["night"]["confirmed"] or sid == coco:
                continue
            warn_task("night", sid, f"{sid}号尚未确认夜间行动")
    elif phase == "speech" and game["public"]["speaker"]:
        sid = game["public"]["speaker"]
        warn_task("speech", sid, f"当前发言人：{sid}号")
    elif phase == "nomination":
        for sid in pending_nominators(game):
            warn_task("nomination", sid, f"{sid}号尚未提名或放弃（可与其他人同时提交）")
    elif phase == "voting":
        for s in eligible_voters(game):
            if s["id"] not in game["votes"]:
                warn_task("voting", s["id"], f"{s['id']}号尚未投票")
    elif phase == "execution":
        for cid in game["execution"]:
            if (
                cid != "nanoka"
                or not game["cards"][cid]["alive"]
                or role_card(game, cid)["uses"].get("bullets", 0) <= 0
            ):
                continue
            sid = owner(game, cid)["id"]
            if sid not in game["execution_ready"]:
                warn_task("execution", sid, f"{sid}号临刑开枪尚未确认")
    balloon = game["public"]["balloon"]
    if balloon["status"] == "collecting":
        for sid in balloon["participants"]:
            if sid not in game["balloon_choices"]:
                warn_task("balloon", sid, f"{sid}号尚未提交热气球选择")
    if phase == "night_review" and game["night"]["preview"] is not None:
        tasks.append(
            {
                "id": "review",
                "kind": "review",
                "title": "审阅本夜预结算并发布夜间结果",
                "detail": "",
                "seats": [],
                "action": "host.advance",
                "payload": {},
                "blocking": True,
            }
        )
    if game["winner_candidate"]:
        tasks.append(
            {
                "id": "winner",
                "kind": "winner",
                "title": "已满足胜利条件，等待确认宣判",
                "detail": game["winner_candidate"]["reason"],
                "seats": [],
                "action": "host.confirm_winner",
                "payload": {},
                "blocking": True,
            }
        )
    if game["surrenders"]:
        tasks.append(
            {
                "id": "surrender",
                "kind": "surrender",
                "title": "有交牌意向待审阅",
                "detail": "",
                "seats": list(game["surrenders"]),
                "action": "host.surrender",
                "payload": {},
                "blocking": True,
            }
        )
    return tasks


def card_view(game, card, host=False):
    result = {k: deepcopy(card[k]) for k in ("id", "role_id", "alive", "witch", "injured", "uses")}
    if host:
        result["states"] = deepcopy(card["states"])
    else:
        states = card["states"]
        result["states"] = {
            k: deepcopy(v)
            for k, v in states.items()
            if k
            in {
                "poisoned",
                "protected",
                "no_vote",
                "learned_brainwash",
                "paint_done",
                "evidence_allowed",
                "evidence_used",
                "witness_role",
                "entry_allowed",
            }
        }
        if states.get("puppet"):
            result["states"]["puppet_master_seat"] = owner(game, states["puppet"])["id"]
        if states.get("madness_target"):
            result["states"]["madness_target_seat"] = owner(game, states["madness_target"])["id"]
        if card["role_id"] == "noah":
            result["states"]["paintings"] = deepcopy(states.get("paintings", []))
    result["states"]["entry_allowed"] = can_use_card(game, card)
    return result


def game_view(game, actor):
    host = actor.get("kind") == "host"
    require(host or actor.get("game_id") == game["id"], "没有本局查看权限")
    own = player_seat(game, actor) if actor.get("kind") == "player" else None
    own_id = own["id"] if own else None
    seats = []
    ready_count = 0
    for s in game["seats"]:
        ready_count += bool(s["ready"])
        entry = {
            "id": s["id"],
            "name": s["name"],
            "avatar_role_id": None if game["status"] == "lobby" else s["avatar_role_id"],
            "occupied": bool(s["occupant_id"]),
            "ready": s["ready"] if host or s["id"] == own_id else None,
            "alive": game["status"] == "lobby" or current(game, s) is not None,
        }
        if host:
            entry["cards"] = [card_view(game, game["cards"][cid], True) for cid in s["cards"]]
        seats.append(entry)
    access = set(actor.get("access_ids", [])) | {actor.get("id")}
    information = [
        {k: deepcopy(item[k]) for k in ("id", "title", "text", "image_id") if k in item}
        for item in game["information"]
        if host or item["audience"] is None or access.intersection(item["audience"])
    ]
    public = deepcopy(game["public"])
    phase = game["phase"]
    if phase == "speech":
        public["current_actor"] = {
            "phase": "speech",
            "seat_id": public["speaker"],
            "label": "顺序发言",
        }
    elif phase == "nomination":
        pending = pending_nominators(game)
        public["current_actor"] = {
            "phase": "nomination",
            "seat_id": None,
            "label": f"同时提名（还有 {len(pending)} 人未提交）",
        }
    elif phase == "voting":
        public["current_actor"] = {
            "phase": "voting",
            "seat_id": game["public"]["votes"].get("candidate"),
            "label": "投票中",
        }
    elif phase == "execution":
        public["current_actor"] = {
            "phase": "execution",
            "seat_id": next(
                (
                    owner(game, cid)["id"]
                    for cid in game["execution"]
                    if owner(game, cid)["id"] not in game["execution_ready"]
                ),
                None,
            ),
            "label": "处决前响应",
        }
    elif phase == "balloon":
        public["current_actor"] = {
            "phase": "balloon",
            "seat_id": None,
            "label": "秘密选择中",
        }
    view = {
        "id": game["id"],
        "version": game["version"],
        "status": game["status"],
        "day": game["day"],
        "half": game["half"],
        "phase": game["phase"],
        "phase_label": PHASES[game["phase"]],
        "deadline": game["deadline"],
        "seats": seats,
        "ready_count": ready_count,
        "self": {
            "seat_id": own_id,
            "cards": [card_view(game, game["cards"][cid]) for cid in own["cards"]] if own else [],
            "current_card_id": current(game, own)["id"] if own and current(game, own) else None,
        },
        "actions": actions_for(game, actor),
        "information": information,
        "public": public,
        "result": deepcopy(game["result"]),
    }
    if own:
        night = game["night"]
        view["self"]["night_confirmed"] = own_id in night["confirmed"]
        view["self"]["night_actions"] = [
            {
                "ability": a["ability"],
                "target_seat": a.get("target_seat"),
                "confirmed": a.get("confirmed", False),
                "image_id": a.get("image_id"),
                "text": a.get("text", ""),
                "guess": deepcopy(a.get("guess", [])),
            }
            for a in night["actions"]
            if a["seat_id"] == own_id
        ]
        if game["water"]["holder"] == own_id and not game["water"]["used"]:
            view["self"]["water"] = True
        view["self"]["balloon_choice"] = game["balloon_choices"].get(own_id)
        view["self"]["vote"] = game["votes"].get(own_id)
        view["self"]["warning_deadline"] = game["warnings"].get(own_id)
        if (
            game["status"] == "lobby"
            and game["phase"] == "ordering"
            and "honoka" in own["cards"]
        ):
            # 穗乃香规则：开局前获知其他人的上层角色（仅文字角色名，不带头像）。
            view["self"]["honoka_upper"] = [
                {
                    "seat_id": s["id"],
                    "name": s["name"],
                    "role_id": game["cards"][s["cards"][0]]["role_id"],
                }
                for s in game["seats"]
                if s["ready"] and s["id"] != own_id and s["cards"]
            ]
    if host:
        view["host"] = {
            "codex": list(game["codex"]),
            "pending": deepcopy(game["pending"]),
            "night_actions": deepcopy(game["night"]["actions"]),
            "night_confirmed": list(game["night"]["confirmed"]),
            "night_preview": deepcopy(game["night"].get("preview")),
            "snapshots": [
                {k: s[k] for k in ("id", "day", "half", "phase", "label")}
                for s in game["snapshots"]
            ],
            "water": deepcopy(game["water"]),
            "balloon_choices": deepcopy(game["balloon_choices"]),
            "balloon_votes": deepcopy(game["balloon_votes"]),
            "votes": deepcopy(game["votes"]),
            "brainwash": deepcopy(game["brainwash"]),
            "deaths": deepcopy(game["deaths"]),
            "spiritual": deepcopy(game["spiritual"]),
            "winner_candidate": deepcopy(game["winner_candidate"]),
            "surrenders": list(game["surrenders"]),
            "warnings": deepcopy(game["warnings"]),
            "execution_rolls": deepcopy(game.get("execution_rolls", [])),
            "declarations": deepcopy(game["declarations"]),
            "nominations": deepcopy(game["nominations"]),
            "nomination_done": list(game.get("nomination_done", [])),
            "vote_rounds": deepcopy(game["vote_rounds"]),
            "photos": deepcopy(game["photos"]),
            "gaze": deepcopy(game.get("gaze")),
            "tasks": host_tasks(game),
        }
    can_chat, reason = False, "当前为只读状态"
    if host:
        can_chat, reason = (
            game["status"] != "ended",
            "" if game["status"] != "ended" else "对局已结束",
        )
    elif own and game["status"] == "lobby":
        can_chat, reason = True, ""
    elif own and game["status"] == "playing":
        if game["phase"] == "speech":
            can_chat = public["speaker"] == own_id
            reason = "" if can_chat else "顺序发言阶段，请等待你的发言顺序"
        elif game["half"] == "day" and current(game, own):
            can_chat, reason = True, ""
        else:
            reason = (
                "夜间与夜间结果阶段无公开发言；可私信主持人"
                if game["half"] == "night"
                else "当前角色已全部出局，等待主持人安排发言"
            )
    view["can_chat"], view["chat_reason"] = can_chat, reason
    return view
