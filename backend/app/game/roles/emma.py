ID = "emma"
VERSION = 1
LABEL = "艾玛"
REQUIRED = True
LAYER = "role"
DEPENDS = ()


def poison_exposed(game, card):
    """艾玛存活时，同席另一牌和左右邻席的当前牌中毒。"""
    from ..state import current, owner

    emma = game["cards"].get(ID)
    if not emma or not emma["alive"]:
        return False
    emma_seat = owner(game, emma["id"])
    target_seat = owner(game, card["id"])
    rest = (game.get("night") or {}).get("rest") or {}
    if (
        game["half"] == "night"
        and rest.get("day") == game["day"]
        and rest.get("seat_id") == target_seat["id"]
    ):
        return False
    if target_seat == emma_seat:
        return card["id"] != emma["id"]
    seats = game["seats"]
    distance = (seats.index(target_seat) - seats.index(emma_seat)) % len(seats)
    return distance in {1, len(seats) - 1} and current(game, target_seat) == card


def night_attacks(game, action):
    """Return one Emma action's attacks at its original position in the night queue."""
    ability = action["ability"]
    if ability == "massacre":
        if game["night"].get("locked"):
            game["night"]["massacre"] = action["card_id"]
        return [
            {"target_card": card["id"], "source_card": action["card_id"], "cause": ability}
            for card in game["cards"].values()
            if card["alive"] and card["id"] != action["card_id"]
        ]
    return []


def execute_declaration(game, events, declaration, target_card):
    """打断一次发言；假声明仍触发可被质疑撤销的当场打断。"""
    from ..state import require

    sid = declaration["seat_id"]
    target = declaration["data"].get("target")
    game["cards"][declaration["card_id"]]["uses"]["interrupt_day"] = game["day"]
    require(target != sid, "不能打断自己的发言")
    if game["phase"] == "speech":
        require(game["public"]["speaker"] == target, "只能打断当前发言者")
        previous_speaker = game["public"].get("interrupted_speaker")
        previous = next(
            (
                d
                for d in reversed(game["declarations"])
                if d["day"] == game["day"]
                and d.get("effects", {}).get("speaker") == target
                and d.get("effects", {}).get("interrupted_speaker") == previous_speaker
            ),
            None,
        )
        declaration["effects"] = {
            "interrupted_speaker": target,
            "speaker": sid,
            "previous_interrupt": previous["id"] if previous else None,
        }
        game["public"]["interrupted_speaker"] = target
        game["public"]["speaker"] = sid


def restore_interrupt(game, effects):
    public = game["public"]
    public["speaker"] = effects["interrupted_speaker"]
    public.pop("interrupted_speaker", None)
    previous = next(
        (d for d in game["declarations"] if d["id"] == effects.get("previous_interrupt")),
        None,
    )
    if previous:
        public["interrupted_speaker"] = previous["effects"]["interrupted_speaker"]


HANDLERS = {}
COMMANDS = {}
