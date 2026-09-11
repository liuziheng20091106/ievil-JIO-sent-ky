"""Allow-list projections: secrets never leave through the public view."""

from copy import deepcopy

from .actions import actions_for
from .catalog import PHASES
from .state import can_use_card, current, next_nominator, owner, player_seat, require


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
    for s in game["seats"]:
        entry = {
            "id": s["id"],
            "name": s["name"],
            "avatar_role_id": None if game["status"] == "lobby" else s["avatar_role_id"],
            "occupied": bool(s["occupant_id"]),
            "ready": s["ready"],
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
    if game["phase"] == "nomination":
        public["nomination_speaker"] = next_nominator(game)
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
