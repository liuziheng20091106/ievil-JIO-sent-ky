"""The single public role catalogue; rules are intentionally data, not subclasses."""

CATALOG = [
    {
        "id": "emma",
        "name": "艾玛",
        "avatar": "/assets/characters/樱羽艾玛.png",
        "normal": "每个白天可打断一次他人发言；顺序发言时可改为最后发言。打断结束后从被打断者按原顺序继续。",
        "witch": "第三天或更晚时，夜里可杀死所有其他角色。",
    },
    {
        "id": "hiro",
        "name": "希罗",
        "avatar": "/assets/characters/二阶堂希罗.png",
        "normal": "好人希罗即将死亡时，可回溯一次至前一天同一时点。保留记忆，恢复普通技能；精神系效果不恢复。",
        "witch": "魔女希罗另有一次回溯额度，保留自身魔女化；可随时主动出局。必须疯狂使艾玛出局，至多一个夜晚例外。",
    },
    {
        "id": "hanna",
        "name": "汉娜",
        "avatar": "/assets/characters/远野汉娜.png",
        "normal": "始终位于疑似凶手名单中。",
        "witch": "可额外杀死一名角色，然后失去本技能。",
    },
    {
        "id": "sherry",
        "name": "雪莉",
        "avatar": "/assets/characters/橘雪莉.png",
        "normal": "不能魔女化。雪莉和汉娜均为上层并共同度过完整白天后绑定：胜负跟随汉娜，不能同意处决汉娜；汉娜被处刑时殉情。复活使汉娜在魔典后移两位，死亡使其前移三位。",
        "witch": "不能魔女化。",
    },
    {
        "id": "meruru",
        "name": "梅露露",
        "avatar": "/assets/characters/冰上梅露露.png",
        "normal": "每晚可庇护一名角色：死亡改为负伤，再次负伤则无条件出局。",
        "witch": "一次复活当天自己杀死的角色，该角色成为不能投票的傀儡；可隐藏自己使用13水杀人的死因。",
    },
    {
        "id": "noah",
        "name": "诺亚",
        "avatar": "/assets/characters/城崎诺亚.png",
        "normal": "每晚可画画；作画或放弃前不获知当夜死讯。死亡后可额外留下任意幅已画作品作证物。",
        "witch": "一次指定任意角色代替自己被视作凶手。",
    },
    {
        "id": "annan",
        "name": "安安",
        "avatar": "/assets/characters/夏目安安.png",
        "normal": "投票时可秘密洗脑一人，令其必须弃票。无论阵营均可破坏热气球。",
        "witch": "一次洗脑全场处决一人；次日失去投票权且必须被处刑。热气球胜利时无论阵营强制落败。",
    },
    {
        "id": "millia",
        "name": "米莉亚",
        "avatar": "/assets/characters/佐伯米莉亚.png",
        "normal": "每夜选择一名玩家。按不交换预结算后，仅当自己上层牌会出局才交换双方上层牌，消耗一次技能并重新结算。",
        "witch": "无额外魔女化技能；魔女可独立使用魔女刀。",
    },
    {
        "id": "coco",
        "name": "可可",
        "avatar": "/assets/characters/泽渡可可.png",
        "normal": "白天可赠送照片；受赠者可以授权你观看自己的夜间行动。",
        "witch": "得知魔典及艾玛是否魔女化；查看其他全部夜间行动后最后行动。",
    },
    {
        "id": "nanoka",
        "name": "奈乃香",
        "avatar": "/assets/characters/黑部奈叶香.png",
        "normal": "6颗子弹，夜间或即将被处决时开枪，命中率1/6。可幻视当天被投出的人中是否有魔女。",
        "witch": "每夜获知全员魔女化状态，开枪命中率提升至1/3。",
    },
    {
        "id": "arisa",
        "name": "亚里沙",
        "avatar": "/assets/characters/紫藤亚里沙.png",
        "normal": "不能魔女化。白天至多组织一次热气球，邀请至多4人；制作加1，任一破坏清零。亚里沙在场、进度13且有存活魔女时好人立即胜，安安强制落败。",
        "witch": "不能魔女化。",
    },
    {
        "id": "marg",
        "name": "玛格",
        "avatar": "/assets/characters/宝生马格.png",
        "normal": "每天可宣布爱上一人或移情，必须疯狂使其出局。全局至多两次夜间解典，获知猜对的位置数量；第二次后失去技能。任何时候可以以其他当前可发言玩家的身份公开发言；出局后失效。",
        "witch": "未魔女化安安洗脑时学会洗脑；两人同时洗脑互相抵消。",
    },
    {
        "id": "leia",
        "name": "蕾雅",
        "avatar": "/assets/characters/莲见蕾雅.png",
        "normal": "白天必须疯狂引人注目。可令一人被注视；当夜一切技能及魔女刀目标只能是你或该人，优先于疯狂攻击要求。",
        "witch": "简易长矛命中率1/2；主持人可裁定你不出现在疑似凶手名单。",
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
    "balloon": "热气球",
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
    "balloon",
    "nomination",
    "voting",
    "execution",
}
AUTO_ADVANCE_DELAY = 5
DAY_ABILITIES = {
    "interrupt": ("emma", "打断发言"),
    "last_speaker": ("emma", "改为最后发言"),
    "brainwash": ("annan", "秘密洗脑"),
    "mass_brainwash": ("annan", "全场洗脑"),
    "love": ("marg", "宣布爱上或移情"),
    "gaze": ("leia", "注视"),
    "photo": ("coco", "赠送照片"),
    "balloon": ("arisa", "组织热气球"),
}
NIGHT_ABILITIES = {
    "knife": (None, "魔女刀"),
    "massacre": ("emma", "全场攻击"),
    "extra_kill": ("hanna", "额外攻击"),
    "protect": ("meruru", "庇护"),
    "paint": ("noah", "作画"),
    "frame": ("noah", "替代凶手"),
    "swap": ("millia", "预选交换"),
    "shoot": ("nanoka", "开枪"),
    "decode": ("marg", "破译魔典"),
    "spear": ("leia", "长矛"),
}
