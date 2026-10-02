import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

import 'api.dart';
import 'models.dart';

const resourcePackNames = ['animation', 'memes'];
const _mediaExtensions = {
  '.png',
  '.jpg',
  '.jpeg',
  '.gif',
  '.webp',
  '.bmp',
  '.svg',
  '.avif',
  '.mp3',
  '.wav',
  '.ogg',
  '.flac',
  '.mp4',
  '.webm',
};
final _md5Pattern = RegExp(r'^[0-9a-f]{32}$');
final _invalidPathCharacters = RegExp(r'[\x00-\x1f\x7f\\:<>"|?*]');
final _reservedName = RegExp(r'^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)',
    caseSensitive: false);

void _validatePack(String pack) {
  if (!resourcePackNames.contains(pack)) {
    throw const FormatException('未知资源包');
  }
}

bool isAnimationScriptPath(String path) =>
    path.startsWith('scripts/') &&
    p.posix.extension(path).toLowerCase() == '.json' &&
    p.posix.basename(path).toLowerCase() != 'manifest.json';

void _validatePath(String pack, String path) {
  final parts = path.split('/');
  if (path.isEmpty ||
      path.length > 1024 ||
      _invalidPathCharacters.hasMatch(path) ||
      parts.any((part) =>
          part.isEmpty ||
          part.length > 255 ||
          part.startsWith('.') ||
          part.startsWith('~') ||
          part.endsWith('.') ||
          part.endsWith(' ') ||
          _reservedName.hasMatch(part)) ||
      (!_mediaExtensions.contains(p.posix.extension(path).toLowerCase()) &&
          !(pack == 'animation' && isAnimationScriptPath(path)))) {
    throw FormatException('资源路径不安全：$path');
  }
}

String animationImagePath(String scriptPath, Object? folder, Object? image) {
  const extensions = {
    '.png',
    '.jpg',
    '.jpeg',
    '.gif',
    '.webp',
    '.bmp',
    '.avif'
  };
  if (folder is! String ||
      (folder.isNotEmpty && !folder.endsWith('/')) ||
      image is! String ||
      !extensions.contains(p.posix.extension(image).toLowerCase())) {
    throw const FormatException('动画图片路径不安全');
  }
  _validatePath('animation', scriptPath);
  _validatePath('animation', image);
  final path = '${p.posix.dirname(scriptPath)}/$folder$image';
  _validatePath('animation', path);
  return path;
}

int _size(Object? value) {
  if (value is! int || value < 0 || value > 9007199254740991) {
    throw const FormatException('资源大小不合法');
  }
  return value;
}

String _hash(Object? value) {
  if (value is! String || !_md5Pattern.hasMatch(value)) {
    throw const FormatException('资源 MD5 不合法');
  }
  return value;
}

int _comparePaths(String first, String second) {
  final left = first.runes.iterator;
  final right = second.runes.iterator;
  while (left.moveNext()) {
    if (!right.moveNext()) return 1;
    final order = left.current.compareTo(right.current);
    if (order != 0) return order;
  }
  return right.moveNext() ? -1 : 0;
}

class ResourcePackFile {
  const ResourcePackFile(
      {required this.path, required this.size, required this.md5});
  final String path;
  final int size;
  final String md5;

  Map<String, dynamic> toJson() => {'path': path, 'size': size, 'md5': md5};
}

class ResourcePackManifest {
  ResourcePackManifest._(this.pack, this.version, this.totalSize, this.files);

  factory ResourcePackManifest.fromJson(Object? value, {required String pack}) {
    _validatePack(pack);
    final raw = jsonObject(value, 'resource manifest');
    if (raw['pack'] != pack) throw const FormatException('资源包名称不一致');
    final version = _hash(raw['version']);
    final total = _size(raw['total_size']);
    final files = <ResourcePackFile>[];
    final paths = <String>{};
    var sum = 0;
    for (final value in jsonArray(raw['files'], 'resource files')) {
      final file = jsonObject(value, 'resource file');
      final path = jsonString(file['path'], 'resource path');
      _validatePath(pack, path);
      if (files.isNotEmpty && _comparePaths(files.last.path, path) >= 0) {
        throw const FormatException('资源清单未按路径排序');
      }
      if (!paths.add(path.toUpperCase().toLowerCase())) {
        throw FormatException('资源路径重复：$path');
      }
      final size = _size(file['size']);
      sum += size;
      if (sum > 9007199254740991) throw const FormatException('资源总大小过大');
      files.add(
          ResourcePackFile(path: path, size: size, md5: _hash(file['md5'])));
    }
    for (final path in paths) {
      final parts = path.split('/');
      for (var i = 1; i < parts.length; i++) {
        if (paths.contains(parts.take(i).join('/'))) {
          throw FormatException('资源文件与目录冲突：$path');
        }
      }
    }
    if (sum != total) throw const FormatException('资源总大小不一致');
    return ResourcePackManifest._(
        pack, version, total, List.unmodifiable(files));
  }

  final String pack;
  final String version;
  final int totalSize;
  final List<ResourcePackFile> files;

  Map<String, dynamic> toJson() => {
        'pack': pack,
        'version': version,
        'total_size': totalSize,
        'files': files.map((file) => file.toJson()).toList(),
      };
}

class ResourcePackCheck {
  const ResourcePackCheck(
      {required this.pack,
      this.remote,
      this.local,
      this.unpublished = false,
      this.error});
  final String pack;
  final ResourcePackManifest? remote;
  final ResourcePackManifest? local;
  final bool unpublished;
  final String? error;
  bool get needsDownload => remote != null && remote!.version != local?.version;
}

class ResourcePackProgress {
  const ResourcePackProgress(this.received, this.total, this.path,
      {this.verifying = false});
  final int received;
  final int total;
  final String path;
  final bool verifying;
  double get fraction =>
      total == 0 ? 1 : (received / total).clamp(0, 1).toDouble();
}

class ResourceDownloadCancelled implements Exception {
  const ResourceDownloadCancelled();
  @override
  String toString() => '已取消下载';
}

/// 内容按 MD5 共享保存；完整下载通过校验后才替换所选包的路径映射。
class ResourcePacks {
  ResourcePacks({required this.api, required this.supportDirectory});
  final GameApi api;
  final Directory supportDirectory;
  static final _updating = <String>{};

  static Future<ResourcePacks> create(GameApi api) async => ResourcePacks(
      api: api, supportDirectory: await getApplicationSupportDirectory());

  Directory get directory =>
      Directory(p.join(supportDirectory.path, 'resources'));

  File _safeFile(Directory base, String relative) {
    final target = p.normalize(p.absolute(p.join(base.path, relative)));
    final root = p.normalize(p.absolute(base.path));
    if (!p.isWithin(root, target)) throw const FormatException('资源路径越界');
    // 系统提供的应用目录上层可有别名（Android /data 等）；只检查应用内缓存。
    var current = p.normalize(p.absolute(supportDirectory.path));
    for (final part in p.split(p.relative(target, from: current))) {
      current = p.join(current, part);
      if (FileSystemEntity.typeSync(current, followLinks: false) ==
          FileSystemEntityType.link) {
        throw const FormatException('资源缓存含符号链接');
      }
    }
    return File(target);
  }

  Future<bool> _matches(File file, ResourcePackFile expected) async {
    if (await FileSystemEntity.type(file.path, followLinks: false) !=
            FileSystemEntityType.file ||
        await file.length() != expected.size) {
      return false;
    }
    return (await md5.bind(file.openRead()).first).toString() == expected.md5;
  }

  Future<ResourcePackManifest?> _local(String pack) async {
    _validatePack(pack);
    final file = _safeFile(directory, '$pack.json');
    if (!await file.exists()) return null;
    return ResourcePackManifest.fromJson(jsonDecode(await file.readAsString()),
        pack: pack);
  }

  Future<ResourcePackManifest?> localManifest(String pack) async {
    final manifest = await _local(pack);
    for (final file in manifest?.files ?? <ResourcePackFile>[]) {
      if (!await _matches(_safeFile(directory, file.md5), file)) {
        throw FormatException('本地资源校验失败：${file.path}');
      }
    }
    return manifest;
  }

  Future<ResourcePackCheck> check(String pack) async {
    _validatePack(pack);
    ResourcePackManifest? local;
    String? localError;
    try {
      local = await localManifest(pack);
    } catch (error) {
      localError = '本地缓存不可用：$error';
    }
    try {
      final remote = ResourcePackManifest.fromJson(
          await api.resourceManifest(pack),
          pack: pack);
      return ResourcePackCheck(
          pack: pack, remote: remote, local: local, error: localError);
    } on ApiException catch (error) {
      return ResourcePackCheck(
          pack: pack,
          local: local,
          unpublished: error.statusCode == 404,
          error: error.statusCode == 404 ? localError : '检查失败：$error');
    } catch (error) {
      return ResourcePackCheck(pack: pack, local: local, error: '检查失败：$error');
    }
  }

  Future<List<ResourcePackCheck>> checkAll() =>
      Future.wait(resourcePackNames.map(check));

  Future<String?> filePath(String pack, String path) async {
    _validatePack(pack);
    _validatePath(pack, path);
    try {
      final manifest = await _local(pack);
      for (final file in manifest?.files ?? <ResourcePackFile>[]) {
        if (file.path == path) {
          final target = _safeFile(directory, file.md5);
          return await _matches(target, file) ? target.path : null;
        }
      }
    } on FileSystemException {
      return null;
    } on FormatException {
      return null;
    }
    return null;
  }

  /// 接收表情读取共享 MD5 缓存，不依赖任何包的路径映射。
  Future<File?> cachedMeme(String hash) async {
    if (!_md5Pattern.hasMatch(hash)) return null;
    try {
      final file = _safeFile(directory, hash);
      if (await FileSystemEntity.type(file.path, followLinks: false) !=
          FileSystemEntityType.file) {
        return null;
      }
      return (await md5.bind(file.openRead()).first).toString() == hash
          ? file
          : null;
    } on FileSystemException {
      return null;
    } on FormatException {
      return null;
    }
  }

  Future<void> _cleanUnused() async {
    final referenced = <String>{};
    for (final pack in resourcePackNames) {
      try {
        final manifest = ResourcePackManifest.fromJson(
            await api.resourceManifest(pack),
            pack: pack);
        referenced.addAll(manifest.files.map((file) => file.md5));
      } on ApiException catch (error) {
        if (error.statusCode != 404) rethrow;
      }
    }
    // 两份服务端清单均已取得后才删除；未下载的包不需要安装，也不会误删共享内容。
    await for (final entity in directory.list(followLinks: false)) {
      final name = p.basename(entity.path);
      if ((entity is File || entity is Link) &&
          !resourcePackNames.any((pack) => name == '$pack.json') &&
          !referenced.contains(name)) {
        await entity.delete();
      }
    }
  }

  Future<void> download(
    ResourcePackManifest manifest, {
    void Function(ResourcePackProgress progress)? onProgress,
    bool Function()? isCancelled,
  }) async {
    final lock = p.normalize(p.absolute(directory.path));
    if (!_updating.add(lock)) throw const ApiException('资源包正在更新');
    Directory? stage;
    void checkCancelled() {
      if (isCancelled?.call() ?? false) throw const ResourceDownloadCancelled();
    }

    try {
      checkCancelled();
      _safeFile(directory, 'animation.json');
      await directory.create(recursive: true);
      stage = await directory.createTemp('.download-');
      var received = 0;
      final verified = <String>{};
      for (final file in manifest.files) {
        checkCancelled();
        final cached = _safeFile(directory, file.md5);
        if (!verified.contains(file.md5) && !await _matches(cached, file)) {
          final target = _safeFile(stage, file.md5);
          if (!await _matches(target, file)) {
            final encoded =
                file.path.split('/').map(Uri.encodeComponent).join('/');
            await api.downloadTo(
                '/api/resources/${manifest.pack}/files/$encoded', target,
                isCancelled: isCancelled,
                onProgress: (bytes, _) => onProgress?.call(ResourcePackProgress(
                    received + bytes, manifest.totalSize, file.path)));
            checkCancelled();
            onProgress?.call(ResourcePackProgress(
                received, manifest.totalSize, file.path,
                verifying: true));
            if (!await _matches(target, file)) {
              throw ApiException('资源校验失败：${file.path}');
            }
          }
        }
        verified.add(file.md5);
        received += file.size;
        onProgress?.call(
            ResourcePackProgress(received, manifest.totalSize, file.path));
      }
      checkCancelled();
      final mapping = _safeFile(stage, '${manifest.pack}.json');
      await mapping.writeAsString(jsonEncode(manifest.toJson()), flush: true);
      await for (final entity in stage.list(followLinks: false)) {
        final name = p.basename(entity.path);
        if (_md5Pattern.hasMatch(name)) {
          await File(entity.path).rename(_safeFile(directory, name).path);
        }
      }
      await mapping.rename(_safeFile(directory, '${manifest.pack}.json').path);
      try {
        await _cleanUnused();
      } catch (error) {
        throw ApiException('资源已更新，但清理失败：$error');
      }
    } finally {
      try {
        if (stage != null && await stage.exists()) {
          await stage.delete(recursive: true);
        }
      } finally {
        _updating.remove(lock);
      }
    }
  }
}
