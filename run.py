"""Start the single-process game server after building the frontend."""

import argparse
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="魔法裁判 · 七双")
    parser.add_argument("--host", default="0.0.0.0", help="绑定地址，默认允许局域网访问")
    parser.add_argument("--port", type=int, default=8000, help="服务端口，默认8000")
    parser.add_argument(
        "--trusted-proxies",
        default=os.environ.get("GAME_TRUSTED_PROXIES", "127.0.0.1"),
        help="可信反向代理地址，逗号分隔；代理不在本机时填它的地址，或用 * 信任全部",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    if not (root / "frontend" / "dist" / "index.html").is_file():
        parser.error("前端尚未构建。请先在 frontend 目录运行 npm install 和 npm run build。")
    import uvicorn

    uvicorn.run(
        "backend.app.main:app",
        host=args.host,
        port=args.port,
        workers=1,
        proxy_headers=True,
        forwarded_allow_ips=args.trusted_proxies,
    )


if __name__ == "__main__":
    main()
