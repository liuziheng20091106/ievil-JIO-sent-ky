from __future__ import annotations

import argparse
import asyncio
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
    def __init__(self, *, ws_url: str, token: str, backend_url: str, gateway_token: str, group_id: int):
        self.ws_url = ws_url
        self.token = token
        self.backend_url = backend_url.rstrip("/")
        self.gateway_token = gateway_token
        self.group_id = group_id

    @property
    def headers(self) -> dict[str, str]:
        return {"X-Gateway-Token": self.gateway_token}

    @staticmethod
    def avatar_url(qq_id: str) -> str:
        return f"https://q1.qlogo.cn/g?b=qq&nk={qq_id}&s=100"

    async def sync_members(self, connection: OneBotConnection) -> None:
        try:
            result = await connection.action("get_group_member_list", {"group_id": self.group_id})
            members = []
            for member in result.get("data", []):
                qq_id = str(member.get("user_id", "")).strip()
                nickname = str(member.get("card") or member.get("nickname") or qq_id).strip()
                if qq_id:
                    members.append(
                        {
                            "qq_id": qq_id,
                            "nickname": nickname,
                            "avatar_url": self.avatar_url(qq_id),
                        }
                    )
            if members:
                async with httpx.AsyncClient(timeout=15) as client:
                    response = await client.post(
                        f"{self.backend_url}/api/internal/qq/members/sync",
                        headers=self.headers,
                        json={"group_id": self.group_id, "members": members},
                    )
                    response.raise_for_status()
                LOG.info("synced %d group members", len(members))
        except Exception as exc:
            LOG.warning("member sync skipped: %s", exc)

    async def bind_login(self, *, code: str, qq_id: str, nickname: str) -> bool:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{self.backend_url}/api/internal/qq/login",
                headers=self.headers,
                json={
                    "code": code,
                    "qq_id": qq_id,
                    "nickname": nickname,
                    "avatar_url": self.avatar_url(qq_id),
                    "group_id": self.group_id,
                },
            )
        if response.status_code == 200:
            return True
        LOG.info("login code %s rejected (%s)", code, response.text[:180])
        return False

    async def acknowledge(self, connection: OneBotConnection, message: str) -> None:
        try:
            await connection.action(
                "send_group_msg", {"group_id": self.group_id, "message": message}, timeout=10
            )
        except Exception as exc:
            LOG.debug("could not send acknowledgement: %s", exc)

    async def handle_event(self, connection: OneBotConnection, event: dict) -> None:
        if event.get("post_type") != "message" or event.get("message_type") != "group":
            return
        if int(event.get("group_id", 0)) != self.group_id:
            return
        match = LOGIN_PATTERN.match(str(event.get("raw_message") or ""))
        if not match:
            return
        sender = event.get("sender") or {}
        qq_id = str(event.get("user_id") or sender.get("user_id") or "").strip()
        nickname = str(sender.get("card") or sender.get("nickname") or qq_id).strip()
        if qq_id and await self.bind_login(code=match.group(1), qq_id=qq_id, nickname=nickname):
            await self.acknowledge(connection, f"{nickname}，登录成功~请回到活动页面。")

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
        group_id=int(required_env("GAME_QQ_GROUP_ID")),
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
    LOG.info("watching group %s; backend=%s", gateway.group_id, gateway.backend_url)
    asyncio.run(gateway.run())


if __name__ == "__main__":
    main()
