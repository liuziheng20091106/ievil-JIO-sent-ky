import 'dart:async';
import 'dart:io';

import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

import 'api.dart';
import 'models.dart';
import 'platform_channel.dart';
import 'release.dart';

/// 更新流程的阶段：界面据此决定显示进度、安装按钮还是重试。
enum UpdateStage {
  idle,
  downloading,
  downloaded,
  installing,
  launching,
  failed,
  unsupported,
}

class UpdateProgress {
  const UpdateProgress(
    this.stage, {
    this.received = 0,
    this.total = -1,
    this.message,
  });

  final UpdateStage stage;
  final int received;
  final int total;
  final String? message;

  /// 服务端没给 Content-Length 时为 null（界面退化成不确定进度条）。
  double? get fraction =>
      total > 0 ? (received / total).clamp(0, 1).toDouble() : null;
}

/// 交给界面处理的安装结果。
enum UpdateOutcome { launched, permissionRequired, failed, unsupported }

class UpdateResult {
  const UpdateResult(this.outcome, {this.message});

  final UpdateOutcome outcome;
  final String? message;

  bool get ok => outcome == UpdateOutcome.launched;
}

/// 下载实现的注入点（默认走 [GameApi.downloadTo]，测试里换成假实现）。
typedef UpdateDownload = Future<int> Function(
  String url,
  File target, {
  void Function(int received, int total)? onProgress,
  bool Function()? isCancelled,
});

/// 启动更新器进程的注入点（默认分离启动，测试里只记录参数）。
typedef UpdateProcessLauncher = Future<void> Function(
  String executable,
  List<String> arguments,
);

/// 删除文件，失败不抛：删不掉只影响缓存占用，下次启动再试。
Future<void> deleteQuietly(File file) async {
  try {
    if (file.existsSync()) await file.delete();
  } on FileSystemException {
    // 忽略：文件可能正被系统占用。
  }
}

/// 应用内更新的平台实现。
///
/// - Android：把 APK 下到应用缓存目录，再交给系统安装器；同一版本的包只下一次。
/// - Windows：把最新 Updater 下到 `%LOCALAPPDATA%\MagicJudge\`，由它准备更新环境、
///   在后台静默替换程序并重启客户端，客户端随即退出让出文件锁。
abstract class UpdateInstaller {
  UpdateInstaller({
    required this.stagingDirectory,
    UpdateDownload? download,
    UpdateProcessLauncher? launchProcess,
    Future<void> Function()? exitApp,
    this.channel = const ClientUpdateChannel(),
  })  : _download = download,
        _launchProcess = launchProcess,
        _exitApp = exitApp;

  final Directory stagingDirectory;
  final UpdateDownload? _download;
  final UpdateProcessLauncher? _launchProcess;
  final Future<void> Function()? _exitApp;
  final ClientUpdateChannel channel;

  /// 按平台创建安装器；测试直接构造具体实现，不经过这里。
  static Future<UpdateInstaller> create() async {
    if (Platform.isAndroid) {
      final cache = await getTemporaryDirectory();
      return AndroidUpdateInstaller(
        stagingDirectory: Directory(p.join(cache.path, 'updates')),
      );
    }
    if (Platform.isWindows) {
      final local = Platform.environment['LOCALAPPDATA'] ?? '';
      return WindowsUpdateInstaller(
        // 与 Updater 自己的约定路径一致：%LOCALAPPDATA%\MagicJudge\
        stagingDirectory: Directory(p.join(
          local.isEmpty ? Directory.systemTemp.path : local,
          'MagicJudge',
        )),
        installDirectory: File(Platform.resolvedExecutable).parent,
      );
    }
    return UnsupportedUpdateInstaller(stagingDirectory: Directory.systemTemp);
  }

  /// 开始更新。返回值表示「已交给系统 / 更新器」还是需要用户再操作一次。
  Future<UpdateResult> start({
    required GameApi api,
    required ClientUpdateInfo info,
    void Function(UpdateProgress progress)? onProgress,
    bool Function()? isCancelled,
  });

  /// 清理上一次更新留下的安装包（Android：版本号不高于当前版本的残留）。
  Future<void> cleanupStale(String currentVersion) async {}

  Future<int> download(
    GameApi api,
    String url,
    File target, {
    void Function(int received, int total)? onProgress,
    bool Function()? isCancelled,
  }) {
    final custom = _download;
    if (custom != null) {
      return custom(url, target,
          onProgress: onProgress, isCancelled: isCancelled);
    }
    return api.downloadTo(url, target,
        onProgress: onProgress, isCancelled: isCancelled);
  }

  Future<void> exitApplication() async {
    final custom = _exitApp;
    if (custom != null) {
      await custom();
      return;
    }
    exit(0);
  }

  /// 分离启动更新器进程（它要等本进程退出，所以不等待它结束）。
  Future<void> launchProcess(String executable, List<String> arguments) async {
    final custom = _launchProcess;
    if (custom != null) {
      await custom(executable, arguments);
      return;
    }
    await Process.start(executable, arguments, mode: ProcessStartMode.detached);
  }

  /// 服务端下发的包大小：为 0 表示没有可校验的信息，只要文件在就算数。
  static bool matchesSize(File file, int size) {
    if (!file.existsSync() || file.lengthSync() <= 0) return false;
    return size <= 0 || file.lengthSync() == size;
  }
}

class AndroidUpdateInstaller extends UpdateInstaller {
  AndroidUpdateInstaller({
    required super.stagingDirectory,
    super.download,
    super.exitApp,
    super.channel,
  });

  /// 同一版本固定同一个文件名：重复点「更新」直接复用，不重复下载。
  File apkFile(String version) =>
      File(p.join(stagingDirectory.path, 'magicjudge-$version.apk'));

  @override
  Future<UpdateResult> start({
    required GameApi api,
    required ClientUpdateInfo info,
    void Function(UpdateProgress progress)? onProgress,
    bool Function()? isCancelled,
  }) async {
    if (!info.hasDownload) {
      const message = '服务端没有下发安装包地址';
      onProgress?.call(const UpdateProgress(UpdateStage.failed, message: message));
      return const UpdateResult(UpdateOutcome.failed, message: message);
    }
    File apk;
    try {
      apk = await ensureApk(
        api: api,
        info: info,
        onProgress: onProgress,
        isCancelled: isCancelled,
      );
    } on ApiException catch (failure) {
      onProgress
          ?.call(UpdateProgress(UpdateStage.failed, message: failure.message));
      return UpdateResult(UpdateOutcome.failed, message: failure.message);
    } on SocketException catch (failure) {
      final message = '无法连接服务器：${failure.message}';
      onProgress?.call(UpdateProgress(UpdateStage.failed, message: message));
      return UpdateResult(UpdateOutcome.failed, message: message);
    }

    if (!await channel.canInstallPackages()) {
      // 安装包留着：用户授权回来再点一次「更新」就直接进安装，不会重下。
      await channel.requestInstallPermission();
      const message = '请先允许「安装未知应用」，授权后回来再点一次更新';
      onProgress?.call(const UpdateProgress(UpdateStage.failed, message: message));
      return const UpdateResult(UpdateOutcome.permissionRequired,
          message: message);
    }

    onProgress?.call(const UpdateProgress(UpdateStage.installing));
    final result = await channel.installApk(apk.path);
    if (result == 'permission-required') {
      await channel.requestInstallPermission();
      const message = '请先允许「安装未知应用」';
      onProgress?.call(const UpdateProgress(UpdateStage.failed, message: message));
      return const UpdateResult(UpdateOutcome.permissionRequired,
          message: message);
    }
    if (result != 'launched') {
      // 连安装器都拉不起来：这份包已经没用了，删掉避免占地方。
      await deleteQuietly(apk);
      const message = '无法拉起系统安装器，请手动安装最新版本';
      onProgress?.call(const UpdateProgress(UpdateStage.failed, message: message));
      return const UpdateResult(UpdateOutcome.failed, message: message);
    }
    onProgress?.call(const UpdateProgress(UpdateStage.launching,
        message: '已交给系统安装：安装完成后应用会重新打开'));
    return const UpdateResult(UpdateOutcome.launched);
  }

  /// 下载（或复用）安装包。已经有同版本、大小对得上的包就不再下载。
  Future<File> ensureApk({
    required GameApi api,
    required ClientUpdateInfo info,
    void Function(UpdateProgress progress)? onProgress,
    bool Function()? isCancelled,
  }) async {
    await stagingDirectory.create(recursive: true);
    final target = apkFile(info.latest);
    if (UpdateInstaller.matchesSize(target, info.size)) {
      onProgress?.call(UpdateProgress(
        UpdateStage.downloaded,
        received: target.lengthSync(),
        total: target.lengthSync(),
        message: '安装包已下载，直接安装',
      ));
      return target;
    }
    await deleteQuietly(target);

    final part = File('${target.path}.part');
    await deleteQuietly(part);
    onProgress?.call(const UpdateProgress(UpdateStage.downloading));
    try {
      await download(
        api,
        info.url,
        part,
        onProgress: (received, total) => onProgress?.call(
            UpdateProgress(UpdateStage.downloading,
                received: received, total: total)),
        isCancelled: isCancelled,
      );
      if (info.size > 0 && part.lengthSync() != info.size) {
        throw const ApiException('安装包不完整，请重试');
      }
      await part.rename(target.path);
    } catch (_) {
      await deleteQuietly(part);
      rethrow;
    }
    onProgress?.call(UpdateProgress(
      UpdateStage.downloaded,
      received: target.lengthSync(),
      total: target.lengthSync(),
    ));
    return target;
  }

  /// 启动时清理残留安装包：版本号不高于当前运行版本的都删掉。
  /// 升级成功后本进程跑的就是新版本，上一份包在下次启动被清掉；安装失败或被放弃时
  /// 同样在下次启动清掉，不会一直占着缓存目录。
  @override
  Future<void> cleanupStale(String currentVersion) async {
    if (!stagingDirectory.existsSync()) return;
    final pattern = RegExp(r'^magicjudge-(\d+\.\d+\.\d+)\.apk$');
    for (final entry in stagingDirectory.listSync()) {
      if (entry is! File) continue;
      final name = p.basename(entry.path);
      if (name.endsWith('.part')) {
        await deleteQuietly(entry);
        continue;
      }
      final match = pattern.firstMatch(name);
      if (match == null) continue;
      final comparison = compareVersionTags(match.group(1), currentVersion);
      if (comparison == null || comparison <= 0) {
        await deleteQuietly(entry);
      }
    }
  }
}

class WindowsUpdateInstaller extends UpdateInstaller {
  WindowsUpdateInstaller({
    required super.stagingDirectory,
    required this.installDirectory,
    super.download,
    super.launchProcess,
    super.exitApp,
    super.channel,
  });

  /// 客户端程序所在目录：更新替换的就是它里面的文件。
  final Directory installDirectory;

  File get stagedUpdater => File(p.join(stagingDirectory.path, 'Updater.exe'));

  @override
  Future<UpdateResult> start({
    required GameApi api,
    required ClientUpdateInfo info,
    void Function(UpdateProgress progress)? onProgress,
    bool Function()? isCancelled,
  }) async {
    await stagingDirectory.create(recursive: true);
    // ① 更新 Updater：更新器很小，每次都取最新的一份，避免旧更新器不认新参数。
    final updater = stagedUpdater;
    final part = File('${updater.path}.part');
    await deleteQuietly(part);
    onProgress?.call(const UpdateProgress(UpdateStage.downloading,
        message: '正在下载更新器'));
    try {
      await download(
        api,
        info.resolvedUpdaterUrl,
        part,
        onProgress: (received, total) => onProgress?.call(
            UpdateProgress(UpdateStage.downloading,
                received: received, total: total)),
        isCancelled: isCancelled,
      );
      await deleteQuietly(updater);
      await part.rename(updater.path);
    } on ApiException catch (failure) {
      await deleteQuietly(part);
      onProgress
          ?.call(UpdateProgress(UpdateStage.failed, message: failure.message));
      return UpdateResult(UpdateOutcome.failed, message: failure.message);
    } on SocketException catch (failure) {
      await deleteQuietly(part);
      final message = '无法连接服务器：${failure.message}';
      onProgress?.call(UpdateProgress(UpdateStage.failed, message: message));
      return UpdateResult(UpdateOutcome.failed, message: message);
    }

    // ② 让 Updater 初始化自身并准备更新环境；③ 由它静默替换程序并重启客户端。
    onProgress?.call(const UpdateProgress(UpdateStage.installing,
        message: '正在准备静默更新'));
    try {
      final executable = File(Platform.resolvedExecutable);
      await launchProcess(updater.path, [
        '--update-app',
        '--from', api.endpoint.toString(),
        '--target', installDirectory.path,
        '--restart', executable.path,
        '--wait-pid', pid.toString(),
        '--silent',
      ]);
    } on ProcessException catch (failure) {
      final message = '无法启动更新器：${failure.message}';
      onProgress?.call(UpdateProgress(UpdateStage.failed, message: message));
      return UpdateResult(UpdateOutcome.failed, message: message);
    }
    onProgress?.call(const UpdateProgress(UpdateStage.launching,
        message: '正在静默更新，客户端会自动重启'));
    await exitApplication();
    return const UpdateResult(UpdateOutcome.launched);
  }
}

class UnsupportedUpdateInstaller extends UpdateInstaller {
  UnsupportedUpdateInstaller({required super.stagingDirectory});

  @override
  Future<UpdateResult> start({
    required GameApi api,
    required ClientUpdateInfo info,
    void Function(UpdateProgress progress)? onProgress,
    bool Function()? isCancelled,
  }) async =>
      const UpdateResult(UpdateOutcome.unsupported,
          message: '当前平台不支持应用内更新，请手动下载最新版本');
}
