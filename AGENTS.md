# 项目约束

## 范围与规则
- 使用中文沟通。实现七人双角色模式，固定真人主持人；不扩展十三人模式或公网基础设施。
- 当前用户确认的规则优先于 `docs/七双模式游戏介绍与完整规则.txt` 和 `docs/七双在线游戏设计方案.txt`；`docs/old` 仅供历史参考。
- 入场使用本局统一玩家邀请码，随机分配空席；全员第一次准备后发牌，私下决定上下牌，再次全员准备后由主持人开局。可调整顺序期间不公开角色头像或名称。
- 玩家身份与持久席位分离；踢人、观战替补不得重抽角色或重置技能。夜间同时行动，死亡者仍可完成当夜行动。
- 提名在白天随时可提交、提交即生效（无需二次确认），进入提名阶段时先前提名或放弃自动视为已确认；同一人可被多人提名，计票去重后每张牌只投一轮，提名过当前候选的玩家自动投同意票。
- 顺序发言可预提交：未轮到的席位可点「本轮不发言（跳过我的顺序）」或「提前写发言（轮到你时公开）」写下内容，轮到时才自动公开；全部提交后阶段自动完成，天黑时清空。
- 真实白天技能声明后立即按技能条目结算（声明留到当天结束，质疑入口与伪装声明完全一致），伪装声明仍由主持人裁定；希罗回溯由本人在行动面板选择，主持人只管非同一天同一时点的特殊裁定。
- 米莉亚临死换牌没有主持人判定点：她的预结算一旦会出局就直接换上层牌重算。
- 不明确的概率和规则交由主持人裁决，保留显式确认与30秒警告。系统自己知道做完的阶段（魔女化、夜间行动、顺序发言、提名、投票、处决前响应）无人待办时5秒后自动推进，主持人可暂停或手动推进；需要主持人判断或宣布的阶段仍由主持人推进。

## 实现边界
- 后端：Python 3.14+、FastAPI、标准库 SQLite，单进程单 worker。前端：Node.js >=22.12、React/TypeScript/Vite；生产前端由 FastAPI 同源提供。
- `backend/app/game/` 维护规则，不依赖 HTTP；`views.py` 在服务端裁剪可见信息，前端隐藏不能代替授权。
- 命令使用 `expected_version`；冲突刷新并要求重新确认，不自动重试写入。复用后端动作描述生成表单。
- 主持人不再使用固定密码：管理员由环境变量 `GAME_ADMIN_QQ` 指定（恒为 5 级），其余主持授权与 QQ 账号绑定、分 1-5 级（1 级只主持 1 局，那一局结束授权即失效）；登录令牌每次请求重新核对等级，任何授权配置都不得写入前端资源。不要增加 ORM、通用规则引擎、状态框架或无需求的新依赖。
- 草稿按对局、参与身份、频道或表单隔离；刷新可恢复，提交成功才清除，不保存密码、会话。替补不得继承旧身份的本地私密草稿。

## 运行与验证
- 安装：`setup.cmd`；启动：`start.cmd`；默认 `http://localhost:8000`。
- 默认数据目录 `data/` 属于用户。验证必须设置 `GAME_DATA_DIR` 为独立临时目录；不得删除或改写用户对局。
- 反向代理：代理必须透传原始 `Host` 或补 `X-Forwarded-Host`/`X-Forwarded-Proto`；代理不在本机时用 `--trusted-proxies` 或 `GAME_TRUSTED_PROXIES` 声明。显式放行来源默认是 `super.tkcloud.online`，用 `GAME_ALLOWED_ORIGINS` 覆盖。
- 后端检查：`.venv/Scripts/python.exe -m unittest discover -s checks -v`。
- 静态检查：`.venv/Scripts/python.exe -m ruff check backend checks run.py`。
- 前端检查/构建：在 `frontend/` 执行 `npm.cmd run build`。
- 客户端编译发行：在 `client/` 执行 `flutter build apk --release --target-platform android-arm64` 与 `flutter build windows --release`。
- 每次编译后运行 `package-release.cmd`：把 `client/build/windows/x64/runner/Release` 重新打成 `魔法裁判Windows.zip`，并与 `app-release.apk` 一起覆盖复制到 `\\192.168.0.114\烟台一中\云控\信息技术`。
- 客户端版本标签：后端 `GAME_CLIENT_LATEST` / `GAME_CLIENT_MINIMUM`（`x.y.z` 三段），低于 latest 提示可更新、低于 minimum 强制更新；客户端内置版本号写在 `client/lib/src/release.dart` 的 `ReleaseMonitor.currentVersion`，发版时与 `client/pubspec.yaml` 的版本名同步手改，不动安卓 versionCode/versionName。
- 有意义的行为修改必须实际启动并验证相关服务或浏览器路径；新增回归检查只保护真实规则、权限或数据丢失边界。
- 更新现有 TXT 运行说明；保持改动最小，不为假设需求搭框架。并发代理修改不同文件，统一在集成结束后格式化、构建和运行检查。

## 版本管理
- 使用本地 Git 管理可回退版本；改动前保留基线，验证完成后提交功能变更。自动推送远端。
- 不提交 `data/`、`.venv/`、`node_modules/`、构建产物、缓存、会话、私密材料或临时联调脚本。
- 删除用户现有修改，每次改完重置工作区并删除所有验证数据。
