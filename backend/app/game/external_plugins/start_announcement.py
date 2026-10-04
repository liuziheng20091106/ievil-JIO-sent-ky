"""Publish a public announcement when the host starts the game."""

from ..state import notify

ID = "start_announcement"
VERSION = 1
NAME = "开局公告"
DESCRIPTION = "对局开始时向全场插播一条公告。"
CATEGORY = "external_default_on"
DEPENDS = ()
COMMANDS = {}
ANNOUNCEMENT = "欢迎来到魔法裁判，祝各位游戏愉快！\n你需要注意，APP内的规则与QQ规则存在部分差异：\n- 梅露露只需要一刀就能制作傀儡\n -汉娜导致雨天脚步相反不受概率影响\n\n剩下的忘了你们想起来记得提醒VVA补上"


def game_started(game, events, context):
    notify(game, events, ANNOUNCEMENT, title=NAME, alert=True)


HANDLERS = {"game_started": game_started}
