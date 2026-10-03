import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:archive/archive.dart'
    show
        CompressionType,
        InputFileStream,
        ZipDirectory,
        ZipFile,
        ZipFileHeader,
        getCrc32;
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

const _maxArchiveSize = 1024 * 1024 * 1024;
const _maxArchiveOutput = 2 * 1024 * 1024 * 1024;
const _maxArchiveFile = 256 * 1024 * 1024;
const _maxManifestSize = 8 * 1024 * 1024;
const _maxArchiveFiles = 20000;

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
      {this.verifying = false, this.status});
  final int received;
  final int total;
  final String path;
  final bool verifying;
  final String? status;
  double get fraction =>
      total == 0 ? 1 : (received / total).clamp(0, 1).toDouble();
}

class ResourcePackInstallResult {
  const ResourcePackInstallResult(
      {required this.installed, this.latest, this.syncError});
  final ResourcePackManifest installed;
  final ResourcePackManifest? latest;
  final String? syncError;
  bool get synchronized => syncError == null && latest != null;
}

class ResourcePackArchive {
  ResourcePackArchive.fromJson(Object? value, {required String pack}) {
    _validatePack(pack);
    final raw = jsonObject(value, 'resource archive');
    if (raw['pack'] != pack) throw const FormatException('ZIP 资源包名称不一致');
    version = _hash(raw['version']);
    size = _size(raw['size']);
    hash = _hash(raw['md5']);
    url = jsonString(raw['url'], 'resource archive URL');
    if (size < 22 ||
        size > _maxArchiveSize ||
        url != '/api/resources/$pack/archive/files/$hash.zip') {
      throw const FormatException('ZIP 元数据不合法');
    }
  }
  late final String version;
  late final int size;
  late final String hash;
  late final String url;
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
  }) =>
      _update(() => _download(manifest,
          onProgress: onProgress, isCancelled: isCancelled));

  Future<T> _update<T>(Future<T> Function() action) async {
    final lock = p.normalize(p.absolute(directory.path));
    if (!_updating.add(lock)) throw const ApiException('资源包正在更新');
    try {
      _safeFile(directory, 'animation.json');
      await directory.create(recursive: true);
      return await action();
    } finally {
      _updating.remove(lock);
    }
  }

  Future<void> _download(
    ResourcePackManifest manifest, {
    void Function(ResourcePackProgress progress)? onProgress,
    bool Function()? isCancelled,
    bool clean = true,
  }) async {
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
      await _install(manifest, stage);
      if (clean) {
        try {
          await _cleanUnused();
        } catch (error) {
          throw ApiException('资源已更新，但清理失败：$error');
        }
      }
    } finally {
      if (stage != null && await stage.exists()) {
        await stage.delete(recursive: true);
      }
    }
  }

  Future<void> _install(ResourcePackManifest manifest, Directory stage) async {
    final mapping = _safeFile(stage, '${manifest.pack}.json');
    await mapping.writeAsString(jsonEncode(manifest.toJson()), flush: true);
    await for (final entity in stage.list(followLinks: false)) {
      final name = p.basename(entity.path);
      if (_md5Pattern.hasMatch(name)) {
        await File(entity.path).rename(_safeFile(directory, name).path);
      }
    }
    await mapping.rename(_safeFile(directory, '${manifest.pack}.json').path);
  }

  Future<ResourcePackInstallResult> downloadArchive(
    String pack, {
    void Function(ResourcePackProgress progress)? onProgress,
    bool Function()? isCancelled,
  }) =>
      _update(() async {
        _validatePack(pack);
        _cancel(isCancelled);
        ResourcePackArchive metadata;
        try {
          metadata = ResourcePackArchive.fromJson(
              await api.resourceArchive(pack),
              pack: pack);
        } on ApiException catch (error) {
          if (error.statusCode == 404) {
            throw const ApiException('全量 ZIP 未发布', statusCode: 404);
          }
          rethrow;
        }
        final stage = await directory.createTemp('.archive-');
        try {
          final zip = _safeFile(stage, 'archive.zip');
          await api.downloadTo(metadata.url, zip, isCancelled: isCancelled,
              onProgress: (received, _) {
            _cancel(isCancelled);
            if (received > metadata.size) {
              throw const FormatException('ZIP 大小超出元数据');
            }
            onProgress
                ?.call(ResourcePackProgress(received, metadata.size, '全量 ZIP'));
          });
          _cancel(isCancelled);
          onProgress?.call(ResourcePackProgress(0, metadata.size, 'ZIP MD5',
              verifying: true));
          var verified = 0;
          Stream<List<int>> zipBytes() async* {
            await for (final chunk in zip.openRead()) {
              _cancel(isCancelled);
              verified += chunk.length;
              onProgress?.call(ResourcePackProgress(
                  verified, metadata.size, 'ZIP MD5',
                  verifying: true));
              yield chunk;
            }
          }

          if (await zip.length() != metadata.size ||
              (await md5.bind(zipBytes()).first).toString() != metadata.hash) {
            throw const FormatException('ZIP 大小或 MD5 校验失败');
          }
          final manifest = await _importZip(pack, zip, stage,
              expectedVersion: metadata.version,
              onProgress: onProgress,
              isCancelled: isCancelled);
          return await _syncInstalled(manifest,
              onProgress: onProgress, isCancelled: isCancelled);
        } finally {
          await stage.delete(recursive: true);
        }
      });

  Future<ResourcePackInstallResult> importArchive(
    String pack,
    File source, {
    void Function(ResourcePackProgress progress)? onProgress,
    bool Function()? isCancelled,
  }) =>
      _update(() async {
        _validatePack(pack);
        _cancel(isCancelled);
        if (await FileSystemEntity.type(source.path, followLinks: false) !=
            FileSystemEntityType.file) {
          throw const FormatException('请选择普通 ZIP 文件');
        }
        final size = await source.length();
        if (size < 22 || size > _maxArchiveSize) {
          throw const FormatException('ZIP 大小不合法（上限 1 GB）');
        }
        final stage = await directory.createTemp('.archive-');
        try {
          final zip = _safeFile(stage, 'archive.zip');
          var received = 0;
          final sink = zip.openWrite();
          try {
            await for (final chunk in source.openRead()) {
              _cancel(isCancelled);
              received += chunk.length;
              if (received > size) throw const FormatException('导入文件发生变化');
              sink.add(chunk);
              await sink.flush();
              onProgress
                  ?.call(ResourcePackProgress(received, size, '正在读取 ZIP'));
            }
          } finally {
            await sink.close();
          }
          if (received != size) throw const FormatException('导入文件发生变化');
          final manifest = await _importZip(pack, zip, stage,
              onProgress: onProgress, isCancelled: isCancelled);
          return await _syncInstalled(manifest,
              onProgress: onProgress, isCancelled: isCancelled);
        } finally {
          await stage.delete(recursive: true);
        }
      });

  Future<ResourcePackInstallResult> _syncInstalled(
    ResourcePackManifest installed, {
    void Function(ResourcePackProgress progress)? onProgress,
    bool Function()? isCancelled,
  }) async {
    ResourcePackManifest? latest;
    try {
      _cancel(isCancelled);
      onProgress?.call(const ResourcePackProgress(0, 0, '正在检查最新增量'));
      latest = ResourcePackManifest.fromJson(
          await api.resourceManifest(installed.pack),
          pack: installed.pack);
      await _download(latest,
          clean: false,
          onProgress: (progress) => onProgress?.call(ResourcePackProgress(
              progress.received, progress.total, progress.path,
              verifying: progress.verifying,
              status: progress.verifying ? '正在校验增量' : '正在增量同步')),
          isCancelled: isCancelled);
      await _cleanUnused();
      return ResourcePackInstallResult(installed: latest, latest: latest);
    } catch (error) {
      return ResourcePackInstallResult(
          installed: (await _local(installed.pack))!,
          latest: latest,
          syncError: error is ResourceDownloadCancelled ||
                  (isCancelled?.call() ?? false)
              ? 'ZIP 已安装 · 增量已取消，未确认最新'
              : 'ZIP 已安装 · 增量同步失败，未确认最新：$error');
    }
  }

  static void _cancel(bool Function()? isCancelled) {
    if (isCancelled?.call() ?? false) throw const ResourceDownloadCancelled();
  }

  // 先检查中央目录，避免 ZipDecoder 合并重复名称或提前解压符号链接。
  ZipDirectory _readZip(String pack, InputFileStream input, int size) {
    final footerStart = size > 65557 ? size - 65557 : 0;
    final footer = input.subset(position: footerStart).toUint8List();
    final data = ByteData.sublistView(footer);
    var end = -1;
    for (var offset = footer.length - 22; offset >= 0; offset--) {
      if (data.getUint32(offset, Endian.little) == 0x06054b50 &&
          offset + 22 + data.getUint16(offset + 20, Endian.little) ==
              footer.length) {
        end = offset;
        break;
      }
    }
    if (end < 0) throw const FormatException('ZIP 目录缺失');
    final count = data.getUint16(end + 10, Endian.little);
    final centralSize = data.getUint32(end + 12, Endian.little);
    final centralOffset = data.getUint32(end + 16, Endian.little);
    if (count < 1 ||
        count > _maxArchiveFiles + 1 ||
        data.getUint16(end + 4, Endian.little) != 0 ||
        data.getUint16(end + 6, Endian.little) != 0 ||
        data.getUint16(end + 8, Endian.little) != count ||
        centralSize > 32 * 1024 * 1024 ||
        centralOffset + centralSize != footerStart + end) {
      throw const FormatException('ZIP 目录越界或文件数量过多');
    }
    final zip = ZipDirectory()
      ..centralDirectoryOffset = centralOffset
      ..centralDirectorySize = centralSize;
    final central = input.subset(position: centralOffset, length: centralSize);
    final names = <String>{};
    final regions = <(int, int)>[];
    var outputSize = 0;
    var extraSize = 0;
    for (var i = 0; i < count; i++) {
      if (central.length < 46 ||
          central.readUint32() != ZipFileHeader.signature) {
        throw const FormatException('ZIP 目录不完整');
      }
      final header = ZipFileHeader()..read(central);
      zip.fileHeaders.add(header);
      if (header.filename != 'manifest.json') {
        _validatePath(pack, header.filename);
      }
      final type = (header.externalFileAttributes >> 16) & 0xf000;
      if (!names.add(header.filename.toUpperCase().toLowerCase()) ||
          (type != 0 && type != 0x8000) ||
          (header.externalFileAttributes & 0x10) != 0 ||
          (header.generalPurposeBitFlag & 0x41) != 0 ||
          (header.compressionMethod != 0 && header.compressionMethod != 8) ||
          header.diskNumberStart != 0 ||
          header.uncompressedSize < 0 ||
          header.uncompressedSize > _maxArchiveFile ||
          header.compressedSize < 0 ||
          header.compressedSize > _maxArchiveSize ||
          header.localHeaderOffset < 0 ||
          header.localHeaderOffset + 30 > centralOffset) {
        throw FormatException('ZIP 成员不安全或重复：${header.filename}');
      }
      final local = ByteData.sublistView(input
          .subset(position: header.localHeaderOffset, length: 30)
          .toUint8List());
      final flags = local.getUint16(6, Endian.little);
      if (local.getUint32(0, Endian.little) != ZipFile.zipSignature ||
          flags != header.generalPurposeBitFlag ||
          local.getUint16(8, Endian.little) != header.compressionMethod) {
        throw const FormatException('ZIP 本地文件头不一致');
      }
      final nameSize = local.getUint16(26, Endian.little);
      final localExtra = local.getUint16(28, Endian.little);
      extraSize += localExtra + (header.extraField?.length ?? 0);
      final end = header.localHeaderOffset +
          30 +
          nameSize +
          localExtra +
          header.compressedSize +
          ((flags & 8) != 0 ? 12 : 0);
      if (nameSize > 4096 ||
          extraSize > _maxManifestSize ||
          end > centralOffset) {
        throw const FormatException('ZIP 成员或扩展文件头越界');
      }
      regions.add((header.localHeaderOffset, end));
      outputSize += header.uncompressedSize;
      if (outputSize > _maxArchiveOutput + _maxManifestSize) {
        throw const FormatException('ZIP 解压总大小超过 2 GB');
      }
    }
    if (!central.isEOS) throw const FormatException('ZIP 目录包含未列出的内容');
    regions.sort((a, b) => a.$1.compareTo(b.$1));
    for (var i = 1; i < regions.length; i++) {
      if (regions[i].$1 < regions[i - 1].$2) {
        throw const FormatException('ZIP 成员范围重叠');
      }
    }
    for (final header in zip.fileHeaders) {
      input.setPosition(header.localHeaderOffset);
      final file = ZipFile(header)..read(input);
      header.file = file;
      if (file.filename != header.filename ||
          file.compressionMethod !=
              (header.compressionMethod == 0
                  ? CompressionType.none
                  : CompressionType.deflate) ||
          file.uncompressedSize != header.uncompressedSize ||
          file.compressedSize != header.compressedSize ||
          file.getStream(decompress: false).length != header.compressedSize) {
        throw const FormatException('ZIP 本地成员与目录不一致');
      }
    }
    return zip;
  }

  Stream<List<int>> _zipBytes(
      ZipFileHeader header, bool Function()? isCancelled) async* {
    final raw = header.file!.getStream(decompress: false);
    raw.reset();
    Stream<List<int>> compressed() async* {
      while (!raw.isEOS) {
        _cancel(isCancelled);
        yield raw
            .readBytes(raw.length < 4096 ? raw.length : 4096)
            .toUint8List();
      }
    }

    final stream = header.compressionMethod == 0
        ? compressed()
        : ZLibDecoder(raw: true).bind(compressed());
    var size = 0;
    var crc = 0;
    await for (final chunk in stream) {
      _cancel(isCancelled);
      size += chunk.length;
      if (size > header.uncompressedSize) {
        throw const FormatException('ZIP 解压大小超出清单');
      }
      crc = getCrc32(chunk, crc);
      yield chunk;
    }
    if (size != header.uncompressedSize || crc != header.crc32) {
      throw FormatException('ZIP 成员大小或 CRC 校验失败：${header.filename}');
    }
  }

  Future<ResourcePackManifest> _importZip(
      String pack, File source, Directory stage,
      {String? expectedVersion,
      void Function(ResourcePackProgress progress)? onProgress,
      bool Function()? isCancelled}) async {
    _cancel(isCancelled);
    final input = InputFileStream(source.path);
    try {
      onProgress
          ?.call(const ResourcePackProgress(0, 0, 'ZIP 目录', verifying: true));
      final zip = _readZip(pack, input, await source.length());
      final entries = {for (final file in zip.fileHeaders) file.filename: file};
      final metadata = entries.remove('manifest.json');
      if (metadata == null || metadata.uncompressedSize > _maxManifestSize) {
        throw const FormatException('ZIP 缺少根目录清单或清单过大');
      }
      final bytes = BytesBuilder(copy: false);
      await for (final chunk in _zipBytes(metadata, isCancelled)) {
        bytes.add(chunk);
      }
      final payload = jsonObject(jsonDecode(utf8.decode(bytes.takeBytes())),
          'resource archive manifest');
      final files = jsonArray(payload['files'], 'resource files');
      if (files.length > _maxArchiveFiles || files.length != entries.length) {
        throw const FormatException('ZIP 清单成员数量不一致或过多');
      }
      final manifest = ResourcePackManifest.fromJson(payload, pack: pack);
      final canonical = [
        for (final file in manifest.files)
          {'md5': file.md5, 'path': file.path, 'size': file.size}
      ];
      if (md5.convert(utf8.encode(jsonEncode(canonical))).toString() !=
              manifest.version ||
          (expectedVersion != null && expectedVersion != manifest.version) ||
          manifest.totalSize > _maxArchiveOutput ||
          entries.length != manifest.files.length) {
        throw const FormatException('ZIP 清单版本或成员不一致');
      }
      for (final file in manifest.files) {
        if (entries[file.path]?.uncompressedSize != file.size) {
          throw FormatException('ZIP 未发布成员或大小不一致：${file.path}');
        }
      }
      var received = 0;
      final verified = <String>{};
      for (final file in manifest.files) {
        _cancel(isCancelled);
        final cached = _safeFile(directory, file.md5);
        final target =
            !verified.contains(file.md5) && !await _matches(cached, file)
                ? _safeFile(stage, file.md5)
                : null;
        final sink = target?.openWrite();
        try {
          Stream<List<int>> content() async* {
            await for (final chunk
                in _zipBytes(entries[file.path]!, isCancelled)) {
              sink?.add(chunk);
              if (sink != null) await sink.flush();
              received += chunk.length;
              onProgress?.call(ResourcePackProgress(
                  received, manifest.totalSize, file.path,
                  verifying: true));
              yield chunk;
            }
          }

          if ((await md5.bind(content()).first).toString() != file.md5) {
            throw FormatException('ZIP MD5 校验失败：${file.path}');
          }
        } finally {
          await sink?.close();
        }
        verified.add(file.md5);
      }
      _cancel(isCancelled);
      await _install(manifest, stage);
      return manifest;
    } finally {
      await input.close();
    }
  }
}
