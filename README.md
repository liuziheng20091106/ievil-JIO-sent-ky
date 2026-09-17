# 魔法裁判 · 七双

七人双角色在线桌游。七名玩家各持两张角色牌，在一名固定真人主持人的带领下进行魔女化、夜间行动、公开讨论、热气球、提名与处决。

## 特点

- 七人双角色：发牌后玩家私下决定上下牌顺序，上层出局后启用下层。
- 真人主持人：开局、阶段推进、概率与未写明情况均由主持人裁定；系统知情的阶段无人待办时 5 秒后自动推进，主持人可随时暂停或手动推进。
- QQ 账号登录：玩家在指定 QQ 群发送“活动登录 123456”完成验证，登录令牌长期有效；账号与对局参与身份分离。
- 开放参局：主持人“开放加入”后，已登录账号自行选择加入或观战，无需审核；发牌前随机占用空席，同一账号不能重复分席。
- 公屏与私信分离：公屏、私信、系统信息各自独立列表与已读游标；私信有邀请、同意、拒绝、结束的完整生命周期。
- 服务端裁剪：角色牌、魔女化状态、私信锁定等全部在服务端判定，前端隐藏不作为授权。
- 多端：React 网页由后端同源提供，另有 Flutter 原生 Android / Windows 客户端。

## 环境要求

- Python 3.14+
- Node.js >= 22.12
- Flutter 3.35+（仅构建原生客户端时需要）
- NapCat（QQ 网关，仅 QQ 登录时需要）

## 安装与启动

```cmd
setup.cmd
start.cmd
```

然后打开 <http://localhost:8000>。默认绑定 `0.0.0.0`，局域网内可直接访问；`start.cmd` 的参数会透传给 `run.py`（如 `start.cmd --port 9000`）。

主持人登录使用固定密码，见 `backend/app/api.py`。这是唯一保留的非 QQ 登录入口。

## QQ 网关（NapCat）

QQ 登录依赖 NapCat 的 OneBot WebSocket 实现，网关把群消息里的六位登录码绑定到账号：

```cmd
copy gateway\.env.example gateway\.env
run-gateway.cmd
```

> **启动后端必须带上同一个密钥。** 网关会用 `X-Gateway-Token` 调 `/api/internal/qq/*`，
> 后端没有 `GAME_GATEWAY_TOKEN` 时会一律返回 401，表现为群成员同步失败、群消息无法登录。
>
> 若返回 403 且文案是「仅允许从本站提交操作」，那不是密钥问题：网关是独立进程，既不带
> `Origin` 也不带会话 Bearer，只靠 `X-Gateway-Token` 认证，必须由 `request_boundary`
> 中间件显式放行（见 `backend/app/main.py`）。密钥错误只会得到 403「QQ群不匹配」或
> 401「网关认证失败」，可据此区分。
>
> 本机已备 `start.cmd.local`（内含密钥与群号，已被 .gitignore 排除）：
>
> ```cmd
> start.cmd.local      rem 代替 start.cmd
> run-gateway.cmd
> ```
>
> 如果改用 `start.cmd` 启动，需自行设置环境变量 `GAME_GATEWAY_TOKEN` 与 `GAME_QQ_GROUP_ID`。

`gateway/.env` 必填项：

| 变量 | 说明 |
| --- | --- |
| `NAPCAT_WS_URL` | NapCat 的 OneBot WebSocket 地址，默认 `ws://127.0.0.1:3001` |
| `NAPCAT_TOKEN` | NapCat 访问令牌，无则留空 |
| `GAME_BACKEND_URL` | 后端地址，默认 `http://127.0.0.1:8000` |
| `GAME_GATEWAY_TOKEN` | 网关与后端共享的密钥，须与后端环境变量一致 |
| `GAME_QQ_GROUP_ID` | 允许登录的 QQ 群号 |

`gateway/.env`、`gateway/napcat/`、`gateway/*.log` 已在 `.gitignore` 中：NapCat 登录态、设备文件、访问令牌和网关共享密钥不得入库，也不得写入 Flutter 资源或网页构建产物。

网关把 `X-Gateway-Token` 放在请求头调用 `/api/internal/qq/login`，后端用 `secrets.compare_digest` 校验；挑战码一次性消费，过期或重放一律拒绝。

## 数据与备份

`data/` 目录（可用 `GAME_DATA_DIR` 覆盖）下有两个 SQLite 文件，备份边界不同：

| 文件 | 内容 | 清空对局时 |
| --- | --- | --- |
| `seven-double.sqlite3` | 对局状态、参与身份、频道、消息、证物图片 | 全部删除 |
| `auth.sqlite3` | QQ 账号、登录挑战、登录令牌（只存 SHA-256 后的令牌） | 保留 |

“一键初始化”和“开启下一局”只清空对局库：QQ 账号、玩家登录令牌和主持人登录都不会失效。踢人或本局拉黑只让对应参与身份失效，不影响账号在其他对局登录。

## Flutter 原生客户端

```cmd
cd client
flutter pub get
flutter analyze
flutter test
flutter build apk --debug
flutter build windows --debug
```

客户端启动后先填写服务根地址：局域网可用 HTTP，公网地址必须 HTTPS。玩家端与主持人端按登录身份自动切换界面；Android 提供触觉反馈，Windows 静默。

### 应用图标

各端 app 图标统一取自 `img/月代雪.png`（透明背景的圆形胸像）。改动源图后重新生成：

```cmd
.venv\Scripts\python.exe tools\gen_app_icons.py
```

脚本会写入 Windows 的 `app_icon.ico`、Android 传统 mipmap 与自适应图标前景/底色、以及网页 `favicon.ico` / `favicon.png` / `apple-touch-icon.png`（需要 Pillow）。图标保留圆形、四周透明；自适应图标前景按 Android 安全区缩放并配主题底色 `#191721`。

## 反向代理

服务可以挂在 nginx / Caddy / Cloudflare 之类的反向代理后面。代理需要：

- 透传原始 `Host`（`proxy_set_header Host $host;`）或补 `X-Forwarded-Host` 与 `X-Forwarded-Proto`；
- 转发 `Authorization` 请求头（原生客户端使用 Bearer 令牌，不要被代理丢弃）；
- 允许 WebSocket 升级到 `/api/live`。

代理不在本机时用 `start.cmd --trusted-proxies <代理地址>`（或环境变量 `GAME_TRUSTED_PROXIES`）声明可信代理，代理地址不固定可写 `*`。

自带有效 Bearer 令牌的请求跳过浏览器同源校验；网页 Cookie 写请求和 WebSocket 仍要求同源。没有 `Origin` 头时：**WebSocket 放行**（原生客户端不发 `Origin`，由 Bearer 令牌认证），**HTTP 写请求按跨站拒绝**——这两条方向不能写反，`checks/test_room.py` 的 `SameOrigin` 会守住它。

`super.tkcloud.online` 属于显式放行的来源，换站点用 `GAME_ALLOWED_ORIGINS` 覆盖（逗号分隔，可写 `host`、`host:port` 或整条 URL），默认值见 `backend/app/auth.py`。

## 虚拟玩家模拟器

`backend/app/simulator/` 是一套自动打完整局的虚拟玩家，用于测试游戏：

- 走真实协议（登录、命令、`expected_version`、服务端可见性裁剪），不直接调用规则层；
- 七名虚拟玩家只依据自己裁剪后的视图决策，主持人由脚本扮演；
- 系统自己能算完的阶段交给 5 秒自动推进，需要裁定的事项按行动默认值处理。

单局跑批（默认每局一个独立临时目录，不碰 `data/`）：

```cmd
.venv\Scripts\python.exe run-simulator.py --games 20
.venv\Scripts\python.exe run-simulator.py --games 5 --seed 100 --verbose
.venv\Scripts\python.exe run-simulator.py --games 3 --url http://127.0.0.1:8000
```

对着已启动的服务跑时，进程内不再需要账号：`--gateway-token` 与 `--group-id` 用来核销登录码，
默认取环境变量 `GAME_GATEWAY_TOKEN`、`GAME_QQ_GROUP_ID`。

`checks/test_simulator.py` 把「一局必须能走到合法收尾」以及「视图列出的行动一定可提交」
固定成回归检查；模拟器一旦在某阶段卡住或行动被拒，检查就会失败并打印决策日志。

## 检查

```cmd
.venv\Scripts\python.exe -m unittest discover -s checks -v
.venv\Scripts\python.exe -m ruff check backend checks run.py gateway run-simulator.py
cd frontend && npm.cmd run build
```

运行检查时请把 `GAME_DATA_DIR` 指向独立临时目录，避免影响 `data/` 中的真实对局。

## 目录结构

```
backend/app/    FastAPI 服务、SQLite 存储、账号令牌、实时推送
backend/app/game/  规则、结算与可见性裁剪
backend/app/simulator/  虚拟玩家模拟器（真实协议驱动整局）
frontend/src/  React + TypeScript 网页界面
client/        Flutter Android / Windows 原生客户端
gateway/       NapCat OneBot QQ 登录网关
checks/        后端回归检查
tools/         应用图标生成脚本
docs/          游戏规则与设计方案
img/           角色头像
```

## 许可

[AGPL-3.0](LICENSE)。
