"""客户端版本标签、应用内更新信息与用户协议。

三份东西都由部署者在 `data/` 下维护，改完即生效、不入库：

- `data/updates.json`：按「平台 + 版本区间」下发不同的更新信息（见文件内示例）；
  文件缺失或没有匹配区间时退回环境变量 `GAME_CLIENT_LATEST` / `GAME_CLIENT_MINIMUM`。
- `data/agreement.md`：用户协议正文（Markdown），客户端首次连接时展示。
- `data/releases/`：更新包本体（Windows zip、APK、Updater.exe），由 `/releases/{name}` 同源下发。

客户端版本从请求的 User-Agent 里读：`seven-double-flutter/<x.y.z> (windows|android)`。
UA 缺失或不是本客户端时一律「不作判断」：既不下发平台相关的更新信息，也不拒绝入局
（浏览器、网页端、模拟器与检查脚本都不发这个 UA）。
"""

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException, Request

from . import storage

# 本客户端与 Windows 更新器自己的 UA：版本号必须三段数字；平台后缀可缺
# （缺了只匹配 platform=any 的区间，更新器则按 Windows 处理）。
#   seven-double-flutter/<x.y.z> (windows|android)
#   magicjudge-updater/<x.y.z> (windows)
CLIENT_AGENT = re.compile(
    r"(seven-double-flutter|magicjudge-updater)/(\d+\.\d+\.\d+)(?:\s*\(([a-z]+)\))?",
    re.IGNORECASE,
)

PLATFORMS = ("windows", "android")

# `data/updates.json` 的字段白名单：认不出的键忽略，避免把配置错误变成 500。
_STRING_FIELDS = ("platform", "latest", "minimum", "min_version", "max_version", "title")
_TEXT_FIELDS = ("notes",)
_URL_FIELDS = ("url", "updater_url", "guide_url")
_INT_FIELDS = ("size",)


def parse_client_agent(user_agent):
    """返回 `(版本, 平台)`；不是本客户端、版本号形状不符时返回 `(None, None)`。"""
    if not user_agent:
        return None, None
    match = CLIENT_AGENT.search(user_agent)
    if not match:
        return None, None
    client = match.group(1).lower()
    version = match.group(2)
    platform = (match.group(3) or "").lower() or None
    if platform is None and client == "magicjudge-updater":
        # Windows 更新器只有 Windows 版：不带平台后缀时按 Windows 取更新包。
        platform = "windows"
    if platform is not None and platform not in PLATFORMS:
        # 平台认不出来时仍认版本（例如以后加了新平台），只是不匹配分平台的区间。
        platform = None
    return version, platform


def parse_version(value):
    """`x.y.z` → `(x, y, z)`；不是三段数字返回 None。"""
    if not isinstance(value, str):
        return None
    parts = value.strip().split(".")
    if len(parts) != 3:
        return None
    numbers = []
    for part in parts:
        if not part.isdigit():
            return None
        numbers.append(int(part))
    return tuple(numbers)


def compare_versions(left, right):
    """三段版本比较；任一侧不是合法版本时返回 None（表示无法判断）。"""
    a, b = parse_version(left), parse_version(right)
    if a is None or b is None:
        return None
    return (a > b) - (a < b)


def _environment_labels():
    latest = (os.environ.get("GAME_CLIENT_LATEST") or "").strip() or None
    minimum = (os.environ.get("GAME_CLIENT_MINIMUM") or "").strip() or None
    return latest, minimum


def load_update_entries():
    """读 `data/updates.json`：返回按文件顺序排列的区间列表，`default` 追加在最后。"""
    path = storage.DATA_DIR / "updates.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    raw = data.get("updates")
    items = list(raw) if isinstance(raw, list) else []
    if isinstance(data.get("default"), dict):
        items.append(data["default"])
    entries = []
    for item in items:
        entry = _clean_entry(item)
        if entry is not None:
            entries.append(entry)
    return entries


def _clean_entry(item):
    if not isinstance(item, dict):
        return None
    entry = {}
    for field in _STRING_FIELDS:
        value = item.get(field)
        if isinstance(value, str) and value.strip():
            entry[field] = value.strip()
    for field in _TEXT_FIELDS:
        value = item.get(field)
        if isinstance(value, str) and value.strip():
            entry[field] = value
    for field in _URL_FIELDS:
        value = item.get(field)
        if isinstance(value, str) and value.strip():
            entry[field] = value.strip()
    for field in _INT_FIELDS:
        value = item.get(field)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            entry[field] = value
    sha = item.get("sha256")
    if isinstance(sha, str) and re.fullmatch(r"[0-9a-fA-F]{64}", sha.strip()):
        entry["sha256"] = sha.strip().lower()
    if entry.get("platform", "any") not in ("any",) + PLATFORMS:
        return None
    # latest 是区间下发的最低要求：没有它就不知道该让客户端升到哪一版。
    if parse_version(entry.get("latest")) is None:
        return None
    for bound in ("min_version", "max_version", "minimum"):
        if bound in entry and parse_version(entry[bound]) is None:
            return None
    return entry


def _matches(entry, version, platform):
    """区间匹配：`min_version <= version < max_version`，平台必须相容。"""
    entry_platform = entry.get("platform", "any")
    if entry_platform != "any" and entry_platform != platform:
        return False
    if version is None:
        return False
    lower = entry.get("min_version")
    if lower is not None:
        comparison = compare_versions(version, lower)
        if comparison is None or comparison < 0:
            return False
    upper = entry.get("max_version")
    if upper is not None:
        comparison = compare_versions(version, upper)
        if comparison is None or comparison >= 0:
            return False
    return True


def match_entry(version, platform):
    """取第一条匹配的区间项；没有匹配返回 None。"""
    for entry in load_update_entries():
        if _matches(entry, version, platform):
            return entry
    return None


def resolve_client(version, platform):
    """返回 `(latest, minimum, update)`。

    - 匹配到区间：`latest`/`minimum` 取自该区间，`update` 只在「确实有更新」时给出。
    - 没有匹配：`latest`/`minimum` 退回环境变量，`update` 为 None（不知道该下发哪个平台）。
    """
    entry = match_entry(version, platform) if version else None
    if entry is None:
        latest, minimum = _environment_labels()
        return latest, minimum, None
    latest = entry["latest"]
    minimum = entry.get("minimum")
    comparison = compare_versions(version, latest)
    if comparison is None or comparison >= 0:
        return latest, minimum, None
    return latest, minimum, build_update(entry, version, platform)


def build_update(entry, version, platform):
    """把区间项整理成客户端认识的更新信息（字段名与 `/api/health` 的 `update` 一致）。"""
    minimum = entry.get("minimum")
    comparison = compare_versions(version, minimum) if minimum else None
    update = {
        "platform": platform or entry.get("platform") or "any",
        "latest": entry["latest"],
        "minimum": minimum,
        "required": bool(comparison is not None and comparison < 0),
        "title": entry.get("title") or "发现新版本",
        "notes": entry.get("notes") or "",
        "url": entry.get("url") or "",
        "updater_url": entry.get("updater_url") or "",
        "guide_url": entry.get("guide_url") or "",
        "sha256": entry.get("sha256") or "",
        "size": entry.get("size") or 0,
    }
    if platform == "windows" and not update["updater_url"]:
        update["updater_url"] = "/releases/Updater.exe"
    return update


def health_payload(user_agent):
    """`/api/health` 的版本字段：任何身份（含无 UA 的网页与旧客户端）都能读。"""
    version, platform = parse_client_agent(user_agent)
    latest, minimum, update = resolve_client(version, platform)
    return {"client_latest": latest, "client_minimum": minimum, "update": update}


def update_available(user_agent):
    """`/api/online` 的「是否有更新」：客户端据此决定要不要重新请求 health。"""
    version, platform = parse_client_agent(user_agent)
    if version is None:
        return False
    entry = match_entry(version, platform)
    if entry is None:
        latest, _ = _environment_labels()
    else:
        latest = entry["latest"]
    comparison = compare_versions(version, latest) if latest else None
    return bool(comparison is not None and comparison < 0)


def require_joinable_client(request: Request):
    """过旧的客户端只拒绝「加入对局」，其它功能一律不受限。

    判据只用 UA 里的版本号：UA 缺失或不是本客户端时放行（浏览器、模拟器、
    检查脚本都不发这个 UA，按「不满足 UA」拦会把它们一起误伤）。
    """
    version, platform = parse_client_agent(request.headers.get("user-agent"))
    if version is None:
        return
    minimum = resolve_client(version, platform)[1]
    if not minimum:
        return
    comparison = compare_versions(version, minimum)
    if comparison is not None and comparison < 0:
        raise HTTPException(426, "客户端版本过旧，请先更新到最新版本再加入对局")


def load_agreement():
    """读 `data/agreement.md`；文件缺失或为空时返回空正文（客户端据此跳过协议门）。"""
    path = storage.DATA_DIR / "agreement.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {"text": "", "hash": "", "updated_at": None}
    text = text.lstrip("\ufeff")
    if not text.strip():
        return {"text": "", "hash": "", "updated_at": None}
    return {
        "text": text,
        "hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "updated_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
    }


def release_path(name):
    """`data/releases/` 下的文件名 → 绝对路径；非法名或不存在返回 None。"""
    if not name or Path(name).name != name or name in {".", ".."}:
        return None
    root = (storage.DATA_DIR / "releases").resolve()
    candidate = (root / name).resolve()
    if not candidate.is_relative_to(root) or not candidate.is_file():
        return None
    return candidate
