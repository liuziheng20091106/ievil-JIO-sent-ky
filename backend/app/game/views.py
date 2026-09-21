"""Allow-list projections: secrets never leave through the public view."""

from copy import deepcopy

from .actions import actions_for, outstanding_seats
from .catalog import PHASES, ROLES
from .resolution import coco_seat
from .state import (
    can_use_card,
    current,
    eligible_voters,
    fallen_upper_role,
    pending_nominators,
    owner,
    player_seat,
    poison_sources,
    require,
    role_card,
)


def host_tasks(game):
    """Ordered to-do list for the host: every item is either blocking or a reminder."""
    tasks = []
    for item in game["pending"]:
        if item["kind"] == "honoka_witness":
            continue
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
    for item in game["pending"]:
        if item["kind"] == "hiro" and item.get("seat_id"):
            warn_task("hiro", item["seat_id"], f"{item['seat_id']}号尚未选择是否回溯")
        elif item["kind"] == "honoka_witness" and item.get("seat_id"):
            warn_task("honoka_witness", item["seat_id"], f"{item['seat_id']}号尚未选择目击显示角色")
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
            if sid not in game["balloon_choices"] and current(game, sid):
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
    if game["phase"] != "night_review":
        waiting = outstanding_seats(game)
        ready = not game["pending"] and not waiting and not game["winner_candidate"]
        tasks.append(
            {
                "id": "advance",
                "kind": "advance",
                "title": "完成当前阶段 / 推进",
                "detail": PHASES[game["phase"]]
                + ("：现在可以推进" if ready else "：先处理上方待办，或等待玩家完成行动"),
                "seats": [],
                "action": "host.advance",
                "payload": {},
                "blocking": ready,
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
                "no_ability",
                "learned_brainwash",
                "evidence_allowed",
                "evidence_used",
                "treasure_protected_day",
                "entry_allowed",
            }
        }
        if states.get("puppet"):
            result["states"]["puppet_master_seat"] = owner(game, states["puppet"])["id"]
    result["states"]["entry_allowed"] = can_use_card(game, card)
    return result


def status_cards(game, own):
    if not own:
        return []
    cards = [game["cards"][card_id] for card_id in own["cards"]]
    active = current(game, own)
    statuses = []

    def add(status_id, tone, title, text):
        statuses.append({"id": status_id, "tone": tone, "title": title, "text": text})

    if active and poison_sources(game, active):
        add("poison", "warning", "中毒", "情报可能错误，技能可能被视为假。")
    destiny = game["public"].get("witch_destiny")
    if destiny and game["status"] != "lobby" and int(own["id"]) <= len(destiny["seats"]):
        will = destiny["seats"][int(own["id"]) - 1]
        add(
            "witch_destiny",
            "danger" if will else "info",
            "魔女化命运",
            "本局你会魔女化。" if will else "本局你不会魔女化。",
        )
    protected = next(
        (card for card in cards if card["states"].get("treasure_protected_day", -1) >= game["day"]),
        None,
    )
    if protected:
        add("treasure", "success", "寻宝保护", "魔女刀、蕾雅长矛和提名暂不能选择你；全场攻击仍有效。")
    swap = next(
        (action for action in game["night"]["actions"] if action["seat_id"] == own["id"] and action["ability"] == "swap"),
        None,
    )
    if swap:
        add("millia_swap", "info", "米莉亚换血", f"本夜与{swap['target_seat']}号换血；其即将死亡时你代替其死亡。")
    nanoka = next((card for card in cards if card["role_id"] == "nanoka"), None)
    if nanoka:
        misses = nanoka["uses"].get("shot_misses", 0)
        add("nanoka_bullets", "info", "奈乃香子弹", f"剩余{nanoka['uses'].get('bullets', 0)}颗；下一枪命中率{min(misses + 1, 6)}/6。")
    if any(card["role_id"] == "marg" for card in cards) and game.get("marg_love"):
        love = game["marg_love"]
        add("marg_love", "info", "玛格之爱", f"当前爱人：{love['seat_id']}号" + ("（已转爱自己）" if love.get("self") else ""))
    if any(card["role_id"] == "sherry" for card in cards) and game["spiritual"]["sherry_bound"]:
        add("sherry_bound", "info", "雪莉绑定", "胜负跟随汉娜，不能同意处决汉娜。")
    for card in cards:
        penalty = game["spiritual"]["annan_penalty"].get(card["id"])
        penalty_day = penalty.get("day") if isinstance(penalty, dict) else penalty
        if penalty_day:
            add("annan_penalty", "danger", "安安后果", f"第{penalty_day}天失去投票权并必须被处刑。")
        if card["states"].get("puppet"):
            add("puppet", "danger", "傀儡", "不能投票，也不能发动角色技能。")
        if card["role_id"] == "noah":
            if card["uses"].get("rain"):
                add("noah_rain", "info", "诺亚下雨", "本局下雨已使用。")
            if card["uses"].get("scapegoat"):
                shown = card["states"].get("display_killer")
                add(
                    "noah_scapegoat",
                    "info",
                    "替罪凶手",
                    "本局已使用" + (f"：显示为{ROLES[shown]['name']}" if shown else "。"),
                )
    return statuses


def game_view(game, actor):
    host = actor.get("kind") == "host"
    spectator = actor.get("kind") == "spectator"
    require(host or actor.get("game_id") == game["id"], "没有本局查看权限")
    own = player_seat(game, actor) if actor.get("kind") == "player" else None
    own_id = own["id"] if own else None
    seats = []
    ready_count = 0
    lobby = game["status"] == "lobby"
    # 夜间出局要等第二天白天才公示，公示前对外沿用出局前的位置信息
    held = (
        {item["seat_id"]: item for item in game["queued_reveals"]}
        if game["status"] == "playing"
        else {}
    )
    for s in game["seats"]:
        ready_count += bool(s["ready"])
        pub = held.get(s["id"])
        entry = {
            "id": s["id"],
            "name": s["name"],
            "avatar_role_id": None
            if lobby
            else pub["avatar_role_id"]
            if pub
            else s["avatar_role_id"],
            "previous_role_id": None
            if lobby
            else pub["previous_role_id"]
            if pub
            else fallen_upper_role(game, s),
            "occupied": bool(s["occupant_id"]),
            # 行动选项里的人物用的是参与者 id，客户端需要它把选项关联到席位与角色，
            # 否则选择界面只能显示座位号而无法显示头像与角色。
            "participant_id": s["occupant_id"],
            "ready": s["ready"] if host or s["id"] == own_id else None,
            "alive": lobby or (pub["alive"] if pub else current(game, s) is not None),
        }
        if host or (spectator and not lobby):
            # 候场/调序阶段不公开任何角色信息；开局后观战者才看只读棋盘。
            entry["cards"] = [card_view(game, game["cards"][cid], host) for cid in s["cards"]]
            entry["current_card_id"] = current(game, s)["id"] if current(game, s) else None
        seats.append(entry)
    access = set(actor.get("access_ids", [])) | {actor.get("id")}
    information = [
        {k: deepcopy(item[k]) for k in ("id", "title", "text", "image_id") if k in item}
        for item in game["information"]
        if host or item["audience"] is None or access.intersection(item["audience"])
    ]
    public = deepcopy(game["public"])
    # 制作过程只给主持人看：对外不带制作/破坏/未提交的人头与席位明细
    public["balloon"].pop("last", None)
    # 当日目击名单：白天到投票结束前，死者和主持人常驻可见；进入处决或隔天自动消失。
    witness = game.get("witness")
    if (
        witness
        and witness["day"] == game["day"]
        and game["half"] == "day"
        and game["phase"] in ("speech", "balloon", "nomination", "voting")
        and (host or own_id == witness["seat_id"])
    ):
        view_witness = {"day": witness["day"], "text": witness["text"]}
    else:
        view_witness = None
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
        "ui_version": 1,
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
            "statuses": status_cards(game, own),
        },
        "actions": actions_for(game, actor),
        "information": information,
        "public": public,
        "witness": view_witness,
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
        if game["status"] == "lobby" and game["phase"] == "ordering" and "honoka" in own["cards"]:
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
            "balloon_proposal": deepcopy(game["balloon_proposal"]),
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
            "speech_passed": list(game.get("speech_passed", [])),
            "vote_rounds": deepcopy(game["vote_rounds"]),
            "photos": deepcopy(game["photos"]),
            "poison_sources": {
                card_id: poison_sources(game, card)
                for card_id, card in game["cards"].items()
                if poison_sources(game, card)
            },
            "log": deepcopy(game.get("log", [])),
            "tasks": host_tasks(game),
        }
    can_chat, reason = False, "当前为只读状态"
    if host:
        can_chat, reason = (
            game["status"] != "ended",
            "" if game["status"] != "ended" else "对局已结束",
        )
    elif spectator and game["status"] != "ended":
        can_chat, reason = True, ""
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
                else "当前角色已全部出局，不再参与白天发言；可私信主持人"
            )
    view["can_chat"], view["chat_reason"] = can_chat, reason
    return view
