import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api.dart';
import 'keepalive.dart';
import 'models.dart';

/// 用户关掉「有新版本可用」时记住的 latest 标签：之后只有出现更新的标签才再提示。
const updateNoticeDismissedKey = 'release_update_notice_dismissed';

/// 用户点过「忽略」电池优化提示后置位，之后不再打扰。
const batteryNoticeDismissedKey = 'release_battery_notice_dismissed';

/// 服务端健康检查返回的客户端版本标签（见 backend/app/api.py /api/health）。
class ClientVersionInfo {
  const ClientVersionInfo({this.latest, this.minimum});

  final String? latest;
  final String? minimum;
}

/// 「major.minor.patch」三段数字比较；解析失败（含 null）返回 null。
int? compareVersionTags(String? a, String? b) {
  if (a == null || b == null) return null;
  List<int>? parse(String value) {
    final parts = value.trim().split('.');
    if (parts.length != 3) return null;
    final parsed = <int>[];
    for (final part in parts) {
      final number = int.tryParse(part);
      if (number == null) return null;
      parsed.add(number);
    }
    return parsed;
  }

  final left = parse(a);
  final right = parse(b);
  if (left == null || right == null) return null;
  for (var index = 0; index < 3; index++) {
    if (left[index] != right[index]) return left[index] - right[index];
  }
  return 0;
}

/// 发布检查：拉取服务端版本标签并与内置版本比较，同时把安卓保活
/// 需要的「忽略电池优化」状态一并查回。任何一步失败都静默降级为不提示。
class ReleaseMonitor extends ChangeNotifier {
  ReleaseMonitor({
    this.currentVersion = '1.0.9',
    SharedPreferences? preferences,
  }) : _preferences = preferences {
    // 「已关闭」的记忆跟着偏好走：重启后不再重复弹同一条提示。
    _dismissedUpdateTag = preferences?.getString(updateNoticeDismissedKey);
    _batteryNoticeDismissed =
        preferences?.getBool(batteryNoticeDismissedKey) ?? false;
  }

  /// 客户端内置版本号，与 client/pubspec.yaml 的 version 名称保持一致；
  /// 故意不用 package_info_plus：不为三行比较代码引依赖（不发版不用改这里）。
  final String currentVersion;

  final SharedPreferences? _preferences;

  ClientVersionInfo? _versions;
  bool _checked = false;
  bool batteryOptimizationIgnored = true;

  /// 用户已经关掉的 latest 标签；等于当前 latest 时不再提示。
  String? _dismissedUpdateTag;
  bool _batteryNoticeDismissed = false;

  bool get updateRequired {
    final comparison = compareVersionTags(currentVersion, _versions?.minimum);
    return _checked && comparison != null && comparison < 0;
  }

  bool get updateAvailable {
    final comparison = compareVersionTags(currentVersion, _versions?.latest);
    return !updateRequired && _checked && comparison != null && comparison < 0;
  }

  /// 可更新的横幅：用户点过「知道了」就不再出现，直到服务端下发更新的标签。
  bool get updateNoticeVisible =>
      updateAvailable && _dismissedUpdateTag != _versions?.latest;

  /// 电池优化横幅：用户点过「忽略」就不再出现。
  bool get batteryNoticeVisible =>
      !batteryOptimizationIgnored && !_batteryNoticeDismissed;

  /// 关闭「有新版本可用」：记住这次被关掉的 latest 标签。
  Future<void> dismissUpdateNotice() async {
    final tag = _versions?.latest;
    if (tag == null || _dismissedUpdateTag == tag) return;
    _dismissedUpdateTag = tag;
    await _preferences?.setString(updateNoticeDismissedKey, tag);
    notifyListeners();
  }

  /// 忽略「忽略电池优化」提示：以后不再提示，仍可自行去系统设置授权。
  Future<void> dismissBatteryNotice() async {
    if (_batteryNoticeDismissed) return;
    _batteryNoticeDismissed = true;
    await _preferences?.setBool(batteryNoticeDismissedKey, true);
    notifyListeners();
  }

  /// 测试与预览用：直接注入服务端标签，跳过网络探测。
  @visibleForTesting
  void applyVersionTags({String? latest, String? minimum}) {
    _versions = ClientVersionInfo(latest: latest, minimum: minimum);
    _checked = true;
    notifyListeners();
  }

  Future<void> check(ServerEndpoint endpoint) async {
    final api = GameApi(endpoint);
    try {
      final health = await api.health();
      _versions = ClientVersionInfo(
        latest: health['client_latest']?.toString(),
        minimum: health['client_minimum']?.toString(),
      );
      _checked = true;
    } on ApiException {
      // 取不到标签就当作没有更新要求，不阻塞使用。
    } on SocketException {
      // 同上：离线时维持现状，连接条已经表达了断线。
    } finally {
      api.close();
    }
    batteryOptimizationIgnored = await KeepAlive.ignoringBatteryOptimizations();
    notifyListeners();
  }

  Future<void> requestBatteryWhitelist() async {
    await KeepAlive.requestIgnoreBatteryOptimizations();
    batteryOptimizationIgnored = await KeepAlive.ignoringBatteryOptimizations();
    notifyListeners();
  }
}
