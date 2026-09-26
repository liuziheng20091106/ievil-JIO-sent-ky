// 应用内更新的回归检查：UA 带版本、更新信息解析、online→health 复检去重、
// 安卓安装包的复用与残留清理、Windows 交给 Updater 的参数。
//
// 运行方式（client 目录）：flutter test test/client_update_test.dart

import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:path/path.dart' as p;
import 'package:seven_double_client/src/api.dart';
import 'package:seven_double_client/src/client_version.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/platform_channel.dart';
import 'package:seven_double_client/src/release.dart';
import 'package:seven_double_client/src/update_installer.dart';
import 'package:shared_preferences/shared_preferences.dart';

Map<String, dynamic> updatePayload({
  String latest = '1.2.0',
  String? minimum,
  bool required = false,
  String notes = '## 更新日志\n- 修好了下载',
  String url = '/releases/app-release.apk',
  String guideUrl = '',
  int size = 0,
}) =>
    {
      'platform': 'android',
      'latest': latest,
      'minimum': minimum,
      'required': required,
      'title': '发现新版本',
      'notes': notes,
      'url': url,
      'updater_url': '',
      'guide_url': guideUrl,
      'sha256': '',
      'size': size,
    };

/// 记录下载次数与内容的假下载器。
class FakeDownloader {
  int calls = 0;
  final List<String> urls = [];
  List<int> bytes = utf8.encode('apk-bytes');

  Future<int> call(
    String url,
    File target, {
    void Function(int received, int total)? onProgress,
    bool Function()? isCancelled,
  }) async {
    calls++;
    urls.add(url);
    onProgress?.call(0, bytes.length);
    if (isCancelled?.call() ?? false) {
      throw const ApiException('已取消下载');
    }
    await target.writeAsBytes(bytes);
    onProgress?.call(bytes.length, bytes.length);
    return bytes.length;
  }
}

/// 假平台通道：安装结果可控，不碰真实 MethodChannel。
class FakeChannel extends ClientUpdateChannel {
  FakeChannel({
    this.allowed = true,
    this.installResult = 'launched',
    this.openResult = true,
  });

  bool allowed;
  String installResult;
  bool openResult;
  int permissionRequests = 0;
  final List<String> installed = [];

  @override
  Future<bool> canInstallPackages() async => allowed;

  @override
  Future<void> requestInstallPermission() async => permissionRequests++;

  @override
  Future<String> installApk(String path) async {
    installed.add(path);
    return installResult;
  }

  @override
  Future<bool> openUrl(String url) async => openResult;
}

GameApi offlineApi() =>
    GameApi(ServerEndpoint.parse('http://127.0.0.1:9'));

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('请求 UA 带版本号', () {
    test('本客户端 UA 形状固定且含平台', () {
      final agent = clientUserAgent();
      expect(agent, startsWith('seven-double-flutter/$kClientVersion ('));
      expect(agent, endsWith(')'));
      // 服务端的解析正则只认这个形状。
      expect(
        RegExp(r'^seven-double-flutter/\d+\.\d+\.\d+ \((windows|android|other)\)$')
            .hasMatch(agent),
        isTrue,
        reason: agent,
      );
    });

    test('Updater 用独立 UA 取 Windows 更新包', () {
      expect(updaterUserAgent('1.2.0'), 'magicjudge-updater/1.2.0 (windows)');
    });

    test('内置版本号非空且三段数字', () {
      expect(compareVersionTags(kClientVersion, kClientVersion), 0);
    });
  });

  group('更新信息解析', () {
    test('从 /api/health 的 update 字段读全字段', () {
      final monitor = ReleaseMonitor(currentVersion: '1.0.0');
      monitor.applyHealthPayload({
        'client_latest': '1.2.0',
        'client_minimum': '1.0.0',
        'update': updatePayload(notes: '## 日志', guideUrl: 'https://x.invalid'),
      });
      final info = monitor.updateInfo!;
      expect(info.latest, '1.2.0');
      expect(info.notes, '## 日志');
      expect(info.guideUrl, 'https://x.invalid');
      expect(info.hasDownload, isTrue);
      expect(info.hasGuide, isTrue);
      expect(monitor.updateAvailable, isTrue);
      expect(monitor.updateRequired, isFalse);
      expect(monitor.updateNoticeVisible, isTrue);
    });

    test('低于 minimum 判为强制更新，横幅不给关闭', () {
      final monitor = ReleaseMonitor(currentVersion: '1.0.0');
      monitor.applyHealthPayload({
        'client_latest': '1.2.0',
        'client_minimum': '1.1.0',
        'update': updatePayload(minimum: '1.1.0', required: true),
      });
      expect(monitor.updateRequired, isTrue);
      expect(monitor.updateAvailable, isFalse);
    });

    test('服务端只给版本标签（旧式配置）时仍然算有更新', () {
      final monitor = ReleaseMonitor(currentVersion: '1.0.0');
      monitor.applyHealthPayload({
        'client_latest': '1.2.0',
        'client_minimum': null,
        'update': null,
      });
      expect(monitor.updateAvailable, isTrue);
      expect(monitor.updateInfo, isNull);
    });

    test('已经是最新版时不提示', () {
      final monitor = ReleaseMonitor(currentVersion: '1.2.0');
      monitor.applyHealthPayload({
        'client_latest': '1.2.0',
        'client_minimum': null,
        'update': null,
      });
      expect(monitor.updateAvailable, isFalse);
    });

    test('Windows 没配 updater_url 时退回同源约定路径', () {
      final info = ClientUpdateInfo.fromJson({
        ...updatePayload(url: '/releases/魔法裁判Windows.zip'),
        'platform': 'windows',
      });
      expect(info.resolvedUpdaterUrl, '/releases/Updater.exe');
      expect(info.url, '/releases/魔法裁判Windows.zip');
    });

    test('关掉横幅不影响「有更新」判断（大厅入口靠它）', () async {
      SharedPreferences.setMockInitialValues({});
      final preferences = await SharedPreferences.getInstance();
      final monitor = ReleaseMonitor(
        currentVersion: '1.0.0',
        preferences: preferences,
      )
        ..applyHealthPayload({
          'client_latest': '1.2.0',
          'client_minimum': null,
          'update': updatePayload(),
        });
      await monitor.dismissUpdateNotice();
      expect(monitor.updateNoticeVisible, isFalse);
      expect(monitor.updateAvailable, isTrue);
    });
  });

  group('online 回报有更新时复检 health', () {
    test('同一服务地址同一标签只查一次，换地址或换标签才再查', () async {
      final monitor = ReleaseMonitor(currentVersion: '1.0.0');
      final first = ServerEndpoint.parse('http://127.0.0.1:9');
      final second = ServerEndpoint.parse('http://127.0.0.1:10');

      expect(monitor.shouldRecheckFromOnline(first), isTrue);
      // 离线环境下这次请求会失败，但去重状态照样要落下来。
      await monitor.checkFromOnline(first);
      expect(monitor.shouldRecheckFromOnline(first), isFalse);
      expect(monitor.shouldRecheckFromOnline(second), isTrue);

      monitor.applyVersionTags(latest: '1.2.0', minimum: null);
      await monitor.checkFromOnline(first);
      expect(monitor.shouldRecheckFromOnline(first), isFalse);
      // 服务端换了 latest 标签（版本真的变了）就应当再查一次。
      monitor.applyVersionTags(latest: '1.3.0', minimum: null);
      expect(monitor.shouldRecheckFromOnline(first), isTrue);
      // 超过去重窗口也会再查。
      expect(
        monitor.shouldRecheckFromOnline(
          first,
          now: DateTime.now().add(ReleaseMonitor.onlineRecheckWindow * 2),
        ),
        isTrue,
      );
    });
  });

  group('安卓安装包：不重复下载、失败清理', () {
    late Directory staging;
    late FakeDownloader downloader;
    late FakeChannel channel;

    setUp(() async {
      staging = await Directory.systemTemp.createTemp('mj-update-test');
      downloader = FakeDownloader();
      channel = FakeChannel();
    });

    tearDown(() async {
      if (staging.existsSync()) await staging.delete(recursive: true);
    });

    AndroidUpdateInstaller installer() => AndroidUpdateInstaller(
          stagingDirectory: staging,
          download: downloader.call,
          channel: channel,
        );

    ClientUpdateInfo info({int size = 0}) => ClientUpdateInfo.fromJson(
        updatePayload(latest: '1.2.0', size: size, url: '/releases/app.apk'));

    test('同一版本只下载一次，重复点更新复用已下载的包', () async {
      final apkBytes = downloader.bytes.length;
      final instance = installer();
      final first = await instance.start(
        api: offlineApi(),
        info: info(size: apkBytes),
      );
      expect(first.outcome, UpdateOutcome.launched);
      expect(downloader.calls, 1);

      final second = await instance.start(
        api: offlineApi(),
        info: info(size: apkBytes),
      );
      expect(second.outcome, UpdateOutcome.launched);
      expect(downloader.calls, 1, reason: '已经有同版本安装包就不该再下');
    });

    test('没授权「安装未知应用」时保留安装包并引导授权', () async {
      channel.allowed = false;
      final instance = installer();
      final result = await instance.start(
        api: offlineApi(),
        info: info(size: downloader.bytes.length),
      );
      expect(result.outcome, UpdateOutcome.permissionRequired);
      expect(channel.permissionRequests, 1);
      expect(instance.apkFile('1.2.0').existsSync(), isTrue,
          reason: '授权后回来再点一次要能直接安装');
      expect(channel.installed, isEmpty);
    });

    test('安装器拉不起来时删掉这份没用的安装包', () async {
      channel.installResult = 'failed';
      final instance = installer();
      final result = await instance.start(
        api: offlineApi(),
        info: info(size: downloader.bytes.length),
      );
      expect(result.outcome, UpdateOutcome.failed);
      expect(instance.apkFile('1.2.0').existsSync(), isFalse);
    });

    test('下载不完整（大小对不上）时报错并删掉半成品', () async {
      final instance = installer();
      final result = await instance.start(
        api: offlineApi(),
        info: info(size: downloader.bytes.length + 10),
      );
      expect(result.outcome, UpdateOutcome.failed);
      expect(instance.apkFile('1.2.0').existsSync(), isFalse);
      expect(
        staging.listSync().where((entry) => entry.path.endsWith('.part')),
        isEmpty,
      );
    });

    test('启动清理：删掉不高于当前版本的残留与半成品，保留更高版本的包', () async {
      final instance = installer();
      await File(p.join(staging.path, 'magicjudge-1.0.9.apk')).writeAsBytes([1]);
      await File(p.join(staging.path, 'magicjudge-1.1.0.apk')).writeAsBytes([1]);
      await File(p.join(staging.path, 'magicjudge-1.2.0.apk')).writeAsBytes([1]);
      await File(p.join(staging.path, 'magicjudge-1.3.0.apk.part')).writeAsBytes([1]);

      await instance.cleanupStale('1.1.0');

      final names = staging
          .listSync()
          .map((entry) => p.basename(entry.path))
          .toList()
        ..sort();
      expect(names, ['magicjudge-1.2.0.apk']);
    });
  });

  group('Windows 交给 Updater 的参数', () {
    late Directory staging;
    late Directory install;
    late FakeDownloader downloader;
    final launched = <String>[];
    final arguments = <String>[];
    var exited = 0;

    setUp(() async {
      staging = await Directory.systemTemp.createTemp('mj-updater-test');
      install = await Directory.systemTemp.createTemp('mj-install-test');
      downloader = FakeDownloader();
      launched.clear();
      arguments.clear();
      exited = 0;
    });

    tearDown(() async {
      for (final directory in [staging, install]) {
        if (directory.existsSync()) await directory.delete(recursive: true);
      }
    });

    test('先下载最新 Updater，再让它准备环境并静默更新', () async {
      final installer = WindowsUpdateInstaller(
        stagingDirectory: staging,
        installDirectory: install,
        download: downloader.call,
        launchProcess: (executable, args) async {
          launched.add(executable);
          arguments.addAll(args);
        },
        exitApp: () async => exited++,
        channel: FakeChannel(),
      );
      final info = ClientUpdateInfo.fromJson({
        ...updatePayload(url: '/releases/魔法裁判Windows.zip'),
        'platform': 'windows',
      });
      final result = await installer.start(api: offlineApi(), info: info);

      expect(result.outcome, UpdateOutcome.launched);
      expect(downloader.urls, ['/releases/Updater.exe']);
      expect(installer.stagedUpdater.existsSync(), isTrue);
      expect(launched.single, installer.stagedUpdater.path);
      expect(arguments.first, '--update-app');
      expect(arguments, containsAll(<String>['--from', '--target', '--restart', '--wait-pid']));
      expect(arguments, contains('--silent'));
      expect(arguments[arguments.indexOf('--target') + 1], install.path);
      expect(arguments[arguments.indexOf('--restart') + 1],
          File(Platform.resolvedExecutable).path);
      expect(arguments[arguments.indexOf('--wait-pid') + 1], '$pid');
      expect(exited, 1, reason: '更新器要等本进程退出才能替换文件');
    });

    test('更新器下载失败时不启动任何进程', () async {
      var launchedAny = false;
      final installer = WindowsUpdateInstaller(
        stagingDirectory: staging,
        installDirectory: install,
        download: (url, target, {onProgress, isCancelled}) async =>
            throw const ApiException('下载超时'),
        launchProcess: (executable, args) async => launchedAny = true,
        exitApp: () async => exited++,
        channel: FakeChannel(),
      );
      final info = ClientUpdateInfo.fromJson({
        ...updatePayload(url: '/releases/win.zip'),
        'platform': 'windows',
      });
      final result = await installer.start(api: offlineApi(), info: info);
      expect(result.outcome, UpdateOutcome.failed);
      expect(launchedAny, isFalse);
      expect(exited, 0);
    });
  });
}
