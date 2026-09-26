"""Stateless proof-of-work guard for unauthenticated challenge endpoints.

登录挑战（POST /api/native/auth/challenges 等）是仅有的未认证写入口：脚本可以
无限刷谜题创建与轮询，灌 login_challenges 表。这里用无状态 PoW 提高刷接口的
单价：领题时签发一段 HMAC 的谜题令牌，客户端枚举 nonce 找到使
sha256(token || nonce) 十六进制串前 difficulty 位为 '0' 的解，创建挑战时连同
令牌一起提交；服务端只做一次哈希与签名校验，不存任何表。

密钥从环境变量读取（GAME_POW_SECRET，缺省派生自 GAME_GATEWAY_TOKEN）；
GAME_POW_DIFFICULTY 未设置或为 0 时整个防护关闭，接口形状完全不变，
旧客户端不受影响。开启后旧客户端会收到 428 与明确的「请更新客户端」提示，
正好接上客户端现有的最低版本强更机制。

令牌 5 分钟有效；服务端无状态，5 分钟窗口内的重放靠「创建登录挑战本身
低价值、且受同一套速率环境约束」接受，不为它建表。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

# 谜题令牌格式（都是 URL 安全字符，可直接放 JSON）：
#   v1.<issued_at 毫秒>.<difficulty>.<random>.<hmac 前 16 字节的 hex>
# HMAC 覆盖前面所有字段：任何一位被改（尤其是 difficulty 调小）都会校验失败。
_TOKEN_VERSION = "v1"
_TOKEN_TTL_SECONDS = 300
# difficulty 上限防误配把所有用户锁在门外：19 位起单题平均就要 2^19≈52 万次哈希。
MAX_DIFFICULTY = 19
MIN_DIFFICULTY = 0


def difficulty() -> int:
    raw = os.environ.get("GAME_POW_DIFFICULTY", "").strip()
    if not raw:
        return 0
    try:
        value = int(raw)
    except ValueError:
        return 0
    return max(MIN_DIFFICULTY, min(value, MAX_DIFFICULTY))


def enabled() -> bool:
    return difficulty() > 0


def _secret() -> bytes:
    """PoW 签名密钥：优先 GAME_POW_SECRET，缺省派生自网关共享密钥。"""
    explicit = os.environ.get("GAME_POW_SECRET", "").strip()
    if explicit:
        return explicit.encode("utf-8")
    shared = os.environ.get("GAME_GATEWAY_TOKEN", "").encode("utf-8")
    return hashlib.sha256(b"seven-double-pow\x00" + shared).digest()


def _sign(payload: str) -> str:
    return hmac.new(_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()[:16]


def issue_puzzle() -> dict:
    """签发一道谜题；difficulty=0（防护关闭）时返回空配置，客户端直接跳过。"""
    level = difficulty()
    if level <= 0:
        return {"required": False}
    issued_at = int(time.time() * 1000)
    payload = f"{_TOKEN_VERSION}.{issued_at}.{level}.{secrets.token_urlsafe(9)}"
    return {
        "required": True,
        "difficulty": level,
        "token": f"{payload}.{_sign(payload)}",
        "expires_in": _TOKEN_TTL_SECONDS,
    }


def verify_solution(token: str, nonce) -> bool:
    """校验客户端提交的解；防护关闭时恒为 True，调用方无需分支。"""
    if not enabled():
        return True
    if not isinstance(token, str) or not token:
        return False
    if isinstance(nonce, bool) or not isinstance(nonce, int):
        return False
    parts = token.split(".")
    if len(parts) != 5 or parts[0] != _TOKEN_VERSION or parts[4] != _sign(".".join(parts[:4])):
        return False
    try:
        issued_at = int(parts[1])
        level = int(parts[2])
    except ValueError:
        return False
    if level < 1 or level > MAX_DIFFICULTY:
        return False
    age = time.time() * 1000 - issued_at
    if not 0 <= age <= _TOKEN_TTL_SECONDS * 1000:
        return False
    digest = hashlib.sha256(f"{token}{nonce}".encode("utf-8")).hexdigest()
    return digest.startswith("0" * level)


def reject_detail() -> str:
    return "请先更新客户端后再登录（服务端已开启工作量验证）"
