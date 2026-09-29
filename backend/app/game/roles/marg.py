ID = "marg"
VERSION = 1
LABEL = "玛格"
REQUIRED = True
LAYER = "role"
DEPENDS = ()
HANDLERS = {}
COMMANDS = {}


def execute_declaration(game, events, declaration, target_card):
    card = game["cards"][declaration["card_id"]]
    card["uses"]["love_day"] = game["day"]
    game["marg_love"] = {
        "seat_id": declaration["data"]["target"],
        "card_id": target_card["id"],
        "day": game["day"],
    }


def active_love(game):
    """Today's declaration starts at night, not during that day's execution."""
    from ..state import present

    love = game.get("marg_love")
    if not love or not present(game, ID):
        return None
    if game["half"] != "night" and game["day"] <= love.get("day", 0):
        return None
    return love


def love_is_self(game):
    """A dead loved card redirects love, except legacy seat-only saves wait for the seat."""
    from ..state import current, seat

    love = active_love(game)
    if not love:
        return False
    cid = love.get("card_id")
    if not cid:
        return current(game, seat(game, love["seat_id"])) is None
    card = game["cards"].get(cid)
    return card is None or not card["alive"]


def loved_card_id(game):
    from ..state import current, owner, seat

    love = active_love(game)
    if not love:
        return None
    if love.get("card_id"):
        card = (
            current(game, owner(game, ID))
            if love_is_self(game)
            else game["cards"].get(love["card_id"])
        )
    else:
        card = current(game, seat(game, love["seat_id"])) or current(game, owner(game, ID))
    return card["id"] if card else None


def contribute_love_attack(game, attacks):
    love = active_love(game)
    if love:
        love["self"] = love_is_self(game)
        target = game["cards"].get(loved_card_id(game) or "")
        if target:
            attacks.append(
                {
                    "target_card": target["id"],
                    "source_card": ID,
                    "cause": "love",
                    "once_injury": True,
                }
            )
