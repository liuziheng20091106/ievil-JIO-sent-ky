"""Privacy-safe action descriptors, also used as authoritative input grammar."""

from .catalog import DAY_ABILITIES, NIGHT_ABILITIES, ROLES
from .resolution import coco_seat, target_allowed
from .state import (
    can_use_card,
    current,
    eligible_voters,
    next_nominator,
    player_seat,
    present,
    role_card,
)


def field(name, label, kind="text", options=None, required=True, **extra):
    item = {"name": name, "label": label, "type": kind, "required": required, **extra}
    if options is not None:
        item["options"] = [{"value": str(v), "label": str(label)} for v, label in options]
    return item


def action(action_id, label, fields=(), payload=None, group="行动", **extra):
    return {
        "id": action_id,
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


def target_field(game, night=False, exclude=None):
    return field(
        "target",
        "目标席位",
        "select",
        [
            (sid, label)
            for sid, label in seat_options(game)
            if sid != exclude and (not night or target_allowed(game, current(game, sid)["id"]))
        ],
    )


def day_fields(game, ability):
    if ability == "last_speaker":
        return []
    if ability == "balloon":
        return [
            field(
                "participants", "参加者（至多4人）", "multiselect", seat_options(game), min=1, max=4
            )
        ]
    if ability == "photo":
        return [
            target_field(game),
            field("text", "照片说明", "textarea", required=False),
            field("image", "照片画面", "drawing", required=False),
        ]
    return [target_field(game)]


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
    if ability in {"interrupt", "last_speaker"}:
        return (
            role == "emma"
            and phase in {"speech", "discussion"}
            and card["uses"].get("interrupt_day") != game["day"]
            and (ability != "last_speaker" or phase == "speech")
        )
    if phase not in {"speech", "discussion", "balloon"}:
        return False
    if DAY_ABILITIES[ability][0] != role:
        return False
    if ability == "love":
        return card["uses"].get("love_day") != game["day"]
    if ability == "gaze":
        return card["uses"].get("gaze_day") != game["day"]
    if ability == "balloon":
        return game["public"]["balloon"]["day"] != game["day"]
    return ability == "photo"


def night_abilities(game, card):
    role, witch, uses = card["role_id"], card["witch"], card["uses"]
    abilities = ["knife"] if witch else []
    if role == "emma" and witch and game["day"] >= 3:
        abilities.append("massacre")
    if role == "hanna" and witch and not uses.get("extra_kill"):
        abilities.append("extra_kill")
    if role == "meruru":
        abilities.append("protect")
    if role == "noah":
        abilities.append("paint")
        if witch and not uses.get("frame"):
            abilities.append("frame")
    if role == "millia" and not uses.get("swap"):
        abilities.append("swap")
    if role == "nanoka" and uses.get("bullets", 0) > 0:
        abilities.append("shoot")
    if role == "marg" and uses.get("decode", 0) < 2:
        abilities.append("decode")
    if role == "leia" and witch:
        abilities.append("spear")
    return abilities


def pending_action(game, item):
    kind = item["kind"]
    fields = []
    if kind == "information":
        fields = [field("text", "发给当事人的裁定信息", "textarea")]
    elif kind == "millia":
        fields = [
            field(
                "follow",
                "交换后行动目标跟随",
                "select",
                [("card", "原角色牌"), ("seat", "原席位当前上层")],
            )
        ]
    elif kind == "hiro":
        choices = [("decline", "不发动回溯")] + [
            (s["id"], f"{s['label']}（日{s['day']}）") for s in game["snapshots"]
        ]
        fields = [
            field("snapshot", "回溯时间点（优先前一天同阶段；其他须裁定）", "select", choices),
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
        fields = [
            field("suspects", "三名疑似凶手", "multiselect", role_options(), min=3, max=3),
            field("omit_leia", "裁定魔女蕾雅不列入名单", "checkbox", required=False),
        ]
        if not item.get("source_card"):
            fields.append(field("true_source", "补充裁定实际真凶", "select", role_options()))
    elif kind == "lower_entry":
        fields = [
            field("allow", "允许下层本阶段行动（同半天仍最多出局一牌）", "checkbox", required=False)
        ]
    elif kind == "declaration":
        fields = [
            field(
                "outcome",
                "声明处理",
                "select",
                [
                    ("execute", "执行尚未执行的效果并保留质疑窗口"),
                    ("complete", "执行并完成声明"),
                    ("stop", "依据裁定停止尚未完成部分"),
                ],
            ),
            field("reason", "裁定说明", "textarea", required=False),
        ]
    elif kind == "challenge":
        fields = [field("confirm", "确认按真实或伪装结算质疑（失败者出局并个人判负）", "checkbox")]
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
            ),
            field("reason", "互动与时机裁定", "textarea"),
        ]
    elif kind == "evidence":
        fields = [
            field("public", "向全员公开", "checkbox", required=False),
            field(
                "recipients",
                "未公开时的接收席位",
                "multiselect",
                seat_options(game, False),
                required=False,
            ),
            field("allow", "准许发布（不勾选为拒绝）", "checkbox", required=False),
        ]
    elif kind == "codex":
        fields = [
            field(
                "outcome",
                "魔典处理",
                "select",
                [("skip", "本日不转化"), ("convert", "指定特殊转化对象")],
            ),
            field(
                "target",
                "特殊转化对象",
                "select",
                [("", "不指定")] + role_options(),
                required=False,
            ),
            field("reason", "裁定说明", "textarea"),
        ]
    elif kind == "balloon_organize":
        fields = [
            field("allow", "确认好人组织投票通过（不勾选为否决）", "checkbox", required=False),
            field(
                "participants",
                "通过时指定参加者（至多4人）",
                "multiselect",
                seat_options(game),
                required=False,
                min=0,
                max=4,
            ),
            field("reason", "组织投票裁定说明", "textarea"),
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
        fields = [field("proceed", "确认按预结算执行（特殊互动请先纠错）", "checkbox")]
    return action("host.resolve", item["title"], fields, {"pending_id": item["id"]}, "裁决待办")


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
        result.append(action("host.advance", "完成当前阶段 / 推进", group="流程"))
    result.extend(pending_action(game, p) for p in game["pending"])
    result.append(
        action(
            "host.water",
            "私下交付唯一13水",
            [field("seat_id", "持有者", "select", seat_options(game, False))],
            group="私密管理",
        )
    )
    if game["status"] == "playing":
        result.extend(
            [
                action(
                    "host.warn",
                    "警告：30秒后结束该玩家操作",
                    [field("seat_id", "被警告席位", "select", seat_options(game, False))],
                    group="流程",
                ),
                action(
                    "host.speech",
                    "安排顺序发言",
                    [
                        field(
                            "order",
                            "发言顺序（按选择顺序）",
                            "multiselect",
                            seat_options(game, False),
                            min=1,
                            max=7,
                        )
                    ],
                    group="流程",
                ),
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
    if game["status"] == "lobby":
        if game["phase"] == "ordering":
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
        result.append(
            action(
                "lobby.ready",
                "取消准备"
                if s["ready"]
                else ("确认上下牌并再次准备" if game["phase"] == "ordering" else "准备发牌"),
                group="准备",
            )
        )
        result.append(
            action(
                "player.profile",
                "设置公开称呼和开局示人头像",
                [
                    field("name", "公开称呼", default=s["name"]),
                    field(
                        "avatar",
                        "示人头像（开局前保密，不代表真实角色）",
                        "select",
                        [("", "开局时使用上层角色头像")] + role_options(),
                        required=False,
                        default=s["avatar_role_id"] or "",
                    ),
                ],
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
                fields = []
                if ability == "paint":
                    fields = [
                        field("image", "夜间画作", "drawing"),
                        field("text", "画作说明", "textarea", required=False),
                    ]
                elif ability == "decode":
                    fields = [
                        field(
                            "guess",
                            "猜测11名角色及顺序",
                            "multiselect",
                            role_options(),
                            min=11,
                            max=11,
                        )
                    ]
                elif ability != "massacre":
                    fields = [target_field(game, True, sid if ability == "swap" else None)]
                result.append(
                    action(
                        "night.submit",
                        ("修改" if ability in submitted else "选择") + NIGHT_ABILITIES[ability][1],
                        fields,
                        {"ability": ability},
                        "夜间",
                    )
                )
            if submitted:
                result.append(action("night.clear", "清除未确认夜间选择", group="夜间"))
            result.append(action("night.confirm", "确认已选行动（未选视为放弃）", group="夜间"))
    if card and game["half"] == "day":
        for ability in DAY_ABILITIES:
            if can_day_ability(game, card, ability) and not any(
                d["seat_id"] == sid and d["ability"] == ability and d["status"] == "open"
                for d in game["declarations"]
            ):
                result.append(
                    action(
                        "day.skill",
                        DAY_ABILITIES[ability][1],
                        day_fields(game, ability),
                        {"ability": ability},
                        "白天技能",
                    )
                )
        if card["role_id"] == "honoka" and phase in {
            "speech",
            "discussion",
            "balloon",
            "nomination",
            "voting",
        }:
            for ability in DAY_ABILITIES:
                if not any(
                    d["seat_id"] == sid and d["ability"] == ability and d["status"] == "open"
                    for d in game["declarations"]
                ):
                    result.append(
                        action(
                            "day.skill",
                            "声称" + DAY_ABILITIES[ability][1],
                            day_fields(game, ability),
                            {"ability": ability},
                            "私密伪装选择",
                        )
                    )
    if card and card["role_id"] == "honoka":
        result.append(
            action(
                "honoka.disguise",
                "选择示人角色",
                [field("role", "示人身份", "select", role_options())],
            )
        )
        if card["witch"]:
            result.append(
                action(
                    "honoka.witness",
                    "设定目击名单中的显示角色",
                    [field("role", "名单显示身份", "select", role_options())],
                )
            )
    if card and card["role_id"] == "hiro" and card["witch"]:
        result.append(action("hiro.exit", "主动出局", danger=True))
    if game["half"] == "day":
        for declaration in game["declarations"]:
            if (
                declaration["status"] == "open"
                and declaration["seat_id"] != sid
                and not any(
                    p["kind"] == "challenge"
                    and p["declaration_id"] == declaration["id"]
                    and p["seat_id"] == sid
                    for p in game["pending"]
                )
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
        result.append(action("speech.done", "结束本次发言", group="流程"))
    if phase == "nomination" and card and next_nominator(game) == sid:
        result.append(action("vote.nominate", "提名候选", [target_field(game)], group="投票"))
        result.append(action("vote.pass", "放弃本次提名并交给下一人", group="投票"))
    if phase == "voting" and s in eligible_voters(game):
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
            )
        )
    if (
        phase == "execution"
        and card
        and card["id"] in game["execution"]
        and sid not in game["execution_ready"]
    ):
        if card["role_id"] == "nanoka" and card["uses"].get("bullets", 0) > 0:
            result.append(
                action(
                    "execution.shoot",
                    "临刑开枪（1/3魔女，1/6普通）",
                    [target_field(game)],
                    group="处决",
                )
            )
        result.append(action("execution.confirm", "放弃临刑行动并确认", group="处决"))
    balloon = game["public"]["balloon"]
    if (
        balloon["status"] == "collecting"
        and sid in balloon["participants"]
        and sid not in game["balloon_choices"]
    ):
        options = [("make", "制作")]
        if card and (card["witch"] or card["role_id"] == "annan"):
            options.append(("break", "破坏"))
        result.append(
            action(
                "balloon.choose",
                "秘密提交热气球选择",
                [field("choice", "选择", "select", options)],
                group="热气球",
            )
        )
    if (
        game["half"] == "day"
        and card
        and not card["witch"]
        and not present(game, "arisa")
        and balloon["day"] != game["day"]
        and phase in {"discussion", "balloon"}
    ):
        result.append(
            action(
                "balloon.organize_vote",
                "好人秘密投票组织热气球",
                [field("agree", "同意组织", "checkbox", required=False)],
                group="热气球",
            )
        )
    for photo in game["photos"]:
        if photo["recipient"] == sid:
            result.append(
                action(
                    "photo.permission",
                    f"{photo['sender']}号的照片：设置夜间行动授权",
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
        targets = [
            k["card_id"]
            for k in meruru["states"].get("kills", [])
            if k["day"] == game["day"] and not game["cards"][k["card_id"]]["alive"]
        ]
        if targets:
            result.append(
                action(
                    "meruru.revive",
                    "复活当日所杀者为无投票权傀儡",
                    [
                        field(
                            "death_id",
                            "复活对象",
                            "select",
                            [
                                (d["id"], f"{d['seat_id']}号当天出局的角色牌")
                                for d in game["deaths"]
                                if d["target_card"] in targets and d["day"] == game["day"]
                            ],
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
            if cid == "noah":
                fields.append(
                    field(
                        "paintings",
                        "额外留下已画作品（可多选）",
                        "multiselect",
                        [
                            (p["image_id"], p.get("text") or f"第{p['day']}天画作")
                            for p in dead["states"].get("paintings", [])
                        ],
                        required=False,
                    )
                )
            result.append(
                action("evidence.submit", "提交夜间遗留证物", fields, {"card_id": cid}, "证物")
            )
    result.append(
        action("player.surrender", "私信主持人申请本阵营交牌", group="私密行动", danger=True)
    )
    return result
