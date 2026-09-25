"""The single public role catalogue; rules are intentionally data, not subclasses."""

CATALOG = [
    {
        "id": "emma",
        "name": "艾玛",
        "avatar": "/assets/characters/樱羽艾玛.png",
        "normal": "即使在下层，每个白天也可打断一次他人发言；未魔女化时艾玛可以在庭院里挖地寻宝...参见原作。只要仍存活，同席另一张牌及相邻席当前牌中毒。前两天不能魔女化；第三天若仍存活则必定魔女化。",
        "witch": "夜里杀死所有其他角色，不能放弃。",
    },
    {
        "id": "hiro",
        "name": "希罗",
        "avatar": "/assets/characters/二阶堂希罗.png",
        "normal": "即将死亡时自动回溯一次（本局该身份一次）：夜间回到前一天顺序发言，白天回到前一天自由发言；找不到该时点则回到开局。保留记忆与普通技能，精神系效果不恢复。",
        "witch": "另有独立的一次回溯额度，回溯后保留魔女化；可随时主动出局。必须疯狂使艾玛出局，至多一个夜晚例外。",
    },
    {
        "id": "hanna",
        "name": "汉娜",
        "avatar": "/assets/characters/远野汉娜.png",
        "normal": "在场时始终位于每份疑似凶手名单中，使名单由三人增加为四人；13水致死同样出现。",
        "witch": "可额外杀死一名角色，然后失去本技能。",
    },
    {
        "id": "sherry",
        "name": "雪莉",
        "avatar": "/assets/characters/橘雪莉.png",
        "normal": "不能魔女化。开局时若雪莉与汉娜均为各自上层，立即绑定；否则需两张牌同时为当前牌并共同度过完整白天后绑定：胜负跟随汉娜，不能同意处决汉娜；汉娜被处刑时殉情。",
        "witch": "不能魔女化。",
    },
    {
        "id": "meruru",
        "name": "梅露露",
        "avatar": "/assets/characters/冰上梅露露.png",
        "normal": "每晚可庇护一张当前牌：死亡改为负伤，再次负伤即出局。",
        "witch": "一次复活当夜由自己造成死亡的角色（不要求目标曾受庇护），该角色成为不能投票、不能发动技能的傀儡，那次死亡的公告、死因与目击一并撤销；可隐藏自己使用13水杀人的死因。",
    },
    {
        "id": "noah",
        "name": "诺亚",
        "avatar": "/assets/characters/城崎诺亚.png",
        "normal": "每局一次令当夜下雨；有来源的夜间死亡会公开凶手座位相对死者的方向，汉娜造成的方向相反。",
        "witch": "每局一次指定任意角色牌，作为自己之后造成死亡时显示的凶手。",
    },
    {
        "id": "annan",
        "name": "安安",
        "avatar": "/assets/characters/夏目安安.png",
        "normal": "只要诺亚是同席的下层牌或相邻席当前牌，这张牌中毒。",
        "witch": "一次洗脑全场处决一人；次日失去投票权且必须被处刑。",
    },
    {
        "id": "millia",
        "name": "米莉亚",
        "avatar": "/assets/characters/佐伯米莉亚.png",
        "normal": "每晚必须交换一名玩家（未提交时由系统随机指定），该目标一直保留到你下一次交换。只有其真的会出局时才由你代替出局（不含处刑、质疑失败、殉情与寻宝地雷；白天只有奈乃香的枪）；玛格的爱人与被庇护的目标优先于你。",
        "witch": "无额外魔女化技能；魔女可独立使用魔女刀。",
    },
    {
        "id": "coco",
        "name": "可可",
        "avatar": "/assets/characters/泽渡可可.png",
        "normal": "白天可赠送无图像信物；受赠者可以授权你观看自己的夜间行动。",
        "witch": "得知魔典；查看其他全部夜间行动后最后行动。",
    },
    {
        "id": "nanoka",
        "name": "奈乃香",
        "avatar": "/assets/characters/黑部奈叶香.png",
        "normal": "6颗子弹，仅在即将被处决时开枪；连续未命中会把下次命中率由1/6逐步提高至必定命中。白天可幻视本日处决名单是否含魔女。",
        "witch": "每夜获知全员当前魔女化状态。",
    },
    {
        "id": "arisa",
        "name": "亚里沙",
        "avatar": "/assets/characters/紫藤亚里沙.png",
        "normal": "不能魔女化。每夜可令环形左右邻座各以50%概率负伤一次；已有负伤的角色再次负伤即无条件出局。如果白天有对跳且没有在对跳里处决，即使你在下层也出局（主持人裁定）。",
        "witch": "不能魔女化。",
    },
    {
        "id": "marg",
        "name": "玛格",
        "avatar": "/assets/characters/宝生马格.png",
        "normal": "白天可宣布爱上一人或移情（从当天夜里开始生效）；若爱人整席出局则转爱自己。每夜令爱人席当前牌负伤一次，同时爱人免疫处决、临刑开枪、魔女刀与13水等一切死亡和其他负伤。",
        "witch": "无额外魔女化技能；魔女可独立使用魔女刀。",
    },
    {
        "id": "leia",
        "name": "蕾雅",
        "avatar": "/assets/characters/莲见蕾雅.png",
        "normal": "白天必须疯狂地引人注目，即使为此说谎。白天可宣布与一张当前牌决斗并失去本技能：今天所有人必须至少同意这两张牌之一，且它们达到半数即可处决。",
        "witch": "无额外魔女技能。",
    },
    {
        "id": "honoka",
        "name": "穗乃香",
        "avatar": None,
        "normal": "开局前获知其他人的上层角色，登场可示人为任意角色但不获得真实技能；可按同样流程声明白天假技能，任何其他人可质疑。",
        "witch": "出现在目击名单时可将自己的显示角色改为任意角色。",
    },
]
ROLES = {role["id"]: role for role in CATALOG}
DEFAULT_CODEX = [role["id"] for role in CATALOG if role["id"] not in {"sherry", "millia", "arisa"}]
PHASES = {
    "lobby": "候场与首次准备",
    "ordering": "私下调整上下牌与再次准备",
    "witch": "当日魔女化检测",
    "night": "夜间行动",
    "night_coco": "最后夜间行动",
    "night_review": "主持人预结算",
    "night_results": "夜间结果与证物",
    "speech": "顺序发言",
    "discussion": "自由发言",
    "nomination": "提名",
    "voting": "投票",
    "execution": "处决前响应",
    "dusk": "天黑与胜负确认",
}

# 系统自己知道做完的阶段：无人待办时倒计时到点自动进入下一阶段，主持人可暂停。
AUTO_PHASES = {
    "witch",
    "night",
    "night_coco",
    "speech",
    "nomination",
    "voting",
    "execution",
}
AUTO_ADVANCE_DELAY = 5


def night_half(game):
    """是否处于开局后的夜间：魔女化检测到夜间结果同属一夜。"""
    return game["status"] == "playing" and game["half"] == "night"


# 自由发言结束请求：六个不同席位提交后，10 秒自动进入提名。
DISCUSSION_END_VOTES = 6
DISCUSSION_END_DELAY = 10
DAY_ABILITIES = {
    "interrupt": ("emma", "打断发言"),
    "mass_brainwash": ("annan", "全场洗脑"),
    "love": ("marg", "宣布爱上或移情"),
    "gaze": ("nanoka", "处决幻视"),
    "duel": ("leia", "决斗"),
    "photo": ("coco", "赠送信物"),
}
# 仍会掷中毒效果骰的技能：只剩可可的「赠送信物」。
# 其余技能一律不受中毒影响（魔女刀、全场攻击、额外攻击、庇护、下雨、替罪凶手、
# 换血与替死、寻宝、令邻座负伤、打断发言、爱人、决斗、临刑开枪、傀儡复活、
# 时间回溯都不再掷骰）；信息类仍按信息骰决定真话还是假话。
POISON_EFFECT_ABILITIES = {"photo"}
NIGHT_ABILITIES = {
    "knife": (None, "魔女刀"),
    "massacre": ("emma", "全场攻击"),
    "extra_kill": ("hanna", "额外攻击"),
    "protect": ("meruru", "庇护"),
    "rain": ("noah", "下雨"),
    "scapegoat": ("noah", "替罪凶手"),
    "swap": ("millia", "换血"),
    "treasure": ("emma", "寻宝"),
    "witch_scan": ("nanoka", "查看魔女化状态"),
    "arisa_injure": ("arisa", "令邻座负伤"),
}
