# 魔法裁判 · 七双

七人双角色在线桌游。七名玩家各持两张角色牌，在一名固定真人主持人的带领下进行魔女化、夜间行动、公开讨论、提名与处决。

## 特点

- 七人双角色：发牌后玩家私下决定上下牌顺序，上层出局后启用下层。
- 真人主持人：开局、阶段推进、概率与未写明情况均由主持人裁定；系统知情的阶段无人待办时 5 秒后自动推进，主持人可随时暂停或手动推进。
- QQ 账号登录：玩家在指定 QQ 群发送“活动登录 123456”完成验证，登录令牌长期有效；账号与对局参与身份分离。
- 开放参局：主持人“开放加入”后，已登录账号自行选择加入或观战，无需审核；发牌前随机占用空席，同一账号不能重复分席。
- 公屏与私信分离：公屏、私信、系统信息各自独立列表与已读游标；私信有邀请、同意、拒绝、结束的完整生命周期；天黑进入夜间时自动结束全部私信，夜间只允许与主持人建立私聊。
- 服务端裁剪：角色牌、魔女化状态、私信锁定等全部在服务端判定，前端隐藏不作为授权。
- 主持人分级与授权：管理员由 `GAME_ADMIN_QQ` 指定（5 级/系统管理员），4 级可授权 1-3 级、5 级可授权 1-5 级主持；1 级只主持 1 局，那一局结束授权即失效。授权与 QQ 账号绑定，没有共享密码；登录令牌每次请求都重新核对等级。
- 公告（原生客户端）：5 级主持用 markdown 发布全服公告，大厅显示列表与未读数；已读按公告内容 sha256 记在本机，公告改动会重新算未读。公告存在独立库 `data/announcements.sqlite3`，跨局保留。
- 成就（原生客户端）：主持人在大厅自定义成就（名称、内容、稀有度 1-10）并授权给玩家；玩家挑一个佩戴，对局内发言时昵称右边显示该成就，点头像可看总成就数与最稀有的 5 个。成就存在独立库 `data/achievements.sqlite3`，跨局保留；3 级起才能管理，稀有度上限随等级。
- 历史对局（原生客户端）：一局结束（或没结束就被清空）后自动留档到独立库 `data/history.sqlite3`，跨局保留；大厅「历史对局」可看胜负、主持人、七个席位的两张角色牌与公开时间线。只归档公开记录——私信与只发给个人的情报不入库。4 级及以上主持人可删除单条历史对局（连同参与身份与公开时间线，删除后不可恢复）。
- 技能播报（原生客户端）：白天技能声明渲染成「[角色头像] N号 昵称 · 使用技能 X」，点击可查看技能说明；目标与伪装标记由服务端按可见范围裁剪（私密目标只有声明者与主持人看得到，伪装标记只有主持人看得到）。
- 对局内悬浮对话框（原生客户端）：结束信息、私聊申请的同意/拒绝、当日目击名单由服务端下发到悬浮卡上；同意/拒绝复用统一的行动表单，仍然只有一次确认并过服务端的行动白名单校验。
- 多端：游戏对局走 Flutter 原生 Android / Windows 客户端；网页首页只提供公告、游戏规则介绍与游戏下载链接。

## 环境要求

- Python 3.14+
- Node.js >= 22.12（仅构建网页首页）
- Flutter 3.35+（仅构建原生客户端时需要）
- NapCat（QQ 网关，仅 QQ 登录时需要）

## 安装与启动

```cmd
setup.cmd
start.cmd
```

然后打开 <http://localhost:8000>：这是公告、游戏规则介绍与游戏下载链接的网页首页；游戏对局在 Flutter 原生客户端进行。默认绑定 `0.0.0.0`，局域网内可直接访问；`start.cmd` 的参数会透传给 `run.py`（如 `start.cmd --port 9000`）。

### 网页首页

无框架静态单页，构建后由后端同源提供。三个栏目：

- **公告**：读取 `GET /api/announcements/public`（公开只读，无需登录），内容来自 5 级主持发布的全服公告。
- **游戏规则**：内容写在 `frontend/rules.md`，构建时由 `frontend/build.mjs` 解析并注入页面。
- **下载游戏**：读取 `GET /api/downloads`，配置文件是 `data/downloads.json`（不入库，改完即生效）：

```json
{
  "downloads": [
    { "name": "Windows 版", "url": "https://s3.tkcloud.online/releases/魔法裁判Windows.zip" },
    { "name": "安卓版", "url": "https://s3.tkcloud.online/releases/app-release.apk" }
  ]
}
```

安装包放在 S3 兼容存储（Cloudflare R2）的 `releases/` 子目录，对外由 `https://s3.tkcloud.online` 公开访问。这两条链接由 `package-release.cmd` 在每次发布成功后自动重写（文件里的其它条目原样保留），所以正常发版不用手工改这里，见「发布发行版」。文件不存在时页面显示「下载链接准备中，敬请期待」。

主持人登录与玩家一样走 QQ 群登录码，**必须在服务端配置管理员 QQ 号**：在 `start.cmd.local.cmd` 里设置 `GAME_ADMIN_QQ=你的QQ号`（多个用英文逗号分隔），否则没有任何账号能进入主持人端。其余主持等级由 4/5 级主持在「主持授权」页授权，授权与 QQ 账号绑定。

## QQ 网关（NapCat）

QQ 登录依赖 NapCat 的 OneBot WebSocket 实现，网关把群消息里的六位登录码绑定到账号：

成功回一句「某某，登录成功~」；失败也在同一个群里回原因（如「某某，登录失败：登录码无效、过期或已经使用」），
后端连不上时回「服务端暂时不可用」，「活动登录」后跟的不是 6 位数字则回格式提示。回复始终发回玩家发言的群；
其他群消息不回应。看网关日志时 `login code ... rejected` 就是被拒的那一次。

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
> 如果改用 `start.cmd` 启动，需自行设置环境变量 `GAME_GATEWAY_TOKEN` 与 `GAME_QQ_GROUP_ID`；
> 后端的 `GAME_QQ_GROUP_ID` 须是网关群号列表的超集（英文逗号分隔），网关提交名单时用列表首个群号做来源校验。

`gateway/.env` 必填项：

| 变量 | 说明 |
| --- | --- |
| `NAPCAT_WS_URL` | NapCat 的 OneBot WebSocket 地址，默认 `ws://127.0.0.1:3001` |
| `NAPCAT_TOKEN` | NapCat 访问令牌，无则留空 |
| `GAME_BACKEND_URL` | 后端地址，默认 `http://127.0.0.1:8000` |
| `GAME_GATEWAY_TOKEN` | 网关与后端共享的密钥，须与后端环境变量一致 |
| `GAME_QQ_GROUP_ID` | 允许登录的 QQ 群号；多个群用英文逗号分隔，网关会同时监听并合并群成员 |

`gateway/.env`、`gateway/napcat/`、`gateway/*.log` 已在 `.gitignore` 中：NapCat 登录态、设备文件、访问令牌和网关共享密钥不得入库，也不得写入 Flutter 资源或网页构建产物。

网关把 `X-Gateway-Token` 放在请求头调用 `/api/internal/qq/login`，后端用 `secrets.compare_digest` 校验；挑战码一次性消费，过期或重放一律拒绝。

### 登录挑战的 PoW 防护

`POST /api/native/auth/challenges`、`POST /api/native/auth/host/challenges`（及 web 变体）是仅有的未认证写入口：脚本可以无限刷挑战、灌 `login_challenges` 表。可选的工作量证明（PoW）用来提高刷接口的单价，默认关闭，设置环境变量开启：

| 变量 | 说明 |
| --- | --- |
| `GAME_POW_DIFFICULTY` | 谜题难度：sha256 十六进制前缀的 `0` 个数，**每 +1 计算量 ×16（不是 ×2）**。建议 4（实测平均约 3.3 万次哈希：桌面亚秒级、手机 1-3 秒）；未设置或 `0` 时防护关闭，接口行为与旧版完全一致。上限 8 由代码钳制，防误配把所有人锁在门外 |
| `GAME_POW_SECRET` | 谜题令牌的 HMAC 签名密钥；缺省从 `GAME_GATEWAY_TOKEN` 派生，两者一致即可不配 |

流程：客户端先 `POST /api/pow/challenges` 领题（关闭时返回 `required=false` 直接跳过），本地枚举 nonce 求解后把 `{token, nonce}` 随挑战创建提交；服务端只做一次哈希与签名校验，不建任何表。令牌 5 分钟有效、一次性由签名与时间戳保证（服务端无状态，靠 5 分钟窗口内的重放代价换实现简单）。开启后不带证明的旧客户端拿到 428「请先更新客户端」，正好接上客户端的最低版本强更提示。检查：`.venv/Scripts/python.exe -m unittest checks.test_pow -v`。

## 数据与备份

`data/` 目录（可用 `GAME_DATA_DIR` 覆盖）下有几个 SQLite 文件，备份边界不同：

| 文件 | 内容 | 清空对局时 |
| --- | --- | --- |
| `seven-double.sqlite3` | 对局状态、参与身份、频道、消息、证物图片 | 全部删除 |
| `auth.sqlite3` | QQ 账号、登录挑战、登录令牌（只存 SHA-256 后的令牌） | 保留 |
| `announcements.sqlite3` | 全服公告（markdown 正文） | 保留 |
| `achievements.sqlite3` | 成就定义、授权与佩戴 | 保留 |
| `history.sqlite3` | 历史对局的公开记录（胜负、七个席位的角色牌、公屏与全场公告时间线） | 保留 |

“一键初始化”和“开启下一局”只清空对局库：QQ 账号、玩家登录令牌和主持人登录都不会失效；公告、成就与历史对局也一并保留。踢人或本局拉黑只让对应参与身份失效，不影响账号在其他对局登录。

## Flutter 原生客户端

```cmd
cd client
flutter pub get
flutter analyze
flutter test
flutter build apk --debug
flutter build windows --debug
```

客户端启动后先填写服务根地址（默认已填好 `https://super.tkcloud.online:447`，可以自行修改）：局域网可用 HTTP，公网地址必须 HTTPS。首次连接某个服务地址时会展示该服务端下发的用户协议（Markdown），由用户选择「同意并继续」或「取消连接」；同意记录按「服务地址 + 协议内容哈希」存在本机，协议改过会重新询问。玩家端与主持人端按登录身份自动切换界面；Android 提供触觉反馈，Windows 静默。Windows 主持人端同时只允许一个实例：重复启动会把已有窗口唤到前台并直接退出，不会开出第二个窗口。

所有请求都带 `seven-double-flutter/<版本> (<平台>)` 形式的 UA，后端据此下发更新信息、并只对「过旧客户端加入对局」设限（详见下文「客户端更新」）。

### 应用图标

各端 app 图标统一取自 `img/月代雪.png`（透明背景的圆形胸像）。改动源图后重新生成：

```cmd
.venv\Scripts\python.exe tools\gen_app_icons.py
```

脚本会写入 Windows 的 `app_icon.ico`、Android 传统 mipmap 与自适应图标前景/底色、以及网页 `favicon.ico` / `favicon.png` / `apple-touch-icon.png`（需要 Pillow）。图标保留圆形、四周透明；自适应图标前景按 Android 安全区缩放并配主题底色 `#191721`。

### 表情资源

客户端聊天与顺序发言的表情面板使用 QFace 的静态 QQ 表情（经典 275 张 + 超级 50 张）。改动来源后重新生成：

```cmd
.venv\Scripts\python.exe tools\gen_emoji.py [QFace 仓库路径]
```

脚本读取 QFace 的 `lib/data.json`、`qq_emoji/face_config.json` 与 `public/static/s<id>.png`，写入 `client/assets/emoji/qq/<id>.png` 与 `client/lib/src/emoji.dart`（表情总表、`[/名字]` token 切分、输入框控制器）。只取静态图，不含动画。

表情在文本里就是 `[/微笑]` 这样的纯文本 token，输入框与消息气泡再把它画成内联图片。因此草稿、2000 字上限、服务端校验与实时推送都不用改动；网页端不渲染 token，但仍能读懂原文。

### 发布发行版

Windows 与安卓发行产物打包上传到 S3 兼容存储（Cloudflare R2），不再走局域网共享目录。配置写在仓库根目录的 `package-release.env`（dotenv 写法，含密钥，已在 `.gitignore` 中）：

| 变量 | 说明 |
| --- | --- |
| `S3_ENDPOINT` | S3 端点，只写到域名，如 `https://<账户ID>.r2.cloudflarestorage.com` |
| `S3_REGION` | R2 固定填 `auto`，自建 MinIO 按服务端配置填 |
| `S3_ACCESS_KEY_ID` / `S3_SECRET_ACCESS_KEY` | 访问密钥 |
| `S3_BUCKET` | 桶名 |
| `S3_PREFIX` | 子目录（对象键前缀），默认 `releases` |
| `S3_PUBLIC_BASE` | 对外访问地址，默认 `https://s3.tkcloud.online` |
| `S3_TIMEOUT` | 可选，单次请求超时秒数，默认 300 |

编译好客户端后执行：

```cmd
package-release.cmd
```

脚本把 `client/build/windows/x64/runner/Release` 打成 `魔法裁判Windows.zip`，与 `client/build/app/outputs/flutter-apk/app-release.apk`、以及**独立发布产物** `Updater.exe`（Windows 安装程序）一起上传到 `<S3_PREFIX>/` 子目录，再回读远端对象核对大小，最后写两处后端下发的配置：

- `data/downloads.json`：网页首页「下载游戏」的三条链接——**Windows 安装程序**（`Updater.exe`）、Windows 便携版（zip）、安卓版；
- `data/updates.json`：客户端应用内更新的「平台 + 版本区间」清单，刷新两个平台兜底区间的 latest/url/size/sha256 与 Windows 的 `updater_url`（手工写的更新日志 `notes`、`minimum`、`guide_url` 与更窄的区间条目都保留）。

**对象键一律带版本号**（`releases/app-release-1.0.11.apk`、`releases/Updater-1.0.11.exe`）：实测 `s3.tkcloud.online` 会把同名对象缓存在边缘（GET 命中缓存、HEAD 不命中，且缓存键忽略 query），复用同一个键会让客户端与更新器下到上一版的旧包——发布后校验因此**用真实 GET 回读对外地址**比对总长度，对不上直接判失败。注意该校验必须显式带 UA：该域名会把 `Python-urllib/*` 直接 403。

可加 `--dry-run` 只打包并打印计划（不联网、不改配置）、`--skip-zip` 复用已有压缩包、`--skip-upload` 复用已上传的对象只做校验与配置刷新、`--no-downloads` / `--no-updates` 分别跳过两处配置刷新、`--no-updater` 不上传安装程序、`--env <路径>` 换配置文件。

上传用 AWS Signature V4，只用 Python 标准库（`hmac`/`hashlib`/`urllib`），不新增依赖；同名的进程环境变量优先于 `package-release.env`。密钥需要该桶的写权限，`S3_PUBLIC_BASE` 对应的域名需要能匿名读取（R2 自定义域或公开桶）；配置缺项或仍是 `*` 占位符时脚本直接报错退出，不会上传半截。

想单独查看当前的更新清单（排查「为什么没提示更新」）：

```cmd
.venv\Scripts\python.exe tools\update_manifest.py --show
```

发行签名：

- 安卓：正式密钥在 `client/android/keystore/magicjudge-release.jks`，口令在 `client/android/key.properties`（两者都已被 `client/android/.gitignore` 忽略，不入库）。`flutter build apk --release` 会自动用它签名；文件缺失时退回 debug 签名并打印警告，只能用于本地调试。**第一次换成正式签名后，存量 debug 签名的安装无法原地覆盖，需要用户卸载后重装一次。**
- Windows：`tools/sign-windows.ps1` 生成自签名代码签名证书、导出公钥并给 `seven_double_client.exe` 与 `Updater.exe` 签名；Updater 在「准备更新环境」时把这张证书装进 `LocalMachine\Root` 与 `LocalMachine\TrustedPublisher`，这样后续静默更新不会被系统质疑来源。**顺序有要求**（证书要先写进头文件再编译，编出来的 Updater 才是内嵌证书的版本）：

  ```cmd
  pwsh -File tools\sign-windows.ps1                    :: 生成/复用证书 + 写 self_signed_cert.local.h
  cd client && flutter build windows --release
  cd .. && pwsh -File tools\sign-windows.ps1 -Trust    :: 签名；-Trust 顺便装进信任库（需管理员）
  ```

  私钥导出在仓库外的 `%LOCALAPPDATA%\MagicJudge\dev-certs\`，绝不入库；`self_signed_cert.local.h` 也被 gitignore，入库的 `self_signed_cert.h` 永远是空证书占位（干净克隆直接能编译，但那种构建的 Updater 会在 `--prepare` 时提示「证书为空」并跳过证书安装）。收尾用 `pwsh -File tools\sign-windows.ps1 -RestorePlaceholder`（只还原头文件）或 `-Uninstall`（连证书与私钥一起清掉）。

## 客户端更新

应用内更新的信息全部由后端下发，客户端只按 UA 里的版本号取用。部署者维护三样东西（都在 `data/` 下，改完即生效、无需重启）：

| 路径 | 作用 |
| --- | --- |
| `data/updates.json` | 按「平台 + 版本区间」下发不同的更新信息（见下） |
| `data/agreement.md` | 用户协议正文（Markdown）；不存在时客户端跳过协议门 |
| `data/releases/` | 更新包本体，由 `GET /releases/{文件名}` 同源下发（用对象存储时不需要） |

`data/updates.json` 的格式（区间取**第一条匹配**，所以窄区间写在前面、兜底区间写在最后）：

```json
{
  "updates": [
    {
      "platform": "windows",
      "min_version": "1.0.0",
      "max_version": "1.2.0",
      "latest": "1.1.0",
      "minimum": "1.1.0",
      "title": "必须更新",
      "notes": "## 更新日志\n\n- 应用内静默更新",
      "url": "https://s3.tkcloud.online/releases/魔法裁判Windows.zip",
      "updater_url": "https://s3.tkcloud.online/releases/Updater.exe",
      "size": 12345678,
      "sha256": "…",
      "guide_url": "https://example.com/help"
    },
    {"platform": "android", "latest": "1.1.0", "notes": "…", "url": "https://…/app-release.apk"}
  ]
}
```

- 匹配规则：`min_version <= 客户端版本 < max_version`（缺省边界表示不限），`platform` 可以是 `windows` / `android` / `any`；没有匹配时退回环境变量 `GAME_CLIENT_LATEST` / `GAME_CLIENT_MINIMUM`。
- 客户端低于该区间的 `minimum` 时判为强制更新：`POST /api/games/{id}/participations`（以玩家身份入局）与接受邀请会被拒（426），**其它功能一律不受限**。UA 缺失或不认识（浏览器、模拟器、检查脚本）时不做任何拦截。
- `notes` 是 Markdown，客户端在更新弹窗里渲染；`guide_url` 非空时多一个「打开网页」按钮；`url` 留空时只引导网页。
- `size` / `sha256` / `updater_url` 由 `package-release.cmd`（`tools/package-release.py` + `tools/update_manifest.py`）自动刷新（只更新该平台「没有区间边界」的那条兜底区间，手工写的 `title` / `notes` / `minimum` / `guide_url` 与更窄的区间条目都保留）。

Windows 客户端的更新流程：客户端下载最新 `Updater.exe` 到 `%LOCALAPPDATA%\MagicJudge\`，由它「准备更新环境」（首次用一次管理员权限把自签名证书加进系统信任库并创建计划任务 `MagicJudgeUpdater`）→ 之后每次更新都用该计划任务以最高权限静默替换程序 → 自动重启客户端，全程无需 UAC。

`Updater.exe` 是**独立发布产物**（网页首页的「Windows 安装程序」，也是首次安装入口）。它的向导给两个选择：

- **安装**（推荐）：填服务器地址与目录即下载安装，并创建快捷方式——**开始菜单**组一定创建，里面是「魔法裁判」与「卸载魔法裁判」（后者就是带 `--uninstall` 参数的更新器）；**桌面**快捷方式默认也建，可以在向导里取消勾选（命令行用 `--no-desktop-shortcut`）。同时写入注册表安装信息（含「应用和功能」里的卸载入口）并准备好应用内静默更新。
- **仅下载便携版**：只把整包解压到指定目录，不写注册表、不建快捷方式、也不装更新组件；换机器直接拷走整个文件夹即可。命令行是 `--install --portable`。

检测到已经装过时可以先选「更新到最新」「下载便携版」「卸载」或「退出」。`--uninstall` 是卸载引导，会一并删掉开始菜单与桌面的快捷方式、注册表键与计划任务，但不会删除 `Updater.exe` 自己。所有功能都有对应命令行参数（`--install --from <地址> [--dir <目录>] [--silent] [--portable] [--to-program-files] [--no-desktop-shortcut]`、`--update-app`、`--prepare`、`--task-entry`、`--uninstall`、`--check-install`），参数足够时零交互。

安卓客户端的更新流程：下载 APK 到应用缓存目录（同版本只下一次）→ 经 FileProvider 交给系统安装器 → 安装完成或失败后清理残留安装包。

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
.venv\Scripts\python.exe -m ruff check backend checks run.py gateway run-simulator.py supervisor.py
cd frontend && npm.cmd run build
```

运行检查时请把 `GAME_DATA_DIR` 指向独立临时目录，避免影响 `data/` 中的真实对局。

## 目录结构

```
backend/app/    FastAPI 服务、SQLite 存储、账号令牌、实时推送
backend/app/game/  规则、结算与可见性裁剪
backend/app/simulator/  虚拟玩家模拟器（真实协议驱动整局）
frontend/       公告、规则与下载的静态网页首页（无框架）
client/         Flutter Android / Windows 原生客户端
gateway/        NapCat OneBot QQ 登录网关
checks/         后端回归检查
tools/          应用图标、表情资源与发行打包上传脚本
docs/          游戏规则与设计方案
img/           角色头像
```

## 许可

本项目以 [AGPL-3.0](LICENSE) 授权，完整条文见根目录的 `LICENSE`。

依 AGPL-3.0 第 13 条，通过网络使用本服务的人有权获得对应版本的完整源码：<https://github.com/liuziheng20091106/ievil-JIO-sent-ky>。修改本程序后作为网络服务对外提供，也必须以同一协议公开源码并保留原有的版权与许可声明。

服务端下发给客户端的用户协议与免责声明正文在 `docs/免责声明与用户协议.md`（官网「免责声明」小节读的是同一份内容）：部署时把它复制成 `data/agreement.md`，客户端首次连接该服务器时会展示并要求同意，协议改动后重新询问。

游戏角色立绘、QQ 表情等素材版权归各自权利人所有，本项目仅将其用于非商业的学习与交流；权利人如有异议会立即移除（见免责声明第六节）。
