ID = "meruru"
VERSION = 1
LABEL = "梅露露"
REQUIRED = True
LAYER = "role"
DEPENDS = ()
HANDLERS = {}


def panel_actions(game, actor, *, as_seat=None):
    from ..actions import action, field
    from ..state import can_use_ability, current, player_seat, revive_deaths, revive_declined

    if actor.get("kind") != "player":
        return []
    own = player_seat(game, actor)
    if as_seat and as_seat != own["id"]:
        return []
    card = current(game, own)
    if not (
        can_use_ability(game, card)
        and card["id"] == ID
        and card["witch"]
        and not card["uses"].get("revive")
        and game["half"] == "night"
        and not revive_declined(game)
    ):
        return []
    deaths = revive_deaths(game)
    if not deaths:
        return []
    return [
        action(
            "meruru.revive",
            "复活当夜所杀者为无角色技能的傀儡",
            [
                field(
                    "death_id",
                    "复活对象",
                    "select",
                    [(death["id"], f"{death['seat_id']}号当夜出局的角色牌") for death in deaths],
                )
            ],
            short_label="复活",
            description="魔女梅露露复活当夜自己击杀的牌；复活者失去投票权和角色技能、由主人代操作，死亡公告撤销，但魔女袭击目击保留；主人出局时傀儡当前牌随之出局。",
        )
    ]


def revoke_death(game, events, death):
    """撤销死亡而保留魔女袭击的目击：被指到的事实不因复活消失。"""
    from ..resolution import WITCH_ATTACK_CAUSES, witness_label, witness_size
    from ..state import check_winner, half_key

    cid, sid = death["target_card"], death["seat_id"]
    keeps_witness = death.get("cause") in WITCH_ATTACK_CAUSES
    game["deaths"] = [item for item in game["deaths"] if item["id"] != death["id"]]
    game["queued_notices"] = [
        notice for notice in game["queued_notices"] if notice != death.get("notice")
    ]
    game["queued_reveals"] = [item for item in game["queued_reveals"] if item["seat_id"] != sid]
    game["queued_deaths"] = [
        item for item in game.get("queued_deaths", []) if item["seat_id"] != sid
    ]
    game["pending"] = [
        item
        for item in game["pending"]
        if not (
            (
                item.get("death_id") == death["id"]
                or (item["kind"] == "suspects" and item.get("victim") == cid)
            )
            and not keeps_witness
        )
    ]
    if keeps_witness:
        for item in game["pending"]:
            if item["kind"] == "suspects" and (
                item.get("death_id") == death["id"] or item.get("victim") == cid
            ):
                item["title"] = (
                    f"{sid}号已被复活，被袭击的目击照发：填写{witness_label(witness_size(game))}"
                )
                item["text"] = item["title"]
    if game.get("witness") and game["witness"].get("death_id") == death["id"] and not keeps_witness:
        game["witness"] = None
    game["cards"][cid]["states"].pop("evidence_allowed", None)
    if game["half_exits"].get(sid) == half_key(game):
        del game["half_exits"][sid]
    check_winner(game)


def revive_command(game, actor, events, payload, *, by_host=False):
    from ..resolution import revive
    from ..state import can_use_ability, current, player_seat, require, revive_declined

    own = player_seat(game, actor)
    card = current(game, own)
    require(
        can_use_ability(game, card)
        and card["id"] == ID
        and card["witch"]
        and not card["uses"].get("revive")
        and game["half"] == "night"
        and not revive_declined(game),
        "当前不能复活",
    )
    assert card is not None
    death = next((d for d in game["deaths"] if d["id"] == payload["death_id"]), None)
    require(
        death is not None
        and death["day"] == game["day"]
        and death["half"] == "night"
        and death.get("source_card") == card["id"],
        "只能复活当夜由该梅露露牌造成的死亡",
    )
    assert death is not None
    require(not game["cards"][death["target_card"]]["alive"], "该死亡已被处理")
    card["uses"]["revive"] = True
    revoke_death(game, events, death)
    revive(game, events, death["target_card"], puppet=card["id"])


COMMANDS = {"meruru.revive": revive_command}


def sync_puppet_bonds(game, events):
    """主人死亡带走当前傀儡；失去操控权只解除关系。"""
    from ..engine import apply_damage
    from ..resolution import resolve_intents
    from ..state import (
        current,
        notify,
        orphan_puppet_cards,
        owner,
        puppet_master_dead,
        release_puppet,
    )

    doomed = [
        card
        for card in orphan_puppet_cards(game)
        if puppet_master_dead(game, card)
        and card["alive"]
        and current(game, owner(game, card["id"])) == card
    ]
    if doomed:
        attacks = [
            {
                "target_card": card["id"],
                "source_card": None,
                "cause": "puppet",
                "unconditional": True,
            }
            for card in doomed
        ]
        if apply_damage(game, events, resolve_intents(game, events, attacks, substitute=False)):
            return
    for card in orphan_puppet_cards(game):
        holder = owner(game, card["id"])
        was_active = card["alive"] and current(game, holder) == card
        release_puppet(card)
        if was_active:
            notify(
                game,
                events,
                "控制关系已解除：你恢复了普通玩家权限。",
                [holder["id"]],
                "傀儡解除",
            )
