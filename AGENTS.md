# 项目约束

## 范围与规则
- 中文沟通。只做七人双角色模式，固定真人主持人；不扩展十三人模式或公网基础设施。
- 用户当前确认的规则优先于 `docs/七双模式游戏介绍与完整规则.txt` 与 `docs/七双在线游戏设计方案.txt`；`docs/old` 仅作历史参考。
- 桌游版说明与实现的差异基线、「不要改」清单见 `docs/规则基线-勿改清单.md`；除已删除的「秘密洗脑」（普通安安）外一律以代码现状为准，改动前先确认。
- 入场用本局统一玩家邀请码，随机分配空席；全员第一次准备后发牌，私下决定上下牌，再次全员准备后由主持人开局。可调整顺序期间不公开角色头像与名称。
- 玩家身份与持久席位分离；踢人、观战替补不得重抽角色或重置技能。夜间同时行动，死亡者仍可完成当夜行动。
- 提名白天随时可提交、提交即生效（无需二次确认）；进入提名阶段时先前的提名或放弃自动视为已确认。同一人可被多人提名，计票去重后每张牌只投一轮，提名过当前候选的玩家自动投同意票。
- 顺序发言可预提交：未轮到的席位可点「本轮不发言（跳过我的顺序）」或「提前写发言（轮到你时公开）」，轮到时自动公开；全部提交后阶段自动完成，天黑清空。另有全场公开的 30 秒计时（顶部横幅显示剩余秒数与进度条），当前发言人公屏发言或继续输入都会重置，到点自动轮到下一位。
- 真实白天技能声明后立即按技能条目结算（声明留到当天结束，质疑入口与伪装声明完全一致），伪装声明仍由主持人裁定；希罗回溯由本人在行动面板选择，主持人只管非同一天同一时点的特殊裁定。
- 米莉亚临死换牌没有主持人判定点：预结算一旦会出局就直接换上层牌重算。
- 不明确的概率和规则交主持人裁决，保留显式确认与 30 秒警告。系统自己知道做完的阶段（魔女化、夜间行动、顺序发言、提名、投票、处决前响应）无人待办时 5 秒后自动推进，主持人可暂停或手动推进；需要主持人判断或宣布的阶段仍由主持人推进。主持人的「推进」是强制推进：未完成的玩家行动立刻按超时处理，只有待裁定事项、胜负宣判与交牌审阅仍拒绝推进。

## 实现边界
- 后端 Python 3.14+ / FastAPI / 标准库 SQLite，单进程单 worker。前端 Node.js >=22.12；网页只是公告、规则介绍与下载链接的静态单页（无框架，`frontend/rules.md` 是规则栏目数据源），生产前端由 FastAPI 同源提供。
- `backend/app/game/` 维护规则、不依赖 HTTP；`views.py` 在服务端裁剪可见信息，前端隐藏不能代替授权。
- 命令带 `expected_version`；冲突即刷新并要求重新确认，不自动重试写入。表单复用后端动作描述生成。
- 主持人不用固定密码：管理员由 `GAME_ADMIN_QQ` 指定（恒 5 级），其余主持授权与 QQ 账号绑定、分 1-5 级（1 级只主持 1 局，该局结束即失效）；登录令牌每次请求重新核对等级，任何授权配置都不得写入前端资源。不加 ORM、通用规则引擎、状态框架或无需求的新依赖。
- 主持授权只代表「有资格主持」：进某一局还要先确认（`POST /api/games/{id}/host/enter`，记在 `game["host_entries"]`），未确认前只有观察者投影——没有全席上下牌、主持人面板、私聊历史，也执行不了任何命令（含禁言、移人、替补、代操作）。放行判据只有 `game.state.host_capable(actor)` 一处，投影、消息可见性、证物、成就与命令校验都走它；非本局主持人确认进入时在本局发一条系统公告（kind=alert，只进这一局的消息记录，不写大厅公告库）。
- 草稿按对局、参与身份、频道或表单隔离；刷新可恢复，提交成功才清除，不保存密码与会话。替补不得继承旧身份的本地私密草稿。

## 运行与验证
- 安装 `setup.cmd`；启动 `start.cmd`；默认 `http://localhost:8000`。
- `data/` 属于用户。验证必须把 `GAME_DATA_DIR` 设为独立临时目录，不得删除或改写用户对局。
- 反向代理必须透传原始 `Host` 或补 `X-Forwarded-Host`/`X-Forwarded-Proto`；代理不在本机时用 `--trusted-proxies` 或 `GAME_TRUSTED_PROXIES` 声明。放行来源默认 `super.tkcloud.online`，用 `GAME_ALLOWED_ORIGINS` 覆盖。
- 后端检查：`.venv/Scripts/python.exe -m unittest discover -s checks -v`。
- 静态检查：`.venv/Scripts/python.exe -m ruff check backend checks run.py gateway run-simulator.py supervisor.py`。
- 前端构建：在 `frontend/` 执行 `npm.cmd run build`。
- 客户端发行：在 `client/` 执行 `flutter build apk --release --target-platform android-arm64` 与 `flutter build windows --release`；环境结论与逐步清单见 `docs/客户端编译发行手册.md`。
- 每次编译后运行 `package-release.cmd`（真正实现在 `tools/package-release.py`，cmd 只是 ASCII 包装，直接 `cmd /c package-release.cmd` 即可）：把 `client/build/windows/x64/runner/Release` 打成 `魔法裁判Windows.zip`，与 `client/build/app/outputs/flutter-apk/app-release.apk`、独立发布产物 `Updater.exe` 一起上传到 S3 兼容存储（Cloudflare R2）的 `S3_PREFIX` 子目录，再把三条链接写进 `data/downloads.json`（网页首页「下载游戏」数据源）。
  - 参数：`--dry-run` 只打包打印计划（不联网、不改配置），`--skip-zip` 复用已有压缩包，`--skip-upload` 复用已上传对象只做校验与配置刷新，`--no-downloads` / `--no-updates` 跳过对应配置刷新，`--no-updater` 不上传安装程序。打包前后比对发行目录文件指纹，`flutter build` 还在跑或 `seven_double_client.exe` 缺失时拒绝出包（退出码 1），不打出新旧混合的半成品。
- 部署端更新标签由 `data/updates.json` 下发（`backend/app/client_release.py`，按「平台 + 版本区间」，区间取第一条匹配，窄区间写在前面）；后端不读 `GAME_CLIENT_LATEST` / `GAME_CLIENT_MINIMUM` 等版本环境变量，清单缺失或没有匹配区间就什么都不下发。低于 latest 提示可更新，低于 minimum 强制更新（只拒绝以玩家身份入局，其它功能不受限）；清单每次请求现读，改完不用重启。Windows 更新器/安装程序（UA `magicjudge-updater/<版本> (windows)`）不问自己旧不旧，永远拿该平台兜底区间那份当前发布包。完整三段发行版本唯一源码是 `client/lib/src/client_version.dart` 的 `kClientVersion`，当前 `1.1.0`；从此正常补丁发版只改该常量，`client/pubspec.yaml` 固定 `version: 1.1.0+1`，仅跨 `x.y` 系列才改其 `x.y`，`+1` 不动。客户端 UA、更新比较、清单 latest、三条版本化上传对象键与 `Updater.exe --version` 使用完整发行版本；APK metadata 的 versionName 为 `1.1.0`、versionCode 为 `1`，Windows runner 系统文件版本来自固定包基线。不得用 `--build-name` / `--build-number` 同步补丁，不做 `flutter clean`；改 Dart 常量仍正常重编 Dart AOT。上传名保留「原 stem-完整发行版本.扩展名」（如 `app-release-1.1.0.apk`），本地输出名不变。本次只迁移版本来源，不上传、不修改 `data/` 线上版本或下载配置。 Flutter 要求三段合法 SemVer，跨系列使用 x.y.0+1；这是固定包基线，并非跟随补丁发行版本同步。
- 应用内更新与用户协议：客户端所有请求带 `seven-double-flutter/<版本> (<平台>)` 的 UA；`/api/online` 只回「有没有更新」，有更新时客户端再请求 `/api/health` 取详情。`data/agreement.md` 是首次连接服务器展示的用户协议（Markdown），`data/releases/` 是可选的自托管更新包目录（`GET /releases/{文件名}`）。`Updater.exe` 是**独立发布产物**（Windows 安装程序）：`package-release.cmd` 一次上传 `魔法裁判Windows.zip`、`app-release.apk` 与它三个对象，并刷新 `data/downloads.json`（安装程序 / 便携版 / 安卓版三条链接，改名前的老名字会被替换）与 `data/updates.json`（两条兜底区间的 latest/url/size/sha256 与 Windows 的 updater_url；手工写的 title/notes/minimum/guide_url 与更窄区间条目保留，逻辑在 `tools/update_manifest.py`）。
- **发新版必须写更新日志**（`data/updates.json` 的 title/notes，两平台各一份）：用 `git log -p -- client/lib/src/client_version.dart` 找上一条**真正改 `kClientVersion` 数值**的提交，从其之后逐个看涉及 `client/`（含 Windows 更新器）的 diff，归纳成用户能读懂的条目，按「新功能 → 修复 → 其它」分组写 markdown；`pubspec.yaml` 的依赖调整不是发版提交，纯后端/文档/发布脚本的改动不进客户端日志。写完把 title 里的版本号改成新版本，Windows 与 Android 的 notes 可按平台差异各写各的。普通后续发版只 stage Dart 版本文件；若该文件有其它改动，只选版本行。跨 `x.y` 系列才另外选中 pubspec 的版本行，不带入其它用户修改。
- Windows 更新器安装向导（无参数运行）给两个选择：**安装**——创建开始菜单组「魔法裁判」（程序入口 + 「卸载魔法裁判」，后者即带 `--uninstall` 的更新器，必建）与桌面快捷方式（默认创建，向导里可取消或用 `--no-desktop-shortcut` 关掉），写注册表与「应用和功能」卸载项，并准备静默更新；**仅下载便携版**（`--install --portable`）——只把整包解压到指定目录，不写注册表、不建快捷方式、不装证书与计划任务。检测到已有安装时同样多一个「下载便携版」选项；`--uninstall` 一并删掉开始菜单与桌面快捷方式。更新器版本号由 CMake 从 `client/lib/src/client_version.dart` 的 `kClientVersion` 注入（`UPDATER_VERSION_STRING`），并将该文件登记到 `CMAKE_CONFIGURE_DEPENDS`，版本宏保持 source scoped，不需手改。
- 客户端回归检查各自独立文件，不要混进别的检查脚本：`checks/test_client_release.py`（后端版本下发/入局门槛/协议/更新包分发）、`client/test/client_update_test.dart`、`client/test/agreement_gate_test.dart`、`client/test/endpoint_default_test.dart`、`checks/test_updater_cli.py`（Windows 更新器命令行，缺 exe 时跳过）。设计阶段不要跑后端全量测试。
- 有意义的行为修改必须实际启动并验证相关服务或浏览器路径；新增回归检查只保护真实规则、权限或数据丢失边界。
- 更新现有 TXT 运行说明；改动最小，不为假设需求搭框架。并发代理改不同文件，统一在集成结束后格式化、构建、跑检查。

## 守护进程（后端 + 登录网关）
- `supervisor.py`（`run-supervisor.cmd` 启动）托管两个子进程：后端 `run.py` 与登录网关 `python -m gateway.gateway`；它代替 `start.cmd` 与 `run-gateway.cmd`，不要两边同时启动（会抢端口）。默认自动拉起两者；子进程意外退出按 2s→60s 退避重启；退出守护进程会一并停掉子进程。输出追加在 `logs/backend.log`、`logs/gateway.log`（`logs/` 已 gitignore）。
- 默认只监听 `127.0.0.1:13900`（`GAME_SUPERVISOR_HOST` / `GAME_SUPERVISOR_PORT` 可改）。`GET /status` 给出两进程的 pid、存活时长、重启次数、日志路径与后端 `/api/health` 是否可达；重启走 POST（设了令牌带 `-H "X-Supervisor-Token: <令牌>"`）：
  - `POST /restart/{backend|gateway|all}`：`all` 先全停再拉起（先后端后网关，避免网关空转重连）。
  - `POST /start|stop/{backend|gateway|all}` 是同一套生命周期；进程名不在白名单返回 404，起不来返回 500 且 body 带退出码与日志末尾，`/status` 里该进程为 `stopped`。
- 后端端口默认 8000，用 `--backend-port` 或 `GAME_SUPERVISOR_BACKEND_PORT` 覆盖；显式改端口时守护进程把网关子进程的 `GAME_BACKEND_URL` 一起改过去。网关环境变量默认读 `gateway/.env`，换端口或测试用 `--gateway-env` 指向别的文件；后端环境变量（`GAME_ADMIN_QQ`、`GAME_GATEWAY_TOKEN`、`GAME_DATA_DIR` 等）由守护进程原样继承，部署时照 `start.cmd.local.cmd` 写一份不入库的 `run-supervisor.cmd.local.cmd`（需在 `.gitignore` 显式列出，`*.cmd.local` 匹配不到 `*.cmd.local.cmd`）设好再启动。
- 绑定非回环地址必须先设 `GAME_SUPERVISOR_TOKEN`，否则拒绝启动；设了令牌后除 `GET /health` 外都要带 `X-Supervisor-Token`。带 `Origin` 的浏览器请求一律 403（该接口只给本机脚本用）。端口被占用直接报错退出，不会静默双开。

## 版本管理
- 本地 Git 管理可回退版本；改动前保留基线，验证完成后提交功能变更，自动推送远端。
- 不提交 `data/`、`.venv/`、`node_modules/`、构建产物、缓存、会话、私密材料或临时联调脚本。
- 不要删除用户现有修改，每次改完删除所有验证数据。
