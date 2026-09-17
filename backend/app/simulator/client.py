"""真实协议客户端：一个虚拟玩家或主持人的登录态、状态视图与命令提交。

刻意不跳过 HTTP 层：登录、命令白名单、expected_version 冲突、可见性裁剪
都走和其它客户端完全相同的路径，这样模拟器发现的缺陷才是真实缺陷。
"""

import json
import threading
import time
from collections.abc import Iterable


class ProtocolError(RuntimeError):
    """服务端拒绝了本次操作；携带状态码与原文，便于模拟器自己决定如何处理。"""

    def __init__(self, status, detail, action="", payload=None):
        super().__init__(f"{status} {action}: {detail}")
        self.status = status
        self.detail = detail
        self.action = action
        self.payload = payload


class VersionConflict(ProtocolError):
    """expected_version 不匹配：状态已被别人推进，需要刷新后重新确认。"""


class ProtocolClient:
    """一个登录身份（玩家或主持人）对后端的全部访问入口。

    ``transport`` 是一个 ``(method, path, body, headers) -> (status, payload)`` 可调用对象，
    生产实现见 :mod:`backend.app.simulator.transport`，检查里可以直接喂 TestClient。
    """

    def __init__(self, transport, label, origin="http://simulator.invalid"):
        self.transport = transport
        self.label = label
        self.origin = origin
        self.token = None
        self.actor = None
        self.game_id = None
        self.view = None
        self._seen_messages = set()

    # ------------------------------------------------------------------ 传输

    def request(self, method, path, body=None, *, token=None, headers=None):
        merged = {"Origin": self.origin}
        bearer = token if token is not None else self.token
        if bearer:
            merged["Authorization"] = "Bearer " + bearer
        if headers:
            merged.update(headers)
        return self.transport(method, path, body, merged)

    def call(self, method, path, body=None, *, action="", token=None):
        status, payload = self.request(method, path, body, token=token)
        if status >= 400:
            detail = payload.get("detail") if isinstance(payload, dict) else payload
            if status == 409 and action:
                raise VersionConflict(status, detail, action, body)
            raise ProtocolError(status, detail, action, body)
        return payload

    # ------------------------------------------------------------------ 登录

    def login_host(self, password="114514"):
        payload = self.call(
            "POST",
            "/api/native/host/login",
            {"password": password},
            action="host.login",
        )
        self.token = payload["session_token"]
        self.actor = payload["session"]["actor"]
        return self.actor

    def login_player(self, qq_id, nickname, *, gateway_token, group_id, authenticator):
        """走 QQ 网关认证路径拿玩家令牌。

        ``authenticator(code, qq_id, nickname, group_id)`` 由调用方提供，可以是
        真实网关 HTTP 调用，也可以直接调 ``auth_storage.complete_challenge``。
        """
        challenge = self.call("POST", "/api/native/auth/challenges", {}, action="challenge")
        authenticator(challenge["code"], qq_id, nickname, group_id)
        payload = self.call(
            "GET",
            "/api/native/auth/challenges/" + challenge["id"],
            action="challenge.poll",
        )
        self.token = payload["session_token"]
        self.actor = payload["session"]["actor"]
        return self.actor

    def logout(self):
        if not self.token:
            return
        try:
            self.call("POST", "/api/logout")
        except ProtocolError:
            pass
        self.token = None
        self.actor = None

    # ------------------------------------------------------------------ 状态

    def refresh(self):
        self.view = self.call("GET", f"/api/games/{self.game_id}/state", action="state")
        return self.view

    @property
    def version(self):
        return self.view["version"] if self.view else None

    def action(self, action_id, payload=None, **match):
        """在当前视图中定位一条已授权行动；``match`` 用于区分同 id 的多条行动。"""
        for descriptor in self.view.get("actions", []):
            if descriptor["id"] != action_id:
                continue
            if any(descriptor.get(key) != value for key, value in match.items()):
                continue
            if payload and any(descriptor["payload"].get(k) != v for k, v in payload.items()):
                continue
            return descriptor
        return None

    def available(self, action_id):
        return [d for d in self.view.get("actions", []) if d["id"] == action_id]

    # ------------------------------------------------------------------ 命令

    def submit(self, action, payload=None, *, expected_version=None, as_seat=None):
        """提交一条命令；版本冲突抛 :class:`VersionConflict`，其它拒绝抛 ProtocolError。"""
        body = {
            "expected_version": self.view["version"] if expected_version is None else expected_version,
            "action": action,
            "payload": payload or {},
        }
        if as_seat:
            body["as_seat"] = as_seat
        state = self.call(
            "POST", f"/api/games/{self.game_id}/commands", body, action=action
        )
        self.view = state
        return state

    def submit_retrying(self, action, payload=None, *, attempts=8, as_seat=None, on_conflict=None):
        """冲突时刷新并重新确认，不自动重试写入之外的语义。

        与 AGENTS.md 一致：真实客户端遇到冲突要刷新后由人重新确认；模拟器里
        「重新确认」由策略重新决策，因此这里重新取值再提交，而不是原样重放。
        """
        last = None
        for _ in range(attempts):
            self.refresh()
            if on_conflict is not None:
                payload = on_conflict(self) if payload is None else payload
            try:
                return self.submit(action, payload, as_seat=as_seat)
            except VersionConflict as error:
                last = error
                time.sleep(0.001)
        raise last

    # ------------------------------------------------------------------ 消息

    def messages(self, *, scope="all", channel_id=None, after=None):
        query = [f"scope={scope}"]
        if channel_id:
            query.append("channel_id=" + channel_id)
        if after is not None:
            query.append(f"after={after}")
        return self.call(
            "GET", f"/api/games/{self.game_id}/messages?" + "&".join(query), action="messages"
        )["messages"]

    def new_messages(self, *, scope="all"):
        """只返回本次会话没见过的消息，便于断言「玩家真的收到了这条信息」。"""
        fresh = []
        for row in self.messages(scope=scope):
            if row["id"] not in self._seen_messages:
                self._seen_messages.add(row["id"])
                fresh.append(row)
        return fresh

    def say(self, text, channel_id="public"):
        return self.call(
            "POST",
            f"/api/games/{self.game_id}/messages",
            {"text": text, "channel_id": channel_id},
            action="chat",
        )

    # ------------------------------------------------------------------ 房间

    def join(self, kind="player"):
        return self.call(
            "POST", f"/api/games/{self.game_id}/participations", {"kind": kind}, action="join"
        )

    def lobby(self):
        return self.call("GET", "/api/lobby", action="lobby")

    def create_game(self, codex):
        payload = self.call("POST", "/api/games", {"codex": list(codex)}, action="create")
        self.game_id = payload["id"]
        self.view = payload
        return payload

    def open_join(self, open=True):
        """开放/关闭主动参局。

        服务端的 ``room.open_join`` 只按目标状态列出（开放时列表里只有 ``open=True``），
        且 ``join_open`` 不在玩家视图里，只有主持人视图的 ``room.open_join``/``host.start``
        列表能反推当前状态：目标状态已在生效时该行动不会出现，此时直接返回。
        """
        self.refresh()
        target = {"open": bool(open)}
        if self.action("room.open_join", target) is None:
            return self.view
        return self.submit("room.open_join", target)

    def seat_view(self, seat_id):
        return self.call(
            "GET",
            f"/api/games/{self.game_id}/seats/{seat_id}/view",
            action="seat_view",
        )

    def __repr__(self):
        kind = self.actor["kind"] if self.actor else "anonymous"
        return f"<ProtocolClient {self.label} {kind}>"


def encode(payload):
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def dedupe(items: Iterable[str]):
    return list(dict.fromkeys(items))


class LockedClient(ProtocolClient):
    """给并发席位加一把锁：多线程同时提交时避免同一身份读改写竞争。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.lock = threading.Lock()
