"""Validated transport inputs; game commands remain domain-validated."""

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from typing import Literal


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Login(Input):
    password: str = Field(max_length=128)


class Create(Input):
    codex: list[str] = Field(min_length=11, max_length=11)


class Participation(Input):
    kind: Literal["player", "spectator"]


class QQLogin(Input):
    code: str = Field(pattern=r"^\d{6}$")
    qq_id: str = Field(pattern=r"^\d{5,20}$")
    nickname: str = Field(min_length=1, max_length=64)
    avatar_url: str = Field(default="", max_length=500)
    group_id: StrictInt


class QQMember(Input):
    # 不在 schema 层卡格式：同步端点逐条跳过非法 QQ 号与空/超长昵称，避免单条脏数据整批 422。
    qq_id: str = Field(max_length=64)
    nickname: str = Field(default="", max_length=256)
    avatar_url: str = Field(default="", max_length=500)


class QQMemberSync(Input):
    group_id: StrictInt
    members: list[QQMember] = Field(max_length=5000)


class Command(Input):
    expected_version: StrictInt = Field(ge=0)
    action: str = Field(min_length=1, max_length=80)
    payload: dict = Field(default_factory=dict)
    as_seat: str | None = Field(default=None, max_length=8)


class Chat(Input):
    channel_id: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=2000)
    as_seat: str | None = Field(default=None, max_length=4)


class Evidence(Input):
    text: str = Field(default="", max_length=4000)
    image: str | None = Field(default=None, max_length=2_800_000)


class Kick(Input):
    participant_id: str
    block: StrictBool = False


class Replace(Input):
    seat_id: str
    participant_id: str
    share_history: StrictBool = False
    keep_actions: StrictBool = False


class Channel(Input):
    name: str = Field(default="", max_length=40)
    participant_ids: list[str] = Field(min_length=1, max_length=20)


class ChannelRef(Input):
    channel_id: str = Field(min_length=1, max_length=100)


class OpenJoin(Input):
    open: StrictBool

class Mute(Input):
    participant_id: str
    muted: StrictBool


class Invite(Input):
    account_id: str = Field(min_length=1, max_length=64)


class Achievement(Input):
    """成就定义：名称、内容、稀有度 1-10（数字越大越稀有）。"""

    name: str = Field(min_length=1, max_length=24)
    detail: str = Field(min_length=1, max_length=200)
    rarity: StrictInt = Field(ge=1, le=10)


class AchievementGrant(Input):
    achievement_id: str = Field(min_length=1, max_length=64)


class AchievementEquip(Input):
    """佩戴某个成就；grant_id 为空表示取消佩戴。"""

    grant_id: str | None = Field(default=None, max_length=64)
