import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lottie/lottie.dart';
import 'package:path/path.dart' as p;
import 'package:seven_double_client/src/animation_player.dart';
import 'package:seven_double_client/src/api.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/resource_pack_dialog.dart';
import 'package:seven_double_client/src/resource_packs.dart';

const _script = 'scripts/sample.json';

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

Map<String, dynamic> _sample({bool green = false}) => {
      'v': '5.13.0',
      'fr': 30,
      'ip': 0,
      'op': 30,
      'w': 64,
      'h': 64,
      'assets': [
        {'id': 'blue', 'w': 8, 'h': 8, 'u': 'images/', 'p': 'blue.png', 'e': 0},
      ],
      'layers': [
        {
          'ty': 2,
          'ind': 1,
          'refId': 'blue',
          'ip': 0,
          'op': 30,
          'st': 0,
          'ks': _transform([8, 8, 0]),
        },
        {
          'ty': 4,
          'ind': 2,
          'ip': 0,
          'op': 30,
          'st': 0,
          'ks': _transform([16, 32, 0])
            ..['p'] = {
              'a': 1,
              'k': [
                {
                  't': 0,
                  's': [16, 32, 0],
                  'e': [48, 32, 0],
                  'o': {'x': 0.33, 'y': 0.33},
                  'i': {'x': 0.67, 'y': 0.67}
                },
                {
                  't': 30,
                  's': [48, 32, 0]
                },
              ],
            },
          'shapes': [
            {
              'ty': 'rc',
              'p': {
                'a': 0,
                'k': [0, 0]
              },
              's': {
                'a': 0,
                'k': [16, 16]
              },
              'r': {'a': 0, 'k': 0}
            },
            {
              'ty': 'fl',
              'c': {
                'a': 0,
                'k': green ? [0, 1, 0, 1] : [1, 0, 0, 1]
              },
              'o': {'a': 0, 'k': 100},
              'r': 1
            },
          ],
        },
      ],
    };

Future<Uint8List> _bluePng({Color color = const Color(0xff0000ff)}) async {
  final recorder = ui.PictureRecorder();
  Canvas(recorder)
      .drawRect(const Rect.fromLTWH(0, 0, 8, 8), Paint()..color = color);
  final picture = recorder.endRecording();
  final image = await picture.toImage(8, 8);
  final data = await image.toByteData(format: ui.ImageByteFormat.png);
  image.dispose();
  picture.dispose();
  return data!.buffer.asUint8List(data.offsetInBytes, data.lengthInBytes);
}

Future<void> _install(
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
        contents.values.fold<int>(0, (size, bytes) => size + bytes.length),
    'files': files,
  }));
}

Future<void> _installSample(
        ResourcePacks cache, Map<String, dynamic> sample, Uint8List png) =>
    _install(cache, {
      _script: Uint8List.fromList(utf8.encode(jsonEncode(sample))),
      'scripts/images/blue.png': png,
    });

Future<Uint8List> _frame(LottieComposition composition, double progress) async {
  final recorder = ui.PictureRecorder();
  final drawable = LottieDrawable(composition, frameRate: FrameRate.max);
  drawable.setProgress(progress);
  drawable.draw(Canvas(recorder), const Rect.fromLTWH(0, 0, 64, 64),
      fit: BoxFit.contain);
  final picture = recorder.endRecording();
  final image = await picture.toImage(64, 64);
  final data = await image.toByteData(format: ui.ImageByteFormat.rawRgba);
  final bytes = Uint8List.fromList(
      data!.buffer.asUint8List(data.offsetInBytes, data.lengthInBytes));
  image.dispose();
  picture.dispose();
  return bytes;
}

List<int> _pixel(Uint8List bytes, int x, int y) =>
    bytes.sublist((y * 64 + x) * 4, (y * 64 + x) * 4 + 4);

void main() {
  LiveTestWidgetsFlutterBinding.ensureInitialized().framePolicy =
      LiveTestWidgetsFlutterBindingFramePolicy.onlyPumps;
  late Directory support;
  late GameApi api;
  late ResourcePacks cache;
  late Uint8List png;

  setUp(() async {
    support = await Directory.systemTemp.createTemp('animation-player-');
    api = GameApi(ServerEndpoint.parse('http://127.0.0.1:1'));
    cache = ResourcePacks(api: api, supportDirectory: support);
    png = await _bluePng();
  });
  tearDown(() async {
    api.close();
    await support.delete(recursive: true);
  });

  test('标准 Lottie 形状逐帧移动，图片从同包 MD5 缓存绘制', () async {
    await _installSample(cache, _sample(), png);
    final composition = await loadAnimationComposition(cache, _script);
    final start = await _frame(composition, 0.1);
    final end = await _frame(composition, 0.9);
    expect(_pixel(start, 12, 12), [0, 0, 255, 255]);
    expect(_pixel(start, 20, 32), [255, 0, 0, 255]);
    expect(_pixel(start, 44, 32).last, 0);
    expect(_pixel(end, 20, 32).last, 0);
    expect(_pixel(end, 44, 32), [255, 0, 0, 255]);
  });

  test('同路径内容和图片更新后不复用旧 composition', () async {
    await _installSample(cache, _sample(), png);
    final before = await loadAnimationComposition(cache, _script);
    await _installSample(cache, _sample(green: true), png);
    final after = await loadAnimationComposition(cache, _script);
    expect(identical(before, after), isFalse);
    expect(_pixel(await _frame(before, 0.1), 20, 32), [255, 0, 0, 255]);
    expect(_pixel(await _frame(after, 0.1), 20, 32), [0, 255, 0, 255]);
    final yellow = await _bluePng(color: const Color(0xffffff00));
    await _installSample(cache, _sample(green: true), yellow);
    final imageUpdated = await loadAnimationComposition(cache, _script);
    expect(_pixel(await _frame(after, 0.1), 12, 12), [0, 0, 255, 255]);
    expect(_pixel(await _frame(imageUpdated, 0.1), 12, 12), [255, 255, 0, 255]);
  });

  test('缺失缓存、坏 MD5、外部图片、表达式及无效时间拒绝播放', () async {
    await expectLater(
        loadAnimationComposition(cache, _script), throwsFormatException);
    await _installSample(cache, _sample(), png);
    final target = await cache.filePath('animation', _script);
    await File(target!).writeAsString('tampered');
    await expectLater(
        loadAnimationComposition(cache, _script), throwsFormatException);
    await _installSample(cache, _sample(), png);
    final image = await cache.filePath('animation', 'scripts/images/blue.png');
    await File(image!).writeAsString('tampered');
    await expectLater(
        loadAnimationComposition(cache, _script), throwsFormatException);
    for (final mutate in <void Function(Map<String, dynamic>)>[
      (value) => value['assets'][0]['u'] = 'https://example.com/',
      (value) => value['assets'][0]['p'] = '../blue.png',
      (value) => value['assets'][0]['p'] = 'data:image/png;base64,AAAA',
      (value) => value['assets'][0]['e'] = 1,
      (value) => value['assets'][0]['e'] = null,
      (value) => value['layers'][1]['ks']['p']['x'] = 'time * 10',
      (value) => value['fonts'] = {
            'list': [
              {'fPath': 'https://example.com/font.ttf'}
            ]
          },
      (value) => value['fr'] = 0,
      (value) => value['w'] = 8193,
      (value) => value['op'] = 1801,
      (value) => value['layers'][0]['ty'] = 6,
    ]) {
      final sample = jsonDecode(jsonEncode(_sample())) as Map<String, dynamic>;
      mutate(sample);
      await _installSample(cache, sample, png);
      await expectLater(
          loadAnimationComposition(cache, _script), throwsFormatException);
    }
    final overflowing =
        jsonEncode(_sample()).replaceFirst('"fr":30', '"fr":1e400');
    await _install(cache, {
      _script: Uint8List.fromList(utf8.encode(overflowing)),
      'scripts/images/blue.png': png,
    });
    await expectLater(
        loadAnimationComposition(cache, _script), throwsFormatException);
    await _installSample(cache, _sample(), Uint8List.fromList([1, 2, 3]));
    await expectLater(
        loadAnimationComposition(cache, _script), throwsFormatException);
  });

  testWidgets('资源入口选择真实脚本，能暂停重播并关闭预览', (tester) async {
    await tester.runAsync(() => _installSample(cache, _sample(), png));
    final manifest =
        await tester.runAsync(() => cache.localManifest('animation'));
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: ResourcePackDialog(
      resources: cache,
      initialChecks: [
        ResourcePackCheck(pack: 'animation', local: manifest, remote: manifest),
        const ResourcePackCheck(pack: 'memes', unpublished: true),
      ],
    ))));
    await tester.runAsync(() async {
      await tester.tap(find.byTooltip('预览动画'));
      for (var attempt = 0;
          attempt < 100 && find.text(_script).evaluate().isEmpty;
          attempt++) {
        await tester.pump();
        await Future<void>.delayed(const Duration(milliseconds: 10));
      }
    });
    await tester.pump();
    expect(find.text(_script), findsOneWidget);
    await tester.runAsync(() async {
      await tester.tap(find.text(_script));
      for (var attempt = 0;
          attempt < 100 && find.byType(Lottie).evaluate().isEmpty;
          attempt++) {
        await tester.pump();
        await Future<void>.delayed(const Duration(milliseconds: 10));
      }
    });
    await tester.pump();
    expect(find.byType(Lottie), findsOneWidget);
    await tester.tap(find.byTooltip('暂停'));
    await tester.pump();
    expect(find.byTooltip('播放'), findsOneWidget);
    await tester.tap(find.byTooltip('重播'));
    await tester.pump();
    expect(find.byTooltip('暂停'), findsOneWidget);
    await tester.tap(find.byTooltip('关闭动画'));
    await tester.pumpAndSettle();
    expect(find.byType(AnimationPlayer), findsNothing);
    expect(find.byType(ResourcePackDialog), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('无缓存明确显示未下载，不构造假动画', (tester) async {
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: AnimationPlayer(resources: cache, scriptPath: _script))));
    await tester.runAsync(() async {
      for (var attempt = 0;
          attempt < 100 && find.textContaining('未下载').evaluate().isEmpty;
          attempt++) {
        await tester.pump();
        await Future<void>.delayed(const Duration(milliseconds: 10));
      }
    });
    await tester.pump();
    expect(find.textContaining('未下载'), findsOneWidget);
    expect(find.byType(Lottie), findsNothing);
    await tester.pumpWidget(const SizedBox.shrink());
  });
}
