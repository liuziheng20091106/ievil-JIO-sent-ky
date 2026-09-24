"""Privacy-safe action descriptors, also used as authoritative input grammar."""

from copy import deepcopy

from .catalog import (
    AUTO_PHASES,
    DAY_ABILITIES,
    DISCUSSION_END_VOTES,
    NIGHT_ABILITIES,
    ROLES,
)
from .resolution import coco_seat, target_allowed, treasure_protected
from .state import (
    can_use_card,
    card_actionable,
    controlled_cards,
    current,
    eligible_voters,
    hanna_witch_window,
    living,
    lost_by_challenge,
    pending_nominators,
    owner,
    player_seat,
    role_card,
    seat,
    seat_operable,
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
    "host.hanna_witch": "汉娜化",
    "host.rewind": "回溯",
    "host.confirm_winner": "宣判",
    "host.surrender": "交牌",
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
    "discussion.request_end": "求结束",
    "vote.nominate": "提名",
    "vote.pass": "弃提名",
    "vote.cast": "投票",
    "execution.shoot": "开枪",
    "execution.confirm": "放弃",
    "photo.permission": "信物",
    "water.use": "用水",
    "meruru.revive": "复活",
    "evidence.submit": "证物",
    "player.surrender": "申请交牌",
}

# 每个行动的一句话说明：两个客户端都已有渲染位（网页表单标题下、Flutter 行动表单与长按预览），
# 这里补齐内容，玩家点开行动时先看到「这一步在做什么、按哪条规则结算」。
# 同一 id 在不同场景需要不同措辞的，在调用处用 description= 覆盖。
DESCRIPTIONS = {
    "host.start": "全员两次准备后开局：锁定上下牌，进入当日魔女化检测。",
    "host.codex": "重新指定11名魔典角色并随机顺序；只改本局魔典，不影响已发出的牌。",
    "host.advance": "当前阶段没有待办时推进到下一阶段；有待裁定事项会先被拒绝。",
    "host.auto": "暂停后本阶段只由主持人手动推进；恢复后无人待办时5秒自动进入下一阶段。",
    "host.warn": "对当前卡住的席位启动30秒倒计时，到期按未操作处理；掉线不会自动放弃行动。",
    "host.water": "在夜间或预结算阶段把一瓶13水私下交给一个存活席位；同夜可发多瓶，各自使用，夜末未用会过期收回。",
    "host.damage": "裁定伤害或直接出局：死亡应用庇护，无条件出局忽略庇护；夜间提交的伤害并入本夜预结算。",
    "host.state": "直接增删角色牌状态（魔女化、中毒、庇护、负伤、投票权、傀儡、生死）；不勾选公开时只通知该席位。",
    "host.information": "向全员或指定席位发放信息与照片；不公开时只有选中的席位能看到。",
    "host.madness": "对某个席位的疯狂行为发起裁定，随后由主持人选择警告、符合要求或执行不利裁定。",
    "host.codex_order": "手动指定11名角色的最终顺序，用于特殊裁定。",
    "host.hanna_witch": "「汉娜魔化」默认关闭：开启后第三天夜里满足条件时由汉娜覆盖当天魔女人选，只在第三天入夜前可改。",
    "host.rewind": "回溯到指定快照时间点，并额外保留精神系状态；希罗的固定回溯由系统自动处理，这里只用于其他特殊裁定。",
    "host.confirm_winner": "本半天全部同时出局与连锁都处理完后确认宣判，按已达成的条件结束对局。",
    "host.surrender": "审阅交牌：好人交牌需全员分别私信同意，魔女交牌仅在只剩可可且本人申请时成立。",
    "host.end": "主持人终止对局或做特殊胜负裁定；提交后本局立即结束。",
    "host.speech": "只在顺序发言阶段可用：改起点或方向会重排本轮顺序。",
    "lobby.order": "发牌后选择哪张牌作为上层；艾玛、米莉亚、亚里沙必须放在下层。",
    "lobby.ready": "确认准备；全员再次准备后由主持人开局。",
    "player.profile": "设置本局的公开称呼，其他玩家和主持人都能看到。",
    "night.clear": "清除本席位尚未确认的夜间选择；已确认的行动要改需主持人裁定。",
    "night.confirm": "确认本席夜间选择；未确认的选择不计入结算，未选视为放弃。",
    "day.challenge": "质疑他人的白天技能声明；质疑失败本局个人判负。",
    "honoka.disguise": "穗乃香选择一个示人角色：只改别人看到的角色名，不获得该角色的技能。",
    "honoka.witness": "选择本次目击名单里显示的角色；这是穗乃香的魔女化技能。",
    "hiro.exit": "希罗主动出局：夜间提交时并入本夜预结算，白天则立即结算。",
    "speech.done": "结束本次发言推进顺序；还没轮到你时是「本轮不发言」，轮到时自动略过。",
    "speech.speak": "提前写下发言内容，轮到你时由系统以本人身份公开，并自动略过你的顺序。",
    "vote.nominate": "提名一名候选人，提交即生效；提名过同一候选的玩家之后自动投同意票。",
    "vote.pass": "放弃本次提名；提名在白天随时可以提交。",
    "execution.shoot": "临刑开枪：命中则目标按标准结算出局，未命中则下次命中率提高1/6。",
    "execution.confirm": "放弃临刑行动并确认，进入处决结算。",
    "photo.permission": "可可赠送的信物：设置是否允许她查看你的夜间行动。",
    "water.use": "用掉本夜的一瓶13水并立即指定目标，毒杀直接进入本夜预结算，无需主持人确认。",
    "meruru.revive": "魔女化梅露露复活当夜由自己击杀的牌；复活者是无投票权、无技能的傀儡，该次死亡的公告与目击一并撤销。",
    "evidence.submit": "提交夜间遗留证物；公开范围由主持人裁定。",
    "player.surrender": "私信主持人申请本阵营交牌；未满足集体条件前继续游戏。",
    "discussion.request_end": "提交一次结束自由发言的请求；六个不同席位提交后10秒自动进入提名。",
    # 私信与房间管理（id 只在 app/views.py 里使用，短名同样是显式给的）。
    "channel.create": "创建私信频道；被邀请者同意后频道生效，期间成员只能在该频道发言。",
    "channel.accept": "同意加入该私信；全部成员同意后频道转为生效。",
    "channel.reject": "拒绝加入，本次私信邀请作废。",
    "channel.end": "结束整个私信频道；已结束的频道只能查看历史，不能再发言。",
    "room.open_join": "控制账号能否主动参局；关闭后仍可由你定向邀请。",
    "room.kick": "把参与者移出本局，可选择同时在本局拉黑。",
    "room.replace": "由观战者接管空席；接管保留该席角色牌、技能次数与裁定状态，不重抽角色。",
    "room.mute": "设置或解除参与者禁言；禁言只影响发言，不影响规则判定。",
}

# 主持人待办的说明：标题已经写明是哪件事，这里补上「裁定后按什么结算」。
PENDING_DESCRIPTIONS = {
    "information": "这段裁定信息会按标题指定的范围发给当事人。",
    "suspects": "为夜间死者填写四名疑似凶手（真凶与汉娜优先），用于当日目击名单。",
    "evidence": "裁定证物内容与公开范围；不公开时只发给指定席位。",
    "codex": "魔典未按时结算时选择跳过或指定特殊转化对象。",
    "madness": "疯狂行为裁定：警告、符合要求，或判定不够疯狂并执行不利裁定。",
    "reaction": "确认按夜间预结算执行；有特殊互动请先退出并纠错。",
}

# 同一个 night.submit 按钮会因为角色与魔女化状态对应不同技能，说明按技能而不是按 id 给。
NIGHT_ABILITY_DESCRIPTIONS = {
    "knife": "魔女刀：指定一名当前牌为目标，按当夜预结算统一生效。",
    "massacre": "全场攻击：杀死所有其他角色，与当夜其他伤害一同预结算。",
    "extra_kill": "额外攻击：本局一次，可再杀死一名角色，之后失去该技能。",
    "protect": "庇护一张当前牌：该牌当夜死亡改为负伤；再次受到普通伤害则出局。",
    "rain": "下雨：本局一次，此后夜间死者会公开凶手座位号的方向线索。",
    "scapegoat": "替罪凶手：本局一次，指定之后自己造成死亡时对外显示的凶手。",
    "swap": "换血：必须选择一名玩家；其即将死亡时由你代替其死亡。",
    "treasure": "寻宝：提交即清空本席其他夜间选择并锁定全夜，1/5概率触发地雷。",
    "witch_scan": "查看全员当前魔女化状态，结果只发给你。",
    "arisa_injure": "令环形左右邻座各以1/2概率负伤；该效果不会把已有负伤升级为死亡。",
}

# 白天技能：真实与伪装走同一条描述，伪装的说明另外点出「可被质疑」。
DAY_ABILITY_DESCRIPTIONS = {
    "interrupt": "立即打断指定席位的发言，每个白天一次；艾玛在下层也可使用。",
    "brainwash": "秘密洗脑一人，该人本轮投票自动弃票；与玛格同时洗脑会互相抵消。",
    "mass_brainwash": "洗脑全场处决一名角色；使用后失去该技能，并在下一天失去投票权且必须被处刑。",
    "love": "宣布爱上一人或移情；此后每夜令爱人席当前牌负伤一次。",
    "gaze": "查看本日处决名单是否含魔女，结果只发给你。",
    "spear": "长矛令一张当前牌立即进入标准出局预结算，你同时加入本日处决名单。",
    "photo": "赠送无图像信物；受赠者可授权你查看其夜间行动。",
}


# 提名说明要写清「提交即生效、计票去重」，两个分支（阶段内/提前）措辞相同。
NOMINATE_DESCRIPTION = (
    "提交即生效，无需二次确认；同一人可被多人提名，进入投票后计票去重，"
    "每个候选人只投一轮，提名过该候选的玩家自动投同意票。"
    "寻宝保护者在保护当天不能被提名。"
)


def field(name, label, kind="text", options=None, required=True, **extra):
    item = {"name": name, "label": label, "type": kind, "required": required, **extra}
    if options is not None:
        item["options"] = [{"value": str(v), "label": str(label)} for v, label in options]
    return item


def action(action_id, label, fields=(), payload=None, group="行动", short_label=None, **extra):
    short = short_label or SHORT_LABELS[action_id]
    if not 2 <= len(short) <= 4:
        raise ValueError(f"行动短名必须为2至4字：{action_id}")
    extra.setdefault("description", DESCRIPTIONS.get(action_id, ""))
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
    # 只有「有人能操作」的席位才算待办：傀儡当前牌在主人出局后无人可代，
    # 排它就会既等不到提交、又挡住自动推进与主持人的阻塞待办。
    def drivable(sid):
        """该席能否提交本阶段行动（含傀儡须有在场主人）。"""
        return seat_operable(game, sid)

    def night_drivable(sid):
        """该席能否代行夜间行动：夜间行动取决于技能，用 card_actionable 判。"""
        return card_actionable(game, game["cards"][game["night"]["actors"][sid]])

    if phase in {"night", "night_coco"}:
        coco = coco_seat(game)
        for sid in game["night"]["actors"]:
            if sid in game["night"]["confirmed"] or (phase == "night" and sid == coco):
                continue
            if night_drivable(sid):
                result.append(sid)
    elif phase == "speech" and game["public"]["speaker"]:
        # sync_speaker 保证 speaker 一定有人可操作：这里照常登记即可，
        # 但再挡一道，避免状态被绕过命令改写后让自动推进空等一个等不到的确认。
        if seat_operable(game, game["public"]["speaker"]):
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
            and card_actionable(game, game["cards"][cid])
        ]
    result += [
        item["seat_id"] for item in game["pending"] if item["kind"] == "honoka_witness"
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
            and (not avoid_treasure or not treasure_protected(game, current(game, sid)["id"]))
        ],
    )


def day_fields(game, ability, exclude=None):
    if ability == "gaze":
        return []
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
    if phase not in {"speech", "discussion", "nomination", "voting"}:
        return False
    if DAY_ABILITIES[ability][0] != role:
        return False
    if ability == "love":
        return card["uses"].get("love_day") != game["day"]
    if ability == "spear":
        return card["uses"].get("spear_day") != game["day"]
    return ability == "photo"


def claimable(role):
    """该示人身份可以声称的白天技能：本角色的技能，魔女玛格另含学到的洗脑。"""
    if not role:
        return set()
    return {ability for ability, (owner, _) in DAY_ABILITIES.items() if owner == role} | (
        {"brainwash"} if role == "marg" else set()
    )


def challengeable(game, declaration):
    """除信物、爱人选择与处决幻视以外，所有开放的白天技能声明均可质疑。

    处决幻视属于处决阶段的临刑技能，不能伪装发动，因此没有可质疑的真假。
    """
    return declaration["ability"] not in {"photo", "love", "gaze"}

def day_fake_allowed(game, card, ability):
    # 处决幻视只能由奈乃香本人在处决阶段发动，不存在伪装声明。
    if ability == "gaze":
        return False
    phase = game["phase"]
    phases = {
        "brainwash": {"voting"},
        "mass_brainwash": {"discussion", "nomination", "voting"},
        "interrupt": {"speech", "discussion"},
    }.get(ability, {"speech", "discussion", "nomination", "voting"})
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
                    ("penalty", "判定不够疯狂并执行不利裁定"),
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
        description=PENDING_DESCRIPTIONS.get(kind, ""),
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
        if hanna_witch_window(game):
            # 默认关闭的主持人开关：只在第三天入夜前可改，标签上直接显示当前状态。
            enabled = bool(game.get("hanna_witch"))
            result.append(
                action(
                    "host.hanna_witch",
                    "汉娜魔化：已开启" if enabled else "汉娜魔化：已关闭",
                    [
                        field(
                            "value",
                            "开关（第三天入夜前可改）",
                            "select",
                            [("on", "开启"), ("off", "关闭")],
                            default="on" if enabled else "off",
                        )
                    ],
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


def puppet_action_panels(game, controller):
    """控制傀儡的魔女梅露露可见的代操作面板：标签与短名前缀星号，逐条携带目标席位。"""
    own = player_seat(game, controller)
    panels = []
    for card in controlled_cards(game, own["id"]):
        target = owner(game, card["id"])
        actions = []
        for descriptor in actions_for(game, controller, puppet_controlled=True, as_seat=target["id"]):
            item = deepcopy(descriptor)
            # 星号只加在 label 上：short_label 受动作协议 2—4 字约束，
            # 加了前缀会让两个客户端都判定协议不符并整体禁用傀儡面板。
            item["label"] = f"*{item['label']}"
            item["as_seat"] = target["id"]
            item["description"] = (
                f"傀儡视角 · {target['id']}号 · {target['name']}；"
                "由你代为执行，仍按该席位的角色与状态结算。"
            )
            actions.append(item)
        panels.append({"seat_id": target["id"], "name": target["name"], "actions": actions})
    return panels


def actions_for(game, actor, *, puppet_controlled=False, as_seat=None):
    """玩家可见行动；puppet_controlled 时生成受控傀儡席的动作并统一加星号前缀。"""
    if game["status"] == "ended":
        return []
    if actor.get("kind") == "host":
        return host_actions(game)
    if actor.get("kind") != "player":
        return []
    s = player_seat(game, actor)
    sid = as_seat or s["id"]
    active_seat = seat(game, sid)
    card = current(game, active_seat)
    result = []
    if game["status"] == "lobby":
        if game["phase"] == "ordering" and not active_seat["ready"]:
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
                                for cid in active_seat["cards"]
                            ],
                        )
                    ],
                    group="准备",
                )
            )
        if game["phase"] == "lobby" or not active_seat["ready"]:
            result.append(
                action(
                    "lobby.ready",
                    "取消准备"
                    if active_seat["ready"]
                    else ("确认上下牌并再次准备" if game["phase"] == "ordering" else "准备发牌"),
                    group="准备",
                    blocking=not active_seat["ready"],
                )
            )
        if "honoka" in active_seat["cards"]:
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
                [field("name", "公开称呼", default=active_seat["name"])],
                group="准备",
            )
        )
        return result
    phase = game["phase"]
    if not can_use_card(game, card, puppet_controlled):
        card = None
    # 傀儡席的原玩家一律看不到游戏行动，由控制它的魔女梅露露代为操作。
    if (
        not puppet_controlled
        and current(game, active_seat)
        and current(game, active_seat)["states"].get("puppet")
    ):
        return []
    if phase in {"night", "night_coco"}:
        night = game["night"]
        cid = night["actors"].get(sid)
        cs = coco_seat(game)
        if (
            cid
            and can_use_card(game, game["cards"][cid], puppet_controlled)
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
                        description=NIGHT_ABILITY_DESCRIPTIONS.get(ability, ""),
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
                    description=DAY_ABILITY_DESCRIPTIONS.get(ability, "")
                    + (
                        "这是伪装声明：不产生技能效果，技能条目已公开，其他人可质疑。"
                        if fake
                        else ""
                    ),
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
    if game["half"] == "day" and not lost_by_challenge(game, active_seat):
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
        result.append(
            action("speech.done", "结束本次发言", group="流程", blocking=True)
        )
    elif (
        phase == "speech"
        and sid in game["public"]["speech_order"]
        and sid not in game.get("speech_passed", [])
    ):
        result.append(
            action("speech.done", "本轮不发言（跳过我的顺序）", group="流程")
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
    if phase == "discussion" and card_actionable(game, card) and sid not in game.get(
        "discussion_end_requests", []
    ):
        submitted = len(game.get("discussion_end_requests", []))
        result.append(
            action(
                "discussion.request_end",
                f"请求结束自由发言（已有{submitted}/{DISCUSSION_END_VOTES}人提交）",
                group="流程",
            )
        )
    nomination_options = [
        option
        for option in seat_options(game)
        if not treasure_protected(game, current(game, option[0])["id"])
    ]
    if phase == "nomination" and card and sid not in game.get("nomination_done", []):
        result.append(
            action(
                "vote.nominate",
                "提名候选",
                [field("target", "目标", "select", nomination_options)],
                group="投票",
                blocking=True,
                description=NOMINATE_DESCRIPTION,
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
                description=NOMINATE_DESCRIPTION,
            )
        )
        result.append(action("vote.pass", "放弃本次提名（可提前）", group="投票"))
    if phase == "voting" and active_seat in eligible_voters(game) and sid not in game["votes"]:
        votes = game["public"]["votes"]
        candidate = votes.get("candidate")
        name = seat(game, candidate)["name"] if candidate else ""
        voters = len(eligible_voters(game))
        result.append(
            action(
                "vote.cast",
                f"对{candidate}号 · {name}投票" if candidate else "提交本候选选票",
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
                description=(
                    f"本轮候选：{candidate}号 · {name}"
                    f"（第{votes.get('round', 1)}/{votes.get('total', 1)}轮）。"
                    f"同意票需严格超过有投票权存活玩家的一半，即至少{voters // 2 + 1}票，"
                    "候选才会进入处决前响应；弃票与不同意都不会通过。"
                    if candidate
                    else "同意票需严格超过有投票权存活玩家的一半，候选才会进入处决前响应。"
                ),
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
                    description=(
                        f"本次命中率{threshold}/6；未命中则下次提高1/6，命中后重置为1/6。"
                        f"命中后目标按标准结算出局（庇护仍然生效）。剩余子弹{card['uses'].get('bullets', 0)}发。"
                    ),
                )
            )
            result.append(
                action("execution.confirm", "放弃临刑行动并确认", group="处决", blocking=True)
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
    if sid in game["water"]["holders"]:
        fields = [target_field(game)]
        if card and card["role_id"] == "meruru" and card["witch"]:
            fields.append(field("hide_cause", "不公开13水死因", "checkbox", required=False))
        result.append(
            action("water.use", "使用本夜13水（立即进入预结算）", fields, group="私密行动", danger=True)
        )
    meruru = role_card(game, "meruru")
    if card and card["id"] == "meruru" and card["witch"] and not card["uses"].get("revive"):
        deaths = [
            death
            for death in game["deaths"]
            if death["day"] == game["day"]
            and death["half"] == "night"
            and death.get("source_card") == meruru["id"]
            and not game["cards"][death["target_card"]]["alive"]
        ]
        if deaths:
            result.append(
                action(
                    "meruru.revive",
                    "复活当夜所杀者为无投票权、无技能傀儡",
                    [
                        field(
                            "death_id",
                            "复活对象",
                            "select",
                            [(death["id"], f"{death['seat_id']}号当夜出局的角色牌") for death in deaths],
                        )
                    ],
                )
            )
    for cid in active_seat["cards"]:
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
