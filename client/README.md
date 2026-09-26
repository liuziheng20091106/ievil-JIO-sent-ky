# 七人双角色 · Flutter 原生客户端

Android 玩家端与 Windows 主持人端。后端（FastAPI）仍是规则、权限与可见性的唯一权威，客户端只解码服务端裁剪后的结果。

## 构建与检查

```cmd
flutter pub get
flutter analyze
flutter test
flutter build apk --debug
flutter build windows --debug
```

发行构建：`flutter build apk --release --target-platform android-arm64` 与 `flutter build windows --release`，随后运行仓库根目录的 `package-release.cmd` 打包 `魔法裁判Windows.zip` 并把 zip 与 `app-release.apk` 覆盖发布到局域网分发目录。

安卓后台保活：应用启动后拉起前台服务（`KeepAliveService`，常驻低优先级通知 + PARTIAL 唤醒锁）维持 WebSocket 心跳；首次连接服务器后若未加入「忽略电池优化」白名单，大厅顶部横幅可一键跳转授权，也可以点「忽略」不再提示（记在 `shared_preferences`）。

版本检查与应用内更新：所有请求都带 `seven-double-flutter/<版本> (<平台>)` 的 UA（`lib/src/client_version.dart`，发版时与 `pubspec.yaml` 的版本名同步手改）。连接服务器后读 `/api/health` 下发的 `client_latest` / `client_minimum` 与 `update` 详情；大厅每 5 秒轮询 `/api/online`，它回一句「有没有更新」，说有更新时客户端再请求一次 `/api/health` 取版本字段与更新日志（同一服务地址、同一 latest 标签 10 分钟内只查一次）。低于 latest 提示可更新、低于 minimum 强制更新（强制更新时不提供「稍后」，且服务端会拒绝以玩家身份入局，其它功能不受限）。

更新弹窗渲染服务端下发的 Markdown 更新日志，`guide_url` 非空时多一个「打开网页」按钮（打不开就把链接复制到剪切板）。「更新」按钮在更新完成或用户主动关掉弹窗前始终可见——大厅里另有一个常驻的「立即更新」入口，关掉横幅或弹窗都不会让它消失。横幅可以点「知道了」关掉，记的是被关掉的 latest 标签，服务端下发更新的版本才会重新提示。

- **Android**：下载 APK 到应用缓存目录（同一版本只下一次）→ 经 FileProvider 交给系统安装器（`REQUEST_INSTALL_PACKAGES` 权限；未授权时引导到「安装未知应用」页）→ 安装完成或失败后清理残留安装包。
- **Windows**：下载最新 `Updater.exe` 到 `%LOCALAPPDATA%\MagicJudge\` → 由它准备更新环境（首次用一次管理员权限把自签名证书装进系统信任库并创建计划任务 `MagicJudgeUpdater`）→ 计划任务以最高权限静默替换程序 → 自动重启客户端。之后每次更新都不再需要 UAC。首次安装用同一个 `Updater.exe`：向导给「安装」（创建开始菜单组，含「卸载魔法裁判」入口；桌面快捷方式默认创建、可取消，或用 `--no-desktop-shortcut` 关掉）与「仅下载便携版」（`--install --portable`，只解压不写注册表、不建快捷方式）两个选择，卸载会一并清掉这些快捷方式。

首次连接某个服务地址时会展示服务端下发的用户协议（`/api/agreement`，Markdown），用户可选「同意并继续」或「取消连接」；同意记录按「服务地址 + 协议内容哈希」存在本机，协议改过会重新询问，服务端没配协议则直接进入登录页。协议正文的仓库副本见 `docs/免责声明与用户协议.md`（部署时复制成服务端的 `data/agreement.md`）。

服务地址默认预填 `https://super.tkcloud.online:447`，可以随意修改（不自动连接）。

安装包用正式密钥签名：安卓见 `client/android/key.properties`（不入库），Windows 见 `tools/sign-windows.ps1`。

Windows 构建需要 Visual Studio 的 C++ 桌面工作负载，以及 `flutter_secure_storage` 依赖的 ATL 组件（`Microsoft.VisualStudio.Component.VC.ATL`）。

## 使用

首次启动填写服务根地址：loopback、localhost 和私有网段可用 HTTP，其他主机必须 HTTPS。玩家在指定 QQ 群发送“活动登录 123456”完成验证，登录页的「一键复制」把这一整句（含前缀与空格）直接放进剪切板，粘贴发送即可；主持人用**同一个群登录码**在主持人页登录——主持授权与 QQ 账号绑定，没有密码入口，没被授权的账号会在核销后被服务端拒绝。

登录令牌保存在 `flutter_secure_storage`，启动时用 `/api/me` 核对，只有 401 才清除。服务地址与其他偏好保存在 `shared_preferences`。

Windows 主持人端禁止重复实例：同一登录会话里重复启动不会开出第二个窗口，而是把已在运行的窗口唤到前台后立刻退出（`client/windows/runner/single_instance.h` 的命名互斥体；互斥体随进程结束由系统释放，崩溃后也能重新启动）。不同 Windows 用户各自可以运行一个实例。

对局被主持人终止（或分出胜负）后，客户端停留在只读结局页：标题栏与结算卡各有一个「返回大厅」入口，点它回到主界面（大厅）后，主持人可确认魔典建立下一局，其他身份等待新局。返回后重启客户端不会被重新拉回已终止的那一局——服务器仍把这一局当作当前局返回给 `/api/me`，是否已经离开由客户端本地判断；需要回看记录请在返回大厅前查看。

屏幕宽度足够时同屏显示多个界面，不再用底栏把页面藏起来：平板横屏（宽 ≥840）左侧固定「状态」牌桌、右侧「对局」，双牌/管理收进右上角抽屉（入口保留该页待办角标）；电脑宽屏（宽 ≥1200）「状态 / 对局 / 我的·管理」三栏并排。手机与平板竖屏保持底部导航一次一页，角标与「已查看」语义不变：同屏可见的页面直接算已查看，窄屏仍由底栏选择触发。

软键盘弹出时对局页进入聚焦输入：标题栏、连接状态、消息筛选、阶段进度、主持人快捷工具、傀儡面板与悬浮底栏全部隐藏，只留消息列表和输入区（发送频道、发送按钮、输入框与紧凑的行动入口），收起键盘立即恢复。宽屏多栏布局不受影响。

在线玩家与对局邀请：大厅与对局内的「状态」页都列出最近一分钟内有活动的已登录账号（不含 QQ 号与令牌）。非观战身份可从「状态」页邀请在线账号加入本局；邀请只是定向通知，受邀者仍须等主持人「开放加入」后才能接受并入席，可随时拒绝。同一局同一账号只保留一条待处理邀请，10 分钟未响应即失效。大厅定时刷新同时充当自己的在线心跳与邀请收件箱，对局内则由 WebSocket 心跳维持在线。

成就：主持人在大厅的「成就管理」里自定义成就（名称、内容、稀有度 1-10，数字越大越稀有、颜色越醒目），并在「玩家授权」里按总玩家列表（最近参赛顺序在前）授权或撤销；玩家在「我的成就」里查看自己获得的成就并挑一个佩戴。对局内玩家发言时昵称右边显示其佩戴的成就（底色即稀有度颜色），点击玩家头像还会在快捷菜单下方展开该玩家的总成就数与最稀有的 5 个（名称 + 内容）。成就保存在后端的独立库 `data/achievements.sqlite3`，跨局保留，「一键初始化」与「建立下一局」都不会清空它。**3 级及以上**的主持才能进这一页，稀有度上限按等级：3 级 ≤3、4 级 ≤4、5 级全部。

主持分级：1 级只主持 1 局（那一局结束或对局被清空后授权立即失效，旧令牌同时失效）；2 级永久组织权；3 级加 1-3 级成就；4 级加 4 级成就、能授权 1-3 级主持并删除历史对局；5 级是系统管理员（公告、全等级成就、授权 1-5 级主持）。内置管理员由服务端 `GAME_ADMIN_QQ` 指定，恒为 5 级，界面上不能改也不能取消。大厅按等级显示入口：成就管理（≥3 级）、主持授权（≥4 级）、公告管理（5 级）；授权页会显示 QQ 号以便区分同名账号。历史对局列表与单局详情里，≥4 级主持人多一个删除入口（确认后整局留档连同参与身份与公开时间线一起删掉，不可恢复）；成就卡右端的「佩戴 / 已佩戴 / 未获得」标识在手机与宽屏下都右对齐成同一列。

公告：5 级主持在大厅的「公告管理」里用 markdown 发布（带实时预览），大厅卡片显示最新几条与未读数、点开看渲染后的正文。已读状态按每条公告的 sha256 存在本机 `shared_preferences`（只存哈希），公告内容改过会重新算未读；公告数据由大厅每 5 秒的轮询顺带带回，不额外开轮询。公告存在后端的独立库 `data/announcements.sqlite3`，跨局保留。markdown 用 `flutter_markdown_plus` 渲染。

界面跟随系统深色模式：浅色与深色共用同一套语义色板（`lib/src/design.dart` 的 `AppPalette`），组件通过 `context.palette` 取色；系统切换深浅色时整套界面（卡片、文字、输入框、底栏、对话框）一起变化。

预测性返回（Android 14+ 边滑时跟手预览）：清单里已开 `enableOnBackInvokedCallback`，且 Flutter 只有在「栈里有可 pop 的路由」时才会向系统注册返回回调——所以对局外壳本身（它是根路由）滑返回等于退出应用，系统只会给静态动画，这是预期行为。有预览的是两类界面：① 从大厅推入的页面（成就、我的成就、主持授权、公告、公告管理、更换服务器），由 Flutter 自带的过渡器处理；② 模态底部面板（行动面板、行动表单、选人/选行动/选魔典/选成就等选择器），由 `lib/src/predictive_sheet.dart` 接返回手势并直接驱动面板自己的动画控制器。`showDialog` 的对话框不在覆盖范围。

表情面板打开时返回键先收面板：聊天输入区与行动表单里的表情面板（`lib/src/emoji_picker.dart` 的 `EmojiPanelScope`）在展开期间挡住返回，一次返回只收起面板，面板收掉后返回恢复原样（对局外壳上仍然是退出应用）。预测性返回同样让路——面板开着时 `predictive_sheet.dart` 不接管手势，否则整个行动表单会连同已填内容一起被收走。

## 结构

```
lib/main.dart              应用入口、服务地址页、登录页、大厅
lib/src/api.dart           HttpClient / WebSocket 传输层与断线退避
lib/src/client_version.dart 内置版本号、UA 与默认服务地址
lib/src/models.dart        协议 DTO、服务地址校验、ui_version 检查、用户协议
lib/src/store.dart         账号、参与身份、视图、频道消息、草稿与角标
lib/src/shell.dart         玩家/主持人壳、宽屏多栏与悬浮底栏、双头像、阶段动画
lib/src/action_sheet.dart  行动表单、二次确认、手绘输入
lib/src/achievements.dart  稀有度色板、成就徽章与头像成就摘要
lib/src/achievement_pages.dart 玩家的「我的成就」与主持人的「成就管理」
lib/src/host_pages.dart    主持等级说明与「主持授权」页
lib/src/announcement_pages.dart 大厅公告、公告页（markdown）与公告管理
lib/src/agreement_gate.dart 首次连接的用户协议门（Markdown）
lib/src/release.dart       版本标签、更新信息、online→health 复检去重
lib/src/update_installer.dart 安卓 APK 下载安装与清理、Windows 交给 Updater
lib/src/update_dialog.dart 更新弹窗（Markdown 日志）与大厅常驻更新入口
lib/src/platform_channel.dart 打开网页 / 安卓安装未知应用的平台通道
lib/src/predictive_sheet.dart 模态底部面板的预测性返回（接系统返回手势，见上）
```

客户端不做规则判断：行动是否可用、是否被私信锁定、能看到哪些牌与消息，全部以服务端返回的描述为准。
