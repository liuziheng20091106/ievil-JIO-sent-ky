# Flutter 原生客户端方案

## Context
将现有七人双角色网页客户端迁移为 Flutter 原生客户端，同时保留 FastAPI 作为规则、权限和可见性权威。首发交付 Android 玩家端与 Windows 主持人端；玩家使用 QQ 群验证登录，主持人继续使用既定固定密码。Flutter 本机持久保存登录令牌和服务地址；服务端把账号、登录挑战及令牌放在独立鉴权数据库，对局数据库只保存对局参与身份与游戏数据。

客户端以用户给出的两个界面为交互参考，不复制其业务：手机主界面使用三项悬浮底栏；“对局”页把聊天记录与当前行动合并，聊天在上、行动入口在输入区下方，点击行动后才弹窗显示说明和参数。网页端继续可用；本方案涉及的登录、主动加入、私信权限、行动确认和上下牌行为同步到网页端，但不重做网页布局。

## 调研记录
- 已确认：`backend/app/game/actions.py` 的 `action()`、`field()` 与 `actions_for()` 已生成按身份裁剪的行动描述，`backend/app/game/engine.py:validate_command()` 以当前描述校验行动、固定 payload 和字段值；Flutter 与网页应继续共用这一协议，不建立第二套规则。
- 已确认：`backend/app/game/views.py:game_view()` 返回版本、阶段、双牌、行动和公开状态；`backend/app/views.py` 再补频道与主持人房间管理；所有 HTTP、WebSocket、历史消息和证物出口都能复用同一权限投影。
- 已确认：现有消息已区分 `public`、玩家与主持人私聊、主持人创建的群组频道及 `information`，消息 ID 可分页和断线补齐；但频道仅主持人创建，没有邀请、同意、拒绝、结束和“私信中”互斥状态。
- 已确认：现有玩家/观战者通过本局邀请码加入，会话与对局数据同存 `data/seven-double.sqlite3`；这与 QQ 账号长期登录、主动参局和独立令牌数据库的新要求冲突，需干净迁移并删除邀请码入口。
- 已确认：`D:/Group Festival/gateway/gateway.py` 已实现 NapCat OneBot WebSocket、六位“活动登录”挑战绑定、群成员同步和断线退避；复制并裁剪这份已运行实现，不重写 OneBot 客户端。
- 已确认：当前 `Seat` 已有 `avatar_role_id`、`previous_role_id`，主持人/本人视图另有两张 `cards` 及 `current_card_id`；双头像可直接从已获授权字段组合，不需要新增泄密字段。

## Approach

### 1. 复制 QQ 网关，拆出账号与登录令牌数据库
1. 把 `D:/Group Festival/gateway/` 中的 `gateway.py`、`requirements.txt`、`.env.example`、`__init__.py` 复制到仓库 `gateway/`；不复制 `__pycache__`、外部项目的 `run-gateway.ps1` 或任何真实令牌。删除源网关读取外部 `config.json` 的兼容分支，只从环境变量读取 `NAPCAT_WS_URL`、`NAPCAT_TOKEN`、`GAME_BACKEND_URL`、`GAME_GATEWAY_TOKEN`、`GAME_QQ_GROUP_ID`。
2. `.gitignore` 增加 `gateway/.env`、`gateway/napcat/`、`gateway/*.log`；仓库只保留无真实值的 `.env.example`。NapCat 登录态、设备文件、访问令牌和网关共享密钥不得进入 Git、Flutter 资源或网页构建产物。
3. 新增 `backend/app/auth_storage.py`，在 `GAME_DATA_DIR/auth.sqlite3` 保存 `accounts(qq_id,nickname,avatar_url)`、`login_challenges` 和 `login_tokens(token_hash,account_id,kind,expires_at,valid)`；只保存 SHA-256 后的令牌。`seven-double.sqlite3` 删除 `sessions`、`invites`，`participants` 改为引用稳定 `account_id`。跨数据库不伪造外键，由单进程事务边界先校验账号，再写对局参与身份。
4. 复用已验证的 QQ 流程：`POST /api/auth/challenges` 生成短期六位码，Flutter/网页显示“活动登录 123456”并轮询 `GET /api/auth/challenges/{id}`；网关用 `X-Gateway-Token` 调用 `POST /api/internal/qq/login` 绑定 QQ 号、群昵称和头像。挑战一次性消费，过期/重放拒绝；真实网关密钥只从环境变量读取并用 `secrets.compare_digest` 校验。
5. QQ 登录成功返回随机长期 Bearer；Flutter 用 `flutter_secure_storage` 持久保存，启动时以 `/api/me` 验证，401 才清除。网页继续用 HttpOnly、SameSite Cookie，但 Cookie 对应的令牌也查 `auth.sqlite3`；原生 Bearer 与网页 Cookie 共用账号、过期和撤销语义。玩家退出只撤销当前令牌，不删除账号。
6. 固定主持人密码入口按项目约束保留，成功后同样在 `auth.sqlite3` 发放 `kind=host` 的持久令牌；密码不写入客户端资源。创建下一局或清空对局只清理对局库，不登出 QQ 账号或主持人；踢出/本局拉黑只使对应参与身份失效，不能误删其全局 QQ 登录。
7. `auth.token_hash(connection)` 严格解析单个 `Authorization: Bearer <token>`，否则回退 Cookie；有效 Bearer 请求可跳过浏览器同源校验，Cookie 写请求和 WebSocket 仍保持同源检查。TLS 证书错误始终拒绝，不把令牌放 URL，也不实现证书绕过。

### 2. 用“开放参局”替换本局邀请码
1. 新对局建立时为不可加入状态。主持人管理动作 `room.open_join`（短名“开放加入”）宣布对局可用并产生全体系统消息；登录账号通过 `/api/lobby` 看到当前开放对局，选择“加入”或“观战”，无需主持人审核。
2. `POST /api/games/{game_id}/participations` 接受封闭枚举 `player|spectator`。选择玩家时仅在首次发牌前随机占用空席，七席已满或已发牌则拒绝并保留“观战”选择；选择观战不占席位。以 `(game_id,account_id)` 保证同一账号不能重复加入或重抽席位。
3. 删除 `Invite`/`Join` 模型、`/invites` 与邀请码 `/join`、`invites` 表及客户端邀请码文案；刷新、换设备登录和重连都按 QQ 账号恢复原参与身份，不重新分席或重发牌。发牌后的替补仍由主持人把现有观战者接管空席，角色牌、技能次数和既有裁定状态不重置。
4. 观战者取得与主持人相近的只读牌桌：能看全席双牌、生死、状态、阶段和结果，但不返回玩家/主持人游戏行动、主持人待办、参与者管理或席位代操作；所有游戏命令、证物提交和管理请求都在服务端拒绝。公屏发言及私信仍按频道权限开放，观战的全牌面视角不得扩展为未加入私信频道的消息或证物权限。

### 3. 把公屏和有生命周期的私信分开
1. 公屏与私信使用独立列表和已读游标，不再把所有可见消息混成一条时间线。消息页顶部提供“全部 / 公屏 / 私信 / 系统 / 主持人”筛选；`GET /messages` 增加封闭 `scope` 查询并在权限过滤后分页，确保筛选历史不是只过滤本机最近一页。
2. 玩家或观战可创建一对一或多人私信，创建弹窗从本局有效参与身份和主持人中多选邀请对象并填写频道名，不经过主持人审核。频道保存 `creator_id`、`status=pending|active|ended`、邀请名单、已同意名单和结束时间；同一非主持人账号同时至多参加一个 active 私信，主持人不受此限制。
3. 非主持人发起时，受邀非主持人成员逐人看到“同意 / 拒绝”；主持人被邀请时自动同意。全部受邀成员同意后频道才 active，任一成员拒绝则本次创建取消且不锁定任何人。主持人发起的频道立即 active，受邀成员无需确认；邀请响应和创建/结束都走服务端动作描述并携带 `expected_version`。
4. 私信 active 后，服务器而非客户端强制其中非主持人成员只能在该频道发言，并拒绝公屏消息；玩家成员的全部游戏行动也被拒绝，观战本来就没有游戏行动。行动区只保留“结束私信”，主持人仍可在任意频道发言、执行行动和管理。任一成员点击“结束私信”即结束整个频道，解除所有非主持人成员限制；断线、刷新或换设备不能绕过限制。
5. 频道转为 active 时向全体发送“甲正在与乙、丙私信”，结束时发送“甲与乙、丙已结束私信”；多人名单使用创建时公开称呼，系统消息不泄露私信内容。频道内消息只给成员与主持人查看，结束后只读保留；替补默认不继承旧操作者私信历史。
6. `views.channels_for()` 同时返回频道状态、邀请状态、成员摘要、`can_send` 和服务端 `reason`；`send_message()`、`command()`、历史分页、实时推送与附件读取共用同一成员和私信锁定检查，不能只靠 Flutter/React 禁用按钮。

### 4. 收紧服务端驱动的行动协议
1. 保留 text、textarea、number、select、multiselect、checkbox、drawing 七种字段，不增加远程脚本、通用规则引擎或动态组件注册。行动描述新增必填 `short_label`，值为 2—4 个汉字，用于按钮；原 `label` 和 `description` 在弹窗中完整显示。
2. 所有玩家行动、私信邀请响应和主持人管理统一二次确认：第一次点击短名按钮只打开说明/参数弹窗，第二次点击“确认提交”才发送。删除 `instant` 绕过语义；零参数、警告、推进、私信结束等动作也必须复核，危险操作继续以文字和颜色双重标记。
3. 动态描述增加顶层 `ui_version: 1`，`GameView` 同样返回该版本；未知版本或字段类型显示“客户端版本不支持此行动，请升级”并禁止提交。Flutter 的输入检查只提供即时提示，`engine.validate_command()` 继续作为唯一权威；所有写命令携带 `expected_version`，409 后保留草稿、刷新并要求重新确认，绝不自动重放。
4. `lobby.order` 仍只提交所选 `top`，后端用另一个卡牌 ID 自动确定下层。Flutter 与网页在选中上层后立即显示“上层 X / 下层 Y”，不再让用户执行第二次选择；换序仍取消第二轮准备。

### 5. 建立最小 Flutter 应用和传输层
1. 新建根目录 `client/`，目标仅 Android 与 Windows。使用 Material 3、Flutter 自带导航/动画/`HapticFeedback`、Dart JSON/HTTP/WebSocket；除 `flutter_secure_storage`、`shared_preferences` 外不加状态框架、路由框架、动态 UI 包或游戏引擎。若 `dart:io` 的 WebSocket Authorization 实测不满足要求，才增加单一 `web_socket_channel`。
2. `ServerEndpoint.parse()` 只接受无路径、查询和片段的服务根地址；loopback、localhost、RFC1918 可用 HTTP，其他主机必须 HTTPS。统一派生 HTTP、`/api/live` 和头像 URL；请求超时 25 秒，写失败后只拉一次状态核对，不自动重放。
3. 一个 `GameApi` 负责 QQ 挑战、`me`、大厅、主动加入、状态、命令、消息分页/发送、证物和登出；一个 `LiveConnection` 消费 `sync/state/message/ping`，65 秒无事件按 1、2、4、8、15 秒退避重连并按消息 ID 补齐。DTO 只解码服务端裁剪结果，不在 Dart 重算规则。
4. 一个 `GameStore` 持有账号、参与身份、目录、视图、频道消息、连接状态、已读游标和单次写入 busy 标记。草稿键按 `[serverUri,gameId,accountId,participantId,channelOrAction,day,half,phase,actionId,fixedPayload]` 隔离；不保存密码、QQ 登录码、令牌副本或邀请码。消息已读、阶段已提醒和行动已查看标记可用 `shared_preferences` 保存。

### 6. 以聊天为主合并玩家行动
1. 玩家“对局”页上方为可分页消息列表，下方固定聊天输入和短行动条；点击行动按钮弹出底部表单，展示完整说明、字段和最终确认。存在多个行动时横向滚动或展开行动抽屉，不把长表单常驻在聊天下方。
2. 软键盘弹出时隐藏行动列表/抽屉，只保留紧凑行动入口和未读提示；新行动出现时入口仍高亮并显示数量，收起键盘后可打开。新行动按服务端行动描述的规范化键（含 `id`、固定 payload、字段与选项）从无到有或发生变化判断；首次同步只建立基线，不把旧行动伪报为新行动。
3. 手机底栏固定三项并采用示例图的悬浮圆角样式：玩家为“对局 / 状态 / 我的”，主持人为“对局 / 状态 / 管理”。新消息、新行动或警告反馈到“对局”；未查看的阶段/牌桌状态反馈到“状态”；双牌私密状态反馈到“我的”；主持人待办反馈到“管理”。角标同时使用数字/文字和颜色，切到对应内容并实际查看后才清除。
4. Android 对按钮确认、频道切换、收到需本人处理的新行动/警告分别调用 `HapticFeedback.selectionClick/lightImpact/heavyImpact`；Windows 静默。应用在后台或系统关闭触觉时不强行振动，不增加原生振动插件。
5. `(gameId,day,half,phase)` 变化时弹出一次全屏阶段动画，显示日数、昼夜和阶段名；首次进入/重连不重复旧动画。消息插入、弹窗、底栏角标、卡牌切层使用 Flutter 内建 `AnimatedSwitcher`/`AnimatedContainer`，遵守系统“减少动态效果”，不自动播放音乐或加入游戏引擎。
6. 每个席位同时绘制两张圆形头像，左右分布并重叠约 50%；当前使用牌位于顶层。未获授权的牌显示“?”，已出局的身份头像灰白化；夜间延迟公开期间严格使用服务端现有 `avatar_role_id/previous_role_id/cards/current_card_id`，客户端不得从动画顺序猜测隐藏牌。自己的“我的”页仍完整显示两张真实角色卡及状态。

### 7. 提供独立且易懂的主持人界面
1. 主持人登录后进入独立 `HostShell`，不把玩家页面堆满管理开关；“管理”按“当前待办 / 流程 / 玩家 / 私密信息 / 纠错”分组，顶部显示阶段、自动推进和真正阻塞项。所有按钮只显示 2—4 字短名，点击后才展开影响、目标、参数和确认。
2. 主持人继续通过同一 `actions` 描述执行推进、警告、裁决、代操作、替补、踢人/拉黑和胜负确认；席位视角读取后再代操作，不能提交该席当前没有的行动。观战只复用主持人的只读牌桌组件，不挂载管理组件。
3. 动画用于说明状态变化而非掩盖等待：阶段推进、牌出局/切换、警告和结算可动画呈现；提交中始终禁用重复写，错误保留表单值并显示服务端原因。管理员私信不限制其公屏、行动或管理入口。

### 8. 同步网页行为并完成迁移
1. React 网页接入 QQ 挑战登录、开放参局、主动加入/观战、公屏与私信分离、邀请同意/拒绝/结束、私信期间服务端限制、全局二次确认和上下牌自动联动；复用现有页面结构、`ActionForm`、`Chat` 和底部导航，不按 Flutter 参考图重做视觉布局。
2. 原生与网页共用 `ui_version`、`short_label`、频道生命周期、消息筛选和错误形状；更新 `frontend/src/types.ts`、`api.ts`、`state.tsx` 的全部调用方后删除旧邀请码、`instant` 和主持人专属建私信兼容路径，不保留双协议。
3. 更新 `README.md` 与 `docs/七双在线游戏设计方案.txt`：QQ/NapCat 配置、两个 SQLite 的备份边界、Flutter/Android/Windows 构建、主动参局、私信锁定、网关启动、反向代理 Authorization/WebSocket 转发；保持 `setup.cmd`/`start.cmd` 单进程单 worker，增加网关启动脚本但不写入密钥。

## Critical files & anchors
- `gateway/gateway.py`、`gateway/.env.example`：复制既有 OneBot 登录绑定，移除外部项目兼容配置和真实密钥。
- `backend/app/auth.py`、新 `auth_storage.py`、`storage.py`：独立账号令牌库、Bearer/Cookie 解析、QQ 账号与对局参与身份分离。
- `backend/app/api.py`、`schemas.py`、`views.py`：QQ 挑战、开放参局、频道生命周期、私信锁定、消息 scope 与观战只读边界。
- `backend/app/game/actions.py`、`engine.py`、`game/views.py`：`short_label`、统一确认所需描述、私信中拒绝游戏行动、双牌可见性。
- `frontend/src/Actions.tsx`、`Chat.tsx`、`state.tsx`、`types.ts`：必要行为同步，不重做网页外观。
- `client/lib/`：连接/QQ 登录、共享 DTO/Store、玩家壳、主持人壳、聊天行动合并页与双头像组件。

## Verification
1. 后端用独立临时 `GAME_DATA_DIR` 执行完整检查；新增一个真实边界流程覆盖：QQ 挑战只能消费一次、原始令牌不落库、Bearer/Cookie 均从 `auth.sqlite3` 恢复、清空对局不登出、踢人不能重登本局但仍保留 QQ 账号。
2. 七个不同 QQ 账号在主持人开放后无需审核随机占满七席，第八个账号被拒但可观战；同账号不能重复分席。发牌后不能新占玩家席，观战替补不重抽牌。观战能读全席牌面状态，但游戏命令、证物提交和管理请求均为 403；公屏与私信只按频道权限开放，不能读取未加入频道的历史、实时消息或附件。
3. 私信流程覆盖玩家或观战创建、多人逐一同意、拒绝取消、主持人默认同意、主持人免同意发起、单个非主持人仅一个 active 频道、开始/结束全体系统消息。active 非主持人成员的公屏消息及玩家成员的游戏命令均被服务端拒绝，主持人不受限制，结束后恢复；历史、实时消息和附件均不越权。
4. 行动协议检查覆盖七种字段、2—4 字 `short_label`、未知 `ui_version`/字段拒绝、所有行动二次确认、409 保留草稿并重新确认；`lobby.order` 选择上层后服务器保存的另一张必为下层。
5. Flutter 执行 `flutter analyze`、最小 DTO/地址解析检查、`flutter build apk --debug`、`flutter build windows --debug`。Android 真机验证 QQ 登录持久恢复、底栏角标、触觉、软键盘隐藏行动列表但保留新行动提醒、阶段动画只出现一次、双头像 50% 重叠/当前牌置顶/死亡灰白；Windows 验证独立主持人工作台和无触觉。
6. 实际启动 FastAPI、网关、Flutter Android、Flutter Windows 和生产网页进行同局联调：两端互收筛选后的公屏/私信与系统消息，规则状态一致，网页登录/主动参局可用且视觉布局未重做。最后执行 Ruff、后端检查与 `npm.cmd run build`，清除临时 `GAME_DATA_DIR`、网关 `.env`、联调脚本和构建产物。

## Assumptions & contingencies
- 首发仍只有一名固定真人主持人、一局七人双角色、单进程单 worker；不扩展十三人、公网账号平台、好友系统、消息撤回、语音、推送服务或后台保活。
- “观战类似管理员视角”落实为全牌面只读，不包含管理权限或游戏行动；公屏和私信按普通非主持人成员的频道权限处理，全牌面视角不能放宽私信与证物授权。
- QQ/NapCat 不可用时保留已验证长期令牌的离线恢复；新账号无法登录时明确报错，不降级为匿名、邀请码或客户端自报 QQ 号。主持人固定密码是唯一保留的非 QQ 登录入口。
- 阶段和行动提醒只在应用内处理；没有明确要求前不增加 Firebase、系统通知、后台服务或额外动画依赖。
