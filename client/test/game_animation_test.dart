import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lottie/lottie.dart';
import 'package:path/path.dart' as p;
import 'package:shared_preferences/shared_preferences.dart';
import 'package:seven_double_client/main.dart';
import 'package:seven_double_client/src/animation_player.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/release.dart';
import 'package:seven_double_client/src/resource_packs.dart';
import 'package:seven_double_client/src/store.dart';

import 'golden_harness.dart';

const _speech = 'scripts/interrogation-start.json';
const _skill = 'scripts/skill-cut-in.json';
const _gameId = 'animation-game';

Map<String, dynamic> animationView({String gameId = _gameId}) => {
      'ui_version': 1,
      'id': gameId,
      'version': 1,
      'status': 'playing',
      'day': 1,
      'half': 'day',
      'phase': 'speech',
      'phase_label': '顺序发言',
      'seats': <dynamic>[],
      'self': <String, dynamic>{},
      'actions': <dynamic>[],
      'public': <String, dynamic>{},
      'channels': [
        {
          'id': 'public',
          'label': '公开讨论',
          'status': 'active',
          'can_send': true,
          'reason': '',
          'actions': <dynamic>[],
        }
      ],
    };

Map<String, dynamic> animationMessage(int id,
        {String script = _speech,
        String channel = 'system',
        Map<String, String> images = const {},
        Map<String, String> texts = const {},
        String gameId = _gameId}) =>
    {
      'id': id,
      'game_id': gameId,
      'kind': script == _speech ? 'speech_turn' : 'information',
      'channel_id': channel,
      'text': '动画事件',
      'payload': {
        'type': script == _speech ? 'speech_turn' : 'skill',
        'animation': {'script': script, 'images': images, 'texts': texts},
      },
    };

/// Native smoke entrypoints can use the same isolated, verified disk cache.
Future<void> installAnimationCache(
    ResourcePacks cache, Map<String, Uint8List> contents) async {
  await cache.directory.create(recursive: true);
  final paths = contents.keys.toList()..sort();
  final files = <Map<String, Object>>[];
  for (final path in paths) {
    final bytes = contents[path]!;
    final hash = md5.convert(bytes).toString();
    await File(p.join(cache.directory.path, hash)).writeAsBytes(bytes);
    files.add({'path': path, 'size': bytes.length, 'md5': hash});
  }
  await File(p.join(cache.directory.path, 'animation.json'))
      .writeAsString(jsonEncode({
    'pack': 'animation',
    'version': md5.convert(utf8.encode(jsonEncode(files))).toString(),
    'total_size':
        contents.values.fold<int>(0, (sum, bytes) => sum + bytes.length),
    'files': files,
  }));
}

Future<Uint8List> _png(Color color, {int width = 16, int height = 8}) async {
  final recorder = ui.PictureRecorder();
  Canvas(recorder).drawRect(
      Rect.fromLTWH(0, 0, width.toDouble(), height.toDouble()),
      Paint()..color = color);
  final picture = recorder.endRecording();
  final image = await picture.toImage(width, height);
  final data = await image.toByteData(format: ui.ImageByteFormat.png);
  final bytes = Uint8List.fromList(
      data!.buffer.asUint8List(data.offsetInBytes, data.lengthInBytes));
  image.dispose();
  picture.dispose();
  return bytes;
}

/// Render the real Lottie drawable, including loaded images and layer alpha.
Future<Uint8List> recordCompositionFrame(
    LottieComposition composition, double progress,
    {int width = 192, int height = 108}) async {
  final recorder = ui.PictureRecorder();
  final drawable = LottieDrawable(composition, frameRate: FrameRate.max);
  drawable.setProgress(progress);
  drawable.draw(Canvas(recorder),
      Rect.fromLTWH(0, 0, width.toDouble(), height.toDouble()),
      fit: BoxFit.contain);
  final picture = recorder.endRecording();
  final image = await picture.toImage(width, height);
  final data = await image.toByteData(format: ui.ImageByteFormat.rawRgba);
  final bytes = Uint8List.fromList(
      data!.buffer.asUint8List(data.offsetInBytes, data.lengthInBytes));
  image.dispose();
  picture.dispose();
  return bytes;
}

Map<String, dynamic> _transform(List<num> position) => {
      'o': {'a': 0, 'k': 100},
      'r': {'a': 0, 'k': 0},
      'p': {'a': 0, 'k': position},
      'a': {
        'a': 0,
        'k': [0, 0, 0]
      },
      's': {
        'a': 0,
        'k': [100, 100, 100]
      },
    };

Map<String, dynamic> _solid() => {
      'v': '5.13.0',
      'fr': 30,
      'ip': 0,
      'op': 30,
      'w': 64,
      'h': 64,
      'assets': <dynamic>[],
      'layers': [
        {
          'ty': 1,
          'ind': 1,
          'sw': 64,
          'sh': 64,
          'sc': '#ff0000',
          'ip': 0,
          'op': 30,
          'st': 0,
          'ks': _transform([0, 0, 0]),
        }
      ],
    };

Future<void> _installSpeech(ResourcePacks cache) =>
    installAnimationCache(cache, {
      _speech: Uint8List.fromList(utf8.encode(jsonEncode(_solid()))),
    });

Future<void> _installSkill(ResourcePacks cache) async {
  final root = Directory('../resources/animation');
  final bytes = await File(p.join(root.path, _skill)).readAsBytes();
  final script = jsonDecode(utf8.decode(bytes)) as Map<String, dynamic>;
  final contents = <String, Uint8List>{_skill: bytes};
  for (final asset in script['assets'] as List) {
    if (asset['p'] == null) continue;
    final path = animationImagePath(_skill, asset['u'], asset['p']);
    contents[path] = await File(p.join(root.path, path)).readAsBytes();
  }
  contents['annan/EX/1.png'] = await _png(const Color(0xffff0000));
  contents['annan/normal/1.png'] =
      await _png(const Color(0xff0000ff), width: 8, height: 16);
  await installAnimationCache(cache, contents);
}

class _DelayedCache extends ResourcePacks {
  _DelayedCache(ResourcePacks cache)
      : super(api: cache.api, supportDirectory: cache.supportDirectory);
  final entered = Completer<void>();
  final release = Completer<void>();
  final finished = Completer<void>();
  bool _delayed = false;

  @override
  Future<String?> filePath(String pack, String path) async {
    if (!_delayed && path == _speech) {
      _delayed = true;
      entered.complete();
      await release.future;
    }
    final target = await super.filePath(pack, path);
    if (path == _speech && !finished.isCompleted) finished.complete();
    return target;
  }
}

class _GateCache extends ResourcePacks {
  _GateCache(ResourcePacks cache)
      : super(api: cache.api, supportDirectory: cache.supportDirectory);

  @override
  Future<List<ResourcePackCheck>> checkAll() async => [
        const ResourcePackCheck(pack: 'animation', error: '资源待确认'),
        const ResourcePackCheck(pack: 'memes', unpublished: true),
      ];
}

Future<void> _waitFor(WidgetTester tester, bool Function() ready) async {
  await tester.runAsync(() async {
    for (var i = 0; i < 200 && !ready(); i++) {
      await tester.pump();
      await Future<void>.delayed(const Duration(milliseconds: 5));
    }
  });
  await tester.pump();
  expect(ready(), isTrue);
}

final _body = find.byKey(const ValueKey('game-animation-body'));
final _mask = find.byKey(const ValueKey('game-animation-mask'));

void _live(GameStore store, Map<String, dynamic> message) =>
    store.applyLiveEvent({'type': 'message', 'message': message});

void main() {
  LiveTestWidgetsFlutterBinding.ensureInitialized().framePolicy =
      LiveTestWidgetsFlutterBindingFramePolicy.onlyPumps;
  late Directory support;
  late GameStore store;
  late ResourcePacks cache;
  late ReleaseMonitor release;

  setUpAll(loadBundledFonts);
  setUp(() async {
    SharedPreferences.setMockInitialValues({});
    final preferences = await SharedPreferences.getInstance();
    support = await Directory.systemTemp.createTemp('game-animation-');
    store = GameStore.forPreview(
        preferences: preferences,
        endpoint: ServerEndpoint.parse('http://127.0.0.1:1'),
        actor: Actor.fromJson({
          'id': 'owner',
          'account_id': 'owner',
          'kind': 'player',
          'seat_id': '1',
          'name': '玩家'
        }),
        gameId: _gameId,
        view: GameView.fromJson(animationView()));
    cache = ResourcePacks(api: store.api!, supportDirectory: support);
    release = ReleaseMonitor(preferences: preferences);
    await _installSpeech(cache);
  });
  tearDown(() async {
    cache.api.close();
    store.api?.close();
    store.dispose();
    release.dispose();
    await support.delete(recursive: true);
  });

  Future<void> mount(WidgetTester tester,
      {ResourcePacks? resources,
      GlobalKey? boundary,
      bool skipGate = true}) async {
    if (skipGate) store.api = null;
    final app = SevenDoubleApp(
        store: store, release: release, resources: resources ?? cache);
    await tester.pumpWidget(
        boundary == null ? app : RepaintBoundary(key: boundary, child: app));
    await tester.pump();
  }

  testWidgets(
      'resource question never plays or queues effects before GameShell mounts',
      (tester) async {
    await mount(tester, resources: _GateCache(cache), skipGate: false);
    await _waitFor(tester, () => find.text('进入对局').evaluate().isNotEmpty);
    _live(store, animationMessage(1));
    await tester.pump();
    expect(_body, findsNothing);
    expect(_mask, findsNothing);
    await tester.tap(find.text('进入对局'));
    await tester.pump(const Duration(milliseconds: 400));
    _live(store, animationMessage(1));
    await tester.pump();
    expect(_body, findsNothing);
    _live(store, animationMessage(2));
    await _waitFor(tester, () => _body.evaluate().isNotEmpty);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('new game drops old events but newly mounted shell stays active',
      (tester) async {
    await mount(tester);
    _live(store, animationMessage(1));
    await _waitFor(tester, () => _body.evaluate().isNotEmpty);
    store.gameId = 'next-game';
    store.applyLiveEvent(
        {'type': 'state', 'state': animationView(gameId: 'next-game')});
    await tester.pump();
    expect(_mask, findsNothing);
    _live(store, animationMessage(2));
    await tester.pump();
    expect(_body, findsNothing);
    _live(store, animationMessage(1, gameId: 'next-game'));
    await _waitFor(tester, () => _body.evaluate().isNotEmpty);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('missing newest resource also invalidates an older pending load',
      (tester) async {
    final delayed = _DelayedCache(cache);
    await mount(tester, resources: delayed);
    _live(store, animationMessage(1));
    await tester.runAsync(() => delayed.entered.future);
    _live(store, animationMessage(2, script: 'scripts/missing.json'));
    delayed.release.complete();
    await tester.runAsync(() => delayed.finished.future);
    await tester.pump();
    expect(_body, findsNothing);
    expect(_mask, findsNothing);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets(
      'history sync reconnect and duplicate ids never replay; live speech plays once',
      (tester) async {
    await mount(tester);
    final history = animationMessage(1);
    store.mergeMessagesForTest([GameMessage.fromJson(history)]);
    store.applyLiveEvent({
      'type': 'sync',
      'state': animationView(),
      'messages': [animationMessage(2)]
    });
    _live(store, history);
    _live(store, animationMessage(2));
    await tester.pump();
    expect(_body, findsNothing);
    _live(store, animationMessage(3));
    await _waitFor(tester, () => _body.evaluate().isNotEmpty);
    final controller =
        tester.widget<Lottie>(_body).controller as AnimationController;
    await tester.pump(const Duration(milliseconds: 400));
    expect(controller.value, greaterThan(.3));
    _live(store, animationMessage(3));
    await tester.pump();
    expect(
        identical(tester.widget<Lottie>(_body).controller, controller), isTrue);
    expect(controller.value, greaterThan(.3));
    await tester.pump(const Duration(seconds: 2));
    expect(_body, findsNothing);
    expect(_mask, findsNothing);
    _live(store, animationMessage(3));
    await tester.pump();
    expect(_body, findsNothing);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets(
      'new missing or malformed resources stop old playback and leave no mask',
      (tester) async {
    await mount(tester);
    _live(store, animationMessage(1));
    await _waitFor(tester, () => _body.evaluate().isNotEmpty);
    final controller =
        tester.widget<Lottie>(_body).controller as AnimationController;
    _live(store, animationMessage(2, script: 'scripts/missing.json'));
    expect(controller.isAnimating, isFalse);
    await tester.pump();
    expect(_body, findsNothing);
    expect(_mask, findsNothing);
    await tester.runAsync(() => installAnimationCache(cache, {
          'scripts/broken.json': Uint8List.fromList(utf8.encode('{broken')),
        }));
    _live(store, animationMessage(3, script: 'scripts/broken.json'));
    await tester.runAsync(
        () => Future<void>.delayed(const Duration(milliseconds: 100)));
    await tester.pump();
    expect(_mask, findsNothing);
    expect(find.byType(CircularProgressIndicator), findsNothing);
    expect(find.textContaining('动画无法播放'), findsNothing);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('late old asynchronous load cannot cover the latest animation',
      (tester) async {
    await tester.runAsync(() => installAnimationCache(cache, {
          _speech: Uint8List.fromList(utf8.encode(jsonEncode(_solid()))),
          'scripts/new.json': Uint8List.fromList(
              utf8.encode(jsonEncode(_solid()..['op'] = 60))),
        }));
    final delayed = _DelayedCache(cache);
    await mount(tester, resources: delayed);
    _live(store, animationMessage(1));
    await tester.runAsync(() => delayed.entered.future);
    _live(store, animationMessage(2, script: 'scripts/new.json'));
    await _waitFor(tester, () => _body.evaluate().isNotEmpty);
    final latest = tester.widget<Lottie>(_body).composition!;
    expect(latest.duration, const Duration(seconds: 2));
    delayed.release.complete();
    await tester.runAsync(() => delayed.finished.future);
    await tester.pump();
    expect(identical(tester.widget<Lottie>(_body).composition, latest), isTrue);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets(
      'root animation paints above dialogs with an opaque body and translucent mask',
      (tester) async {
    final boundary = GlobalKey();
    await mount(tester, boundary: boundary);
    final navigator =
        tester.state<NavigatorState>(find.byType(Navigator).first);
    unawaited(showDialog<void>(
        context: navigator.context,
        builder: (_) => const Dialog(
            child: SizedBox(
                width: 500,
                height: 400,
                child: ColoredBox(color: Colors.white)))));
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.byType(Dialog), findsOneWidget);
    _live(store, animationMessage(1));
    await _waitFor(tester, () => _body.evaluate().isNotEmpty);
    final controller =
        tester.widget<Lottie>(_body).controller as AnimationController;
    controller.stop();
    controller.value = .5;
    await tester.pump();
    final mask = tester.widget<ColoredBox>(_mask);
    expect(mask.color.a, closeTo(.55, .01));
    expect(
        find.ancestor(of: _body, matching: find.byType(Opacity)), findsNothing);
    final render =
        boundary.currentContext!.findRenderObject() as RenderRepaintBoundary;
    final image = await render.toImage(pixelRatio: 1);
    final data = await image.toByteData(format: ui.ImageByteFormat.rawRgba);
    final x = image.width ~/ 2, y = image.height ~/ 2;
    final pixel = data!.buffer
        .asUint8List(data.offsetInBytes + (y * image.width + x) * 4, 4);
    expect(pixel.toList(), [255, 0, 0, 255]);
    image.dispose();
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets(
      'private owner skill plays outside scope and exit stops and releases images',
      (tester) async {
    await tester.runAsync(() => _installSkill(cache));
    await mount(tester);
    store.messageScope = 'public';
    _live(
        store,
        animationMessage(1,
            script: _skill,
            channel: 'private:owner',
            images: {'skill-portrait': 'annan/EX/1.png'},
            texts: {'role-title': '夏目安安 · 魔女', 'skill-name': '全场洗脑'}));
    await _waitFor(tester, () => _body.evaluate().isNotEmpty);
    final composition = tester.widget<Lottie>(_body).composition!;
    final controller =
        tester.widget<Lottie>(_body).controller as AnimationController;
    expect(
        composition.layers
            .firstWhere((layer) => layer.name == 'role-title')
            .text!
            .keyframes
            .first
            .startValue!
            .text,
        '夏目安安 · 魔女');
    await tester.runAsync(store.returnToLobby);
    expect(controller.isAnimating, isFalse);
    expect(
        composition.images.values.every((asset) => asset.loadedImage == null),
        isTrue);
    await tester.pump();
    expect(_mask, findsNothing);
    _live(store, animationMessage(2));
    await tester.pump();
    expect(_body, findsNothing);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  test(
      'private template overrides keep title, full long names and distinct unscaled source bitmaps',
      () async {
    await _installSkill(cache);
    final ex = await loadAnimationComposition(cache, _skill,
        images: {'skill-portrait': 'annan/EX/1.png'},
        texts: {'role-title': '夏目安安 · 魔女', 'skill-name': '全场洗脑'});
    final name = '这是一个很长很长且必须完整呈现不能裁切的技能名称';
    final normal = await loadAnimationComposition(cache, _skill,
        images: {'skill-portrait': 'annan/normal/1.png'},
        texts: {'role-title': '夏目安安 · 普通', 'skill-name': name});
    final exTitle = ex.layers
        .firstWhere((layer) => layer.name == 'role-title')
        .text!
        .keyframes
        .first
        .startValue!;
    final normalTitle = normal.layers
        .firstWhere((layer) => layer.name == 'role-title')
        .text!
        .keyframes
        .first
        .startValue!;
    final skillName = normal.layers
        .firstWhere((layer) => layer.name == 'skill-name')
        .text!
        .keyframes
        .first
        .startValue!;
    expect(exTitle.text, '夏目安安 · 魔女');
    expect(normalTitle.text, '夏目安安 · 普通');
    expect(skillName.text, name);
    final painter = TextPainter(
        textDirection: TextDirection.ltr,
        text: TextSpan(
            text: name,
            style: TextStyle(
                fontFamily: 'HarmonyOS Sans SC',
                fontSize: skillName.size,
                fontWeight: FontWeight.bold)))
      ..layout();
    expect(painter.width, lessThanOrEqualTo(1000.01));
    painter.dispose();
    final exImage = ex.images.values.single.loadedImage!;
    final normalImage = normal.images.values.single.loadedImage!;
    expect([exImage.width, exImage.height], [16, 8]);
    expect([normalImage.width, normalImage.height], [8, 16]);
    final exFrame = await recordCompositionFrame(ex, .45);
    final normalFrame = await recordCompositionFrame(normal, .45);
    expect(exFrame, isNot(orderedEquals(normalFrame)));
    disposeAnimationComposition(ex);
    disposeAnimationComposition(normal);
    await expectLater(
        loadAnimationComposition(cache, _skill,
            images: {'skill-portrait': '../memes/1.png'}),
        throwsFormatException);
    final memeBytes = await _png(const Color(0xff0000ff), width: 8, height: 16);
    final memeHash = md5.convert(memeBytes).toString();
    await File(p.join(cache.directory.path, memeHash)).writeAsBytes(memeBytes);
    await File(p.join(cache.directory.path, 'memes.json'))
        .writeAsString(jsonEncode({
      'pack': 'memes',
      'version': memeHash,
      'total_size': memeBytes.length,
      'files': [
        {'path': 'memes-only/1.png', 'size': memeBytes.length, 'md5': memeHash}
      ],
    }));
    await expectLater(
        loadAnimationComposition(cache, _skill,
            images: {'skill-portrait': 'memes-only/1.png'}),
        throwsFormatException);
  });

  test('short and long skill titles stay inside the banner while drifting',
      () async {
    await _installSkill(cache);
    for (final name in ['爱上/移情', '这是一个很长很长且必须完整呈现不能裁切的技能名称']) {
      for (final progress in [.4, .6]) {
        final composition = await loadAnimationComposition(cache, _skill,
            images: {'skill-portrait': 'annan/EX/1.png'},
            texts: {'role-title': '玛格 · 魔女', 'skill-name': name});
        final frame = await recordCompositionFrame(composition, progress,
            width: 480, height: 270);
        composition.layers
            .removeWhere((layer) => layer.name != 'crimson-banner');
        final banner = await recordCompositionFrame(composition, progress,
            width: 480, height: 270);
        var textPixels = 0;
        var outside = 0;
        for (var offset = 0; offset < frame.length; offset += 4) {
          if (frame[offset] > 235 &&
              frame[offset + 1] > 210 &&
              frame[offset + 2] > 160 &&
              frame[offset + 3] > 220) {
            textPixels++;
            if (banner[offset + 3] < 200) outside++;
          }
        }
        expect(textPixels, greaterThan(100), reason: name);
        expect(outside, 0, reason: '$name at $progress');
        disposeAnimationComposition(composition);
      }
    }
  });

  test(
      'portrait fit preserves aspect ratio and transparent letterbox without PNG resampling',
      () async {
    final sample = _solid();
    sample['assets'] = [
      {
        'id': 'portrait',
        'w': 40,
        'h': 40,
        'u': 'images/',
        'p': 'default.png',
        'e': 0,
      }
    ];
    sample['layers'] = [
      {
        'ty': 2,
        'ind': 1,
        'refId': 'portrait',
        'ip': 0,
        'op': 30,
        'st': 0,
        'ks': _transform([12, 12, 0]),
      }
    ];
    await installAnimationCache(cache, {
      _skill: Uint8List.fromList(utf8.encode(jsonEncode(sample))),
      'annan/EX/1.png': await _png(const Color(0xffff0000)),
    });
    final composition = await loadAnimationComposition(cache, _skill,
        images: {'portrait': 'annan/EX/1.png'});
    final frame =
        await recordCompositionFrame(composition, .5, width: 64, height: 64);
    List<int> pixel(int x, int y) =>
        frame.sublist((y * 64 + x) * 4, (y * 64 + x) * 4 + 4);
    expect(pixel(32, 15), [0, 0, 0, 0]);
    expect(pixel(32, 24), [255, 0, 0, 255]);
    expect(pixel(32, 40), [255, 0, 0, 255]);
    expect(pixel(32, 48), [0, 0, 0, 0]);
    expect(composition.images.values.single.loadedImage!.width, 16);
    disposeAnimationComposition(composition);
  });

  test('custom shape script ignores unused portrait and text slots', () async {
    final composition = await loadAnimationComposition(cache, _speech,
        images: {'skill-portrait': 'annan/EX/missing.png'},
        texts: {'role-title': '夏目安安 · 魔女', 'skill-name': '全场洗脑'});
    final frame =
        await recordCompositionFrame(composition, .5, width: 64, height: 64);
    expect(frame.sublist((32 * 64 + 32) * 4, (32 * 64 + 32) * 4 + 4),
        [255, 0, 0, 255]);
    disposeAnimationComposition(composition);
  });
}
