import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:path/path.dart' as p;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:seven_double_client/src/api.dart';
import 'package:seven_double_client/src/emoji.dart';
import 'package:seven_double_client/src/emoji_picker.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/resource_packs.dart';
import 'package:seven_double_client/src/shell.dart';
import 'package:seven_double_client/src/store.dart';

class ObservedPacks extends ResourcePacks {
  ObservedPacks({required super.api, required super.supportDirectory});
  var loaded = Completer<void>();
  final selected = Completer<void>();
  var received = Completer<void>();

  @override
  Future<ResourcePackManifest?> localManifest(String pack) async {
    try {
      return await super.localManifest(pack);
    } finally {
      if (!loaded.isCompleted) loaded.complete();
    }
  }

  @override
  Future<String?> filePath(String pack, String path) async {
    try {
      return await super.filePath(pack, path);
    } finally {
      if (!selected.isCompleted) selected.complete();
    }
  }

  @override
  Future<File?> cachedMeme(String hash) async {
    try {
      return await super.cachedMeme(hash);
    } finally {
      if (!received.isCompleted) received.complete();
    }
  }
}

Future<ObservedPacks> installedPack(Map<String, Uint8List> images) async {
  final support = await Directory.systemTemp.createTemp('emoji-memes-');
  final api = GameApi(ServerEndpoint.parse('http://127.0.0.1:1'));
  final cache = ObservedPacks(api: api, supportDirectory: support);
  addTearDown(() {
    api.close();
    support.deleteSync(recursive: true);
  });
  await cache.directory.create();
  final paths = images.keys.toList()..sort();
  final files = <Map<String, Object>>[];
  for (final path in paths) {
    final bytes = images[path]!;
    final hash = md5.convert(bytes).toString();
    files.add({'path': path, 'size': bytes.length, 'md5': hash});
    await File(p.join(cache.directory.path, hash)).writeAsBytes(bytes);
  }
  await File(p.join(cache.directory.path, 'memes.json'))
      .writeAsString(jsonEncode({
    'pack': 'memes',
    'version': md5.convert(utf8.encode(jsonEncode(files))).toString(),
    'total_size':
        images.values.fold<int>(0, (size, bytes) => size + bytes.length),
    'files': files,
  }));
  return cache;
}

Future<Uint8List> assetBytes(EmojiFace face) async {
  final data = await rootBundle.load(face.asset);
  return data.buffer.asUint8List(data.offsetInBytes, data.lengthInBytes);
}

Future<void> showPanel(WidgetTester tester, ObservedPacks cache,
    Future<void> Function(String) onPick) async {
  cache.loaded = Completer<void>();
  await tester.runAsync(() async {
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: EmojiPicker(
      height: 450,
      resources: cache,
      onPick: (_) {},
      onPickMeme: onPick,
    ))));
    await cache.loaded.future.timeout(const Duration(seconds: 5));
    await Future<void>.delayed(Duration.zero);
  });
  await tester.pump();
}

GameMessage stickerMessage(String hash, {bool recalled = false}) =>
    GameMessage.fromJson({
      'id': 1,
      'kind': 'chat',
      'text': '',
      'channel_id': 'public',
      'sender_id': 'p2',
      'sticker_md5': hash,
      'recalled': recalled,
      'payload': {'type': 'sticker', 'md5': hash},
    });

void main() {
  LiveTestWidgetsFlutterBinding.ensureInitialized().framePolicy =
      LiveTestWidgetsFlutterBindingFramePolicy.onlyPumps;
  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    loadRecentEmojiIds(await SharedPreferences.getInstance());
  });

  testWidgets('目录首图、纯图片内容与点选发送真实 MD5', (tester) async {
    late ObservedPacks cache;
    late Uint8List first;
    await tester.runAsync(() async {
      first = await assetBytes(emojiFaces.first);
      final second = await assetBytes(emojiFaces[1]);
      cache = await installedPack({
        'Pack/b.png': second,
        'Pack/a.png': first,
        'Other/a.png': second,
      });
    });
    String? picked;
    await showPanel(tester, cache, (hash) async {
      picked = hash;
    });
    final icon = tester.widget<Image>(find.descendant(
        of: find.byTooltip('Pack'), matching: find.byType(Image)));
    final provider = icon.image as ResizeImage;
    expect((provider.imageProvider as FileImage).file.path,
        p.join(cache.directory.path, md5.convert(first).toString()));
    await tester.tap(find.byTooltip('Pack'));
    await tester.pump();
    final cell = find.byKey(const ValueKey('all:meme:Pack/a.png'));
    expect(find.byKey(const ValueKey('all:meme:Other/a.png')), findsNothing);
    expect(
        find.descendant(of: cell, matching: find.byType(Text)), findsNothing);
    await tester.runAsync(() async {
      await tester.tap(cell);
      await cache.selected.future.timeout(const Duration(seconds: 5));
      await Future<void>.delayed(Duration.zero);
    });
    await tester.pump();
    expect(picked, md5.convert(first).toString());
    expect(recentEmojiIds, isEmpty);
    recentEmojiIds.clear();
    loadRecentEmojiIds(await SharedPreferences.getInstance());
    expect(recentEmojiIds, isEmpty);
    await tester.pumpWidget(const SizedBox());
    await showPanel(tester, cache, (hash) async {
      picked = hash;
    });
    expect(find.byKey(const ValueKey('recent:meme:Pack/a.png')), findsNothing);
    await tester.pumpWidget(const SizedBox());
  });

  for (final remove in [true, false]) {
    testWidgets('打开后${remove ? '移除' : '破坏'}缓存不会误发', (tester) async {
      late ObservedPacks cache;
      late Uint8List bytes;
      await tester.runAsync(() async {
        bytes = await assetBytes(emojiFaces.first);
        cache = await installedPack({'Pack/a.png': bytes});
      });
      String? sent;
      await showPanel(tester, cache, (hash) async => sent = hash);
      await tester.tap(find.byTooltip('Pack'));
      await tester.pump();
      await tester.runAsync(() async {
        final file =
            File(p.join(cache.directory.path, md5.convert(bytes).toString()));
        if (remove) {
          await file.delete();
        } else {
          await file.writeAsBytes(List<int>.filled(bytes.length, 0));
        }
        await tester.tap(find.byKey(const ValueKey('all:meme:Pack/a.png')));
        await cache.selected.future.timeout(const Duration(seconds: 5));
        await Future<void>.delayed(Duration.zero);
      });
      await tester.pump();
      expect(sent, isNull);
      expect(recentEmojiIds, isEmpty);
      expect(find.byKey(const ValueKey('all:meme:Pack/a.png')), findsNothing);
      await tester.pumpWidget(const SizedBox());
    });
  }

  test('共享 MD5 文件无需 memes 映射，坏内容与缺文件不可用', () async {
    final bytes = await assetBytes(emojiFaces.first);
    final cache = await installedPack({'Pack/a.png': bytes});
    final hash = md5.convert(bytes).toString();
    await File(p.join(cache.directory.path, 'memes.json')).delete();
    final file = (await cache.cachedMeme(hash))!;
    expect(await file.readAsBytes(), bytes);
    await file.writeAsBytes(List<int>.filled(bytes.length, 0));
    expect(await cache.cachedMeme(hash), isNull);
    await file.writeAsBytes(bytes);
    expect(await (await cache.cachedMeme(hash))!.readAsBytes(), bytes);
    await file.delete();
    expect(await cache.cachedMeme(hash), isNull);
    expect(stickerMessage(hash, recalled: true).stickerMd5, isNull);
    expect(() => stickerMessage('../cache'), throwsFormatException);
  });

  testWidgets('未下载表情有占位，已下载接收图在窄宽屏都有固定上限', (tester) async {
    late ObservedPacks cache;
    late String hash;
    await tester.runAsync(() async {
      final bytes = await assetBytes(emojiFaces.first);
      hash = md5.convert(bytes).toString();
      cache = await installedPack({'Pack/a.png': bytes});
      await File(p.join(cache.directory.path, 'memes.json')).delete();
    });
    for (final width in [360.0, 1000.0]) {
      tester.view.physicalSize = Size(width, 700);
      tester.view.devicePixelRatio = 1;
      await tester.pumpWidget(MaterialApp(
          home: Scaffold(
              body: MessageBubble(
        message: stickerMessage(hash),
      ))));
      await tester.pump();
      expect(find.bySemanticsLabel('表情资源未下载或不可用'), findsOneWidget);
      final edge = width < 600 ? 128.0 : 160.0;
      expect(tester.getSize(find.bySemanticsLabel('表情资源未下载或不可用')),
          Size(edge, edge));
      cache.received = Completer<void>();
      await tester.runAsync(() async {
        await tester.pumpWidget(MaterialApp(
            home: Scaffold(
                body: MessageBubble(
          message: stickerMessage(hash),
          resources: cache,
        ))));
        await cache.received.future.timeout(const Duration(seconds: 5));
        await Future<void>.delayed(Duration.zero);
      });
      await tester.pump();
      final image = find.bySemanticsLabel('聊天表情');
      expect(image, findsOneWidget);
      expect(tester.getSize(image), Size(edge, edge));
    }
    tester.view.resetPhysicalSize();
    tester.view.resetDevicePixelRatio();
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('聊天点下载表情立即发送独立 MD5 消息，文本草稿不变', (tester) async {
    final overrides = HttpOverrides.current;
    HttpOverrides.global = null;
    addTearDown(() => HttpOverrides.global = overrides);
    late HttpServer server;
    late ObservedPacks cache;
    late GameStore store;
    late String hash;
    final sent = Completer<void>();
    Map<String, dynamic>? requestBody;
    await tester.runAsync(() async {
      final bytes = await assetBytes(emojiFaces.first);
      hash = md5.convert(bytes).toString();
      cache = await installedPack({'Pack/a.png': bytes});
      server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      server.listen((request) async {
        requestBody = jsonDecode(await utf8.decoder.bind(request).join())
            as Map<String, dynamic>;
        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode({
          'id': 1,
          'kind': 'chat',
          'text': '',
          'channel_id': 'public',
          'sender_id': 'p1',
          'sticker_md5': hash,
          'payload': {'type': 'sticker', 'md5': hash},
        }));
        await request.response.close();
      });
      final endpoint = ServerEndpoint.parse('http://127.0.0.1:${server.port}');
      store = GameStore.forPreview(
        preferences: await SharedPreferences.getInstance(),
        endpoint: endpoint,
        actor: Actor.fromJson(
            {'id': 'p1', 'kind': 'player', 'seat_id': '1', 'name': 'A'}),
        gameId: 'game-1',
        view: GameView.fromJson({
          'ui_version': 1,
          'id': 'game-1',
          'version': 1,
          'status': 'playing',
          'day': 1,
          'half': 'day',
          'phase': 'discussion',
          'phase_label': 'Discussion',
          'seats': <dynamic>[],
          'self': <String, dynamic>{},
          'public': <String, dynamic>{},
          'actions': <dynamic>[],
          'channels': [
            {
              'id': 'public',
              'label': 'Public',
              'status': 'active',
              'can_send': true,
              'reason': '',
              'actions': <dynamic>[]
            }
          ],
        }),
      );
      store.addListener(() {
        if (!store.writeBusy &&
            store.messages.any((message) => message.stickerMd5 == hash)) {
          if (!sent.isCompleted) sent.complete();
        }
      });
    });
    addTearDown(() async {
      store.dispose();
      await server.close(force: true);
    });
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: ChatActionPage(
      store: store,
      resources: cache,
      bottomInset: 0,
    ))));
    await tester.enterText(find.byType(TextField), '保留草稿');
    await tester.runAsync(() async {
      await tester.tap(find.byIcon(Icons.emoji_emotions_outlined));
      await tester.pump();
      await cache.loaded.future.timeout(const Duration(seconds: 5));
      await Future<void>.delayed(Duration.zero);
    });
    await tester.pump();
    await tester.tap(find.byTooltip('Pack'));
    await tester.pump();
    await tester.runAsync(() async {
      await tester.tap(find.byKey(const ValueKey('all:meme:Pack/a.png')));
      await sent.future.timeout(const Duration(seconds: 5));
      await Future<void>.delayed(Duration.zero);
    });
    await tester.pump();
    expect(requestBody, {'channel_id': 'public', 'sticker_md5': hash});
    expect(store.messages.single.stickerMd5, hash);
    expect(store.messages.single.text, '');
    expect(store.messages.single.image, isNull);
    expect(tester.widget<TextField>(find.byType(TextField)).controller!.text,
        '保留草稿');
    expect(find.byType(AlertDialog), findsNothing);
    expect(recentEmojiIds, isEmpty);
    await tester.pumpWidget(const SizedBox());
  });
}
