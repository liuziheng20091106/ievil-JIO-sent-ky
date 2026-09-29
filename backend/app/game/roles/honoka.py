ID = "honoka"
VERSION = 1
LABEL = "穗乃香"
REQUIRED = True
LAYER = "role"
DEPENDS = ()
HANDLERS = {}


def apply_disguise(game, seat):
    """Apply a previously chosen disguise when the lower card enters."""
    from ..state import current

    card = game["cards"][ID]
    if current(game, seat) != card or card["states"].get("disguise_locked"):
        return None
    role = card["states"].get("disguise")
    if not role:
        return None
    card["states"]["disguise_locked"] = True
    seat["avatar_role_id"] = role
    return role


def queue_witness(game, events, item, suspects):
    from ..resolution import publish_witness
    from ..state import notify, owner, pending

    if ID not in suspects or not game["cards"][ID]["witch"]:
        publish_witness(game, events, item, suspects)
        return
    sid = owner(game, ID)["id"]
    pending(
        game,
        "honoka_witness",
        "穗乃香被列入目击：等待本人选择显示角色",
        seat_id=sid,
        victim=item["victim"],
        witness_seat=item["seat_id"],
        death_id=item.get("death_id"),
        suspects=list(suspects),
    )
    notify(
        game,
        events,
        "你被列入一份目击名单，请选择本次显示的角色；超时将显示穗乃香。",
        [sid],
        "目击改名",
    )


def resolve_witness(game, events, item, role=None):
    from ..resolution import publish_witness

    publish_witness(
        game, events, {**item, "seat_id": item["witness_seat"]}, item["suspects"], role or ID
    )
    game["pending"] = [
        pending_item for pending_item in game["pending"] if pending_item["id"] != item["id"]
    ]


def disguise(game, actor, events, payload, *, by_host=False):
    from ..catalog import ROLES
    from ..state import current, notify, owner, player_seat, require

    sid = player_seat(game, actor)["id"]
    seat = owner(game, ID)
    card = current(game, seat)
    hc = game["cards"][ID]
    require(seat["id"] == sid, "只有穗乃香可以选择示人角色")
    if game["status"] == "lobby":
        hc["states"]["disguise"] = payload["role"]
        notify(
            game,
            events,
            f"开局前示人选择已记录：{ROLES[payload['role']]['name']}（穗乃香登场时生效）。",
            [sid],
            "穗乃香示人",
        )
        return
    require(hc["alive"], "穗乃香已经出局")
    require(not hc["states"].get("disguise_locked"), "示人角色已经确定，不能再更改")
    hc["states"]["disguise"] = payload["role"]
    if card and card["id"] == ID:
        hc["states"]["disguise_locked"] = True
        seat["avatar_role_id"] = payload["role"]
        notify(game, events, f"{sid}号示人为{ROLES[payload['role']]['name']}。", [], "穗乃香示人")
    else:
        notify(
            game,
            events,
            f"示人选择已记录：{ROLES[payload['role']]['name']}（登场时生效）。",
            [sid],
            "穗乃香示人",
        )


def witness(game, actor, events, payload, *, by_host=False):
    from ..state import player_seat

    sid = player_seat(game, actor)["id"]
    item = next(
        pending_item
        for pending_item in game["pending"]
        if pending_item["id"] == payload["pending_id"]
        and pending_item["kind"] == "honoka_witness"
        and pending_item["seat_id"] == sid
    )
    resolve_witness(game, events, item, payload["role"])


def panel_actions(game, actor, *, as_seat=None):
    from ..actions import action, field, role_options
    from ..state import current, owner, player_seat, seat

    if actor.get("kind") != "player":
        return []

    sid = as_seat or player_seat(game, actor)["id"]
    current_card = current(game, seat(game, sid))
    result = []
    if game["status"] == "lobby":
        if ID in seat(game, sid)["cards"]:
            result.append(
                action(
                    "honoka.disguise",
                    "选择示人角色（穗乃香）",
                    [field("role", "示人身份", "select", role_options())],
                    group="准备",
                    short_label="示人",
                    description="穗乃香选择一个示人角色：只改别人看到的角色名，不获得该角色的技能。",
                )
            )
        return result
    item = next(
        (
            item
            for item in game["pending"]
            if item["kind"] == "honoka_witness" and item["seat_id"] == sid
        ),
        None,
    )
    if item:
        result.append(
            action(
                "honoka.witness",
                "选择本次目击名单中的显示角色",
                [field("role", "名单显示身份", "select", role_options())],
                {"pending_id": item["id"]},
                "私密信息",
                short_label="目击",
                description="选择本次目击名单里显示的角色；这是穗乃香的魔女化技能。",
                blocking=True,
            )
        )
    hc = game["cards"][ID]
    if (
        not actor.get("puppet_controlled")
        and as_seat in (None, player_seat(game, actor)["id"])
        and hc["alive"]
        and owner(game, ID)["id"] == sid
        and not hc["states"].get("disguise_locked")
    ):
        result.append(
            action(
                "honoka.disguise",
                "选择示人角色（登场时生效）"
                if not current_card or current_card["id"] != ID
                else "选择示人角色",
                [field("role", "示人身份", "select", role_options())],
                short_label="示人",
                description="穗乃香选择一个示人角色：只改别人看到的角色名，不获得该角色的技能。",
            )
        )
    return result


COMMANDS = {"honoka.disguise": disguise, "honoka.witness": witness}
