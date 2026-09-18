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

Windows 构建需要 Visual Studio 的 C++ 桌面工作负载，以及 `flutter_secure_storage` 依赖的 ATL 组件（`Microsoft.VisualStudio.Component.VC.ATL`）。

## 使用

首次启动填写服务根地址：loopback、localhost 和私有网段可用 HTTP，其他主机必须 HTTPS。玩家在指定 QQ 群发送“活动登录 123456”完成验证，登录页的「一键复制」把这一整句（含前缀与空格）直接放进剪切板，粘贴发送即可；主持人在同一页面输入固定密码。

登录令牌保存在 `flutter_secure_storage`，启动时用 `/api/me` 核对，只有 401 才清除。服务地址与其他偏好保存在 `shared_preferences`。

Windows 主持人端禁止重复实例：同一登录会话里重复启动不会开出第二个窗口，而是把已在运行的窗口唤到前台后立刻退出（`client/windows/runner/single_instance.h` 的命名互斥体；互斥体随进程结束由系统释放，崩溃后也能重新启动）。不同 Windows 用户各自可以运行一个实例。

对局被主持人终止（或分出胜负）后，客户端停留在只读结局页：标题栏与结算卡各有一个「返回大厅」入口，点它回到主界面（大厅）后，主持人可确认魔典建立下一局，其他身份等待新局。返回后重启客户端不会被重新拉回已终止的那一局——服务器仍把这一局当作当前局返回给 `/api/me`，是否已经离开由客户端本地判断；需要回看记录请在返回大厅前查看。

屏幕宽度足够时同屏显示多个界面，不再用底栏把页面藏起来：平板横屏（宽 ≥840）左侧固定「状态」牌桌、右侧「对局」，双牌/管理收进右上角抽屉（入口保留该页待办角标）；电脑宽屏（宽 ≥1200）「状态 / 对局 / 我的·管理」三栏并排。手机与平板竖屏保持底部导航一次一页，角标与「已查看」语义不变：同屏可见的页面直接算已查看，窄屏仍由底栏选择触发。

## 结构

```
lib/main.dart              应用入口、服务地址页、登录页、大厅
lib/src/api.dart           HttpClient / WebSocket 传输层与断线退避
lib/src/models.dart        协议 DTO、服务地址校验、ui_version 检查
lib/src/store.dart         账号、参与身份、视图、频道消息、草稿与角标
lib/src/shell.dart         玩家/主持人壳、宽屏多栏与悬浮底栏、双头像、阶段动画
lib/src/action_sheet.dart  行动表单、二次确认、手绘输入
```

客户端不做规则判断：行动是否可用、是否被私信锁定、能看到哪些牌与消息，全部以服务端返回的描述为准。
