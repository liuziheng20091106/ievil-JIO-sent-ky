"""Start the single-process game server after building the frontend."""

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="魔法裁判 · 七双")
    parser.add_argument("--host", default="0.0.0.0", help="绑定地址，默认允许局域网访问")
    parser.add_argument("--port", type=int, default=8000, help="服务端口，默认8000")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    if not (root / "frontend" / "dist" / "index.html").is_file():
        parser.error("前端尚未构建。请先在 frontend 目录运行 npm install 和 npm run build。")
    import uvicorn

    uvicorn.run("backend.app.main:app", host=args.host, port=args.port, workers=1)


if __name__ == "__main__":
    main()
