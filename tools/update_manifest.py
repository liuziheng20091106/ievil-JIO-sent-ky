#!/usr/bin/env python3
"""应用内更新清单 `data/updates.json` 的维护逻辑（供 `tools/package-release.py` 调用）。

后端 `/api/health` 按「平台 + 版本区间」下发不同的更新信息；发布时只需要刷新每个
平台那条**兜底区间**（没有 `min_version` / `max_version` 的）的 latest / url / size /
sha256 / updater_url：

- 手工写的 `title` / `notes` / `minimum` / `guide_url` 一律保留；
- 更窄的区间条目（给老版本走「先升到中间版本」这类路径）原样保留；
  区间取**第一条匹配**，所以窄区间要写在兜底区间前面。

单独也能跑（排查清单问题时很方便）：

    .venv\\Scripts\\python.exe tools\\update_manifest.py --show
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PUBSPEC = ROOT / "client" / "pubspec.yaml"


class ManifestError(Exception):
    """清单本身有问题（配置坏掉或版本读不出来）。"""


def client_version() -> str:
    """客户端版本名：与 `client/lib/src/client_version.dart` 同步手改的 pubspec 版本。"""
    if not PUBSPEC.exists():
        raise ManifestError(f"缺少 {PUBSPEC}")
    for raw in PUBSPEC.read_text(encoding="utf-8").splitlines():
        if raw.startswith("version:"):
            value = raw.split(":", 1)[1].strip().split("+")[0]
            if re.fullmatch(r"\d+\.\d+\.\d+", value):
                return value
    raise ManifestError(f"{PUBSPEC} 里没有形如 `version: 1.2.3+1` 的版本名")


def find_catch_all(items: list, platform: str) -> int | None:
    """找该平台的「兜底区间」下标：没有 min_version / max_version 的那条。"""
    found = None
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        if item.get("platform", "any") not in (platform, "any"):
            continue
        if item.get("min_version") or item.get("max_version"):
            continue
        found = index
    return found


def load_manifest(path: Path) -> dict:
    if not path.exists():
        return {"updates": []}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ManifestError(f"{path} 不是合法 JSON，未改动：{error}") from error
    return loaded if isinstance(loaded, dict) else {"updates": []}


def refresh_manifest(path: Path, version: str, entries: list[dict], log=print) -> None:
    """刷新/追加每个平台的兜底区间，并写回清单文件。"""
    data = load_manifest(path)
    raw_items = data.get("updates")
    items = list(raw_items) if isinstance(raw_items, list) else []

    for entry in entries:
        index = find_catch_all(items, entry["platform"])
        target = items[index] if index is not None else None
        if target is None:
            target = {"platform": entry["platform"]}
            items.append(target)
            action = "新增"
        else:
            action = "刷新"
        for key, value in entry.items():
            target[key] = value
        target["latest"] = version
        log(f"  {action} {entry['platform']} 兜底区间：latest={version} url={entry['url']}")

    data["updates"] = items
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    log(f"已刷新更新清单 {path}")


def show(path: Path) -> int:
    """打印当前清单与匹配到的版本，排查「为什么没提示更新」时用。"""
    print(f"客户端版本：{client_version()}（来自 {PUBSPEC}）")
    print(f"更新清单：{path}")
    if not path.exists():
        print("  （文件不存在：后端会退回 GAME_CLIENT_LATEST / GAME_CLIENT_MINIMUM）")
        return 0
    for item in load_manifest(path).get("updates") or []:
        if not isinstance(item, dict):
            continue
        print(
            "  platform={platform} 区间=[{low}, {high}) latest={latest} minimum={minimum}".format(
                platform=item.get("platform", "any"),
                low=item.get("min_version") or "-",
                high=item.get("max_version") or "-",
                latest=item.get("latest") or "-",
                minimum=item.get("minimum") or "-",
            )
        )
        for key in ("url", "updater_url", "guide_url"):
            if item.get(key):
                print(f"    {key}={item[key]}")
        if item.get("size"):
            print(f"    size={item['size']} sha256={(item.get('sha256') or '')[:16]}…")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="查看应用内更新清单 data/updates.json")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data", help="data 目录")
    parser.add_argument("--show", action="store_true", help="打印当前清单")
    args = parser.parse_args(argv)
    try:
        return show(args.data_dir / "updates.json")
    except ManifestError as error:
        print(f"读取失败：{error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
