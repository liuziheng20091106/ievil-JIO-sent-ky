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

另有一个同源分发接口 GET /releases/{文件名}：把 `data/releases/` 里的更新包
（`魔法裁判Windows.zip`、`app-release.apk`、`Updater.exe`）直接发给客户端，
应用内更新因此不必依赖局域网共享。`data/updates.json` 里的 `url` 可以写
`/releases/app-release.apk` 这样的相对路径，也可以写绝对地址。
"""

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from . import client_release, storage

router = APIRouter(prefix="/api/downloads")

releases_router = APIRouter(prefix="/releases")


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


@releases_router.get("/{name}")
async def get_release(name: str):
    """同源下发更新包：只认 `data/releases/` 下的单个文件名，不做目录穿透。

    不需要登录：安卓客户端在更新时可能正好处于登录失效状态，更新不该因此被卡住；
    这里提供的都是公开分发的安装包，没有对局数据。
    """
    path = client_release.release_path(name)
    if path is None:
        raise HTTPException(404, "安装包不存在")
    return FileResponse(
        path,
        filename=name,
        headers={"Cache-Control": "private, no-store"},
    )
