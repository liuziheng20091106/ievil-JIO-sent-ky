"""从 NapCat(OneBot v11) 网关拉取指定 QQ 群的聊天记录。

凭据复用 gateway/.env 里的 NAPCAT_WS_URL / NAPCAT_TOKEN（同名进程环境变量优先），
群号默认取 GAME_QQ_GROUP_ID 的第一个。拉取方式是固定 message_seq=0（最新），
把 count 从少到多翻倍地加大：一次请求返回的是「截止到最新消息、往前数 count 条」的
窗口，所以 count 越大拿到的历史越深。直到某次请求超时、或再加大也拿不到新消息为止，
把每次窗口并集去重后落盘到 temp/。

拉完顺手整理一份纯文字版：去掉图片/语音等媒体段，丢弃正文超过 --max-chars 字的消息。

用法：
    .venv/Scripts/python.exe tools/fetch_group_history.py
    .venv/Scripts/python.exe tools/fetch_group_history.py --group 1105925736 --start 50
    .venv/Scripts/python.exe tools/fetch_group_history.py --clean-only   # 只重新整理已有原始记录
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import pathlib
import secrets
import sys
import time
from typing import Any

import websockets

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_ENV = REPO_ROOT / "gateway" / ".env"
DEFAULT_OUT_DIR = REPO_ROOT / "temp"

# 图片/语音等媒体段整体去掉，不留占位符。
MEDIA_TYPES = {"image", "record", "video", "file"}
# 其余非文字段给一个短标记，避免整条消息无声消失（回复引用不占正文，直接忽略）。
PLACEHOLDERS = {
    "forward": "[合并转发]",
    "json": "[卡片]",
    "xml": "[卡片]",
    "markdown": "[卡片]",
    "poke": "[戳一戳]",
    "mface": "[表情]",
    "bface": "[表情]",
    "dice": "[骰子]",
    "rps": "[猜拳]",
    "music": "[音乐]",
    "location": "[位置]",
    "share": "[分享]",
    "contact": "[推荐]",
}
IGNORED_TYPES = {"reply", "source"}

WS_MAX_SIZE = 200 * 1024 * 1024


def log(message: str) -> None:
    stamp = dt.datetime.now().strftime("%H:%M:%S")
    print(f"[{stamp}] {message}", flush=True)


def parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        values[name.strip()] = value.strip()
    return values


def read_env_file(path: pathlib.Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    return parse_env(path.read_text(encoding="utf-8"))


def resolve_credentials(args: argparse.Namespace) -> tuple[str, str, dict[str, str]]:
    """返回 (ws 地址, 令牌, 环境文件内容)。优先级：命令行 > 进程环境变量 > 文件。"""
    values = read_env_file(args.env)
    ws_url = args.ws_url or os.getenv("NAPCAT_WS_URL") or values.get("NAPCAT_WS_URL") or ""
    token = args.token or os.getenv("NAPCAT_TOKEN") or values.get("NAPCAT_TOKEN") or ""
    if not ws_url:
        raise SystemExit(f"缺少 NAPCAT_WS_URL：请写在 {args.env} 或用 --ws-url 指定")
    return ws_url, token, values


def resolve_group(args: argparse.Namespace, values: dict[str, str]) -> int:
    if args.group:
        return int(args.group)
    raw = os.getenv("GAME_QQ_GROUP_ID") or values.get("GAME_QQ_GROUP_ID") or ""
    first = raw.split(",")[0].strip()
    if not first:
        raise SystemExit("没有 --group，环境文件里也没有 GAME_QQ_GROUP_ID")
    return int(first)


def connect_url(ws_url: str, token: str) -> str:
    if not token:
        return ws_url
    separator = "&" if "?" in ws_url else "?"
    return f"{ws_url}{separator}access_token={token}"


async def call(ws, action: str, params: dict[str, Any]) -> dict[str, Any]:
    echo = secrets.token_hex(8)
    await ws.send(json.dumps({"action": action, "params": params, "echo": echo}, ensure_ascii=False))
    while True:
        data = json.loads(await ws.recv())
        if str(data.get("echo")) != echo:
            continue  # 事件推送或别的响应，直接跳过
        if data.get("retcode") not in (None, 0) and data.get("status") != "ok":
            wording = data.get("wording") or data.get("message") or data.get("retcode")
            raise RuntimeError(f"{action} 失败：{wording}")
        return data


def message_key(message: dict[str, Any]) -> str:
    for field in ("message_id", "message_seq", "real_id"):
        value = message.get(field)
        if value:
            return str(value)
    return json.dumps(message, ensure_ascii=False, sort_keys=True)


def next_count(count: int, factor: float, max_count: int) -> int:
    grown = max(count + 1, int(count * factor))
    return min(grown, max_count)


async def fetch_history(args: argparse.Namespace, group_id: int, ws_url: str, token: str):
    """按「从少到多」的窗口逐次抓取，返回 (消息列表, 每次尝试的记录)。"""
    store: dict[str, dict[str, Any]] = {}
    attempts: list[dict[str, Any]] = []
    deadline = time.perf_counter() + args.max_seconds
    count = max(1, args.start)
    async with websockets.connect(
        connect_url(ws_url, token), max_size=WS_MAX_SIZE, ping_interval=30, ping_timeout=10
    ) as ws:
        while count <= args.max_count:
            if time.perf_counter() > deadline:
                log(f"总时长超过 {args.max_seconds:.0f}s，停止加深")
                break
            began = time.perf_counter()
            try:
                data = await asyncio.wait_for(
                    call(
                        ws,
                        "get_group_msg_history",
                        {"group_id": group_id, "message_seq": 0, "count": count},
                    ),
                    timeout=args.timeout,
                )
            except TimeoutError:
                elapsed = time.perf_counter() - began
                log(f"count={count} 请求超时（{elapsed:.1f}s > {args.timeout:.0f}s），就此停手")
                attempts.append(
                    {"count": count, "ok": False, "reason": "timeout", "elapsed": round(elapsed, 1)}
                )
                break
            except Exception as exc:  # noqa: BLE001
                elapsed = time.perf_counter() - began
                log(f"count={count} 请求失败（{elapsed:.1f}s）：{exc!r}，就此停手")
                attempts.append(
                    {
                        "count": count,
                        "ok": False,
                        "reason": f"{type(exc).__name__}: {exc}",
                        "elapsed": round(elapsed, 1),
                    }
                )
                break
            elapsed = time.perf_counter() - began
            messages = (data.get("data") or {}).get("messages") or []
            fresh = 0
            for message in messages:
                key = message_key(message)
                if key not in store:
                    store[key] = message
                    fresh += 1
            attempts.append(
                {
                    "count": count,
                    "ok": True,
                    "returned": len(messages),
                    "fresh": fresh,
                    "total": len(store),
                    "elapsed": round(elapsed, 1),
                }
            )
            log(
                f"count={count} 返回 {len(messages)} 条，新增 {fresh} 条，"
                f"累计 {len(store)} 条，用时 {elapsed:.1f}s"
            )
            if not messages or fresh == 0:
                log("再加大 count 也拿不到新消息了，停止加深")
                break
            if count >= args.max_count:
                log(f"到达 count 上限 {args.max_count}，停止加深")
                break
            count = next_count(count, args.factor, args.max_count)
    ordered = sorted(store.values(), key=lambda item: (item.get("time", 0), message_key(item)))
    return ordered, attempts


def write_raw(path: pathlib.Path, group_id: int, messages: list[dict], attempts: list[dict]) -> None:
    payload = {
        "group_id": group_id,
        "message_count": len(messages),
        "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
        "attempts": attempts,
        "messages": messages,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


def read_raw(path: pathlib.Path) -> tuple[int, list[dict]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return int(payload.get("group_id") or 0), list(payload.get("messages") or [])


def display_name(sender: dict[str, Any]) -> str:
    name = str(sender.get("card") or sender.get("nickname") or "").strip()
    return name


def build_names(messages: list[dict]) -> dict[str, str]:
    names: dict[str, str] = {}
    for message in messages:
        qq = str(message.get("user_id") or "")
        name = display_name(message.get("sender") or {})
        if qq and name and qq not in names:
            names[qq] = name
    return names


def face_label(data: dict[str, Any]) -> str:
    raw = data.get("raw") or {}
    face_text = str(raw.get("faceText") or "").strip().lstrip("/")
    return f"[{face_text}]" if face_text else "[表情]"


def render_text(message: dict[str, Any], names: dict[str, str], stats: dict[str, int]) -> str:
    parts: list[str] = []
    for segment in message.get("message") or []:
        kind = str(segment.get("type") or "")
        data = segment.get("data") or {}
        if kind == "text":
            parts.append(str(data.get("text") or ""))
        elif kind == "at":
            qq = str(data.get("qq") or "")
            if qq == "all":
                parts.append("@全体成员")
            else:
                parts.append("@" + (names.get(qq) or qq))
        elif kind == "face":
            parts.append(face_label(data))
        elif kind in MEDIA_TYPES:
            stats["media_removed"] += 1
        elif kind in PLACEHOLDERS:
            stats["placeholder_added"] += 1
            parts.append(PLACEHOLDERS[kind])
        elif kind in IGNORED_TYPES:
            continue
        else:
            stats["unknown_removed"] += 1
    return "".join(parts).strip()


def clean_messages(messages: list[dict], max_chars: int):
    names = build_names(messages)
    stats = {
        "total": len(messages),
        "kept": 0,
        "dropped_empty": 0,
        "dropped_long": 0,
        "media_removed": 0,
        "placeholder_added": 0,
        "unknown_removed": 0,
    }
    entries: list[dict[str, Any]] = []
    for message in messages:
        text = render_text(message, names, stats)
        if not text:
            stats["dropped_empty"] += 1
            continue
        if len(text) > max_chars:
            stats["dropped_long"] += 1
            continue
        sender = message.get("sender") or {}
        entries.append(
            {
                "time": dt.datetime.fromtimestamp(message.get("time", 0)).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),
                "timestamp": message.get("time", 0),
                "user_id": message.get("user_id"),
                "name": display_name(sender) or str(message.get("user_id") or ""),
                "text": text,
                "message_id": message.get("message_id"),
            }
        )
        stats["kept"] += 1
    entries.sort(key=lambda item: (item["timestamp"], str(item["message_id"])))
    return entries, stats


def write_clean_txt(path: pathlib.Path, group_id: int, entries: list[dict], stats: dict, max_chars: int):
    lines = [
        f"# QQ 群 {group_id} 聊天记录整理",
        f"# 原始 {stats['total']} 条 -> 保留 {stats['kept']} 条"
        f"（已去掉图片/语音等媒体内容，并丢弃正文超过 {max_chars} 字的消息）",
        f"# 生成时间 {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]
    if entries:
        lines.insert(
            3, f"# 时间范围 {entries[0]['time']} ~ {entries[-1]['time']}"
        )
    for entry in entries:
        lines.append(f"{entry['time']}  {entry['name']}({entry['user_id']}): {entry['text']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def summarize(stats: dict, max_chars: int) -> str:
    return (
        f"原始 {stats['total']} 条；保留 {stats['kept']} 条；"
        f"纯媒体/空消息丢弃 {stats['dropped_empty']} 条；"
        f"正文超过 {max_chars} 字丢弃 {stats['dropped_long']} 条；"
        f"去掉媒体段 {stats['media_removed']} 个；"
        f"补占位标记 {stats['placeholder_added']} 个；"
        f"未知段忽略 {stats['unknown_removed']} 个"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="拉取 QQ 群聊天记录并整理成纯文字版")
    parser.add_argument("--group", type=int, help="群号；默认取 GAME_QQ_GROUP_ID 的第一个")
    parser.add_argument("--env", type=pathlib.Path, default=DEFAULT_ENV, help="凭据文件")
    parser.add_argument("--ws-url", help="覆盖 NAPCAT_WS_URL")
    parser.add_argument("--token", help="覆盖 NAPCAT_TOKEN")
    parser.add_argument("--out-dir", type=pathlib.Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--start", type=int, default=50, help="首次请求的 count")
    parser.add_argument("--factor", type=float, default=2.0, help="count 增长倍数")
    parser.add_argument("--max-count", type=int, default=20000, help="count 上限")
    parser.add_argument("--timeout", type=float, default=180.0, help="单次请求超时（秒）")
    parser.add_argument("--max-seconds", type=float, default=900.0, help="整体抓取时间上限（秒）")
    parser.add_argument("--max-chars", type=int, default=30, help="保留消息的正文长度上限")
    parser.add_argument("--clean-only", action="store_true", help="跳过抓取，只重新整理已有原始记录")
    return parser


async def main_async(args: argparse.Namespace) -> int:
    args.out_dir.mkdir(parents=True, exist_ok=True)
    values: dict[str, str] = {}
    if args.clean_only:
        group_id = resolve_group(args, read_env_file(args.env))
    else:
        ws_url, token, values = resolve_credentials(args)
        group_id = resolve_group(args, values)
        raw_path = args.out_dir / f"qq_{group_id}_raw.json"
        log(f"连接 {ws_url}（令牌{'已带上' if token else '为空'}），目标群 {group_id}")
        messages, attempts = await fetch_history(args, group_id, ws_url, token)
        if not messages:
            log("一条消息都没拿到，不写文件")
            return 1
        write_raw(raw_path, group_id, messages, attempts)
        log(f"原始记录已写入 {raw_path}（{len(messages)} 条）")

    raw_path = args.out_dir / f"qq_{group_id}_raw.json"
    if not raw_path.is_file():
        log(f"找不到原始记录 {raw_path}，请先抓取")
        return 1
    _, messages = read_raw(raw_path)
    entries, stats = clean_messages(messages, args.max_chars)
    txt_path = args.out_dir / f"qq_{group_id}_clean.txt"
    json_path = args.out_dir / f"qq_{group_id}_clean.json"
    write_clean_txt(txt_path, group_id, entries, stats, args.max_chars)
    json_path.write_text(json.dumps(entries, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"整理完成：{summarize(stats, args.max_chars)}")
    log(f"纯文字版已写入 {txt_path} 与 {json_path}")
    return 0


def main() -> int:
    args = build_parser().parse_args()
    try:
        return asyncio.run(main_async(args))
    except KeyboardInterrupt:
        log("被中断")
        return 130


if __name__ == "__main__":
    sys.exit(main())
