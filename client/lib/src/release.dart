import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api.dart';
import 'client_version.dart';
import 'keepalive.dart';
import 'models.dart';

/// 用户关掉「有新版本可用」时记住的 latest 标签：之后只有出现更新的标签才再提示。
/// 关掉的只是横幅；大厅里的「立即更新」入口不会消失（见 update_dialog.dart）。
const updateNoticeDismissedKey = 'release_update_notice_dismissed';

/// 用户点过「忽略」电池优化提示后置位，之后不再打扰。
const batteryNoticeDismissedKey = 'release_battery_notice_dismissed';

/// 服务端健康检查返回的客户端版本标签（见 backend/app/api.py /api/health）。
class ClientVersionInfo {
  const ClientVersionInfo({this.latest, this.minimum});

  final String? latest;
  final String? minimum;
}

/// 服务端按「平台 + 版本区间」下发的更新信息（`/api/health` 的 `update` 字段）。
///
/// 只有「确实有更新」时服务端才给这个对象；字段都可缺省，客户端据此决定
/// 显示更新日志、下载按钮还是「打开网页」引导。
class ClientUpdateInfo {
  const ClientUpdateInfo({
    required this.platform,
    required this.latest,
    required this.mandatory,
    this.minimum,
    this.title = '发现新版本',
    this.notes = '',
    this.url = '',
    this.updaterUrl = '',
    this.guideUrl = '',
    this.sha256 = '',
    this.size = 0,
  });

  factory ClientUpdateInfo.fromJson(Map<String, dynamic> raw) =>
      ClientUpdateInfo(
        platform: raw['platform']?.toString() ?? '',
        latest: raw['latest']?.toString() ?? '',
        mandatory: raw['required'] == true,
        minimum: raw['minimum']?.toString(),
        title: (raw['title']?.toString().trim().isNotEmpty ?? false)
            ? raw['title'].toString().trim()
            : '发现新版本',
        notes: raw['notes']?.toString() ?? '',
        url: raw['url']?.toString() ?? '',
        updaterUrl: raw['updater_url']?.toString() ?? '',
        guideUrl: raw['guide_url']?.toString() ?? '',
        sha256: raw['sha256']?.toString() ?? '',
        size: raw['size'] is int ? raw['size'] as int : 0,
      );

  final String platform;

  /// 目标版本：低于它的客户端应当更新。
  final String latest;

  /// 服务端判定的强制更新（低于该区间的 minimum）。
  final bool mandatory;

  final String? minimum;

  /// 更新弹窗标题：服务端可为不同区间起不同标题。
  final String title;

  /// Markdown 更新日志。
  final String notes;

  /// 应用内更新包地址；为空时只走 [guideUrl] 引导网页。
  final String url;

  /// Windows 更新器地址（缺省时取同源 `/releases/Updater.exe`）。
  final String updaterUrl;

  /// 必要时引导用户打开的网页。
  final String guideUrl;

  final String sha256;
  final int size;

  bool get hasDownload => url.trim().isNotEmpty;
  bool get hasGuide => guideUrl.trim().isNotEmpty;

  /// Windows 更新器的实际地址：服务端没给就退回同源约定路径。
  String get resolvedUpdaterUrl =>
      updaterUrl.trim().isNotEmpty ? updaterUrl.trim() : '/releases/Updater.exe';
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

/// 发布检查：拉取服务端版本标签与更新信息并与内置版本比较，同时把安卓保活
/// 需要的「忽略电池优化」状态一并查回。任何一步失败都静默降级为不提示。
///
/// 两条取更新信息的路径：
/// 1. 连接某个服务地址时查一次 `/api/health`（见 [check]）；
/// 2. 大厅轮询 `/api/online` 回来说「有更新」时再查一次（见 [checkFromOnline]）——
///    同一服务地址、同一 latest 标签在 [onlineRecheckWindow] 内只查一次，
///    避免 5 秒一次的大厅轮询反复请求 health。
class ReleaseMonitor extends ChangeNotifier {
  ReleaseMonitor({
    this.currentVersion = kClientVersion,
    SharedPreferences? preferences,
  }) : _preferences = preferences {
    // 「已关闭」的记忆跟着偏好走：重启后不再重复弹同一条提示。
    _dismissedUpdateTag = preferences?.getString(updateNoticeDismissedKey);
    _batteryNoticeDismissed =
        preferences?.getBool(batteryNoticeDismissedKey) ?? false;
  }

  /// 同一服务地址 + 同一标签的 online 触发复检间隔。
  static const onlineRecheckWindow = Duration(minutes: 10);

  /// 客户端内置版本号，与 client/pubspec.yaml 的 version 名称保持一致；
  /// 故意不用 package_info_plus：不为三行比较代码引依赖（不发版不用改这里）。
  final String currentVersion;

  final SharedPreferences? _preferences;

  ClientVersionInfo? _versions;
  ClientUpdateInfo? updateInfo;
  bool _checked = false;
  bool batteryOptimizationIgnored = true;

  /// 用户已经关掉的 latest 标签；等于当前 latest 时不再提示。
  String? _dismissedUpdateTag;
  bool _batteryNoticeDismissed = false;

  /// online 触发复检的去重状态。
  ServerEndpoint? _onlineEndpoint;
  String? _onlineTag;
  DateTime? _onlineCheckedAt;

  /// 是否已经拿到过服务端的版本判断（取不到就不要提示）。
  bool get checked => _checked;

  bool get updateRequired {
    if (updateInfo?.mandatory == true) return true;
    final comparison = compareVersionTags(currentVersion, _versions?.minimum);
    return _checked && comparison != null && comparison < 0;
  }

  bool get updateAvailable {
    // 强制更新与「可更新」互斥：强制更新走 updateRequired 那条横幅与入口。
    if (updateRequired) return false;
    final info = updateInfo;
    if (info != null && compareVersionTags(currentVersion, info.latest) != null) {
      return compareVersionTags(currentVersion, info.latest)! < 0;
    }
    final comparison = compareVersionTags(currentVersion, _versions?.latest);
    return _checked && comparison != null && comparison < 0;
  }

  /// 可更新的横幅：用户点过「知道了」就不再出现，直到服务端下发更新的标签。
  /// 横幅可以关，但大厅里的更新入口不会消失（那是「始终显示更新按钮」的落点）。
  bool get updateNoticeVisible =>
      updateAvailable && _dismissedUpdateTag != _versions?.latest;

  /// 电池优化横幅：用户点过「忽略」就不再出现。
  bool get batteryNoticeVisible =>
      !batteryOptimizationIgnored && !_batteryNoticeDismissed;

  /// 关闭「有新版本可用」横幅：记住这次被关掉的 latest 标签。
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

  /// 测试与预览用：直接注入服务端下发的更新信息。
  @visibleForTesting
  void applyUpdate(ClientUpdateInfo? info) {
    updateInfo = info;
    if (info != null && info.latest.isNotEmpty) {
      _versions = ClientVersionInfo(
        latest: info.latest,
        minimum: info.minimum ?? _versions?.minimum,
      );
    }
    _checked = true;
    notifyListeners();
  }

  /// 把 `/api/health`（或测试用的等价载荷）套用到当前状态。
  void applyHealthPayload(Map<String, dynamic> health) {
    _versions = ClientVersionInfo(
      latest: health['client_latest']?.toString(),
      minimum: health['client_minimum']?.toString(),
    );
    final raw = health['update'];
    updateInfo = raw is Map
        ? ClientUpdateInfo.fromJson(
            raw.map((key, value) => MapEntry(key.toString(), value)))
        : null;
    _checked = true;
  }

  Future<void> check(ServerEndpoint endpoint) async {
    final api = GameApi(endpoint);
    try {
      final health = await api.health();
      applyHealthPayload(health);
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

  /// `/api/online` 回来说「有更新」时的复检：重新请求 `/api/health` 取版本字段。
  /// 同一个服务地址与同一个标签在 [onlineRecheckWindow] 内只查一次。
  Future<void> checkFromOnline(ServerEndpoint endpoint) async {
    if (!shouldRecheckFromOnline(endpoint)) return;
    await check(endpoint);
    _onlineEndpoint = endpoint;
    _onlineTag = _versions?.latest;
    _onlineCheckedAt = DateTime.now();
  }

  /// 复检去重的判据：同一服务地址、同一标签、且还在 [onlineRecheckWindow] 之内时不再查。
  @visibleForTesting
  bool shouldRecheckFromOnline(ServerEndpoint endpoint, {DateTime? now}) {
    final moment = now ?? DateTime.now();
    final fresh = identical(endpoint, _onlineEndpoint) &&
        _onlineCheckedAt != null &&
        moment.difference(_onlineCheckedAt!) < onlineRecheckWindow &&
        _onlineTag == _versions?.latest;
    return !fresh;
  }

  Future<void> requestBatteryWhitelist() async {
    await KeepAlive.requestIgnoreBatteryOptimizations();
    batteryOptimizationIgnored = await KeepAlive.ignoringBatteryOptimizations();
    notifyListeners();
  }
}
