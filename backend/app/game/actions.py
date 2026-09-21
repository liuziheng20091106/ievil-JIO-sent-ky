"""Privacy-safe action descriptors, also used as authoritative input grammar."""

from .catalog import AUTO_PHASES, DAY_ABILITIES, NIGHT_ABILITIES, ROLES
from .resolution import coco_seat, target_allowed
from .state import (
    can_use_card,
    current,
    eligible_voters,
    hiro_dilemma,
    living,
    lost_by_challenge,
    pending_nominators,
    owner,
    player_seat,
    present,
    role_card,
    snapshot_for,
)


SHORT_LABELS = {
    "host.resolve": "裁定",
    "host.water": "交水",
    "host.end": "终止",
    "host.codex": "魔典",
    "host.advance": "推进",
    "host.start": "开局",
    "host.auto": "自动",
    "host.warn": "警告",
    "host.speech": "发言",
    "host.damage": "伤害",
    "host.state": "改状态",
    "host.information": "发信息",
    "host.madness": "疯狂",
    "host.codex_order": "典序",
    "host.rewind": "回溯",
    "host.confirm_winner": "宣判",
    "host.surrender": "交牌",
    "hiro.rewind": "回溯",
    "hiro.decline": "继续",
    "lobby.order": "排牌",
    "lobby.ready": "准备",
    "player.profile": "称呼",
    "night.submit": "夜行",
    "night.clear": "清除",
    "night.confirm": "确认",
    "day.skill": "技能",
    "day.challenge": "质疑",
    "honoka.disguise": "示人",
    "honoka.witness": "目击",
    "hiro.exit": "出局",
    "speech.done": "结束发言",
    "speech.speak": "写发言",
    "vote.nominate": "提名",
    "vote.pass": "弃提名",
    "vote.cast": "投票",
    "execution.shoot": "开枪",
    "execution.confirm": "放弃",
    "balloon.choose": "选气球",
    "balloon.agree": "同意",
    "balloon.decline": "拒绝",
    "balloon.propose": "提名单",
    "photo.permission": "信物",
    "water.use": "用水",
    "meruru.revive": "复活",
    "evidence.submit": "证物",
    "player.surrender": "申请交牌",
}


def field(name, label, kind="text", options=None, required=True, **extra):
    item = {"name": name, "label": label, "type": kind, "required": required, **extra}
    if options is not None:
        item["options"] = [{"value": str(v), "label": str(label)} for v, label in options]
    return item


def action(action_id, label, fields=(), payload=None, group="行动", short_label=None, **extra):
    short = short_label or SHORT_LABELS[action_id]
    if not 2 <= len(short) <= 4:
        raise ValueError(f"行动短名必须为2至4字：{action_id}")
    return {
        "ui_version": 1,
        "id": action_id,
        "short_label": short,
        "label": label,
        "fields": list(fields),
        "payload": payload or {},
        "group": group,
        **extra,
    }


def seat_options(game, alive=True):
    return [
        (s["id"], f"{s['id']}号 · {s['name']}")
        for s in game["seats"]
        if not alive or current(game, s)
    ]


def role_options():
    return [(r, d["name"]) for r, d in ROLES.items()]




def speech_start(game):
    """Speeches usually start at today's last dead seat; fall back to the first living seat."""
    alive = [s["id"] for s in living(game)]
    return next(
        (
            d["seat_id"]
            for d in reversed(game["deaths"])
            if d["day"] == game["day"] and d["seat_id"] in alive
        ),
        alive[0] if alive else "1",
    )


def outstanding_seats(game):
    """Seats whose missing input currently holds up the flow; only these are worth warning."""
    if game["status"] != "playing":
        return []
    phase = game["phase"]
    result = []
    if phase in {"night", "night_coco"}:
        coco = coco_seat(game)
        for sid in game["night"]["actors"]:
            if sid in game["night"]["confirmed"] or (phase == "night" and sid == coco):
                continue
            result.append(sid)
    elif phase == "speech" and game["public"]["speaker"]:
        result.append(game["public"]["speaker"])
    elif phase == "nomination":
        result = pending_nominators(game)
    elif phase == "voting":
        result = [s["id"] for s in eligible_voters(game) if s["id"] not in game["votes"]]
    elif phase == "execution":
        result = [
            owner(game, cid)["id"]
            for cid in game["execution"]
            if cid == "nanoka"
            and game["cards"][cid]["alive"]
            and role_card(game, cid)["uses"].get("bullets", 0) > 0
            and owner(game, cid)["id"] not in game["execution_ready"]
        ]
    result += [
        item["seat_id"] for item in game["pending"] if item["kind"] == "honoka_witness"
    ]
    proposal = game.get("balloon_proposal")
    if proposal:
        # 名单表决期所有未表态的存活玩家都卡住流程，警告与自动推进都要等他们。
        result += [s["id"] for s in living(game) if s["id"] not in proposal["votes"]]
    balloon = game["public"]["balloon"]
    if balloon["status"] == "collecting":
        # 收集横跨白天多个阶段，期间出局者无法再提交，按默认跳过处理、不算待办。
        result += [
            sid
            for sid in balloon["participants"]
            if sid not in game["balloon_choices"] and current(game, sid)
        ]
    return list(dict.fromkeys(result))


def target_field(game, night=False, exclude=None, avoid_treasure=False):
    return field(
        "target",
        "目标席位",
        "select",
        [
            (sid, label)
            for sid, label in seat_options(game)
            if sid != exclude
            and (not night or target_allowed(game, current(game, sid)["id"]))
            and (
                not avoid_treasure
                or current(game, sid)["states"].get("treasure_protected_day") != game["day"]
            )
        ],
    )


def day_fields(game, ability, exclude=None):
    if ability == "gaze":
        return []
    if ability == "balloon":
        return [
            field(
                "participants",
                "参加者（不含自己，至多4人）",
                "multiselect",
                [(sid, label) for sid, label in seat_options(game) if sid != exclude],
                min=1,
                max=4,
            )
        ]
    return [target_field(game, avoid_treasure=ability == "spear")]


def can_day_ability(game, card, ability):
    phase = game["phase"]
    role = card["role_id"]
    witch = card["witch"]
    if ability == "brainwash":
        return (
            phase == "voting"
            and (
                role == "annan"
                and not witch
                or role == "marg"
                and witch
                and card["states"].get("learned_brainwash")
            )
            and card["id"] not in game["brainwash"]
        )
    if ability == "mass_brainwash":
        return (
            phase in {"discussion", "nomination", "voting"}
            and role == "annan"
            and witch
            and not card["uses"].get("mass_brainwash")
        )
    if ability == "interrupt":
        return (
            role == "emma"
            and phase in {"speech", "discussion"}
            and card["uses"].get("interrupt_day") != game["day"]
        )
    if ability == "gaze":
        return role == "nanoka" and phase == "execution" and card["uses"].get("gaze_day") != game["day"]
    if phase not in {"speech", "discussion", "balloon", "nomination", "voting"}:
        return False
    if DAY_ABILITIES[ability][0] != role:
        return False
    if ability == "love":
        return card["uses"].get("love_day") != game["day"]
    if ability == "spear":
        return card["uses"].get("spear_day") != game["day"]
    if ability == "balloon":
        return game["public"]["balloon"]["day"] != game["day"]
    return ability == "photo"


def claimable(role):
    """该示人身份可以声称的白天技能：本角色的技能，魔女玛格另含学到的洗脑。"""
    if not role:
        return set()
    return {ability for ability, (owner, _) in DAY_ABILITIES.items() if owner == role} | (
        {"brainwash"} if role == "marg" else set()
    )


def challengeable(game, declaration):
    """除信物与爱以外，所有开放的白天技能声明均可质疑。"""
    return declaration["ability"] not in {"photo", "love"}

def day_fake_allowed(game, card, ability):
    phase = game["phase"]
    phases = {
        "brainwash": {"voting"},
        "mass_brainwash": {"discussion", "nomination", "voting"},
        "interrupt": {"speech", "discussion"},
        "gaze": {"execution"},
    }.get(ability, {"speech", "discussion", "balloon", "nomination", "voting"})
    shown = card["states"].get("disguise") if card["id"] == "honoka" else card["role_id"]
    if phase not in phases or ability not in claimable(shown):
        return False
    if card["id"] == "honoka":
        return True
    if ability == "brainwash":
        return not (
            card["role_id"] == "annan" and not card["witch"]
            or card["role_id"] == "marg"
            and card["witch"]
            and card["states"].get("learned_brainwash")
        )
    return ability == "mass_brainwash" and not (
        card["role_id"] == "annan" and card["witch"]
    )


def night_abilities(game, card):
    role, witch, uses = card["role_id"], card["witch"], card["uses"]
    abilities = ["knife"] if witch else []
    if role == "emma":
        abilities.append("treasure")
        if witch:
            abilities.append("massacre")
    if role == "hanna" and witch and not uses.get("extra_kill"):
        abilities.append("extra_kill")
    if role == "meruru":
        abilities.append("protect")
    if role == "noah":
        if not uses.get("rain"):
            abilities.append("rain")
        if witch and not uses.get("scapegoat"):
            abilities.append("scapegoat")
    if role == "millia":
        abilities.append("swap")
    if role == "nanoka" and witch:
        abilities.append("witch_scan")
    if role == "arisa":
        abilities.append("arisa_injure")
    return abilities


def pending_action(game, item):
    kind = item["kind"]
    fields = []
    if kind == "information":
        fields = [field("text", "发给当事人的裁定信息", "textarea", default=item.get("text", ""))]
    elif kind == "hiro":
        choices = [("decline", "不发动回溯")] + [
            (s["id"], f"{s['label']}（日{s['day']}）") for s in game["snapshots"]
        ]
        preferred = next(
            (snap for snap in reversed(game["snapshots"]) if snap["half"] == game["half"]), None
        ) or (game["snapshots"][-1] if game["snapshots"] else None)
        fields = [
            field(
                "snapshot",
                "回溯时间点（优先前一天同阶段；其他须裁定）",
                "select",
                choices,
                default=preferred["id"] if preferred else None,
            ),
            field(
                "keep_states",
                "额外保留的状态归属（精神系自动保留）",
                "multiselect",
                role_options(),
                required=False,
            ),
            field("reason", "特殊时间点的裁定说明", "textarea", required=False),
        ]
    elif kind == "suspects":
        source = item.get("source_card")
        killer = game["cards"][source]["states"].get("display_killer", source) if source else None
        suggested = list(dict.fromkeys(role for role in (killer, "hanna") if role))
        suggested.extend(role for role in ROLES if role not in suggested and len(suggested) < 4)
        fields = [
            field(
                "suspects",
                "四名疑似凶手（汉娜额外一人）",
                "multiselect",
                role_options(),
                min=4,
                max=4,
                default=suggested,
            )
        ]
        if not item.get("source_card"):
            fields.append(field("true_source", "补充裁定实际真凶", "select", role_options()))
    elif kind == "lower_entry":
        fields = [
            field(
                "allow",
                "允许下层本阶段行动（同半天仍最多出局一牌）",
                "checkbox",
                required=False,
                default=True,
            )
        ]
    elif kind == "water":
        fields = [
            field(
                "outcome",
                "13水互动裁定",
                "select",
                [
                    ("kill", "毒杀，仍应用现有庇护"),
                    ("unconditional", "裁定无条件出局"),
                    ("injure", "裁定只负伤"),
                    ("cancel", "本次时机不合法，退回13水"),
                ],
                default="kill",
            ),
            field("reason", "互动与时机裁定", "textarea", default="13水：按现有庇护结算"),
        ]
    elif kind == "evidence":
        fields = [
            field("public", "向全员公开", "checkbox", required=False, default=True),
            field(
                "recipients",
                "未公开时的接收席位",
                "multiselect",
                seat_options(game, False),
                required=False,
            ),
            field("allow", "准许发布（不勾选为拒绝）", "checkbox", required=False, default=True),
        ]
    elif kind == "codex":
        fields = [
            field(
                "outcome",
                "魔典处理",
                "select",
                [("skip", "本日不转化"), ("convert", "指定特殊转化对象")],
                default="skip",
            ),
            field(
                "target",
                "特殊转化对象",
                "select",
                [("", "不指定")] + role_options(),
                required=False,
            ),
            field("reason", "裁定说明", "textarea", default="魔典未按时结算，按跳过处理"),
        ]
    elif kind == "madness":
        fields = [
            field(
                "outcome",
                "疯狂裁定",
                "select",
                [
                    ("warn", "警告"),
                    ("penalty", "判定不够疯狂，禁用成就并执行不利裁定"),
                    ("satisfied", "符合要求"),
                ],
                default="warn",
            ),
            field(
                "penalty",
                "不利裁定",
                "select",
                [
                    ("none", "无额外牌面变动"),
                    ("death", "指定牌出局"),
                    ("poison", "指定牌中毒"),
                    ("lose", "指定操作者个人判负"),
                ],
            ),
            field("target", "不利裁定目标牌", "select", role_options()),
            field("reason", "裁定说明", "textarea"),
        ]
    elif kind == "reaction":
        fields = [
            field("proceed", "确认按预结算执行（特殊互动请先纠错）", "checkbox", default=True)
        ]
    return action(
        "host.resolve",
        item["title"],
        fields,
        {"pending_id": item["id"]},
        "裁决待办",
        blocking=True,
    )


def host_actions(game):
    result = []
    if game["status"] == "lobby":
        if game["phase"] == "ordering":
            result.append(action("host.start", "全部再次准备后开局", group="流程"))
        result.append(
            action(
                "host.codex",
                "重新确认魔典名单并随机顺序",
                [field("roles", "11名魔典角色", "multiselect", role_options(), min=11, max=11)],
                group="开局",
            )
        )
    else:
        result.append(action("host.advance", "完成当前阶段 / 推进", group="流程", blocking=True))
    result.extend(
        pending_action(game, item) for item in game["pending"] if item["kind"] != "honoka_witness"
    )
    result.append(
        action(
            "host.water",
            "私下交付唯一13水",
            [field("seat_id", "持有者", "select", seat_options(game, False))],
            group="私密管理",
        )
    )
    if game["status"] == "playing":
        outstanding = outstanding_seats(game)
        if game["phase"] in AUTO_PHASES:
            paused = bool(game["public"].get("auto_advance_off"))
            result.append(
                action(
                    "host.auto",
                    "恢复自动推进" if paused else "暂停自动推进",
                    group="流程",
                )
            )
        if outstanding:
            result.append(
                action(
                    "host.warn",
                    "警告：30秒后结束该玩家操作",
                    [
                        field(
                            "seat_id",
                            "被警告席位（仅列出当前卡住的席位）",
                            "select",
                            [
                                (sid, label)
                                for sid, label in seat_options(game, False)
                                if sid in outstanding
                            ],
                            required=False,
                        ),
                        field("all", "警告当前全部卡住的席位", "checkbox", required=False),
                    ],
                    group="流程",
                    blocking=True,
                )
            )
        speech_controls = (
            [
                action(
                    "host.speech",
                    "安排顺序发言",
                    [
                        field(
                            "start",
                            "从谁开始（通常为死者）",
                            "select",
                            seat_options(game),
                            default=speech_start(game),
                        ),
                        field(
                            "direction",
                            "方向",
                            "select",
                            [("asc", "顺序（序号递增）"), ("desc", "逆序（序号递减）")],
                            default="asc",
                        ),
                    ],
                    group="流程",
                )
            ]
            if game["phase"] == "speech"
            else []
        )
        result.extend(
            speech_controls
            + [
                action(
                    "host.damage",
                    "裁定伤害 / 出局",
                    [
                        field(
                            "targets", "目标角色牌", "multiselect", role_options(), min=1, max=14
                        ),
                        field(
                            "effect",
                            "伤害方式",
                            "select",
                            [
                                ("death", "死亡（应用庇护）"),
                                ("injury", "负伤"),
                                ("unconditional", "无条件出局"),
                            ],
                        ),
                        field(
                            "source",
                            "真凶（可在夜间目击环节补充裁定）",
                            "select",
                            [("", "无 / 另行裁定")] + role_options(),
                            required=False,
                        ),
                        field("reason", "裁定说明", "textarea"),
                    ],
                    group="裁定纠错",
                    danger=True,
                ),
                action(
                    "host.state",
                    "调整指定牌状态",
                    [
                        field("card_id", "角色牌", "select", role_options()),
                        field(
                            "state",
                            "状态",
                            "select",
                            [
                                ("witch", "魔女化"),
                                ("poisoned", "中毒"),
                                ("protected", "庇护"),
                                ("injured", "负伤标记"),
                                ("no_vote", "失去投票权"),
                                ("puppet", "傀儡"),
                                ("alive", "存活 / 出局"),
                            ],
                        ),
                        field("value", "启用 / 存活", "checkbox", required=False),
                        field(
                            "master",
                            "傀儡主人",
                            "select",
                            [("", "无")] + role_options(),
                            required=False,
                        ),
                        field("persistent", "此状态不随回溯恢复", "checkbox", required=False),
                        field(
                            "public", "公开裁定说明（不公开私密状态）", "checkbox", required=False
                        ),
                        field("reason", "裁定说明", "textarea"),
                    ],
                    group="裁定纠错",
                ),
                action(
                    "host.information",
                    "发放信息 / 照片",
                    [
                        field("title", "信息标题"),
                        field("text", "正文", "textarea", required=False),
                        field("image", "附图", "drawing", required=False),
                        field("public", "全员公开", "checkbox", required=False),
                        field(
                            "recipients",
                            "私密接收席位",
                            "multiselect",
                            seat_options(game, False),
                            required=False,
                        ),
                    ],
                    group="信息",
                ),
                action(
                    "host.madness",
                    "发起疯狂行为裁定",
                    [
                        field("seat_id", "席位", "select", seat_options(game, False)),
                        field("reason", "需裁定的行为", "textarea"),
                    ],
                    group="裁决",
                ),
                action(
                    "host.codex_order",
                    "裁定魔典顺序",
                    [
                        field(
                            "roles",
                            "全部11名角色的最终顺序",
                            "multiselect",
                            [(r, ROLES[r]["name"]) for r in game["codex"]],
                            min=11,
                            max=11,
                        ),
                        field("reason", "裁定说明", "textarea"),
                    ],
                    group="裁定纠错",
                ),
            ]
        )
        if game["snapshots"]:
            result.append(
                action(
                    "host.rewind",
                    "特殊回溯裁定",
                    [
                        field(
                            "snapshot",
                            "目标时间点",
                            "select",
                            [(s["id"], s["label"]) for s in game["snapshots"]],
                        ),
                        field(
                            "keep_states",
                            "额外保留状态的角色",
                            "multiselect",
                            role_options(),
                            required=False,
                        ),
                        field("reason", "裁定说明", "textarea"),
                    ],
                    group="裁定纠错",
                    danger=True,
                )
            )
        if game["winner_candidate"]:
            result.append(
                action(
                    "host.confirm_winner",
                    "确认本半天全部连锁完成并宣判",
                    [field("confirm", "本半天所有同时出局与连锁均已处理", "checkbox")],
                    group="胜负",
                    danger=True,
                    blocking=True,
                )
            )
        if game["surrenders"]:
            result.append(
                action(
                    "host.surrender",
                    "审阅并确认交牌",
                    [
                        field(
                            "side",
                            "交牌阵营",
                            "select",
                            [("good", "好人"), ("witch", "魔女（仅剩可可）")],
                        ),
                        field("reason", "裁定说明", "textarea"),
                    ],
                    group="胜负",
                    danger=True,
                    blocking=True,
                )
            )
    result.append(
        action(
            "host.end",
            "主持人终止 / 特殊胜负裁定",
            [
                field(
                    "winner",
                    "结果",
                    "select",
                    [("good", "好人胜"), ("witch", "魔女胜"), ("aborted", "终止对局")],
                ),
                field("reason", "完整裁定说明", "textarea"),
            ],
            group="管理",
            danger=True,
        )
    )
    return result


def actions_for(game, actor):
    if game["status"] == "ended":
        return []
    if actor.get("kind") == "host":
        return host_actions(game)
    if actor.get("kind") != "player":
        return []
    s = player_seat(game, actor)
    sid = s["id"]
    card = current(game, s)
    result = []
    dilemma = hiro_dilemma(game, sid)
    if dilemma:
        snap = snapshot_for(game, dilemma)
        if snap:
            result.append(
                action(
                    "hiro.rewind",
                    f"回溯到前一天同一时点（{snap['label']}）",
                    group="流程",
                    blocking=True,
                )
            )
        result.append(action("hiro.decline", "按预结算继续（不回溯）", group="流程", blocking=True))
    if game["status"] == "lobby":
        if game["phase"] == "ordering" and not s["ready"]:
            result.append(
                action(
                    "lobby.order",
                    "选择上层角色",
                    [
                        field(
                            "top",
                            "上层角色",
                            "select",
                            [
                                (cid, ROLES[game["cards"][cid]["role_id"]]["name"])
                                for cid in s["cards"]
                            ],
                        )
                    ],
                    group="准备",
                )
            )
        if game["phase"] == "lobby" or not s["ready"]:
            result.append(
                action(
                    "lobby.ready",
                    "取消准备"
                    if s["ready"]
                    else ("确认上下牌并再次准备" if game["phase"] == "ordering" else "准备发牌"),
                    group="准备",
                    blocking=not s["ready"],
                )
            )
        if "honoka" in s["cards"]:
            result.append(
                action(
                    "honoka.disguise",
                    "选择示人角色（穗乃香）",
                    [field("role", "示人身份", "select", role_options())],
                    group="准备",
                )
            )
        result.append(
            action(
                "player.profile",
                "设置公开称呼",
                [field("name", "公开称呼", default=s["name"])],
                group="准备",
            )
        )
        return result
    phase = game["phase"]
    if not can_use_card(game, card):
        card = None
    if phase in {"night", "night_coco"}:
        night = game["night"]
        cid = night["actors"].get(sid)
        cs = coco_seat(game)
        if (
            cid
            and can_use_card(game, game["cards"][cid])
            and sid not in night["confirmed"]
            and ((phase == "night" and sid != cs) or (phase == "night_coco" and sid == cs))
        ):
            acting = game["cards"][cid]
            submitted = {a["ability"] for a in night["actions"] if a["seat_id"] == sid}
            for ability in night_abilities(game, acting):
                if ability == "treasure" and submitted - {"treasure"}:
                    continue
                if "treasure" in submitted and ability != "treasure":
                    continue
                fields = []
                if ability == "scapegoat":
                    fields = [field("target_card", "显示为凶手的角色牌", "select", role_options())]
                elif ability not in {"massacre", "rain", "treasure", "witch_scan", "arisa_injure"}:
                    fields = [
                        target_field(
                            game,
                            True,
                            sid if ability == "swap" else None,
                            avoid_treasure=ability == "knife",
                        )
                    ]
                result.append(
                    action(
                        "night.submit",
                        ("修改" if ability in submitted else "选择") + NIGHT_ABILITIES[ability][1],
                        fields,
                        {"ability": ability},
                        "夜间",
                        danger=ability == "treasure",
                    )
                )
            if submitted:
                result.append(action("night.clear", "清除未确认夜间选择", group="夜间"))
            result.append(
                action("night.confirm", "确认已选行动（未选视为放弃）", group="夜间", blocking=True)
            )
    if card and game["half"] == "day":
        day_cards = [card]
        # 新版规则：艾玛即使在下层也可打断一次发言。
        emma_card = next((c for c in game["cards"].values() if c["role_id"] == "emma"), None)
        if (
            emma_card
            and emma_card["alive"]
            and owner(game, "emma")["id"] == sid
            and emma_card["id"] != card["id"]
        ):
            day_cards.append(emma_card)
        for ability in DAY_ABILITIES:
            ability_card = next(
                (
                    c
                    for c in day_cards
                    if can_day_ability(game, c, ability) or day_fake_allowed(game, c, ability)
                ),
                None,
            )
            if ability_card is None:
                continue
            if any(
                declaration["seat_id"] == sid
                and declaration["ability"] == ability
                and declaration["status"] == "open"
                for declaration in game["declarations"]
            ):
                continue
            fake = not can_day_ability(game, ability_card, ability)
            payload = {"ability": ability}
            # 下层艾玛打断才需要指定用牌，提交时一并带回。
            if ability_card["id"] != card["id"]:
                payload["card_id"] = ability_card["id"]
            result.append(
                action(
                    "day.skill",
                    ("声称" if fake else "") + DAY_ABILITIES[ability][1],
                    day_fields(game, ability, sid),
                    payload,
                    "私密伪装选择" if fake else "白天技能",
                    danger=ability == "spear",
                )
            )
    witness = next(
        (
            item
            for item in game["pending"]
            if item["kind"] == "honoka_witness" and item["seat_id"] == sid
        ),
        None,
    )
    if witness:
        result.append(
            action(
                "honoka.witness",
                "选择本次目击名单中的显示角色",
                [field("role", "名单显示身份", "select", role_options())],
                {"pending_id": witness["id"]},
                "私密信息",
                blocking=True,
            )
        )
    honoka = game["cards"]["honoka"]
    if card and card["id"] == "honoka" and not honoka["states"].get("disguise_locked"):
        result.append(
            action(
                "honoka.disguise",
                "选择示人角色",
                [field("role", "示人身份", "select", role_options())],
            )
        )
    if card and card["role_id"] == "hiro" and card["witch"]:
        result.append(action("hiro.exit", "主动出局", danger=True))
    if game["half"] == "day" and not lost_by_challenge(game, s):
        for declaration in game["declarations"]:
            if (
                declaration["status"] == "open"
                and declaration["seat_id"] != sid
                and challengeable(game, declaration)
            ):
                result.append(
                    action(
                        "day.challenge",
                        f"质疑{declaration['seat_id']}号的{DAY_ABILITIES[declaration['ability']][1]}",
                        payload={"declaration_id": declaration["id"]},
                        danger=True,
                    )
                )
    if phase == "speech" and game["public"]["speaker"] == sid:
        result.append(action("speech.done", "结束本次发言", group="流程", blocking=True))
    elif (
        phase == "speech"
        and sid in game["public"]["speech_order"]
        and sid not in game.get("speech_passed", [])
    ):
        result.append(
            action(
                "speech.done",
                "本轮不发言（跳过我的顺序）",
                group="流程",
            )
        )
    if (
        phase == "speech"
        and sid in game["public"]["speech_order"]
        and sid not in game.get("speech_passed", [])
    ):
        result.append(
            action(
                "speech.speak",
                "提前写发言（轮到你时公开）",
                [field("text", "发言内容", "textarea")],
                group="流程",
            )
        )
    nomination_options = [
        option
        for option in seat_options(game)
        if current(game, option[0])["states"].get("treasure_protected_day") != game["day"]
    ]
    if phase == "nomination" and card and sid not in game.get("nomination_done", []):
        result.append(
            action(
                "vote.nominate",
                "提名候选",
                [field("target", "目标", "select", nomination_options)],
                group="投票",
                blocking=True,
            )
        )
        result.append(action("vote.pass", "放弃本次提名", group="投票", blocking=True))
    elif game["half"] == "day" and card and sid not in game.get("nomination_done", []):
        result.append(
            action(
                "vote.nominate",
                "提名候选（可提前）",
                [field("target", "目标", "select", nomination_options)],
                group="投票",
            )
        )
        result.append(action("vote.pass", "放弃本次提名（可提前）", group="投票"))
    if phase == "voting" and s in eligible_voters(game) and sid not in game["votes"]:
        result.append(
            action(
                "vote.cast",
                "提交本候选选票",
                [
                    field(
                        "choice",
                        "选票",
                        "select",
                        [("yes", "同意"), ("no", "不同意"), ("abstain", "弃票")],
                    )
                ],
                group="投票",
                blocking=True,
            )
        )
    if (
        phase == "execution"
        and card
        and card["id"] in game["execution"]
        and sid not in game["execution_ready"]
    ):
        if card["role_id"] == "nanoka" and card["uses"].get("bullets", 0) > 0:
            threshold = min(card["uses"].get("shot_misses", 0) + 1, 6)
            result.append(
                action(
                    "execution.shoot",
                    f"临刑开枪（命中率{threshold}/6）",
                    [target_field(game)],
                    group="处决",
                    blocking=True,
                    danger=True,
                )
            )
            result.append(
                action("execution.confirm", "放弃临刑行动并确认", group="处决", blocking=True)
            )
    balloon = game["public"]["balloon"]
    if (
        balloon["status"] == "collecting"
        and sid in balloon["participants"]
        and sid not in game["balloon_choices"]
    ):
        options = [("make", "制作"), ("skip", "不制作")]
        if card and (card["witch"] or card["role_id"] == "annan"):
            options.append(("break", "破坏"))
        result.append(
            action(
                "balloon.choose",
                "秘密提交热气球选择",
                [field("choice", "选择", "select", options)],
                group="热气球",
                blocking=True,
            )
        )
    proposal = game["balloon_proposal"]
    if proposal and card and current(game, s) and sid not in proposal["votes"]:
        result.append(
            action(
                "balloon.agree",
                f"同意{proposal['by']}号的热气球名单",
                group="热气球",
            )
        )
        result.append(action("balloon.decline", "不同意该名单", group="热气球"))
    if (
        game["half"] == "day"
        and card
        and not present(game, "arisa")
        and balloon["day"] != game["day"]
        and not proposal
    ):
        result.append(
            action(
                "balloon.propose",
                "提议热气球名单（至多5人，过半同意即组织）",
                [
                    field(
                        "participants",
                        "提议参加者（至多5人）",
                        "multiselect",
                        seat_options(game),
                        min=1,
                        max=5,
                    )
                ],
                group="热气球",
            )
        )
    for photo in game["photos"]:
        if photo["target"] == sid:
            result.append(
                action(
                    "photo.permission",
                    f"{photo['sender']}号的信物：设置夜间行动授权",
                    [
                        field(
                            "allow",
                            "允许查看我的夜间行动",
                            "checkbox",
                            required=False,
                            default=photo.get("allowed", False),
                        )
                    ],
                    {"photo_id": photo["id"]},
                    "私密信息",
                )
            )
    if game["water"]["holder"] == sid and not game["water"]["used"]:
        fields = [target_field(game)]
        if card and card["role_id"] == "meruru" and card["witch"]:
            fields.append(field("hide_cause", "不公开13水死因", "checkbox", required=False))
        result.append(
            action(
                "water.use", "使用唯一13水（主持人裁定互动）", fields, group="私密行动", danger=True
            )
        )
    meruru = role_card(game, "meruru")
    if card and card["id"] == "meruru" and card["witch"] and not card["uses"].get("revive"):
        deaths = [
            death
            for death in game["deaths"]
            if death["day"] == game["day"]
            and death.get("source_card") == meruru["id"]
            and not game["cards"][death["target_card"]]["alive"]
        ]
        if deaths:
            result.append(
                action(
                    "meruru.revive",
                    "复活当日所杀者为无投票权、无技能傀儡",
                    [
                        field(
                            "death_id",
                            "复活对象",
                            "select",
                            [(death["id"], f"{death['seat_id']}号当天出局的角色牌") for death in deaths],
                        )
                    ],
                )
            )
    for cid in s["cards"]:
        dead = game["cards"][cid]
        if dead["states"].get("evidence_allowed") and not dead["states"].get("evidence_used"):
            fields = [
                field("text", "留下一个证物", "textarea", required=False),
                field("image", "证物图像", "drawing", required=False),
            ]
            result.append(
                action("evidence.submit", "提交夜间遗留证物", fields, {"card_id": cid}, "证物")
            )
    result.append(
        action("player.surrender", "私信主持人申请本阵营交牌", group="私密行动", danger=True)
    )
    return result
