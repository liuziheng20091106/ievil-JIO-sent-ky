// 「按 Enter 发送」回归检查：平台默认值（安卓关闭 / 桌面开启）、偏好持久化、
// 聊天设置里的开关，以及输入框据此切换的回车行为。
//
// 运行方式（client 目录）：flutter test test/enter_to_send_test.dart
import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/shell.dart';
import 'package:seven_double_client/src/store.dart';

import 'golden_harness.dart';

/// 最小对局状态：公屏可发言，够 [ChatActionPage] 渲染输入区即可。
Map<String, dynamic> viewJson() => {
      'ui_version': 1,
      'id': 'game-1',
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
        },
      ],
    };

Actor actorJson() => Actor.fromJson({
      'id': 'p1',
      'account_id': 'a1',
      'kind': 'player',
      'seat_id': '1',
      'name': '一号',
    });

/// 按给定偏好构造 store：没传 values 时用空的 mock 偏好，验证平台默认值。
Future<GameStore> previewStore([Map<String, Object> values = const {}]) async {
  SharedPreferences.setMockInitialValues(values);
  final preferences = await SharedPreferences.getInstance();
  final store = GameStore.forPreview(
    preferences: preferences,
    endpoint: ServerEndpoint.parse('http://127.0.0.1:8000'),
    actor: actorJson(),
    view: GameView.fromJson(viewJson()),
    gameId: 'game-1',
  );
  // 预览用不上服务端：留着会让发消息真的走一次网络（测试里必然失败）。
  store.api = null;
  return store;
}

/// 渲染真实外壳：设置的改动靠 GameShell 收到 store 通知后重建对局页生效，
/// 直接 pump 单个页面看不到配置跟着变。
Future<void> pumpComposer(WidgetTester tester, GameStore store) =>
    pumpPhone(tester, GameShell(store: store));

/// 测试环境的 [defaultTargetPlatform] 恒为 android（Flutter 的规定），
/// 要按某个平台跑就显式覆写，结束后恢复。
void usePlatform(TargetPlatform platform) {
  debugDefaultTargetPlatformOverride = platform;
  addTearDown(() => debugDefaultTargetPlatformOverride = null);
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  TextField composer(WidgetTester tester) =>
      tester.widget<TextField>(find.byType(TextField));

  /// 输入框当前是否聚焦。
  bool composerFocused(WidgetTester tester) => tester
      .widget<EditableText>(find.descendant(
        of: find.byType(TextField),
        matching: find.byType(EditableText),
      ))
      .focusNode
      .hasFocus;

  group('按 Enter 发送', () {
    test('平台默认值：安卓关闭、桌面开启', () {
      expect(GameStore.defaultEnterToSendFor(TargetPlatform.android), isFalse);
      expect(GameStore.defaultEnterToSendFor(TargetPlatform.windows), isTrue);
      expect(GameStore.defaultEnterToSendFor(TargetPlatform.linux), isTrue);
    });

    test('Windows 默认开启，切换立即持久化', () async {
      usePlatform(TargetPlatform.windows);
      final store = await previewStore();
      expect(store.enterToSendEnabled, isTrue);
      store.setEnterToSendEnabled(false);
      expect(store.preferences.getBool('chat_enter_to_send'), isFalse);
      store.setEnterToSendEnabled(true);
      expect(store.preferences.getBool('chat_enter_to_send'), isTrue);
    });

    test('安卓上默认关闭', () async {
      usePlatform(TargetPlatform.android);
      expect((await previewStore()).enterToSendEnabled, isFalse);
    });

    test('已存的偏好优先于平台默认', () async {
      expect(
        (await previewStore({'chat_enter_to_send': true})).enterToSendEnabled,
        isTrue,
      );
      expect(
        (await previewStore({'chat_enter_to_send': false})).enterToSendEnabled,
        isFalse,
      );
    });
  });

  group('输入框的回车行为', () {
    testWidgets('聊天设置里的开关切换输入框的发送方式', (tester) async {
      // 平台默认值由上面的纯测试覆盖；widget 测试里不能留 platforms 覆写
      // （测试结束时的 foundation 不变量检查会报「debug 变量被改过」），
      // 这里直接置位。
      final store = await previewStore();
      store.setEnterToSendEnabled(true);
      await pumpComposer(tester, store);

      // 桌面默认开启：回车发送，输入类型跟着切成单行（安卓据此才会报 send 动作）。
      expect(composer(tester).textInputAction, TextInputAction.send);
      expect(composer(tester).keyboardType, TextInputType.text);

      await tester.tap(find.byIcon(Icons.tune));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 400));
      expect(find.text('按 Enter 发送'), findsOneWidget);

      await tester.tap(find.widgetWithText(SwitchListTile, '按 Enter 发送'));
      await tester.pump();

      expect(store.enterToSendEnabled, isFalse);
      expect(store.preferences.getBool('chat_enter_to_send'), isFalse);
      // 关闭后回到多行 + 换行：回车只换行，发送仍走右侧按钮。
      expect(composer(tester).textInputAction, TextInputAction.newline);
      expect(composer(tester).keyboardType, TextInputType.multiline);
    });

    testWidgets('开启时收到 send 动作即发出并保留焦点', (tester) async {
      final store = await previewStore();
      store.setEnterToSendEnabled(true);
      await pumpComposer(tester, store);

      await tester.enterText(find.byType(TextField), '按回车发送');
      // 测试里用 receiveAction 走框架的 performAction：真机上引擎把回车翻成的就是这个动作。
      await tester.testTextInput.receiveAction(TextInputAction.send);
      await tester.pump();

      expect(find.text('按回车发送'), findsNothing, reason: '发出后输入框要清空');
      final editable = tester.widget<EditableText>(find.descendant(
        of: find.byType(TextField),
        matching: find.byType(EditableText),
      ));
      expect(editable.focusNode.hasFocus, isTrue, reason: '发送后继续打下一条，不收键盘');
    });

    testWidgets('关闭时换行动作不把内容发出去', (tester) async {
      final store = await previewStore();
      store.setEnterToSendEnabled(false);
      await pumpComposer(tester, store);

      await tester.enterText(find.byType(TextField), '只换行不发送');
      // 「换行」由引擎在真机上插入，框架侧只负责不发送：这里锁住后者。
      await tester.testTextInput.receiveAction(TextInputAction.newline);
      await tester.pump();

      expect(find.text('只换行不发送'), findsOneWidget, reason: '换行不该把内容发出去');
    });
  });

  group('发送后的焦点', () {
    // 桌面端（Windows）点在输入框以外的地方会让输入框失焦，这是 EditableText
    // 默认 onTapOutside 的规矩；发送按钮就在输入框外，所以点一下发送焦点就没了。
    testWidgets('Windows 上点发送按钮，发完输入框仍保持聚焦', (tester) async {
      debugDefaultTargetPlatformOverride = TargetPlatform.windows;
      try {
        final store = await previewStore();
        expect(store.enterToSendEnabled, isTrue);
        await pumpComposer(tester, store);

        await tester.enterText(find.byType(TextField), '点按钮发送');
        await tester.pump();
        expect(composerFocused(tester), isTrue, reason: '打字时输入框是聚焦的');

        await tester.tap(find.byIcon(Icons.arrow_upward_rounded));
        await tester.pump();

        expect(find.text('点按钮发送'), findsNothing, reason: '消息发出去了');
        expect(composerFocused(tester), isTrue,
            reason: '发完接着打下一条，不用再点一次输入框');
      } finally {
        // 只能在测试体里恢复：foundation 不变量检查跑在 tearDown 之前。
        debugDefaultTargetPlatformOverride = null;
      }
    });

    // 真机上发送时 store.writeBusy 为真（写请求在飞），界面会因此重建。
    // TextField 一旦被禁掉，会把 FocusNode 的 canRequestFocus 一起关掉，正在
    // 聚焦的输入框当场失焦——按钮和回车两条路径都会中招。
    testWidgets('发送期间输入框保持可用且不丢焦点', (tester) async {
      final store = await previewStore();
      await pumpComposer(tester, store);

      await tester.enterText(find.byType(TextField), '发送中的草稿');
      await tester.pump();
      expect(composerFocused(tester), isTrue);

      store.writeBusy = true;
      store.selectChannel('public'); // 触发一次与发送同源的重建。
      await tester.pump();

      expect(composer(tester).enabled, isTrue, reason: '发送期间还能继续打下一条');
      expect(composerFocused(tester), isTrue, reason: '写请求在飞不该把焦点带走');
      // 发送期间按回车不该把还没发出去的草稿清掉。
      await tester.testTextInput.receiveAction(TextInputAction.send);
      await tester.pump();
      expect(find.text('发送中的草稿'), findsOneWidget, reason: '草稿要留着');

      store.writeBusy = false;
    });
  });
}
