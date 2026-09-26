# 项目约束

## 范围与规则
- 使用中文沟通。实现七人双角色模式，固定真人主持人；不扩展十三人模式或公网基础设施。
- 当前用户确认的规则优先于 `docs/七双模式游戏介绍与完整规则.txt` 和 `docs/七双在线游戏设计方案.txt`；`docs/old` 仅供历史参考。
- 桌游版说明与实际游戏版本存在差异：差异基线与「不要改」清单见 `docs/规则基线-勿改清单.md`。除已删除的「秘密洗脑」（普通安安）外，其余差异一律以代码现状为准，改动前先确认。
- 入场使用本局统一玩家邀请码，随机分配空席；全员第一次准备后发牌，私下决定上下牌，再次全员准备后由主持人开局。可调整顺序期间不公开角色头像或名称。
- 玩家身份与持久席位分离；踢人、观战替补不得重抽角色或重置技能。夜间同时行动，死亡者仍可完成当夜行动。
- 提名在白天随时可提交、提交即生效（无需二次确认），进入提名阶段时先前提名或放弃自动视为已确认；同一人可被多人提名，计票去重后每张牌只投一轮，提名过当前候选的玩家自动投同意票。
- 顺序发言可预提交：未轮到的席位可点「本轮不发言（跳过我的顺序）」或「提前写发言（轮到你时公开）」写下内容，轮到时才自动公开；全部提交后阶段自动完成，天黑时清空。
- 真实白天技能声明后立即按技能条目结算（声明留到当天结束，质疑入口与伪装声明完全一致），伪装声明仍由主持人裁定；希罗回溯由本人在行动面板选择，主持人只管非同一天同一时点的特殊裁定。
- 米莉亚临死换牌没有主持人判定点：她的预结算一旦会出局就直接换上层牌重算。
- 不明确的概率和规则交由主持人裁决，保留显式确认与30秒警告。系统自己知道做完的阶段（魔女化、夜间行动、顺序发言、提名、投票、处决前响应）无人待办时5秒后自动推进，主持人可暂停或手动推进；需要主持人判断或宣布的阶段仍由主持人推进。主持人的「推进」是强制推进：未完成的玩家行动立刻按超时处理，只有待裁定事项、胜负宣判与交牌审阅仍会拒绝推进。

## 实现边界
- 后端：Python 3.14+、FastAPI、标准库 SQLite，单进程单 worker。前端：Node.js >=22.12；网页只是公告、规则介绍与下载链接的静态单页（无框架，`frontend/rules.md` 是规则栏目数据源），生产前端由 FastAPI 同源提供。
- `backend/app/game/` 维护规则，不依赖 HTTP；`views.py` 在服务端裁剪可见信息，前端隐藏不能代替授权。
- 命令使用 `expected_version`；冲突刷新并要求重新确认，不自动重试写入。复用后端动作描述生成表单。
- 主持人不再使用固定密码：管理员由环境变量 `GAME_ADMIN_QQ` 指定（恒为 5 级），其余主持授权与 QQ 账号绑定、分 1-5 级（1 级只主持 1 局，那一局结束授权即失效）；登录令牌每次请求重新核对等级，任何授权配置都不得写入前端资源。不要增加 ORM、通用规则引擎、状态框架或无需求的新依赖。
- 主持授权只说明「有资格主持」：主持账号进入某一局还要先确认（`POST /api/games/{id}/host/enter`，记在 `game["host_entries"]`），未确认前只有观察者投影——没有全席上下牌、主持人面板、私聊历史，也执行不了任何命令（含禁言、移人、替补、代操作）。放行判据只有 `game.state.host_capable(actor)` 一处，投影、消息可见性、证物、成就与命令校验都走它；非本局主持人确认进入时另在本局发一条系统公告（kind=alert，只进这一局的消息记录，不写大厅的全服公告库）。
- 草稿按对局、参与身份、频道或表单隔离；刷新可恢复，提交成功才清除，不保存密码、会话。替补不得继承旧身份的本地私密草稿。

## 运行与验证
- 安装：`setup.cmd`；启动：`start.cmd`；默认 `http://localhost:8000`。
- 默认数据目录 `data/` 属于用户。验证必须设置 `GAME_DATA_DIR` 为独立临时目录；不得删除或改写用户对局。
- 反向代理：代理必须透传原始 `Host` 或补 `X-Forwarded-Host`/`X-Forwarded-Proto`；代理不在本机时用 `--trusted-proxies` 或 `GAME_TRUSTED_PROXIES` 声明。显式放行来源默认是 `super.tkcloud.online`，用 `GAME_ALLOWED_ORIGINS` 覆盖。
- 后端检查：`.venv/Scripts/python.exe -m unittest discover -s checks -v`。
- 静态检查：`.venv/Scripts/python.exe -m ruff check backend checks run.py gateway run-simulator.py supervisor.py`。
- 前端检查/构建：在 `frontend/` 执行 `npm.cmd run build`。
- 客户端编译发行：在 `client/` 执行 `flutter build apk --release --target-platform android-arm64` 与 `flutter build windows --release`。
- 每次编译后运行 `package-release.cmd`：把 `client/build/windows/x64/runner/Release` 重新打成 `魔法裁判Windows.zip`，与 `client/build/app/outputs/flutter-apk/app-release.apk` 一起上传到 S3 兼容存储（Cloudflare R2）的 `S3_PREFIX` 子目录，再把两条对外链接写进 `data/downloads.json`（网页首页「下载游戏」的数据源）。不再使用局域网共享目录。真正的实现在 `tools/package-release.py`，`package-release.cmd` 只是它的 ASCII 包装。
- 发布配置在仓库根目录的 `package-release.env`（dotenv 写法，含密钥，已在 `.gitignore` 中）：`S3_ENDPOINT`（只到域名）、`S3_REGION`（R2 填 `auto`）、`S3_ACCESS_KEY_ID`、`S3_SECRET_ACCESS_KEY`、`S3_BUCKET`、`S3_PREFIX`（子目录，默认 `releases`）、`S3_PUBLIC_BASE`（对外访问地址，默认 `https://s3.tkcloud.online`）、可选 `S3_TIMEOUT`。同名进程环境变量优先于该文件。缺项或值里还留着 `*` 占位符时脚本报错退出，不会上传半截。
- `package-release.cmd` 已是纯 ASCII，中文路径与码页不再影响它，DSH/自动化里直接 `cmd /c package-release.cmd` 即可（不再需要 `chcp 936`，`.venv` 的 python 用 `-X utf8` 运行，输出的中文按 UTF-8 管道可正常解码）。`--dry-run` 只打包并打印计划（不联网、不改 `downloads.json`），`--skip-zip` 复用已有压缩包，`--no-downloads` 跳过写下载链接。
- 发布后不要只看退出码：脚本自己会回读远端对象，逐个比对 `Content-Length` 与本地一致（ETag 与本地 MD5 不同只提示不失败），不一致就以退出码 1 结束。此外还要确认网页首页 `GET /api/downloads` 返回的两条链接指向 `S3_PUBLIC_BASE` 且能直接下到刚发布的文件；APK 版本号用 `client\build\app\outputs\apk\release\output-metadata.json` 的 `versionName` 核对，安卓 `versionCode` 保持不动。
- 客户端版本标签：后端 `GAME_CLIENT_LATEST` / `GAME_CLIENT_MINIMUM`（`x.y.z` 三段），低于 latest 提示可更新、低于 minimum 强制更新；客户端内置版本号写在 `client/lib/src/release.dart` 的 `ReleaseMonitor.currentVersion`，发版时与 `client/pubspec.yaml` 的版本名同步手改，不动安卓 versionCode/versionName。部署环境的标签在本地不入库的 `start.cmd.local.cmd` 里，改完必须重启服务端进程，`/api/health` 才会下发新版本。
- 有意义的行为修改必须实际启动并验证相关服务或浏览器路径；新增回归检查只保护真实规则、权限或数据丢失边界。
- 更新现有 TXT 运行说明；保持改动最小，不为假设需求搭框架。并发代理修改不同文件，统一在集成结束后格式化、构建和运行检查。

## 守护进程（后端 + 登录网关）
- `supervisor.py`（用 `run-supervisor.cmd` 启动）托管两个子进程：后端 `run.py` 与登录网关 `python -m gateway.gateway`。它代替 `start.cmd` 与 `run-gateway.cmd`，不要两边同时启动（会抢端口）。默认自动拉起两者；子进程意外退出按 2s→60s 退避自动重启；退出守护进程会一并停掉子进程。子进程输出追加在 `logs/backend.log`、`logs/gateway.log`（`logs/` 已 gitignore）。
- 默认只监听 `127.0.0.1:13900`（`GAME_SUPERVISOR_HOST` / `GAME_SUPERVISOR_PORT` 可改）。`GET /status` 给出两个进程的 pid、存活时长、重启次数、日志路径与后端 `/api/health` 是否可达；重启走 POST（设了令牌就带 `-H "X-Supervisor-Token: <令牌>"`）：
  - `POST /restart/backend` 重启后端；`POST /restart/gateway` 重启登录网关；`POST /restart/all` 先把两个都停掉再拉起（先后端后网关，避免网关空转重连）。
  - `POST /start|stop/{backend|gateway|all}` 是同一套生命周期；进程名不在白名单返回 404，起不来返回 500 且 body 带退出码与日志末尾，`/status` 里该进程为 `stopped`。
- 后端端口默认 8000，用 `--backend-port` 或 `GAME_SUPERVISOR_BACKEND_PORT` 覆盖；显式改端口时守护进程会把网关子进程的 `GAME_BACKEND_URL` 一起改到该端口。网关的环境变量默认读 `gateway/.env`，测试或换端口用 `--gateway-env` 指向别的文件；后端的环境变量（`GAME_ADMIN_QQ`、`GAME_GATEWAY_TOKEN`、`GAME_DATA_DIR`、客户端版本标签等）由守护进程原样继承，所以部署时照 `start.cmd.local.cmd` 的样子写一份不入库的 `run-supervisor.cmd.local.cmd`（和它一样显式列在 `.gitignore` 里，`*.cmd.local` 匹配不到 `*.cmd.local.cmd`）设好再启动。
- 绑定非回环地址必须先设 `GAME_SUPERVISOR_TOKEN`，否则拒绝启动；设了令牌后除 `GET /health` 外的请求都要带 `X-Supervisor-Token`。带 `Origin` 的浏览器请求一律 403——这个接口只给本机脚本用，不能让网页重启服务。端口被占用会直接报错退出，不会静默双开。

## 版本管理
- 使用本地 Git 管理可回退版本；改动前保留基线，验证完成后提交功能变更。自动推送远端。
- 不提交 `data/`、`.venv/`、`node_modules/`、构建产物、缓存、会话、私密材料或临时联调脚本。
- 不要删除用户现有修改，每次改完删除所有验证数据。
