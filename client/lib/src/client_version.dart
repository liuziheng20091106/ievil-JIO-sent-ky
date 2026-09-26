import 'dart:io';

/// 客户端内置版本号：发版时与 `client/pubspec.yaml` 的版本名同步手改；
/// 后端按 UA 里的这个版本做更新下发与入局门槛，故意不用 package_info_plus。
const kClientVersion = '1.0.11';

/// 默认后端服务地址：首次进入「连接服务器」时预填，但玩家可以随意改成别的地址。
const kDefaultServerEndpoint = 'https://super.tkcloud.online:447';

/// 当前平台标签：后端用它匹配分平台的更新区间（windows / android）。
String get clientPlatform {
  if (Platform.isWindows) return 'windows';
  if (Platform.isAndroid) return 'android';
  return 'other';
}

/// 所有客户端请求都带的 UA：`seven-double-flutter/<版本> (<平台>)`。
/// 后端只认这个形状；不带或形状不对时一律不下发平台相关的更新信息、也不拦入局。
String clientUserAgent() => 'seven-double-flutter/$kClientVersion ($clientPlatform)';

/// Updater 自己的 UA：Windows 更新器请求 `/api/health` 时用它取 Windows 更新包。
String updaterUserAgent(String version) => 'magicjudge-updater/$version (windows)';
