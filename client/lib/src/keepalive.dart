import 'dart:async';
import 'dart:io';

import 'package:flutter/services.dart';

/// 后台保活（仅 Android）：Kotlin 侧前台服务在应用启动后自动拉起，
/// 这里只负责查询与请求「忽略电池优化」白名单。其他平台全部为无操作。
class KeepAlive {
  static const _channel = MethodChannel('keepalive');

  static bool get _supported => Platform.isAndroid;

  static Future<bool> ignoringBatteryOptimizations() async {
    if (!_supported) return true;
    try {
      return await _channel.invokeMethod<bool>(
                'ignoringBatteryOptimizations',
              ) ==
              true;
    } on PlatformException {
      return true;
    } on MissingPluginException {
      return true;
    }
  }

  static Future<void> requestIgnoreBatteryOptimizations() async {
    if (!_supported) return;
    try {
      await _channel.invokeMethod<void>('requestIgnoreBatteryOptimizations');
    } on PlatformException {
      // 系统入口缺失时静默放弃，保活仍靠前台服务兜底。
    } on MissingPluginException {
      // 非 Android 构建没有该插件。
    }
  }
}
