"""游戏下载链接配置：`data/downloads.json`，由部署者手工维护。

首页从 GET /api/downloads 读取；文件不存在时返回空列表，页面显示「敬请期待」。
格式（不入库，改完即生效，无需重启）：

```json
{
  "downloads": [
    {"name": "Windows 版", "url": "https://example.com/MagicJudge.zip"},
    {"name": "安卓版", "url": "https://example.com/app-release.apk"}
  ]
}
```
"""

import json

from fastapi import APIRouter

from . import storage

router = APIRouter(prefix="/api/downloads")


def load_downloads():
    """读 data/downloads.json；文件缺失或格式不对都按「暂无下载」处理。"""
    path = storage.DATA_DIR / "downloads.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = data.get("downloads") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    downloads = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        url = item.get("url")
        if isinstance(name, str) and isinstance(url, str) and name and url:
            downloads.append({"name": name, "url": url})
    return downloads


@router.get("")
async def get_downloads():
    return {"downloads": load_downloads()}
