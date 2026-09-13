# 魔法裁判 · 七双

七人双角色在线桌游。七名玩家各持两张角色牌，在一名固定真人主持人的带领下进行魔女化、夜间行动、公开讨论、热气球、提名与处决。

## 特点

- 七人双角色：发牌后玩家私下决定上下牌顺序，上层出局后启用下层。
- 真人主持人：开局、阶段推进、概率与未写明情况均由主持人裁定；系统知情的阶段无人待办时 5 秒后自动推进，主持人可随时暂停或手动推进。
- 共享邀请码：玩家用本局统一邀请码随机入场，观战者用观战码入场。
- 两段式准备：全员首次准备后发牌，再次全员准备后开局。
- 服务端裁剪：角色牌、魔女化状态等私密信息按身份下发，前端隐藏不作为授权。
- 单机部署：一个 Python 进程 + 一个 SQLite 文件，生产前端由后端同源提供。

## 环境要求

- Python 3.14+
- Node.js >= 22.12

## 安装与启动

```cmd
setup.cmd
start.cmd
```

然后打开 <http://localhost:8000>。默认绑定 `0.0.0.0`，局域网内可直接访问；`start.cmd` 的参数会透传给 `run.py`（如 `start.cmd --port 9000`）。

主持人登录使用固定密码，见 `backend/app/api.py`。

## 检查

```cmd
.venv\Scripts\python.exe -m unittest discover -s checks -v
.venv\Scripts\python.exe -m ruff check backend checks run.py
cd frontend && npm.cmd run build
```

运行检查时请把 `GAME_DATA_DIR` 指向独立临时目录，避免影响 `data/` 中的真实对局。

## 目录结构

```
backend/app/    FastAPI 服务、SQLite 存储、会话与实时推送
backend/app/game/  规则、结算与可见性裁剪
frontend/src/  React + TypeScript 界面
checks/        后端回归检查
docs/          游戏规则与设计方案
img/           角色头像
```

## 许可

[AGPL-3.0](LICENSE)。
