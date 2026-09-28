"""Fixed intent/roll night resolution, damage previews, and linked exits."""

from copy import deepcopy
from random import SystemRandom

from .catalog import NIGHT_ABILITIES, ROLES
from .state import (
    apply_honoka_disguise,
    card_actionable,
    fallen_upper_role,
    check_winner,
    current,
    effect_effective,
    half_key,
    hiro_rewind,
    log_event,
    notify,
    owner,
    pending,
    present,
    protection_active,
    release_puppet,
    require,
    role_card,
    seat,
    uid,
)


def information(game, events, card, title, truth, false_text, image_id=None):
    sid = owner(game, card["id"])["id"]
    # 中毒只影响这条信息是真是假，不告诉本人掷骰结果（主持人日志里仍有中毒骰）。
    text = (
        truth
        if effect_effective(game, card, f"信息：{title}")
        else false_text
    )
    notify(game, events, text, [sid], title, image_id)

def witch_information(game, events):
    if present(game, "coco") and role_card(game, "coco")["witch"]:
        codex = game["codex"]
        information(
            game,
            events,
            role_card(game, "coco"),
            "魔女可可线索",
            "魔典顺序：" + "、".join(ROLES[r]["name"] for r in codex),
            "魔典顺序：" + "、".join(ROLES[r]["name"] for r in codex[-1:] + codex[:-1]),
        )


def night_text(game, actions):
    """可可看到的夜间行动清单。

    除玩家提交的行动外，还要带上 `extra_attacks` 里的额外攻击（主持人伤害、13 水），
    否则可可的「查看其他全部夜间行动」与照片授权报告都会漏掉这两类。
    """
    lines = [
        f"{a['seat_id']}号：{NIGHT_ABILITIES[a['ability']][1]}"
        + (f"，目标{a['target_seat']}号" if a.get("target_seat") else "")
        for a in actions
    ]
    for attack in (game.get("night") or {}).get("extra_attacks", []):
        source = game["cards"].get(attack.get("source_card"))
        target = game["cards"].get(attack.get("target_card"))
        who = f"{owner(game, source['id'])['id']}号" if source else "主持人"
        where = f"，目标{owner(game, target['id'])['id']}号" if target else ""
        label = {"water": "13水", "host": "主持人伤害"}.get(
            attack.get("cause"), attack.get("cause") or ""
        )
        lines.append(f"{who}：{label}{where}")
    return "\n".join(lines) or "其余玩家均未发动行动。"


def sync_night_confirmations(game, events):
    """把「本夜没有任何可提交行动」的席位补进已确认集合。

    傀儡化、失去技能或出局都可能在一夜之间发生（主持人裁定、魔女化、复活的
    傀儡牌），这些席位既不会拿到行动也不该留下阻塞待办，因此统一在这里对齐。
    """
    if game["status"] != "playing" or game["phase"] not in {"night", "night_coco"}:
        return
    # actions imports this module; the ability list stays a local import to avoid a cycle.
    from .actions import night_abilities

    night = game["night"]

    def drivable(cid):
        card = game["cards"].get(cid)
        return bool(card) and card_actionable(game, card) and night_abilities(game, card)

    for sid, cid in night["actors"].items():
        if sid in night["confirmed"] or drivable(cid):
            continue
        night["confirmed"].append(sid)
        notify(game, events, "本夜你没有可执行的技能，已自动确认（未操作视为放弃）。", [sid])


def begin_night(game, events):
    game["half"] = "night"
    game["phase"] = "night"
    # 上一夜未使用的13水过期收回；米莉亚的换血目标单独持久保存，直到下次有效换血覆盖。
    game["water"] = {"holders": []}
    game["night"] = {
        "actors": {s["id"]: current(game, s)["id"] for s in game["seats"] if current(game, s)},
        "actions": [],
        "confirmed": [],
        "locked": False,
        "preview": None,
        "reactions": [],
        # 本夜梅露露是否已经放弃复活：主持人推进或30秒警告到点时写入，入口随之关闭。
        "revive_declined": False,
    }
    # 用 card_actionable：傀儡牌由控制它的梅露露代行，不能当「本夜无事可做」自动确认掉。
    sync_night_confirmations(game, events)
    witch_information(game, events)
    notify(game, events, "夜间行动开始，请选择行动后确认；也可放弃并确认。")
    # Everyone else auto-confirming can leave Coco as the only pending actor; nobody
    # would trigger the final confirmation step for her otherwise.
    unlock_coco(game, events)


def coco_seat(game):
    card = role_card(game, "coco")
    sid = owner(game, card["id"])["id"]
    return sid if card["witch"] and game["night"]["actors"].get(sid) == card["id"] else None


def unlock_coco(game, events):
    cs = coco_seat(game)
    others = set(game["night"]["actors"]) - ({cs} if cs else set())
    if cs and others.issubset(game["night"]["confirmed"]) and game["phase"] == "night":
        game["phase"] = "night_coco"
        information(
            game,
            events,
            role_card(game, "coco"),
            "其余夜间行动已锁定",
            night_text(game, game["night"]["actions"]),
            "中毒幻觉：未辨识到有效夜间行动",
        )


def target_allowed(game, target_card_id):
    return True


def treasure_protected(game, target_card_id):
    """这张牌当天是否受寻宝保护：魔女刀、蕾雅决斗与提名都不能选中它。"""
    return game["cards"][target_card_id]["states"].get("treasure_protected_day") == game["day"]


def active_love(game):
    """玛格的爱此刻是否已经生效。

    声明当天白天不生效：爱要等当天夜里才开始起作用（因此当天处决不受它保护）。
    """
    love = game.get("marg_love")
    if not love or not present(game, "marg"):
        return None
    if game["half"] != "night" and game["day"] <= love.get("day", 0):
        return None
    return love


def love_is_self(game):
    """玛格是否已经转爱自己。

    用户批注（B20）：被爱的那张角色牌出局即转爱自己，不再等整席两张牌都出局。
    老状态下没有记下被爱的牌（``card_id`` 缺失）时退回「被爱席位整席出局」的旧口径。
    """
    love = active_love(game)
    if not love:
        return False
    cid = love.get("card_id")
    if not cid:
        return current(game, seat(game, love["seat_id"])) is None
    card = game["cards"].get(cid)
    return card is None or not card["alive"]


def loved_card_id(game):
    """玛格当前爱人的角色牌；被爱的那张牌出局后，玛格转爱自己。

    玛格的爱在结算顺序里优先级最高，见 damage_preview 与 millia_substitute。
    """
    love = active_love(game)
    if not love:
        return None
    if love.get("card_id"):
        card = (
            current(game, owner(game, "marg"))
            if love_is_self(game)
            else game["cards"].get(love["card_id"])
        )
    else:
        # 兼容没有记下具体牌的老状态：按被爱席位的当前牌算，整席出局才转爱自己。
        card = current(game, seat(game, love["seat_id"])) or current(game, owner(game, "marg"))
    return card["id"] if card else None


def force_millia_swap(game, events):
    """米莉亚的换血是强制 debuff：忘交或超时的时候由系统随机指定一名玩家。

    没有任何合法目标（除自己外没有别的当前牌）时免于强制，避免整夜无人推进。
    """
    millia = role_card(game, "millia")
    night = game["night"]
    sid = owner(game, "millia")["id"]
    actors = night.get("actors") or {}
    if not millia["alive"] or not isinstance(actors, dict) or actors.get(sid) != millia["id"]:
        return
    if any(a["seat_id"] == sid and a["ability"] == "swap" for a in night["actions"]):
        return
    options = [s["id"] for s in game["seats"] if s["id"] != sid and current(game, s)]
    if not options:
        return
    target = SystemRandom().choice(options)
    target_card = current(game, seat(game, target))
    game["millia_swap"] = {"seat": target, "day": game["day"]}
    night["actions"].append(
        {
            "id": uid(),
            "seat_id": sid,
            "participant_id": seat(game, sid)["occupant_id"],
            "card_id": millia["id"],
            "ability": "swap",
            "target_seat": target,
            "target_card": target_card["id"],
            "confirmed": True,
            "by_host": True,
            "forced": True,
            "title": f"{sid}号夜间选择",
        }
    )
    log_event(game, "system", f"米莉亚未提交换血，系统随机指定{target}号。")
    notify(game, events, f"你本夜未提交换血，系统已随机指定{target}号为目标。", [sid], "换血强制")


def lock_night(game, events):
    night = game["night"]
    require(not night["locked"], "本夜已经锁定")
    require(set(night["actors"]).issubset(night["confirmed"]), "仍有玩家未确认；可先警告并等待30秒")
    force_millia_swap(game, events)
    night["locked"] = True
    for action in night["actions"]:
        card = game["cards"][action["card_id"]]
        ability = action["ability"]
        action["title"] = f"{action['seat_id']}号 · {NIGHT_ABILITIES[ability][1]}"
        if action.get("resolved"):
            continue
        # 夜间技能都不吃中毒效果骰，锁定后一律视为生效；信息类在下面的分支单独结算。
        action["effective"] = True
        if ability == "witch_scan":
            cards = list(game["cards"].values())
            information(
                game,
                events,
                card,
                "全员魔女化状态",
                "；".join(f"{ROLES[c['role_id']]['name']}：{'魔女' if c['witch'] else '普通'}" for c in cards),
                "；".join(f"{ROLES[c['role_id']]['name']}：{'普通' if c['witch'] else '魔女'}" for c in cards),
            )
            continue
        if ability in {"extra_kill", "rain", "scapegoat"}:
            card["uses"][ability] = True
        if ability == "rain" and action["effective"]:
            night["rain"] = True
        if ability == "scapegoat" and action["effective"]:
            card["states"]["display_killer"] = action["target_card"]
        if ability == "rest" and action["effective"]:
            # 安安在医务室休息：本夜免艾玛毒素，雨天脚印改成直接公布凶手是不是她。
            night["rest"] = {
                "seat_id": action["seat_id"],
                "card_id": card["id"],
                "day": game["day"],
            }
        if ability == "arisa_injure" and action["effective"]:
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
    for photo in game["photos"]:
        if photo.get("allowed"):
            actions = [a for a in night["actions"] if a["seat_id"] == photo["target"]]
            notify(game, events, night_text(game, actions), [photo["sender"]], "照片授权的夜间行动")
    if night.get("rest"):
        # 医务室休息是公开信息：其他玩家当夜就知道安安是否在休息。
        notify(
            game,
            events,
            f"{night['rest']['seat_id']}号今晚在医务室休息。",
            title="医务室休息",
        )
    game["phase"] = "night_review"
    prepare_night_preview(game, events)

def damage_preview(game, attacks, protection=()):
    injured = {c["id"]: c["injured"] for c in game["cards"].values()}
    dead = {}
    guarded_seats = {sid for sid, key in game["half_exits"].items() if key == half_key(game)}
    loved = loved_card_id(game)
    for index, attack in enumerate(attacks):
        cid = attack["target_card"]
        if cid not in game["cards"] or not game["cards"][cid]["alive"]:
            continue
        sid = owner(game, cid)["id"]
        if sid in guarded_seats or cid in dead:
            continue
        if cid == loved and attack.get("cause") != "love":
            # 玛格的爱优先级最高：爱人免疫魔女刀、13水、全场攻击、处决等其他一切死亡与负伤。
            # 玛格自己每夜那一发（cause="love"）不在这里短路，落到下面的负伤判定：
            # 第一次只负伤，已有负伤时再次负伤即无条件死亡（规则「免疫所有死亡和其他负伤」）。
            continue
        if current(game, sid)["id"] != cid and not attack.get("allow_lower"):
            continue
        protected = cid in protection or protection_active(game, game["cards"][cid])
        # attack_index 只给米莉亚替死用来定位「哪一击真的造成了这次出局」，不进公告。
        if (
            attack.get("once_injury")
            or attack.get("injury")
            or (protected and not attack.get("unconditional"))
        ):
            # 负伤没有「只负伤一次、永不升级」的例外：已有负伤时再次负伤无条件死亡。
            if injured[cid]:
                dead[cid] = {**attack, "seat_id": sid, "attack_index": index}
                guarded_seats.add(sid)
            else:
                injured[cid] = True
        else:
            dead[cid] = {**attack, "seat_id": sid, "attack_index": index}
            guarded_seats.add(sid)
    if (
        game["spiritual"]["sherry_bound"]
        and "hanna" in dead
        and dead["hanna"].get("cause") == "execution"
    ):
        sherry = role_card(game, "sherry")
        sid = owner(game, "sherry")["id"]
        if sherry["alive"] and sid not in guarded_seats:
            dead["sherry"] = {
                "target_card": "sherry",
                "seat_id": sid,
                "cause": "devotion",
                "source_card": "hanna",
                "unconditional": True,
            }
    return {"deaths": list(dead.values()), "injured": injured, "attacks": deepcopy(attacks)}


def millia_swap_effective(game):
    """换血是否生效：米莉亚的换血与替死不吃中毒效果骰，选中即一直生效。"""
    swap = game.get("millia_swap")
    if not swap or not swap.get("seat"):
        return None
    return swap


def millia_substitute(game, attacks, protection=()):
    """米莉亚替死：换血目标这一批里真的会出局时，才把致死的那一击转给米莉亚牌。

    换血目标存在状态里并一直生效（跨白天），直到下一次有效换血覆盖它；
    处刑、殉情、质疑整席出局与寻宝地雷显式不走替死（临刑开枪可以替死）。
    玛格的爱与庇护优先于替死：爱人免疫一切伤害、或被庇护的这一次伤害不至于
    出局时都不会「即将死亡」，因此也不转移给米莉亚。
    """
    at_night = game["phase"] in {"night", "night_coco", "night_review"}
    night = game["night"]
    swap = millia_swap_effective(game)
    if (
        swap is None
        # 替死是米莉亚这张牌的技能：她还没登场（上层牌未出局）时不替死，这一击照常打在
        # 原目标身上。只判 alive 会把改写后的攻击落到非当前牌上，被 damage_preview 静默
        # 丢弃——目标不伤不死、米莉亚也不出局。
        or not present(game, "millia")
        or (at_night and "millia" in night["reactions"])
    ):
        return attacks
    target = current(game, seat(game, swap["seat"]))
    if not target or target["id"] == loved_card_id(game):
        return attacks
    # 先按「不替死」做一次纯试算：只有换血目标确实会在这一批出局时，才转移那一击。
    probe = damage_preview(game, attacks, protection)
    death = next(
        (item for item in probe["deaths"] if item["target_card"] == target["id"]), None
    )
    if death is None or death.get("cause") in {"devotion", "execution", "challenge", "treasure"}:
        return attacks
    index = death.get("attack_index")
    if index is None or not 0 <= index < len(attacks):
        return attacks
    rewritten = [dict(attack) for attack in attacks]
    # 转移的是「致死的那一击」：抹掉负伤标记，让米莉亚按死亡结算（她自己的庇护仍可把它降级）。
    lethal = {
        key: value
        for key, value in rewritten[index].items()
        if key not in {"injury", "once_injury"}
    }
    rewritten[index] = {**lethal, "target_card": "millia"}
    if at_night:
        night["reactions"].append("millia")
    return rewritten


# 魔女一方的袭击能力：目击的触发条件是「被它指到」，不是「因此出局」。
# 庇护把这一击降级成负伤、玛格的爱免除它、米莉亚替死把致死一击转走，都算被指到。
WITCH_ATTACK_CAUSES = frozenset({"knife", "extra_kill", "massacre"})

# 没有对应夜间技能名的死因，在主持人日志里用的中文备注。
DEATH_CAUSE_LABELS = {"puppet": "傀儡随主人出局"}


def witch_witness_targets(game, attacks):
    """本夜被魔女袭击（魔女刀、额外攻击、全场攻击）指到的席位，每个席位一条。

    必须在米莉亚替死改写攻击目标之前调用：替死把致死一击转到米莉亚牌上，被指到的
    原目标这一侧就再也看不出来了。全场攻击会同时列出上下两张牌，而名单是按席位发
    的，所以按席位去重，victim 取该席当前牌。
    """
    targets, seen = [], set()
    for attack in attacks:
        cid = attack.get("target_card")
        if attack.get("cause") not in WITCH_ATTACK_CAUSES or not cid:
            continue
        card = game["cards"].get(cid)
        if not card or not card["alive"]:
            continue
        s = owner(game, cid)
        if s["id"] in seen:
            continue
        seen.add(s["id"])
        now = current(game, s)
        targets.append(
            {
                "seat_id": s["id"],
                "victim": now["id"] if now else cid,
                "source_card": attack.get("source_card"),
                "cause": attack["cause"],
            }
        )
    return targets


def publish_survivor_witnesses(game, events, preview, killed):
    """被魔女袭击指到但没出局的席位同样要一份目击名单。

    真正出局的席位由普通死亡路径发名单，这里只补「本夜没死」的那些：庇护降级为
    负伤、爱人免疫、米莉亚替死都只改变结算结果，不改变「他被袭击了」这件事。
    名单同样经主持人填写（技能处理后的真凶与穗乃香改名都走原路径）；当事人中毒时
    与死者一样只掷一次信息骰。
    """
    died_cards = {death["target_card"] for death in killed}
    died_seats = {death["seat_id"] for death in killed}
    for target in preview.get("witch_targets", []):
        if target["seat_id"] in died_seats or target["victim"] in died_cards:
            continue
        card = game["cards"][target["victim"]]
        truthful = effect_effective(game, card, "夜间目击名单")
        label = NIGHT_ABILITIES[target["cause"]][1]
        title = (
            f"{target['seat_id']}号夜间被{label}袭击（未出局）："
            f"填写{witness_label(witness_size(game))}（真凶与汉娜优先）"
        )
        if not truthful:
            title += "；本夜当事人中毒、目击信息骰失败，发给他的名单不含真凶"
        pending(
            game,
            "suspects",
            title,
            seat_id=target["seat_id"],
            victim=target["victim"],
            source_card=target.get("source_card"),
            truthful=truthful,
        )


def prepare_night_preview(game, events=None):
    night = game["night"]
    night["reactions"] = [r for r in night["reactions"] if r != "millia"]
    preview, dead = night_damage(game)
    night["preview"] = preview
    # 夜间预结算里希罗死亡时立即回溯到前一天顺序发言，不放主持人待办。
    # 事件队列必须原样传下去：回溯是公开事件，用空列表会把「游戏时间已回溯」
    # 吞掉，玩家只会看到整夜被打回重来（额度却照扣）。只有拿不到队列的
    # REST 入口（api.room_command 的替补接管）才允许传 None。
    if "hiro" in dead:
        hiro = role_card(game, "hiro")
        if not game["spiritual"]["hiro_used"]["witch" if hiro["witch"] else "normal"]:
            hiro_rewind(game, events if events is not None else [], "night")


def night_damage(game):
    attacks, protection = [], []
    night = game["night"]
    for action in night["actions"]:
        if not action.get("effective"):
            continue
        ability = action["ability"]
        target = action.get("target_card")
        if action.get("follow_seat") and action.get("target_seat"):
            now = current(game, action["target_seat"])
            target = now["id"] if now else None
        if ability == "protect" and target:
            protection.append(target)
        elif ability in {"knife", "extra_kill"} and target:
            attacks.append({"target_card": target, "source_card": action["card_id"], "cause": ability})
        elif ability == "massacre":
            if night.get("locked"):
                # 用户裁定（2026-09-27）：清场夜＝对局结束——只要全场攻击在本夜正常结算
                # （没被希罗回溯撤销），就直接判艾玛单独获胜。这里记下标记，胜负判定见
                # state.emma_solo_win；回溯会把整个 night 还原回快照，标记随之消失。
                night["massacre"] = action["card_id"]
            attacks.extend(
                {"target_card": card["id"], "source_card": action["card_id"], "cause": ability}
                for card in game["cards"].values()
                if card["alive"] and card["id"] != action["card_id"]
            )
        elif ability == "arisa_injure":
            attacks.extend(
                {"target_card": target_id, "source_card": action["card_id"], "cause": ability, "once_injury": True}
                for target_id in action.get("injuries", [])
            )
        elif ability == "treasure" and action.get("mine"):
            # 寻宝触发地雷：伤害并入本夜预结算，不替死（见 millia_substitute 的排除死因）。
            attacks.append(
                {
                    "target_card": action["card_id"],
                    "source_card": action["card_id"],
                    "cause": "treasure",
                }
            )
    love = active_love(game)
    if love:
        # 被爱的那张牌出局后玛格转爱自己：love["self"] 只用于界面提示。
        love["self"] = love_is_self(game)
        target = game["cards"].get(loved_card_id(game) or "")
        if target:
            attacks.append({"target_card": target["id"], "source_card": "marg", "cause": "love", "once_injury": True})
    attacks.extend(night.get("extra_attacks", []))
    # 「被魔女指到就有目击」按意图记账：必须在替死改写目标之前抓一份。
    witch_targets = witch_witness_targets(game, attacks)
    attacks = millia_substitute(game, attacks, protection)
    preview = damage_preview(game, attacks, protection)
    preview["witch_targets"] = witch_targets
    return preview, {death["target_card"] for death in preview["deaths"]}


def eliminate_seat(game, events, seat, notice):
    """整席出局：两张牌直接作废，不触发出局流程（亡语、回溯、证物、疑似凶手等）。

    「质疑失败」是「同一名玩家同一半天最多出局一张牌」的唯一例外：这里一次带走两张，
    但已经出局的牌不再重复记账，也不再为它补写一条 death。
    """
    for card_id in seat["cards"]:
        card = game["cards"][card_id]
        if not card["alive"]:
            continue
        card["alive"] = False
        # 整席出局没有「傀儡当前牌出局」的解除流程，状态必须在这里一并清掉：
        # 留着 puppet/no_ability 会让这张牌被回溯或主持人复活后继续当别人的傀儡。
        release_puppet(card)
        game["deaths"].append(
            {
                "id": uid(),
                "day": game["day"],
                "half": game["half"],
                "seat_id": seat["id"],
                "target_card": card_id,
                "cause": "challenge",
            }
        )
    if set(seat["cards"]) & {"sherry", "hanna"} and game.get("day_binding"):
        game["day_binding"]["intact"] = False
    game["half_exits"][seat["id"]] = half_key(game)
    notify(game, events, notice, alert=True)
    check_winner(game)


def publish_witness(game, events, item, suspects, honoka_role="honoka"):
    """向死者发送疑似凶手名单（三人；汉娜在场时四人），并记录本夜已发目击供复活撤销。"""
    shown = [honoka_role if role == "honoka" else role for role in suspects]
    text = f"{witness_label(len(shown))}：" + "、".join(ROLES[role]["name"] for role in shown)
    notify(game, events, text, [item["seat_id"]], "夜间目击名单")
    game["witness"] = {
        "day": game["day"],
        "seat_id": item["seat_id"],
        "death_id": item.get("death_id"),
        "text": text,
    }
    victim_seat = seat(game, item["seat_id"])
    if not current(game, victim_seat):
        game["cards"][item["victim"]]["states"]["evidence_allowed"] = True


WITNESS_BASE = 3
WITNESS_CN = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五"}


def witness_size(game):
    """七双目击名单人数：基础三人；汉娜在场（存活且是该席当前牌）时多一人。

    用户批注（A01/A02）：只按汉娜是否在场决定 3 还是 4；梅露露不再必进名单。
    """
    return WITNESS_BASE + (1 if present(game, "hanna") else 0)


def witness_label(size):
    return f"{WITNESS_CN.get(size, size)}名疑似凶手"


def witness_suspects(game, killer_role):
    """七双目击名单：真凶（技能处理后的显示凶手）+ 在场的汉娜，余位随机补齐。"""
    size = witness_size(game)
    fixed = [role for role in (killer_role, "hanna" if present(game, "hanna") else None) if role]
    suspects = list(dict.fromkeys(fixed))[:size]
    pool = [role for role in ROLES if role not in suspects]
    SystemRandom().shuffle(pool)
    return suspects + pool[: size - len(suspects)]


def false_witness(game, suspects, shown_source):
    """中毒信息失败时发出去的假目击名单：把显示真凶换成一名未入选角色。

    汉娜按规则始终在名单里，真凶就是汉娜时给不出不含真凶的名单，只能原样保留。
    """
    if not shown_source or shown_source == "hanna" or shown_source not in suspects:
        return list(suspects)
    pool = [role for role in ROLES if role not in suspects]
    if not pool:
        return list(suspects)
    SystemRandom().shuffle(pool)
    return [pool[0] if role == shown_source else role for role in suspects]


def death_batch(game, events, preview):
    for cid, injured in preview["injured"].items():
        game["cards"][cid]["injured"] = injured
    killed = []
    for death in preview["deaths"]:
        cid = death["target_card"]
        card = game["cards"][cid]
        s = owner(game, cid)
        if not card["alive"] or game["half_exits"].get(s["id"]) == half_key(game):
            continue
        before = {
            "seat_id": s["id"],
            "avatar_role_id": s["avatar_role_id"],
            "previous_role_id": fallen_upper_role(game, s),
            "alive": current(game, s) is not None,
        }
        # 疑凶目击是发给死者的信息：死者中毒时同样只掷一次信息骰，各1/2生效；
        # 必须在判定出局前掷，否则出局后艾玛邻接毒源会随当前牌变化而失效。
        witness_truthful = True
        if game["half"] == "night":
            witness_truthful = effect_effective(game, card, "夜间目击名单")
        card["alive"] = False
        if cid in {"sherry", "hanna"} and game.get("day_binding"):
            game["day_binding"]["intact"] = False
        game["half_exits"][s["id"]] = half_key(game)
        record = {
            "id": uid(),
            "day": game["day"],
            "half": game["half"],
            # attack_index 只服务于替死定位，不进对局记录与主持人视图。
            **{k: v for k, v in deepcopy(death).items() if k != "attack_index"},
        }
        game["deaths"].append(record)
        killed.append(record)
        source = death.get("source_card")
        if source:
            game["cards"][source]["states"].setdefault("kills", []).append(
                {"card_id": cid, "day": game["day"]}
            )
        if game["half"] == "night" and game["night"].get("rain") and source:
            shown_source = game["cards"][source]["states"].get("display_killer", source)
            source_seat = owner(game, shown_source)
            if source_seat["id"] != s["id"]:
                rest = game["night"].get("rest") or {}
                if rest:
                    # 安安在医务室休息：方向不一样，脚印直接公布凶手是不是她。
                    notify(
                        game,
                        events,
                        f"雨夜脚印：凶手{'是' if source_seat['id'] == rest['seat_id'] else '不是'}"
                        f"{rest['seat_id']}号（医务室方向）。",
                        title="雨夜脚印",
                    )
                else:
                    greater = int(source_seat["id"]) > int(s["id"])
                    if source == "hanna":
                        greater = not greater
                    notify(
                        game,
                        events,
                        f"雨夜脚印：凶手座位号{'大于' if greater else '小于'}死者座位号。",
                        title="雨夜脚印",
                    )
        hidden = bool(death.get("hide_cause"))
        suffixed = death.get("cause") == "water" and not hidden
        notice = (
            f"{s['id']}号玩家被13水毒杀。"
            if suffixed
            else f"{s['id']}号玩家一张角色牌出局。"
        )
        record["notice"] = notice
        # 非夜间技能造成的死亡（处决、质疑、傀儡随主人出局等）没有技能名，按死因备注。
        cause_label = DEATH_CAUSE_LABELS.get(death.get("cause")) or NIGHT_ABILITIES.get(
            death.get("cause"), (None, death.get("cause") or "")
        )[1]
        src = death.get("source_card")
        src_label = ROLES.get(src, {}).get("name", src) if src else ""
        detail = f"（{cause_label}" + (f"·{src_label}" if src_label else "") + ")" if cause_label else ""
        log_event(game, "death", f"{s['id']}号的{ROLES[cid]['name']}出局{detail}")
        if game["half"] == "night":
            # 夜间出局连同头像一起压到第二天白天再公示，夜间阶段不泄露
            game["queued_notices"].append(notice)
            game["queued_reveals"].append(before)
            if suffixed:
                # 未隐藏的13水死亡：直接构造并随机排序疑凶目击，无需主持人待办。
                # 替罪凶手与主持人填写路径口径一致：名单按「显示凶手」取名单位。
                shown = (
                    game["cards"][src]["states"].get("display_killer", src) if src else None
                )
                suspects = witness_suspects(game, shown)
                if not witness_truthful:
                    suspects = false_witness(game, suspects, shown)
                witness_item = {"seat_id": s["id"], "victim": cid, "death_id": record["id"]}
                if "honoka" in suspects and game["cards"]["honoka"]["witch"]:
                    # 魔女穗乃香被列进自动名单时，同样由本人选择本次显示的角色。
                    pending(
                        game,
                        "honoka_witness",
                        "穗乃香被列入目击：等待本人选择显示角色",
                        seat_id=owner(game, "honoka")["id"],
                        victim=cid,
                        witness_seat=s["id"],
                        # 与主持人填写路径同一口径：带上这次死亡，梅露露复活时才撤得掉目击。
                        death_id=record["id"],
                        suspects=list(suspects),
                    )
                    notify(
                        game,
                        events,
                        "你被列入一份目击名单，请选择本次显示的角色；超时将显示穗乃香。",
                        [owner(game, "honoka")["id"]],
                        "目击改名",
                    )
                else:
                    publish_witness(game, events, witness_item, suspects)
            else:
                title = (
                    f"{s['id']}号夜间死者："
                    f"填写{witness_label(witness_size(game))}（真凶与汉娜优先）"
                )
                if not witness_truthful:
                    title += "；本夜死者中毒、目击信息骰失败，发给他的名单不含真凶"
                pending(
                    game,
                    "suspects",
                    title,
                    seat_id=s["id"],
                    death_id=record["id"],
                    victim=cid,
                    source_card=source,
                    truthful=witness_truthful,
                )
        else:
            notify(game, events, notice, alert=True)
            # 白天死亡当场公示，下层牌立即登场并取得本阶段的行动。
            lower = current(game, s)
            if lower:
                s["avatar_role_id"] = lower["role_id"]
                text = f"下层角色{ROLES[lower['role_id']]['name']}已登场。"
                if lower["id"] == "honoka":
                    shown = apply_honoka_disguise(game, s)
                    text += (
                        f"按先前选择示人为{ROLES[shown]['name']}。"
                        if shown
                        else "你可以选择一次示人角色。"
                    )
                notify(game, events, text, [s["id"]], "下层登场")
        if release_puppet(card):
            # 傀儡当前牌出局：控制关系解除；该席下层牌仍存活则本人重新回到游戏。
            if current(game, s):
                notify(
                    game,
                    events,
                    "你已重新回到游戏，恢复普通玩家权限。",
                    [s["id"]],
                    "傀儡解除",
                )
    if game["half"] == "night":
        # 被魔女袭击指到却没出局的席位同样要有目击：目击看的是「被指到」。
        publish_survivor_witnesses(game, events, preview, killed)
    wipe_massacred_seats(game, events, killed)
    # 无人出局也要判一次胜负：魔女化艾玛的清场夜即使一个人都没打死（庇护/爱/替死全挡住）
    # 同样直接判她单独获胜，见 state.emma_solo_win。check_winner 是幂等的。
    check_winner(game)


def wipe_massacred_seats(game, events, killed):
    """全场攻击是「杀死所有其他角色」：被它打下当前牌的席位，另一张牌一并作废。

    用户 2026-09-27 追加：这是「同一半天同一人最多出一张牌」的第二条例外（第一条是
    质疑失败整席出局）。这里只把剩下的牌直接置为出局、**不补 death 记录**——同一玩家
    一夜只该有一条死亡公告、一份目击与一个证物，补记录会把这些都翻倍。
    被庇护、玛格的爱或米莉亚替死挡下当前牌的席位不算被打下场，照常两张牌都在。
    """
    for death in killed:
        if death.get("cause") != "massacre":
            continue
        s = seat(game, death["seat_id"])
        for cid in s["cards"]:
            card = game["cards"][cid]
            if not card["alive"]:
                continue
            card["alive"] = False
            release_puppet(card)
            log_event(game, "death", f"{s['id']}号的{ROLES[cid]['name']}被全场攻击一并打下场")
    return killed


def revoke_death(game, events, death):
    """梅露露复活：撤销该次死亡在公共记录、待办与已发目击里的痕迹。

    被魔女袭击（魔女刀、额外攻击、全场攻击）留下的目击不撤销：目击的触发条件是
    「被指到」而不是「出局」，复活撤掉的是死亡本身（公告、死因与半天出局），当事人
    仍然记得那一击。13水毒杀等其他死因照旧连目击一起撤销。
    """
    cid, sid = death["target_card"], death["seat_id"]
    keeps_witness = death.get("cause") in WITCH_ATTACK_CAUSES
    game["deaths"] = [item for item in game["deaths"] if item["id"] != death["id"]]
    game["queued_notices"] = [
        notice for notice in game["queued_notices"] if notice != death.get("notice")
    ]
    game["queued_reveals"] = [item for item in game["queued_reveals"] if item["seat_id"] != sid]
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
        # 待办标题原本写着「夜间死者」：复活后要跟主持人说清这人还在场、名单照发。
        for item in game["pending"]:
            if item["kind"] == "suspects" and (
                item.get("death_id") == death["id"] or item.get("victim") == cid
            ):
                item["title"] = (
                    f"{sid}号已被复活，被袭击的目击照发："
                    f"填写{witness_label(witness_size(game))}"
                )
                item["text"] = item["title"]
    if game.get("witness") and game["witness"].get("death_id") == death["id"] and not keeps_witness:
        game["witness"] = None
    # 这次死亡换来的「可留证物」随死亡一起撤销：否则被复活的活人还能给一场已经
    # 不存在的出局留遗物（未隐藏死因的 13 水自动目击那条路径很容易踩到）。
    game["cards"][cid]["states"].pop("evidence_allowed", None)
    if game["half_exits"].get(sid) == half_key(game):
        del game["half_exits"][sid]
    check_winner(game)


def revive(game, events, card_id, puppet=None):
    card = game["cards"][card_id]
    require(not card["alive"], "该牌尚未出局")
    card["alive"] = True
    card["injured"] = False
    if puppet:
        card["states"]["puppet"] = puppet
        card["states"]["no_ability"] = True
    else:
        # 回溯或主持人复活的牌一律不是傀儡：留着旧的 puppet/no_ability 会让它带着
        # 「继续被控制」或「永久无技能」的残留状态重新登场。
        release_puppet(card)
    owner_seat = owner(game, card_id)
    now = current(game, owner_seat)
    if now:
        owner_seat["avatar_role_id"] = now["role_id"]
    # 复活不单独播报：它与「当夜死亡通告被撤销 → 天亮判为平安夜」自相矛盾，还会把
    # 「当夜有人被杀、魔女用过复活」这两件事一起泄露出去。撤销本身照常发生。
    check_winner(game)
