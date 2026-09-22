from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import logging
import os
import re
import secrets
from typing import Any

import httpx
import websockets
from websockets.exceptions import ConnectionClosed

LOG = logging.getLogger("seven-double-gateway")
LOGIN_PATTERN = re.compile(r"^\s*活动登录\s+(\d{6})\s*$")
# 看起来在登录但码不对（位数错、抄漏前缀等）：不静默吞掉，回一句格式提示。
ATTEMPT_PATTERN = re.compile(r"^\s*活动登录")
LOGIN_HINT = "登录码应为 6 位数字，请照抄客户端显示的整句「活动登录 123456」"
# 服务端 QQMemberSync.members 上限 5000；多群合并后可能超过，分批发。
SYNC_BATCH = 4000


def avatar_url(qq_id: str) -> str:
    return f"https://q1.qlogo.cn/g?b=qq&nk={qq_id}&s=100"


def clean_members(raw_members) -> list[dict]:
    """合并多个群的原始成员并按 QQ 号去重，先出现的群优先。"""
    merged: dict[str, dict] = {}
    for member in raw_members:
        qq_id = str(member.get("user_id", "")).strip()
        # 服务端只接受 5-20 位纯数字 QQ 号；匿名/系统/异常账号跳过，不拖垮整批同步。
        if not (qq_id.isdigit() and 5 <= len(qq_id) <= 20) or qq_id in merged:
            continue
        nickname = str(member.get("card") or member.get("nickname") or qq_id).strip()
        # 昵称兜底 QQ 号并截断到服务端上限，避免单条脏数据让整批 422。
        if not nickname:
            nickname = qq_id
        merged[qq_id] = {
            "qq_id": qq_id,
            "nickname": nickname[:64],
            "avatar_url": avatar_url(qq_id),
        }
    return list(merged.values())


def error_detail(response) -> str:
    """取后端 HTTPException 的 detail 作为回群文案；形状异常（无 JSON / Pydantic 校验列表）回退成状态码。"""
    try:
        data = response.json()
    except ValueError:
        data = None
    detail = data.get("detail") if isinstance(data, dict) else None
    if isinstance(detail, str) and detail.strip():
        return detail.strip()
    return f"服务端返回 HTTP {response.status_code}"


def parse_group_ids(value: str) -> tuple[int, ...]:
    """`GAME_QQ_GROUP_ID` 支持英文逗号分隔的多个群号。"""
    group_ids = []
    for item in value.split(","):
        item = item.strip()
        if item:
            group_ids.append(int(item))
    if not group_ids:
        raise RuntimeError("missing required environment variable: GAME_QQ_GROUP_ID")
    return tuple(group_ids)


class OneBotConnection:
    def __init__(self, ws_url: str, token: str):
        self.ws_url = ws_url
        self.token = token
        self.ws = None
        self.pending: dict[str, asyncio.Future] = {}
        self.reader_task: asyncio.Task | None = None
        self.events: asyncio.Queue[dict] = asyncio.Queue()

    async def connect(self) -> None:
        url = self.ws_url
        if self.token:
            url += ("&" if "?" in url else "?") + f"access_token={self.token}"
        self.ws = await websockets.connect(
            url, max_size=10 * 1024 * 1024, ping_interval=30, ping_timeout=10
        )
        self.reader_task = asyncio.create_task(self._read_loop())
        LOG.info("connected to NapCat at %s", self.ws_url)

    async def close(self) -> None:
        if self.reader_task:
            self.reader_task.cancel()
            await asyncio.gather(self.reader_task, return_exceptions=True)
            self.reader_task = None
        if self.ws:
            await self.ws.close()
            self.ws = None
        for future in self.pending.values():
            if not future.done():
                future.cancel()
        self.pending.clear()

    async def _read_loop(self) -> None:
        try:
            async for raw in self.ws:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    LOG.warning("ignored non-JSON OneBot frame")
                    continue
                echo = data.get("echo")
                future = self.pending.pop(str(echo), None) if echo is not None else None
                if future and not future.done():
                    future.set_result(data)
                elif not echo:
                    await self.events.put(data)
        except (ConnectionClosed, asyncio.CancelledError):
            if not asyncio.current_task().cancelled():
                await self.events.put({"_gateway_closed": True})

    async def action(self, action: str, params: dict[str, Any], timeout: float = 20) -> dict:
        if self.ws is None:
            raise RuntimeError("NapCat is not connected")
        echo = secrets.token_hex(8)
        future = asyncio.get_running_loop().create_future()
        self.pending[echo] = future
        await self.ws.send(
            json.dumps({"action": action, "params": params, "echo": echo}, ensure_ascii=False)
        )
        result = await asyncio.wait_for(future, timeout=timeout)
        if result.get("retcode") not in (None, 0) and result.get("status") != "ok":
            raise RuntimeError(
                f"{action}: {result.get('wording') or result.get('message') or result.get('retcode')}"
            )
        return result


class QQGateway:
    def __init__(self, *, ws_url: str, token: str, backend_url: str, gateway_token: str, group_ids: tuple[int, ...]):
        self.ws_url = ws_url
        self.token = token
        self.backend_url = backend_url.rstrip("/")
        self.gateway_token = gateway_token
        self.group_ids = group_ids

    @property
    def headers(self) -> dict[str, str]:
        return {"X-Gateway-Token": self.gateway_token}

    async def fetch_members(self, connection: OneBotConnection, group_id: int) -> list[dict]:
        try:
            result = await connection.action("get_group_member_list", {"group_id": group_id})
        except Exception as exc:
            # 单群拉取失败不该拖垮其余群：记日志后当这个群没有成员。
            LOG.warning("member fetch failed for group %s: %s", group_id, exc)
            return []
        return result.get("data", [])

    async def sync_members(self, connection: OneBotConnection) -> None:
        raw: list[dict] = []
        for group_id in self.group_ids:
            raw.extend(await self.fetch_members(connection, group_id))
        members = clean_members(raw)
        if not members:
            return
        # 服务端只用 group_id 校验网关来源，所以合并后的名单只提交一次（超限则分批）。
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                for batch in itertools.batched(members, SYNC_BATCH):
                    response = await client.post(
                        f"{self.backend_url}/api/internal/qq/members/sync",
                        headers=self.headers,
                        json={"group_id": self.group_ids[0], "members": list(batch)},
                    )
                    response.raise_for_status()
            LOG.info(
                "synced %d group members from groups %s",
                len(members),
                ",".join(str(item) for item in self.group_ids),
            )
        except Exception as exc:
            LOG.warning("member sync skipped: %s", exc)

    async def bind_login(self, *, code: str, qq_id: str, nickname: str, group_id: int) -> str | None:
        """成功返回 None；失败返回一句可直接发回群里的原因。"""
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self.backend_url}/api/internal/qq/login",
                headers=self.headers,
                json={
                    "code": code,
                    "qq_id": qq_id,
                    "nickname": nickname,
                    "avatar_url": avatar_url(qq_id),
                    "group_id": group_id,
                },
            )
        if response.status_code == 200:
            return None
        detail = error_detail(response)
        LOG.info("login code %s from group %s rejected (%s)", code, group_id, detail)
        return detail

    async def acknowledge(self, connection: OneBotConnection, group_id: int, message: str) -> None:
        try:
            await connection.action(
                "send_group_msg", {"group_id": group_id, "message": message}, timeout=10
            )
        except Exception as exc:
            LOG.debug("could not send acknowledgement: %s", exc)

    async def handle_event(self, connection: OneBotConnection, event: dict) -> None:
        if event.get("post_type") != "message" or event.get("message_type") != "group":
            return
        group_id = int(event.get("group_id", 0))
        if group_id not in self.group_ids:
            return
        match = LOGIN_PATTERN.match(str(event.get("raw_message") or ""))
        if not match:
            # 明显的登录尝试但格式不对：同样回一句，避免玩家以为机器人没收到。
            if ATTEMPT_PATTERN.match(str(event.get("raw_message") or "")):
                await self.acknowledge(connection, group_id, LOGIN_HINT)
            return
        sender = event.get("sender") or {}
        qq_id = str(event.get("user_id") or sender.get("user_id") or "").strip()
        nickname = str(sender.get("card") or sender.get("nickname") or qq_id).strip()
        if not qq_id:
            return
        # 回执必须发回玩家实际发言的群，否则多群时提示会落在别的群。
        try:
            reason = await self.bind_login(
                code=match.group(1), qq_id=qq_id, nickname=nickname, group_id=group_id
            )
        except Exception as exc:
            # 后端不可达时也要给群里的玩家一个说法，不静默吞掉。
            LOG.warning("login bind failed for %s in group %s: %s", qq_id, group_id, exc)
            reason = "服务端暂时不可用"
        if reason is None:
            await self.acknowledge(connection, group_id, f"{nickname}，登录成功~")
        else:
            await self.acknowledge(connection, group_id, f"{nickname}，登录失败：{reason}")

    async def run(self) -> None:
        delay = 2.0
        while True:
            connection = OneBotConnection(self.ws_url, self.token)
            try:
                await connection.connect()
                delay = 2.0
                await self.sync_members(connection)
                while True:
                    event = await connection.events.get()
                    if event.get("_gateway_closed"):
                        raise OSError("NapCat connection closed")
                    await self.handle_event(connection, event)
            except (ConnectionClosed, OSError, asyncio.TimeoutError) as exc:
                LOG.warning("NapCat connection lost: %s", exc)
            except Exception:
                LOG.exception("gateway loop failed")
            finally:
                await connection.close()
            LOG.info("reconnecting in %.1fs", delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60.0)


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"missing required environment variable: {name}")
    return value


def build_gateway() -> QQGateway:
    return QQGateway(
        ws_url=os.getenv("NAPCAT_WS_URL", "ws://127.0.0.1:3001"),
        token=os.getenv("NAPCAT_TOKEN", ""),
        backend_url=os.getenv("GAME_BACKEND_URL", "http://127.0.0.1:13888"),
        gateway_token=required_env("GAME_GATEWAY_TOKEN"),
        group_ids=parse_group_ids(required_env("GAME_QQ_GROUP_ID")),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="NapCat OneBot gateway for Seven Double")
    parser.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"))
    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    gateway = build_gateway()
    LOG.info(
        "watching groups %s; backend=%s",
        ",".join(str(item) for item in gateway.group_ids),
        gateway.backend_url,
    )
    asyncio.run(gateway.run())


if __name__ == "__main__":
    main()
