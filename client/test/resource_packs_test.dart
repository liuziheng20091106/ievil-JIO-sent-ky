import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:path/path.dart' as p;
import 'package:seven_double_client/src/api.dart';
import 'package:seven_double_client/src/design.dart';
import 'package:seven_double_client/src/models.dart';
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
    'version': md5.convert(utf8.encode(jsonEncode(files))).toString(),
    'total_size': contents.values
        .fold<int>(0, (sum, value) => sum + utf8.encode(value).length),
    'files': files,
  };
}

class ResourceApi extends GameApi {
  ResourceApi([String server = 'http://127.0.0.1:19285'])
      : super(ServerEndpoint.parse(server));
  final manifests = <String, Map<String, dynamic>>{};
  final contents = <String, String>{};
  final downloads = <String>[];
  final unpublished = <String>{};
  final failures = <String>{};
  void Function()? afterDownload;

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
  });
  tearDown(() async {
    api.close();
    await support.delete(recursive: true);
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

  testWidgets('进局前询问，选择继续才挂载对局，刷新不重弹，换局重新检查', (tester) async {
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
    await tester.pumpWidget(MaterialApp(
      theme: buildAppTheme(),
      home: AnimatedBuilder(
          animation: store,
          builder: (context, _) => ResourcePackEntry(
                api: api,
                gameId: store.gameId!,
                resources: entryCache,
                child: GameShell(store: store, resources: cache),
              )),
    ));
    expect(find.byType(GameShell), findsNothing);
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
    entryCache.pending = Completer<List<ResourcePackCheck>>();
    store.gameId = 'game-2';
    store.applyLiveEvent({'type': 'state', 'state': gamePayload('game-2')});
    await tester.pump();
    expect(find.byType(GameShell), findsNothing);
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
