import 'dart:io';

import 'package:flutter/services.dart';

/// 应用内更新需要的平台能力：打开外部网页（两端）与安卓 APK 安装（仅 Android）。
///
/// 与 keepalive 一样走自建 MethodChannel，不引入 url_launcher / open_filex 之类的依赖：
/// 这两个动作各只需要平台侧十几行代码。写成实例方法是为了在测试里替换掉真实通道。
class ClientUpdateChannel {
  const ClientUpdateChannel();

  static const _channel = MethodChannel('client_update');

  /// 用系统默认浏览器打开 [url]；失败返回 false（界面据此提示手动复制链接）。
  Future<bool> openUrl(String url) async {
    final value = url.trim();
    if (value.isEmpty) return false;
    try {
      return await _channel.invokeMethod<bool>('openUrl', {'url': value}) ==
          true;
    } on PlatformException {
      return false;
    } on MissingPluginException {
      return false;
    }
  }

  /// Android：系统是否允许本应用「安装未知来源应用」。其它平台恒为 true。
  Future<bool> canInstallPackages() async {
    if (!Platform.isAndroid) return true;
    try {
      return await _channel.invokeMethod<bool>('canInstallPackages') == true;
    } on PlatformException {
      return true;
    } on MissingPluginException {
      return true;
    }
  }

  /// Android：跳到「安装未知应用」授权页，用户同意后回来再点一次更新即可。
  Future<void> requestInstallPermission() async {
    if (!Platform.isAndroid) return;
    try {
      await _channel.invokeMethod<void>('requestInstallPermission');
    } on PlatformException {
      // 少数 ROM 没有这个入口：下次点更新仍然会尝试拉起安装器。
    } on MissingPluginException {
      // 非 Android 构建没有该处理器。
    }
  }

  /// Android：拉起系统安装器。返回 `launched` / `permission-required` / `failed`。
  Future<String> installApk(String path) async {
    if (!Platform.isAndroid) return 'failed';
    try {
      final result =
          await _channel.invokeMethod<String>('installApk', {'path': path});
      return result ?? 'failed';
    } on PlatformException {
      return 'failed';
    } on MissingPluginException {
      return 'failed';
    }
  }
}
