"""Disable codex conversions from the fourth day without changing earlier rules."""

from ..state import log_event

ID = "codex_disabled"
VERSION = 1
NAME = "禁用魔典转化"
DESCRIPTION = "第四天及之后不再通过魔典产生新的魔女；前三天规则、已有魔女与魔典信息保持不变。"
CATEGORY = "external_default_on"
DEPENDS = ()
COMMANDS = {}


def witch_conversion(game, events, context):
    if context["day"] >= 4:
        context["skip"] = True
        log_event(game, "system", "禁用魔典转化：本夜不产生新的魔女。")


HANDLERS = {"witch_conversion": witch_conversion}
