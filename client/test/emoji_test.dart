import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:seven_double_client/src/emoji.dart';
import 'package:seven_double_client/src/emoji_picker.dart';

/// 系统返回：引擎在非预测性返回时就是往 flutter/navigation 发 popRoute。
Future<void> pressSystemBack(WidgetTester tester) async {
  await tester.binding.defaultBinaryMessenger.handlePlatformMessage(
    'flutter/navigation',
    const JSONMethodCodec().encodeMethodCall(const MethodCall('popRoute')),
    (ByteData? _) {},
  );
  await tester.pumpAndSettle();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(recentEmojiIds.clear);

  test('表情目录：经典 275 + 超级 50，id 与名字都不重复', () {
    expect(emojiFaces.where((face) => !face.superFace).length, 275);
    expect(emojiFaces.where((face) => face.superFace).length, 50);
    expect(emojiFaces.map((face) => face.id).toSet().length, emojiFaces.length);
    expect(emojiFaces.map((face) => face.name).toSet().length, emojiFaces.length);
  });

  test('每张静态表情都随包提供且可解码', () async {
    final errors = <String>[];
    final previous = FlutterError.onError;
    FlutterError.onError = (details) => errors.add(details.exceptionAsString());
    addTearDown(() => FlutterError.onError = previous);

    for (final face in emojiFaces) {
      final bytes = await rootBundle.load(face.asset);
      // 最小的纯色图标也有 544 字节；低于 400 基本是空文件或占位图。
      expect(bytes.lengthInBytes, greaterThan(400), reason: '${face.id} 图片过小');
      final codec = await ui.instantiateImageCodec(bytes.buffer.asUint8List());
      final frame = await codec.getNextFrame();
      // 原图只有 128×128 与 56×56 两种，都必须方正规整，
      // 出现别的尺寸说明取错了文件（比如混进了动画首帧或占位图）。
      expect(frame.image.width, frame.image.height, reason: '${face.id} 不是正方形');
      expect(frame.image.width, greaterThanOrEqualTo(56), reason: '${face.id} 尺寸过小');
    }
    expect(errors, isEmpty, reason: '解码过程中出现错误：${errors.join(' / ')}');
  });

  test('token 切分：只把总表里的名字画成表情，其它方括号保持原样', () {
    final spans = emojiSpans('你好[/微笑]再见');
    expect(spans.length, 3);
    expect((spans[0] as TextSpan).text, '你好');
    expect(spans[1], isA<WidgetSpan>());
    expect((spans[2] as TextSpan).text, '再见');

    // 名字不在总表里就不认，正文里恰好写成方括号的内容不会被误伤。
    final plain = emojiSpans('[*不是表情*]');
    expect(plain.length, 1);
    expect((plain.single as TextSpan).text, '[*不是表情*]');
    expect(hasEmojiToken('[*不是表情*]'), isFalse);
    expect(hasEmojiToken('[/微笑]'), isTrue);
  });

  test('控制器在光标处插入 token，并替换选中的内容', () {
    final face = emojiFaceByName('微笑')!;
    final controller = EmojiEditingController(text: 'ab');
    controller.selection = const TextSelection.collapsed(offset: 1);
    controller.insertFace(face);
    expect(controller.text, 'a${face.token}b');
    expect(controller.selection.baseOffset, 1 + face.token.length);

    controller.selection = const TextSelection(baseOffset: 0, extentOffset: 1);
    controller.insertFace(face);
    expect(controller.text, '${face.token}${face.token}b');
  });

  testWidgets('消息正文把 token 画成表情图', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Text.rich(TextSpan(children: emojiSpans('收到[/微笑]'))),
        ),
      ),
    );
    await tester.pump();
    final image = tester.widget<Image>(find.byType(Image));
    expect(
      (image.image as AssetImage).assetName,
      emojiFaceByName('微笑')!.asset,
    );
  });

  testWidgets('面板按名字搜索后点选回调，并记入最近使用', (tester) async {
    EmojiFace? picked;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: EmojiPicker(onPick: (face) => picked = face, height: 300),
        ),
      ),
    );
    await tester.enterText(find.byType(TextField), '微笑');
    await tester.pump();
    final cells = find.descendant(
      of: find.byType(GridView),
      matching: find.byType(InkWell),
    );
    expect(cells, findsOneWidget);
    await tester.tap(cells);
    expect(picked?.name, '微笑');
    expect(recentEmojiIds, ['14']);

    // 分组切换会退出搜索，否则点了分组没有反应。
    await tester.tap(find.widgetWithText(FilterChip, '超级'));
    await tester.pump();
    expect(tester.widget<TextField>(find.byType(TextField)).controller!.text, '');
  });

  // 返回键绑定到关闭表情面板：面板占的是输入区，玩家按返回想收的只是面板。
  // 聊天页的面板就在根路由上，没有这一层时返回会让应用直接退出。
  testWidgets('表情面板打开时返回键只收面板，不请求退出应用', (tester) async {
    var open = true;
    final platformCalls = <MethodCall>[];
    tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
      SystemChannels.platform,
      (call) async {
        platformCalls.add(call);
        return null;
      },
    );
    addTearDown(() => tester.binding.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, null));
    bool requestedExit() =>
        platformCalls.any((call) => call.method == 'SystemNavigator.pop');

    await tester.pumpWidget(
      MaterialApp(
        home: StatefulBuilder(
          builder: (context, setState) => Scaffold(
            body: open
                ? EmojiPanelScope(
                    onClose: () => setState(() => open = false),
                    child: const SizedBox(
                      height: 300,
                      child: Center(child: Text('表情面板')),
                    ),
                  )
                : const Center(child: Text('对局页')),
          ),
        ),
      ),
    );
    await tester.pump();

    await pressSystemBack(tester);
    expect(find.text('对局页'), findsOneWidget, reason: '返回只收面板，页面留着');
    expect(find.text('表情面板'), findsNothing);
    expect(requestedExit(), isFalse, reason: '面板开着时返回不能请求退出应用');

    // 面板收起后返回恢复原样：这次才轮到页面自己处理（根路由上就是退出应用）。
    await pressSystemBack(tester);
    expect(requestedExit(), isTrue, reason: '面板收起后返回不再被拦');
  });
}
