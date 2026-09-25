"""Allow-list projections: secrets never leave through the public view."""

from copy import deepcopy

from .actions import actions_for, outstanding_seats, puppet_action_panels
from .catalog import PHASES, ROLES
from .resolution import coco_seat
from .state import (
    annan_penalty_day,
    card_actionable,
    controlled_cards,
    current,
    duel_cards,
    eligible_voters,
    fallen_upper_role,
    host_capable,
    host_label,
    host_view_actor,
    pending_nominators,
    owner,
    player_seat,
    poison_sources,
    protection_active,
    require,
    role_card,
    seat_operable,
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
        # 未完成的玩家行动不再是「阻塞项」：主持人可以直接强制推进，让它们立刻超时。
        # 这条待办只提示主持人还能先警告、再等30秒。
        tasks.append(
            {
                "id": f"{kind}:{seat_id}" if seat_id else kind,
                "kind": kind,
                "title": title,
                "detail": "可直接推进（未完成的行动立刻按超时处理），或先警告并等待30秒。",
                "seats": [seat_id] if seat_id else [],
                "action": "host.warn",
                "payload": {"seat_id": seat_id} if seat_id else {},
                "blocking": False,
            }
        )

    phase = game["phase"]
    for item in game["pending"]:
        if item["kind"] == "honoka_witness" and item.get("seat_id"):
            warn_task("honoka_witness", item["seat_id"], f"{item['seat_id']}号尚未选择目击显示角色")
    if phase in {"night", "night_coco"}:
        coco = coco_seat(game) if phase == "night" else None
        for sid in game["night"]["actors"]:
            if sid in game["night"]["confirmed"] or sid == coco:
                continue
            warn_task("night", sid, f"{sid}号尚未确认夜间行动")
    elif phase == "speech" and game["public"]["speaker"]:
        sid = game["public"]["speaker"]
        # 无人可操作的发言人会被 advance 直接顺延，不该给主持人留一条永远等不到的警告。
        if seat_operable(game, sid):
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
        if ready:
            detail = PHASES[game["phase"]] + "：现在可以推进"
        elif waiting and not game["pending"] and not game["winner_candidate"]:
            detail = (
                PHASES[game["phase"]]
                + f"：仍{len(waiting)}个席位未完成，推进将立刻把它们按超时处理"
            )
        else:
            detail = PHASES[game["phase"]] + "：先处理上方待办，或等待玩家完成行动"
        tasks.append(
            {
                "id": "advance",
                "kind": "advance",
                "title": "完成当前阶段 / 推进",
                "detail": detail,
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
                "protected_day",
                "no_vote",
                "no_ability",
                "evidence_allowed",
                "evidence_used",
                "treasure_protected_day",
                "entry_allowed",
            }
        }
        if states.get("puppet"):
            result["states"]["puppet_master_seat"] = owner(game, states["puppet"])["id"]
    result["states"]["entry_allowed"] = card_actionable(game, card)
    return result


def status_cards(game, own):
    if not own:
        return []
    cards = [game["cards"][card_id] for card_id in own["cards"]]
    statuses = []

    def add(status_id, tone, title, text):
        statuses.append({"id": status_id, "tone": tone, "title": title, "text": text})

    destiny = game["public"].get("witch_destiny")
    if destiny and game["status"] != "lobby" and int(own["id"]) <= len(destiny["seats"]):
        will = destiny["seats"][int(own["id"]) - 1]
        faction = list(destiny.get("first", []))
        if own["id"] in faction:
            # A、B 是魔女阵营：本人的那一份要说清是哪一天当值，而不是笼统的「会魔女化」。
            text = f"你是魔女阵营：第{faction.index(own['id']) + 1}天你的当前牌会魔女化。"
        else:
            text = "本局你会魔女化。" if will else "本局你不会魔女化。"
        add("witch_destiny", "danger" if will else "info", "魔女化命运", text)
    protected = next(
        (card for card in cards if card["states"].get("treasure_protected_day", -1) >= game["day"]),
        None,
    )
    if protected:
        add("treasure", "success", "寻宝保护", "魔女刀、蕾雅决斗和提名暂不能选择你；全场攻击仍有效。")
    protection_day = next(
        (card["states"].get("protected_day") for card in cards if protection_active(game, card)),
        None,
    )
    if protection_day is not None:
        add(
            "protection",
            "success",
            "庇护",
            f"致命伤害改为负伤一次；到第{protection_day + 1}天夜里自动过期。",
        )
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
        pending = game["half"] != "night" and game["day"] <= love.get("day", 0)
        add(
            "marg_love",
            "info",
            "玛格之爱",
            f"当前爱人：{love['seat_id']}号"
            + (
                "（当天夜里才开始生效）"
                if pending
                else "（已转爱自己）"
                if love.get("self")
                else "（免疫死亡与其他负伤）"
            ),
        )
    duel = duel_cards(game)
    if duel:
        leia_seat = owner(game, duel[0])["id"]
        target_seat = owner(game, duel[1])["id"]
        add(
            "duel",
            "danger",
            "蕾雅决斗",
            f"今天所有人必须至少同意{leia_seat}号或{target_seat}号之一，"
            "且这两张牌达到半数即可处决。",
        )
    if any(card["role_id"] == "sherry" for card in cards) and game["spiritual"]["sherry_bound"]:
        add("sherry_bound", "info", "雪莉绑定", "胜负跟随汉娜，不能同意处决汉娜。")
    penalty_day = annan_penalty_day(game, own["id"])
    if penalty_day:
        add("annan_penalty", "danger", "安安后果", f"第{penalty_day}天失去投票权并必须被处刑。")
    for card in cards:
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


def seat_chat(game, own):
    """某席位的公开发言权限；傀儡席由其控制者代发。"""
    if game["status"] == "lobby":
        return True, ""
    if game["status"] != "playing":
        return False, "当前为只读状态"
    if game["phase"] == "speech":
        can = game["public"]["speaker"] == own["id"]
        return can, "" if can else "顺序发言阶段，请等待你的发言顺序"
    if game["half"] == "day" and current(game, own):
        return True, ""
    return (
        False,
        "夜间与夜间结果阶段无公开发言；可私信主持人"
        if game["half"] == "night"
        else "当前角色已全部出局，不再参与白天发言；可私信主持人",
    )


def game_view(game, actor):
    # 「确认进入管理界面」是服务端的数据放行条件：未确认的主持人在这里只拿到
    # 最窄的观察者投影——没有全席双牌、没有主持人面板与主持行动，也看不到私聊。
    host = host_capable(actor)
    spectator = actor.get("kind") == "spectator"
    require(host or actor.get("game_id") == game["id"], "没有本局查看权限")
    # 未确认进入的主持人按观察者生成行动表（空），避免下发主持与房间管理入口。
    view_actor = host_view_actor(actor)
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
    # 未确认进入的主持人不属于本局任何名单：连挂在自己名下的私密情报也不下发。
    access = set(actor.get("access_ids", []))
    if not (actor.get("kind") == "host" and not host):
        access.add(actor.get("id"))
    information = [
        {k: deepcopy(item[k]) for k in ("id", "title", "text", "image_id") if k in item}
        for item in game["information"]
        if host or item["audience"] is None or access.intersection(item["audience"])
    ]
    public = deepcopy(game["public"])
    # 魔女化命运只私下告知本人（设计文档：命运只私下告知本人并常驻「我的」页状态卡），
    # 逐席布尔值绝不能整体下发，否则任何人一眼就能看出谁会魔女化。本人那一份由
    # status_cards 单独投影，主持人仍然看到全部。
    if not host:
        public.pop("witch_destiny", None)
    # 自由发言结束请求是公开进度：两端都要显示「已有几人提交」与 10 秒倒计时。
    public["discussion_end_requests"] = list(game.get("discussion_end_requests", []))
    # 当日目击名单：白天到投票结束前，死者和主持人常驻可见；进入处决或隔天自动消失。
    witness = game.get("witness")
    if (
        witness
        and witness["day"] == game["day"]
        and game["half"] == "day"
        and game["phase"] in ("speech", "nomination", "voting")
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
    view = {
        "ui_version": 1,
        "id": game["id"],
        "version": game["version"],
        "status": game["status"],
        "day": game["day"],
        "half": game["half"],
        "phase": game["phase"],
        "phase_label": PHASES[game["phase"]],
        # 本局主持人的展示名（主持人(昵称)）：对局内显示主持人时用它，
        # 让玩家分得清主持这一局的是哪个账号。
        "host_name": host_label(game),
        # 主持人警告只私下提醒被警告的席位（self.warning_deadline），不对全场暴露倒计时。
        "deadline": game["deadline"] if host else None,
        "seats": seats,
        "ready_count": ready_count,
        "self": {
            "seat_id": own_id,
            "cards": [card_view(game, game["cards"][cid]) for cid in own["cards"]] if own else [],
            "current_card_id": current(game, own)["id"] if own and current(game, own) else None,
            "statuses": status_cards(game, own),
        },
        # 未确认进入的主持人不生成任何行动：连房间管理与私信都不给，
        # 只有「确认进入管理界面」这个接口能推进（见 api.host_enter）。
        "actions": actions_for(game, view_actor),
        "information": information,
        "public": public,
        "witness": view_witness,
        "result": deepcopy(game["result"]),
        # 客户端据此显示「进入对局管理界面」的确认页；服务端才是权威，
        # 确认成功后这次投影会立刻换成完整主持投影。
        "host_entry_required": actor.get("kind") == "host" and not host,
    }
    if own:
        night = game["night"]
        view["self"]["night_confirmed"] = own_id in night["confirmed"]
        controlled = controlled_cards(game, own_id)
        view["self"]["puppet_spectator"] = bool(
            current(game, own) and current(game, own)["states"].get("puppet") and not controlled
        )
        view["self"]["puppet_controls"] = (
            puppet_action_panels(game, actor) if controlled else []
        )
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
        if own_id in game["water"]["holders"]:
            view["self"]["water"] = True
        view["self"]["vote"] = game["votes"].get(own_id)
        view["self"]["warning_deadline"] = game["warnings"].get(own_id)
        if game["status"] == "lobby" and game["phase"] == "ordering" and "honoka" in own["cards"]:
            # 穗乃香规则：开局前获知其他人的上层角色（仅文字角色名，不带头像）。
            # 只列已准备的席位：准备即锁定上层牌，没准备的人还没定上层，无可告知。
            # 这必然让她知道谁已准备（席位投影对其他人隐藏 ready），设计文档允许，别当泄露「修」掉。
            known = []
            for s in game["seats"]:
                top = current(game, s)
                if s["id"] != own_id and s["occupant_id"] and s["ready"] and top:
                    known.append(
                        {"seat_id": s["id"], "name": s["name"], "role_id": top["role_id"]}
                    )
            view["self"]["honoka_upper"] = known
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
            "votes": deepcopy(game["votes"]),
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
    elif own:
        if view["self"].get("puppet_spectator"):
            can_chat, reason = False, "你当前是傀儡，由魔女梅露露代为行动"
        else:
            can_chat, reason = seat_chat(game, own)
    view["can_chat"], view["chat_reason"] = can_chat, reason
    return view
