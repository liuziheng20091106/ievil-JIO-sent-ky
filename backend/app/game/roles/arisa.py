from random import SystemRandom

ID = "arisa"
VERSION = 1
LABEL = "亚里沙"
REQUIRED = True
LAYER = "role"
DEPENDS = ()
HANDLERS = {}
COMMANDS = {}


def roll_injuries(game, action):
    """Roll once at night lock; intents later consume these fixed target cards."""
    from ..state import current, log_event, owner

    card = game["cards"][action["card_id"]]
    seats = game["seats"]
    index = seats.index(owner(game, card["id"]))
    action["injuries"] = []
    for neighbor in (seats[(index - 1) % len(seats)], seats[(index + 1) % len(seats)]):
        target = current(game, neighbor)
        roll = SystemRandom().randrange(2)
        injured = roll == 0 and target is not None
        if injured:
            action["injuries"].append(target["id"])
        log_event(
            game,
            "roll",
            f"亚里沙令{neighbor['id']}号邻座负伤：骰值{roll}，{'发生' if injured else '未发生'}。",
        )


def contribute_attacks(action, attacks):
    attacks.extend(
        {
            "target_card": target_id,
            "source_card": action["card_id"],
            "cause": "arisa_injure",
            "once_injury": True,
        }
        for target_id in action.get("injuries", [])
    )
