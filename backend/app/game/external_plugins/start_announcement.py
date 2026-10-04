"""Publish a public announcement when the host starts the game."""

from ..state import notify

ID = "start_announcement"
VERSION = 1
NAME = "开局公告"
DESCRIPTION = "对局开始时向全场插播一条公告。"
CATEGORY = "external_default_on"
DEPENDS = ()
COMMANDS = {}
ANNOUNCEMENT = "欢迎来到魔法裁判，祝各位游戏愉快！"


def game_started(game, events, context):
    notify(game, events, ANNOUNCEMENT, title=NAME, alert=True)


HANDLERS = {"game_started": game_started}
