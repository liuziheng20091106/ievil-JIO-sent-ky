import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:archive/archive.dart'
    show
        ArchiveFile,
        InputMemoryStream,
        OutputMemoryStream,
        ZipDirectory,
        ZipEncoder;
import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:path/path.dart' as p;
import 'package:seven_double_client/src/api.dart';
import 'package:seven_double_client/src/design.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/release.dart';
import 'package:seven_double_client/src/resource_pack_dialog.dart';
import 'package:seven_double_client/src/resource_packs.dart';
import 'package:seven_double_client/src/shell.dart';
import 'package:seven_double_client/src/store.dart';
import 'package:shared_preferences/shared_preferences.dart';

Map<String, dynamic> manifestPayload(
    String pack, Map<String, String> contents) {
  final paths = contents.keys.toList()..sort();
  final files = paths.map((path) {
    final bytes = utf8.encode(contents[path]!);
    return {
      'path': path,
      'size': bytes.length,
      'md5': md5.convert(bytes).toString()
    };
  }).toList();
  return {
    'pack': pack,
    'version': md5
        .convert(utf8.encode(jsonEncode([
          for (final file in files)
            {'md5': file['md5'], 'path': file['path'], 'size': file['size']},
        ])))
        .toString(),
    'total_size': contents.values
        .fold<int>(0, (sum, value) => sum + utf8.encode(value).length),
    'files': files,
  };
}

Uint8List zipPayload(
    Map<String, dynamic> manifest, Map<String, String> contents,
    {List<ArchiveFile> extra = const [], String? password}) {
  final output = OutputMemoryStream();
  final encoder = ZipEncoder(password: password)..startEncode(output);
  encoder.add(
      ArchiveFile.bytes('manifest.json', utf8.encode(jsonEncode(manifest))));
  for (final entry in contents.entries) {
    encoder.add(ArchiveFile.bytes(entry.key, utf8.encode(entry.value)));
  }
  for (final entry in extra) {
    encoder.add(entry);
  }
  encoder.endEncode();
  return output.getBytes();
}

ZipDirectory zipDirectory(Uint8List bytes) =>
    ZipDirectory()..read(InputMemoryStream(bytes));

class ResourceApi extends GameApi {
  ResourceApi([String server = 'http://127.0.0.1:19285'])
      : super(ServerEndpoint.parse(server));
  final manifests = <String, Map<String, dynamic>>{};
  final contents = <String, String>{};
  final downloads = <String>[];
  final unpublished = <String>{};
  final failures = <String>{};
  void Function()? afterDownload;
  final archiveMetadata = <String, Map<String, dynamic>>{};
  final archiveBodies = <String, Uint8List>{};
  final archiveRequests = <String>[];
  final manifestRequests = <String>[];

  void publishArchive(String pack, Map<String, String> files) {
    final manifest = manifestPayload(pack, files);
    final bytes = zipPayload(manifest, files);
    final hash = md5.convert(bytes).toString();
    archiveBodies[pack] = bytes;
    archiveMetadata[pack] = {
      'pack': pack,
      'version': manifest['version'],
      'size': bytes.length,
      'md5': hash,
      'url': '/api/resources/$pack/archive/files/$hash.zip'
    };
  }

  @override
  Future<Map<String, dynamic>> resourceArchive(String pack) async {
    archiveRequests.add(pack);
    if (!archiveMetadata.containsKey(pack)) {
      throw const ApiException('ZIP 未发布', statusCode: 404);
    }
    return archiveMetadata[pack]!;
  }

  void publish(String pack, Map<String, String> files) {
    manifests[pack] = manifestPayload(pack, files);
    for (final entry in files.entries) {
      contents['$pack/${entry.key}'] = entry.value;
    }
  }

  ResourcePackManifest manifest(String pack) =>
      ResourcePackManifest.fromJson(manifests[pack], pack: pack);

  @override
  Future<Map<String, dynamic>> resourceManifest(String pack) async {
    manifestRequests.add(pack);
    if (failures.contains(pack)) {
      throw const ApiException('不可达', statusCode: 503);
    }
    if (unpublished.contains(pack)) {
      throw const ApiException('未发布', statusCode: 404);
    }
    return manifests[pack]!;
  }

  @override
  Future<int> downloadTo(
    String url,
    File target, {
    void Function(int received, int total)? onProgress,
    bool Function()? isCancelled,
  }) async {
    final parts = Uri.parse(url).pathSegments;
    if (parts[3] == 'archive') {
      downloads.add('${parts[2]}/ZIP');
      final bytes = archiveBodies[parts[2]]!;
      await target.writeAsBytes(bytes);
      onProgress?.call(bytes.length, bytes.length);
      afterDownload?.call();
      return bytes.length;
    }
    final key = '${parts[2]}/${parts.skip(4).join('/')}';
    downloads.add(key);
    if (isCancelled?.call() ?? false) throw const ResourceDownloadCancelled();
    final bytes = utf8.encode(contents[key]!);
    await target.writeAsBytes(bytes);
    onProgress?.call(bytes.length, bytes.length);
    afterDownload?.call();
    return bytes.length;
  }
}

class EntryResources extends ResourcePacks {
  EntryResources({required super.api, required super.supportDirectory});
  Completer<List<ResourcePackCheck>> pending =
      Completer<List<ResourcePackCheck>>();
  @override
  Future<List<ResourcePackCheck>> checkAll() => pending.future;
}

class EntryRelease extends ReleaseMonitor {
  EntryRelease() : super(currentVersion: '1.0.0');
  Completer<void> pending = Completer<void>();
  String latest = '1.1.0';

  @override
  Future<void> check(ServerEndpoint endpoint) async {
    await pending.future;
    applyHealthPayload({
      'client_latest': latest,
      'update': {
        'platform': 'windows',
        'latest': latest,
        'title': '客户端更新 $latest',
        'notes': '入局更新检查',
      },
    });
    notifyListeners();
  }
}

Map<String, dynamic> gamePayload(String id) => {
      'ui_version': 1,
      'id': id,
      'version': 1,
      'status': 'lobby',
      'day': 0,
      'half': 'day',
      'phase': 'lobby',
      'phase_label': '候场',
      'deadline': null,
      'ready_count': 0,
      'actions': <dynamic>[],
      'channels': <dynamic>[],
      'seats': <dynamic>[],
      'self': <String, dynamic>{},
      'public': <String, dynamic>{},
    };

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  late Directory support;
  late ResourceApi api;
  late ResourcePacks cache;

  setUp(() async {
    support = await Directory.systemTemp.createTemp('resource-packs-test-');
    api = ResourceApi();
    cache = ResourcePacks(api: api, supportDirectory: support);
    api.publish('animation', {'角色/EX/1.png': 'good'});
    api.publish('memes', {'hello.png': 'meme'});
    api.publish('audio', {'music/theme.mp3': 'audio'});
  });
  tearDown(() async {
    api.close();
    await support.delete(recursive: true);
  });

  Future<File> localZip(Uint8List bytes) async =>
      File(p.join(support.path, 'import.zip')).writeAsBytes(bytes);

  test('音频包复用增量、全量 ZIP 与本地导入校验流程', () async {
    await cache.download(api.manifest('audio'));
    expect(await File((await cache.filePath('audio', 'music/theme.mp3'))!)
        .readAsString(), 'audio');
    api.publishArchive('audio', {'music/theme.mp3': 'zip audio'});
    api.publish('audio', {'music/theme.mp3': 'latest audio'});
    final full = await cache.downloadArchive('audio');
    expect(full.synchronized, isTrue);
    expect(await File((await cache.filePath('audio', 'music/theme.mp3'))!)
        .readAsString(), 'latest audio');
    final imported = ResourcePacks(api: api,
        supportDirectory: Directory(p.join(support.path, 'imported')));
    final source = await localZip(api.archiveBodies['audio']!);
    final result = await imported.importArchive('audio', source);
    expect(result.synchronized, isTrue);
    final path = (await imported.filePath('audio', 'music/theme.mp3'))!;
    expect(await File(path).readAsString(), 'latest audio');
    await File(path).writeAsString('tampered');
    expect(await imported.filePath('audio', 'music/theme.mp3'), isNull);
    for (final unsafe in ['../song.mp3', 'https://host/song.mp3', 'cover.png']) {
      expect(() => ResourcePackManifest.fromJson(
          manifestPayload('audio', {unsafe: 'bad'}), pack: 'audio'),
          throwsFormatException);
    }
  });

  test('动画音效优先脚本旁及固定后缀，坏首选缓存不能静默降级', () async {
    api.publish('animation', {
      'scripts/nested/sample.json': '{}',
      'scripts/nested/sample.wav': 'inline wav',
    });
    api.publish('audio', {'scripts/nested/sample.mp3': 'fallback mp3'});
    await cache.download(api.manifest('animation'));
    await cache.download(api.manifest('audio'));
    expect(await cache.animationSoundPath('scripts/nested/sample.json'),
        await cache.filePath('animation', 'scripts/nested/sample.wav'));
    api.publish('animation', {
      'scripts/nested/sample.json': '{}',
      'scripts/nested/sample.wav': 'inline wav',
      'scripts/nested/sample.mp3': 'inline mp3',
    });
    await cache.download(api.manifest('animation'));
    final preferred = await cache.filePath('animation', 'scripts/nested/sample.mp3');
    expect(await cache.animationSoundPath('scripts/nested/sample.json'), preferred);
    await File(preferred!).writeAsString('corrupt');
    await expectLater(cache.animationSoundPath('scripts/nested/sample.json'),
        throwsFormatException);
    api.publish('animation', {'scripts/nested/sample.json': '{}'});
    await cache.download(api.manifest('animation'));
    expect(await cache.animationSoundPath('scripts/nested/sample.json'),
        await cache.filePath('audio', 'scripts/nested/sample.mp3'));
    await expectLater(cache.animationSoundPath('../outside.json'),
        throwsFormatException);
  });

  test('旧 ZIP 安装后重新获取最新清单，跨包共享缓存只下载差异', () async {
    api.publish('memes', {'face.png': 'shared'});
    await cache.download(api.manifest('memes'));
    final shared = File((await cache.filePath('memes', 'face.png'))!);
    final modified = DateTime.utc(2001);
    await shared.setLastModified(modified);
    const oldFiles = {'a.png': 'shared', 'b.png': 'before'};
    final old = manifestPayload('animation', oldFiles);
    final source = await localZip(zipPayload(old, oldFiles));
    api.publish(
        'animation', {'a.png': 'shared', 'b.png': 'after', 'c.png': 'shared'});
    api.downloads.clear();
    api.manifestRequests.clear();
    final result = await cache.importArchive('animation', source);
    expect(result.synchronized, isTrue);
    expect(result.installed.version, api.manifest('animation').version);
    expect(api.downloads, ['animation/b.png']);
    expect(api.manifestRequests.first, 'animation');
    expect((await shared.lastModified()).toUtc(), modified);
    expect(await cache.filePath('animation', 'a.png'), shared.path);
    expect(await cache.filePath('animation', 'c.png'), shared.path);
    expect(
        await File((await cache.filePath('animation', 'b.png'))!)
            .readAsString(),
        'after');
  });

  test('全量下载校验 ZIP 元数据，并在安装后补齐最新差异', () async {
    const oldFiles = {'a.png': 'old'};
    api.publishArchive('animation', oldFiles);
    api.publish('animation', {'a.png': 'new'});
    final phases = <ResourcePackProgress>[];
    final result =
        await cache.downloadArchive('animation', onProgress: phases.add);
    expect(result.synchronized, isTrue);
    expect(api.downloads, ['animation/ZIP', 'animation/a.png']);
    expect(phases.any((progress) => progress.verifying), isTrue);
    expect(phases.any((progress) => progress.path == '正在检查最新增量'), isTrue);
    expect(
        await File((await cache.filePath('animation', 'a.png'))!)
            .readAsString(),
        'new');
  });

  test('全量 ZIP 的 404、错误大小、MD5 或版本不回退到增量，也不替换旧映射', () async {
    final old = api.manifest('animation');
    await cache.download(old);
    api.downloads.clear();
    await expectLater(
        cache.downloadArchive('animation'),
        throwsA(isA<ApiException>()
            .having((error) => error.statusCode, 'status', 404)));
    expect(api.downloads, isEmpty);
    for (final field in ['size', 'md5', 'version']) {
      api.publishArchive('animation', {'next.png': 'new'});
      final metadata = api.archiveMetadata['animation']!;
      if (field == 'size') {
        metadata[field] = (metadata[field] as int) + 1;
      } else {
        metadata[field] = '0' * 32;
        if (field == 'md5') {
          metadata['url'] =
              '/api/resources/animation/archive/files/${metadata[field]}.zip';
        }
      }
      await expectLater(
          cache.downloadArchive('animation'), throwsFormatException);
      expect((await cache.localManifest('animation'))!.version, old.version);
    }
    expect(api.downloads.every((path) => path == 'animation/ZIP'), isTrue);
  });

  test('离线导入保留验证成功的 ZIP，失败增量不宣称最新也不删另一包', () async {
    await cache.download(api.manifest('memes'));
    final meme = await cache.filePath('memes', 'hello.png');
    const files = {'offline.png': 'safe'};
    final old = manifestPayload('animation', files);
    final source = await localZip(zipPayload(old, files));
    api.failures.addAll(resourcePackNames);
    final result = await cache.importArchive('animation', source);
    expect(result.synchronized, isFalse);
    expect(result.latest, isNull);
    expect(result.syncError, contains('ZIP 已安装'));
    expect(result.syncError, contains('未确认最新'));
    expect((await cache.localManifest('animation'))!.version, old['version']);
    expect(
        await File((await cache.filePath('animation', 'offline.png'))!)
            .readAsString(),
        'safe');
    expect(await File(meme!).readAsString(), 'meme');
    api.failures.clear();
    api.publish('animation', {'offline.png': 'next'});
    api.contents['animation/offline.png'] = 'oops';
    final failed = await cache.importArchive('animation', source);
    expect(failed.synchronized, isFalse);
    expect(failed.latest!.version, api.manifest('animation').version);
    expect(failed.installed.version, old['version']);
    expect(
        await File((await cache.filePath('animation', 'offline.png'))!)
            .readAsString(),
        'safe');
  });

  test('ZIP 穿越、未列出文件、重复、链接、目录与坏内容均保持原映射及缓存', () async {
    final old = api.manifest('animation');
    await cache.download(old);
    final oldPath = (await cache.filePath('animation', '角色/EX/1.png'))!;
    const files = {'a.png': 'next', 'b.png': 'good'};
    final next = manifestPayload('animation', files);
    final symlink = ArchiveFile.bytes('a.png', utf8.encode('next'))
      ..mode = 0xa1ff;
    final cases = <Uint8List>[
      zipPayload(next, files,
          extra: [ArchiveFile.string('../outside.png', 'bad')]),
      zipPayload(next, files,
          extra: [ArchiveFile.string('outside.png', 'bad')]),
      zipPayload(next, files, extra: [ArchiveFile.string('a.png', 'next')]),
      zipPayload(next, files, extra: [ArchiveFile.string('A.png', 'next')]),
      zipPayload(next, {'b.png': 'good'}, extra: [symlink]),
      zipPayload(next, files, extra: [ArchiveFile.directory('folder/')]),
      zipPayload(next, {'a.png': 'next', 'b.png': 'oops'}),
      zipPayload(next, {'a.png': 'next', 'b.png': 'longer'}),
      zipPayload(manifestPayload('memes', files), files),
      zipPayload({...next, 'version': '0' * 32}, files),
      zipPayload(next, files, password: 'secret'),
      zipPayload(
          manifestPayload('animation', {'scripts/../../outside.json': '{}'}),
          {'scripts/../../outside.json': '{}'}),
    ];
    for (final bytes in cases) {
      await expectLater(cache.importArchive('animation', await localZip(bytes)),
          throwsFormatException);
      expect((await cache.localManifest('animation'))!.version, old.version);
      expect(await File(oldPath).readAsString(), 'good');
      expect(await cache.filePath('animation', 'a.png'), isNull);
      expect(
          await File(p.join(cache.directory.path,
                  md5.convert(utf8.encode('next')).toString()))
              .exists(),
          isFalse);
      expect(await Directory(p.join(cache.directory.path, 'folder')).exists(),
          isFalse);
      expect(await File(p.join(support.path, 'outside.png')).exists(), isFalse);
    }
  });

  test('ZIP 假小解压炸弹、巨大声明、目录越界与本地中央名称不一致均拒绝', () async {
    await cache.download(api.manifest('animation'));
    final version = (await cache.localManifest('animation'))!.version;
    const files = {'a.png': 'safe'};
    final payload = manifestPayload('animation', files);
    final bomb = zipPayload(payload, {'a.png': 'x' * (1024 * 1024)});
    final bombZip = zipDirectory(bomb);
    final bombHeader = bombZip.fileHeaders.last;
    final bombData = ByteData.sublistView(bomb);
    bombData.setUint32(bombHeader.localHeaderOffset + 22, 4, Endian.little);
    var central = bombZip.centralDirectoryOffset;
    for (final header in bombZip.fileHeaders) {
      if (header.filename == 'a.png') {
        bombData.setUint32(central + 24, 4, Endian.little);
      }
      central += 46 +
          utf8.encode(header.filename).length +
          (header.extraField?.length ?? 0) +
          utf8.encode(header.fileComment).length;
    }
    final giant = zipPayload(payload, files);
    final giantZip = zipDirectory(giant);
    ByteData.sublistView(giant).setUint32(giantZip.centralDirectoryOffset + 24,
        256 * 1024 * 1024 + 1, Endian.little);
    final outside = zipPayload(payload, files);
    ByteData.sublistView(outside)
        .setUint32(outside.length - 6, outside.length, Endian.little);
    final renamed = zipPayload(payload, files);
    final localHeader = zipDirectory(renamed).fileHeaders.last;
    renamed[localHeader.localHeaderOffset + 30] = 'b'.codeUnitAt(0);
    for (final bytes in [bomb, giant, outside, renamed]) {
      await expectLater(cache.importArchive('animation', await localZip(bytes)),
          throwsFormatException);
      expect((await cache.localManifest('animation'))!.version, version);
    }
  });

  test('ZIP 导入校验可取消；ZIP 安装后取消增量仍保留可用安装', () async {
    await cache.download(api.manifest('animation'));
    final old = (await cache.localManifest('animation'))!.version;
    const files = {'a.png': 'new', 'b.png': 'safe'};
    final payload = manifestPayload('animation', files);
    final source = await localZip(zipPayload(payload, files));
    var cancelled = false;
    await expectLater(
        cache.importArchive('animation', source,
            isCancelled: () => cancelled,
            onProgress: (progress) {
              if (progress.path == 'a.png') cancelled = true;
            }),
        throwsA(isA<ResourceDownloadCancelled>()));
    expect((await cache.localManifest('animation'))!.version, old);
    cancelled = false;
    final result = await cache.importArchive('animation', source,
        isCancelled: () => cancelled,
        onProgress: (progress) {
          if (progress.path == '正在检查最新增量') cancelled = true;
        });
    expect(result.synchronized, isFalse);
    expect(result.syncError, contains('已取消'));
    expect(
        (await cache.localManifest('animation'))!.version, payload['version']);
    expect(
        await File((await cache.filePath('animation', 'a.png'))!)
            .readAsString(),
        'new');
  });

  test('增量、全量与导入共享互斥，失败后锁可再次使用', () async {
    const files = {'a.png': 'new'};
    final source =
        await localZip(zipPayload(manifestPayload('animation', files), files));
    api.publishArchive('animation', files);
    Future<void>? overlap;
    final imported =
        cache.importArchive('animation', source, onProgress: (progress) {
      overlap ??= () async {
        await expectLater(cache.download(api.manifest('memes')),
            throwsA(isA<ApiException>()));
        await expectLater(
            cache.downloadArchive('memes'), throwsA(isA<ApiException>()));
      }();
    });
    await imported;
    await overlap;
    await cache.downloadArchive('animation');
    expect((await cache.localManifest('animation'))!.version,
        api.manifest('animation').version);
  });

  test('全量下载与 ZIP MD5 校验均可取消，取消后不切换映射且释放互斥', () async {
    await cache.download(api.manifest('animation'));
    final old = (await cache.localManifest('animation'))!.version;
    api.publishArchive('animation', {'next.png': 'new'});
    var cancelled = false;
    api.afterDownload = () => cancelled = true;
    await expectLater(
        cache.downloadArchive('animation', isCancelled: () => cancelled),
        throwsA(isA<ResourceDownloadCancelled>()));
    expect((await cache.localManifest('animation'))!.version, old);
    api.afterDownload = null;
    cancelled = false;
    await expectLater(
        cache.downloadArchive('animation',
            isCancelled: () => cancelled,
            onProgress: (progress) {
              if (progress.path == 'ZIP MD5') cancelled = true;
            }),
        throwsA(isA<ResourceDownloadCancelled>()));
    expect((await cache.localManifest('animation'))!.version, old);
    await cache.download(api.manifest('memes'));
  });

  test('本地 ZIP 输入链接与 MD5 缓存链接不得被解压读取或覆盖', () async {
    const files = {'a.png': 'safe'};
    final source =
        await localZip(zipPayload(manifestPayload('animation', files), files));
    final link = Link(p.join(support.path, 'linked.zip'));
    await link.create(source.path);
    await expectLater(cache.importArchive('animation', File(link.path)),
        throwsFormatException);
    await cache.directory.create(recursive: true);
    final outside = File(p.join(support.path, 'outside'));
    await outside.writeAsString('untouched');
    final hash = md5.convert(utf8.encode('safe')).toString();
    await Link(p.join(cache.directory.path, hash)).create(outside.path);
    await expectLater(
        cache.importArchive('animation', source), throwsFormatException);
    expect(await outside.readAsString(), 'untouched');
    expect(await cache.localManifest('animation'), isNull);
  });

  testWidgets('全量模式明确报告 ZIP 404，不偷偷执行增量下载', (tester) async {
    await tester.pumpWidget(MaterialApp(
        theme: buildAppTheme(),
        home: ResourcePackDialog(resources: cache, initialChecks: [
          ResourcePackCheck(
              pack: 'animation', remote: api.manifest('animation')),
          const ResourcePackCheck(pack: 'memes', unpublished: true),
        ])));
    await tester.tap(find.text('全量 ZIP'));
    await tester.pumpAndSettle();
    await tester.runAsync(() async {
      await tester.tap(find.text('下载所选'));
      await Future<void>.delayed(const Duration(milliseconds: 100));
    });
    await tester.pumpAndSettle();
    expect(api.archiveRequests, ['animation']);
    expect(api.downloads, isEmpty);
    expect(find.textContaining('全量 ZIP 未发布'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  test('坏 MD5 不能替换完整版本，重试下载后才切换', () async {
    final good = api.manifest('animation');
    await cache.download(good);
    final oldPath = await cache.filePath('animation', '角色/EX/1.png');
    api.publish('animation', {'角色/EX/1.png': 'next'});
    final next = api.manifest('animation');
    api.contents['animation/角色/EX/1.png'] = 'oops';
    await expectLater(cache.download(next), throwsA(isA<ApiException>()));
    expect((await cache.localManifest('animation'))!.version, good.version);
    expect(await cache.filePath('animation', '角色/EX/1.png'), oldPath);
    expect(await File(oldPath!).readAsString(), 'good');
    api.contents['animation/角色/EX/1.png'] = 'next';
    await cache.download(next);
    expect((await cache.localManifest('animation'))!.version, next.version);
    expect(
        await File((await cache.filePath('animation', '角色/EX/1.png'))!)
            .readAsString(),
        'next');
    expect(await File(oldPath).exists(), isFalse);
  });

  test('取消另一包不影响已安装包，也不发布半包', () async {
    await cache.download(api.manifest('animation'));
    api.publish('memes', {'a.png': 'first', 'b.png': 'second'});
    var cancelled = false;
    api.afterDownload = () => cancelled = true;
    await expectLater(
        cache.download(api.manifest('memes'), isCancelled: () => cancelled),
        throwsA(isA<ResourceDownloadCancelled>()));
    expect(await cache.localManifest('memes'), isNull);
    expect(await cache.filePath('memes', 'a.png'), isNull);
    expect(
        await File((await cache.filePath('animation', '角色/EX/1.png'))!)
            .readAsString(),
        'good');
    api.afterDownload = null;
    await cache.download(api.manifest('memes'));
    expect(await File((await cache.filePath('memes', 'b.png'))!).readAsString(),
        'second');
  });

  test('增量下载只复用内容校验正确的文件', () async {
    api.publish('animation', {'a.png': 'unchanged', 'b.png': 'before'});
    await cache.download(api.manifest('animation'));
    api.downloads.clear();
    api.publish('animation', {'a.png': 'unchanged', 'b.png': 'after'});
    await cache.download(api.manifest('animation'));
    expect(api.downloads, ['animation/b.png']);
    final path = await cache.filePath('animation', 'a.png');
    await File(path!).writeAsString('tampering');
    expect(await cache.filePath('animation', 'a.png'), isNull);
    api.downloads.clear();
    api.publish('animation', {'a.png': 'unchanged', 'b.png': 'again'});
    await cache.download(api.manifest('animation'));
    expect(api.downloads, ['animation/a.png', 'animation/b.png']);
  });

  test('系统应用目录的上层别名不妨碍两包下载及读取', () async {
    final actual = Directory(p.join(support.path, 'actual', 'app-support'));
    await actual.create(recursive: true);
    final alias = Link(p.join(support.path, 'data-user'));
    await alias.create(actual.parent.path);
    final aliased = ResourcePacks(
        api: api,
        supportDirectory: Directory(p.join(alias.path, 'app-support')));
    for (final check in await aliased.checkAll()) {
      expect(check.error, isNull);
      expect(check.needsDownload, isTrue);
    }
    for (final pack in resourcePackNames) {
      final manifest = api.manifest(pack);
      await aliased.download(manifest);
      expect((await aliased.localManifest(pack))!.version, manifest.version);
      final file = manifest.files.single;
      final cached = await aliased.filePath(pack, file.path);
      expect(await File(cached!).readAsString(),
          api.contents['$pack/${file.path}']);
      expect((await aliased.check(pack)).needsDownload, isFalse);
    }
    final meme = api.manifest('memes').files.single;
    expect(await (await aliased.cachedMeme(meme.md5))!.readAsString(), 'meme');
  });

  test('缓存目录和MD5文件的链接仍拒绝，外部文件不得被读取或改写', () async {
    final outside = await Directory.systemTemp.createTemp('resource-outside-');
    addTearDown(() => outside.delete(recursive: true));
    final outsideFile = File(p.join(outside.path, 'content'));
    await outsideFile.writeAsString('good');
    await Link(cache.directory.path).create(outside.path);
    await expectLater(
        cache.download(api.manifest('animation')), throwsFormatException);
    expect(await outsideFile.readAsString(), 'good');
    expect(
        await File(p.join(outside.path, 'animation.json')).exists(), isFalse);
    await Link(cache.directory.path).delete();
    await cache.directory.create();
    final manifest = api.manifest('animation');
    await File(p.join(cache.directory.path, 'animation.json'))
        .writeAsString(jsonEncode(manifest.toJson()));
    await Link(p.join(cache.directory.path, manifest.files.single.md5))
        .create(outsideFile.path);
    expect(
        await cache.filePath('animation', manifest.files.single.path), isNull);
    expect(await cache.cachedMeme(manifest.files.single.md5), isNull);
    await expectLater(cache.download(manifest), throwsFormatException);
    expect(await outsideFile.readAsString(), 'good');
  });

  test('MD5 文件跨路径与跨包复用，更新后删除服务端两清单均未引用的文件', () async {
    api.publish('animation', {'a.png': 'shared', 'b.png': 'shared'});
    api.publish('memes', {'face.png': 'shared', 'old.png': 'unused'});
    await cache.download(api.manifest('animation'));
    expect(api.downloads, ['animation/a.png']);
    final sharedPath = await cache.filePath('animation', 'a.png');
    expect(
        p.basename(sharedPath!), md5.convert(utf8.encode('shared')).toString());
    expect(await cache.filePath('animation', 'b.png'), sharedPath);
    await cache.download(api.manifest('memes'));
    expect(await cache.filePath('memes', 'face.png'), sharedPath);
    final oldPath = await cache.filePath('memes', 'old.png');
    api.downloads.clear();
    api.publish('animation', {'renamed.png': 'shared'});
    api.publish('memes', {'face.png': 'shared'});
    final orphan = File(p.join(cache.directory.path, 'unused.png'));
    await orphan.writeAsString('orphan');
    await cache.download(api.manifest('animation'));
    expect(api.downloads, isEmpty);
    expect(await cache.filePath('animation', 'renamed.png'), sharedPath);
    expect(await File(sharedPath).exists(), isTrue);
    expect(await File(oldPath!).exists(), isFalse);
    expect(await orphan.exists(), isFalse);
    expect(await cache.filePath('memes', 'old.png'), isNull);
    api.unpublished.add('memes');
    expect((await cache.check('memes')).unpublished, isTrue);
  });

  test('清单获取失败不能当成空清单清理缓存，恢复后更新可清理', () async {
    await cache.download(api.manifest('animation'));
    final oldPath = await cache.filePath('animation', '角色/EX/1.png');
    api.publish('animation', {'角色/EX/1.png': 'next'});
    api.failures.add('memes');
    await expectLater(cache.download(api.manifest('animation')),
        throwsA(isA<ApiException>()));
    expect(await File(oldPath!).exists(), isTrue);
    expect(
        await File((await cache.filePath('animation', '角色/EX/1.png'))!)
            .readAsString(),
        'next');
    api.failures.clear();
    await cache.download(api.manifest('animation'));
    expect(await File(oldPath).exists(), isFalse);
  });

  test('远端及本地清单拒绝穿越、Windows路径和冲突', () async {
    for (final path in [
      '../outside.png',
      '/absolute.png',
      r'a\b.png',
      'C:/file.png',
      'x:stream.png',
      'CON.png',
      'a./b.png',
      'a /b.png',
      '.hidden.png',
      'a//b.png'
    ]) {
      expect(
          () => ResourcePackManifest.fromJson(
              manifestPayload('animation', {path: 'x'}),
              pack: 'animation'),
          throwsFormatException,
          reason: path);
    }
    for (final paths in [
      {'A.png': 'x', 'a.png': 'y'},
      {'a.png': 'x', 'a.png/b.png': 'y'},
    ]) {
      expect(
          () => ResourcePackManifest.fromJson(
              manifestPayload('animation', paths),
              pack: 'animation'),
          throwsFormatException);
    }
    final bad = manifestPayload('animation', {'safe.png': 'x'})
      ..['total_size'] = 2;
    expect(() => ResourcePackManifest.fromJson(bad, pack: 'animation'),
        throwsFormatException);
    await cache.download(api.manifest('animation'));
    final current = File(p.join(cache.directory.path, 'animation.json'));
    await current.writeAsString(
        jsonEncode(manifestPayload('animation', {'../outside.png': 'x'})));
    expect(await cache.filePath('animation', '角色/EX/1.png'), isNull);
    final check = await cache.check('animation');
    expect(check.local, isNull);
    expect(check.needsDownload, isTrue);
    expect(check.error, contains('本地缓存不可用'));
  });

  test('动画脚本只允许 animation 包的 scripts 目录，清单本身永不下发', () {
    final payload =
        manifestPayload('animation', {'scripts/nested/sample.json': '{}'});
    final manifest = ResourcePackManifest.fromJson(payload, pack: 'animation');
    expect(manifest.files.single.path, 'scripts/nested/sample.json');
    for (final pack in resourcePackNames) {
      for (final path in [
        'manifest.json',
        'scripts/MANIFEST.json',
        'other/sample.json'
      ]) {
        expect(
            () => ResourcePackManifest.fromJson(
                manifestPayload(pack, {path: '{}'}),
                pack: pack),
            throwsFormatException);
      }
    }
    expect(
        () => ResourcePackManifest.fromJson(
            manifestPayload('memes', {'scripts/sample.json': '{}'}),
            pack: 'memes'),
        throwsFormatException);
  });

  testWidgets('入局先提示客户端更新再询问资源，刷新不重弹，换局重新检查', (tester) async {
    SharedPreferences.setMockInitialValues({});
    final store = GameStore.forPreview(
      preferences: await SharedPreferences.getInstance(),
      endpoint: api.endpoint,
      actor: Actor.fromJson({
        'id': 'p1',
        'account_id': 'a1',
        'kind': 'player',
        'game_id': 'game-1',
        'seat_id': '1',
        'name': '玩家'
      }),
      view: GameView.fromJson(gamePayload('game-1')),
      gameId: 'game-1',
    );
    store.api = api;
    addTearDown(store.dispose);
    final entryCache = EntryResources(api: api, supportDirectory: support);
    final release = EntryRelease();
    addTearDown(release.dispose);
    await tester.pumpWidget(MaterialApp(
      theme: buildAppTheme(),
      home: AnimatedBuilder(
          animation: store,
          builder: (context, _) => ResourcePackEntry(
                api: api,
                gameId: store.gameId!,
                store: store,
                release: release,
                resources: entryCache,
                child: GameShell(store: store, resources: cache),
              )),
    ));
    expect(find.byType(GameShell), findsNothing);
    expect(find.byType(ResourcePackDialog), findsNothing);
    release.pending.complete();
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.text('客户端更新 1.1.0'), findsOneWidget);
    expect(find.byType(ResourcePackDialog), findsNothing);
    expect(find.byType(GameShell), findsNothing);
    await tester.tap(find.text('稍后'));
    await tester.pump();
    entryCache.pending.complete([
      for (final pack in resourcePackNames)
        ResourcePackCheck(pack: pack, remote: api.manifest(pack)),
    ]);
    await tester.pumpAndSettle();
    expect(find.byType(ResourcePackDialog), findsOneWidget);
    expect(find.byType(GameShell), findsNothing);
    expect(api.downloads, isEmpty);
    await tester.tap(find.text('进入对局'));
    await tester.pumpAndSettle();
    expect(find.byType(GameShell), findsOneWidget);
    store.applyLiveEvent({'type': 'state', 'state': gamePayload('game-1')});
    await tester.pumpAndSettle();
    expect(find.byType(ResourcePackDialog), findsNothing);
    expect(find.text('客户端更新 1.1.0'), findsNothing);
    release.pending = Completer<void>();
    release.latest = '1.2.0';
    entryCache.pending = Completer<List<ResourcePackCheck>>();
    store.gameId = 'game-2';
    store.applyLiveEvent({'type': 'state', 'state': gamePayload('game-2')});
    await tester.pump();
    expect(find.byType(GameShell), findsNothing);
    release.pending.complete();
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.text('客户端更新 1.2.0'), findsOneWidget);
    expect(find.byType(ResourcePackDialog), findsNothing);
    await tester.tap(find.text('稍后'));
    await tester.pump();
    entryCache.pending.complete([
      for (final pack in resourcePackNames)
        ResourcePackCheck(pack: pack, remote: api.manifest(pack)),
    ]);
    await tester.pumpAndSettle();
    expect(find.byType(ResourcePackDialog), findsOneWidget);
    expect(find.byType(GameShell), findsNothing);
    expect(api.downloads, isEmpty);
    await tester.tap(find.text('进入对局'));
    await tester.pumpAndSettle();
    await tester.pumpWidget(const SizedBox.shrink());
  });
}
