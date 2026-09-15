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

首次启动填写服务根地址：loopback、localhost 和私有网段可用 HTTP，其他主机必须 HTTPS。玩家在指定 QQ 群发送“活动登录 123456”完成验证；主持人在同一页面输入固定密码。

登录令牌保存在 `flutter_secure_storage`，启动时用 `/api/me` 核对，只有 401 才清除。服务地址与其他偏好保存在 `shared_preferences`。

## 结构

```
lib/main.dart              应用入口、服务地址页、登录页、大厅
lib/src/api.dart           HttpClient / WebSocket 传输层与断线退避
lib/src/models.dart        协议 DTO、服务地址校验、ui_version 检查
lib/src/store.dart         账号、参与身份、视图、频道消息、草稿与角标
lib/src/shell.dart         玩家/主持人壳、悬浮底栏、双头像、阶段动画
lib/src/action_sheet.dart  行动表单、二次确认、手绘输入
```

客户端不做规则判断：行动是否可用、是否被私信锁定、能看到哪些牌与消息，全部以服务端返回的描述为准。
