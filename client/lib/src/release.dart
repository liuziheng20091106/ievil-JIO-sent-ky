import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';

import 'api.dart';
import 'keepalive.dart';
import 'models.dart';

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
  ReleaseMonitor({this.currentVersion = '1.0.4'});

  /// 客户端内置版本号，与 client/pubspec.yaml 的 version 名称保持一致；
  /// 故意不用 package_info_plus：不为三行比较代码引依赖（不发版不用改这里）。
  final String currentVersion;

  ClientVersionInfo? _versions;
  bool _checked = false;
  bool batteryOptimizationIgnored = true;

  bool get updateRequired {
    final comparison = compareVersionTags(currentVersion, _versions?.minimum);
    return _checked && comparison != null && comparison < 0;
  }

  bool get updateAvailable {
    final comparison = compareVersionTags(currentVersion, _versions?.latest);
    return !updateRequired &&
        _checked &&
        comparison != null &&
        comparison < 0;
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
