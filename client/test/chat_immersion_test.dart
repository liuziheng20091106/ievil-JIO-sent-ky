import 'package:flutter/foundation.dart';
import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:seven_double_client/src/chat_immersion.dart';
import 'package:seven_double_client/src/design.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/shell.dart';
import 'package:seven_double_client/src/store.dart';

Future<GameStore> previewStore() async {
  final store = GameStore.forPreview(
    preferences: await SharedPreferences.getInstance(),
    endpoint: ServerEndpoint.parse('http://127.0.0.1:8000'),
    actor: Actor.fromJson({'id': 'p1', 'kind': 'player', 'name': '玩家'}),
    gameId: 'immersion-game',
    messages: [
      for (var id = 1; id <= 40; id++)
        GameMessage.fromJson({
          'id': id,
          'game_id': 'immersion-game',
          'kind': 'chat',
          'channel_id': 'public',
          'sender_id': 'p1',
          'text': '聊天消息 $id',
          'audience': [],
        }),
    ],
    view: GameView.fromJson({
      'ui_version': 1,
      'id': 'immersion-game',
      'version': 1,
      'status': 'playing',
      'day': 1,
      'half': 'night',
      'phase': 'night',
      'phase_label': '夜间行动',
      'seats': [],
      'self': {},
      'public': {},
      'can_chat': true,
      'actions': [],
      'channels': [
        {
          'id': 'public',
          'label': '公屏',
          'status': 'active',
          'can_send': true,
          'members': [],
          'actions': [],
        },
      ],
    }),
  );
  store.api!.close();
  store.api = null;
  return store;
}

Future<void> hideAfterIdle(WidgetTester tester) async {
  await tester.pump(const Duration(seconds: 15));
  await tester.pump(const Duration(milliseconds: 500));
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('平台默认值与本机持久偏好，关闭音频立即通知', () async {
    addTearDown(() => debugDefaultTargetPlatformOverride = null);
    SharedPreferences.setMockInitialValues({});
    for (final platform in TargetPlatform.values) {
      debugDefaultTargetPlatformOverride = platform;
      final store = await previewStore();
      expect(store.immersionEnabled,
          platform == TargetPlatform.android || platform == TargetPlatform.iOS);
      expect(store.allowAudioEnabled, isTrue);
      store.dispose();
    }
    debugDefaultTargetPlatformOverride = TargetPlatform.windows;
    final store = await previewStore();
    addTearDown(store.dispose);
    var notifications = 0;
    store.addListener(() => notifications++);
    store.setImmersionEnabled(true);
    store.setAllowAudioEnabled(false);
    expect(notifications, 2);
    expect(store.allowAudioEnabled, isFalse);
    final restored = await previewStore();
    addTearDown(restored.dispose);
    expect(restored.immersionEnabled, isTrue);
    expect(restored.allowAudioEnabled, isFalse);
  });

  testWidgets('15 秒边界、0.5 秒释放布局，hover 与键盘恢复且保留草稿焦点', (tester) async {
    final controller = TextEditingController(text: '未发送草稿');
    final focus = FocusNode();
    addTearDown(controller.dispose);
    addTearDown(focus.dispose);
    var visibility = 1.0;
    Widget session({bool enabled = true, bool active = true}) => MaterialApp(
          home: ChatImmersionSession(
            enabled: enabled,
            active: active,
            builder: (context, value, activity) {
              visibility = value;
              return Scaffold(
                body: Column(children: [
                  ImmersionChrome(
                    key: const ValueKey('chrome'),
                    visibility: value,
                    child: SizedBox(
                      height: 100,
                      child: TextField(
                        controller: controller,
                        focusNode: focus,
                        onChanged: (_) => activity(),
                      ),
                    ),
                  ),
                  const Expanded(child: SizedBox(key: ValueKey('messages'))),
                ]),
              );
            },
          ),
        );
    await tester.pumpWidget(session());
    focus.requestFocus();
    await tester.pump();
    final fieldState = tester.state(find.byType(TextField));
    final initialHeight =
        tester.getSize(find.byKey(const ValueKey('messages'))).height;
    await tester.pump(const Duration(milliseconds: 14999));
    expect(visibility, 1);
    await tester.pump(const Duration(milliseconds: 1));
    expect(visibility, 1);
    await tester.pump(const Duration(milliseconds: 250));
    expect(visibility, greaterThan(0));
    expect(visibility, lessThan(1));
    await tester.pump(const Duration(milliseconds: 250));
    expect(visibility, 0);
    expect(tester.getSize(find.byKey(const ValueKey('messages'))).height,
        initialHeight + 100);
    expect(tester.state(find.byType(TextField)), same(fieldState));
    expect(controller.text, '未发送草稿');
    expect(focus.hasFocus, isTrue);
    final mouse = await tester.createGesture(kind: PointerDeviceKind.mouse);
    await mouse.addPointer(location: const Offset(200, 200));
    await mouse.moveTo(const Offset(201, 200));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    expect(visibility, 1);
    await hideAfterIdle(tester);
    expect(visibility, 0);
    await tester.sendKeyEvent(LogicalKeyboardKey.arrowLeft);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    expect(visibility, 1);
    await hideAfterIdle(tester);
    tester.testTextInput.enterText('输入法继续编辑');
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    expect(visibility, 1);
    expect(controller.text, '输入法继续编辑');
    await hideAfterIdle(tester);
    await tester.sendEventToBinding(const PointerScrollEvent(
      position: Offset(200, 200),
      scrollDelta: Offset(0, 20),
    ));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    expect(visibility, 1);
    await hideAfterIdle(tester);
    await tester.tapAt(const Offset(200, 200));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    expect(visibility, 1);
    await hideAfterIdle(tester);
    await tester.pumpWidget(session(enabled: false));
    await tester.pump(const Duration(milliseconds: 500));
    expect(visibility, 1);
    await tester.pump(const Duration(seconds: 20));
    expect(visibility, 1);
    await mouse.removePointer();
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('前后台、聊天不可见与非用户重建不延长闲置时间', (tester) async {
    var visibility = 1.0;
    Widget session({bool active = true}) => MaterialApp(
          home: ChatImmersionSession(
            enabled: true,
            active: active,
            builder: (context, value, _) {
              visibility = value;
              return const SizedBox.expand();
            },
          ),
        );
    await tester.pumpWidget(session());
    await tester.pump(const Duration(seconds: 10));
    await tester.pumpWidget(session());
    await tester.pump(const Duration(seconds: 5));
    await tester.pump(const Duration(milliseconds: 500));
    expect(visibility, 0);
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.paused);
    await tester.pump(const Duration(seconds: 20));
    tester.binding.handleAppLifecycleStateChanged(AppLifecycleState.resumed);
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 500));
    expect(visibility, 1);
    await tester.pump(const Duration(seconds: 14));
    expect(visibility, 1);
    await tester.pumpWidget(session(active: false));
    await tester.pump(const Duration(seconds: 20));
    expect(visibility, 1);
    await tester.pumpWidget(session());
    await hideAfterIdle(tester);
    expect(visibility, 0);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  for (final platform in [TargetPlatform.android, TargetPlatform.windows]) {
    testWidgets('窄屏 $platform 只收起指定控件，聊天元素保持', (tester) async {
      debugDefaultTargetPlatformOverride = platform;
      addTearDown(() => debugDefaultTargetPlatformOverride = null);
      SharedPreferences.setMockInitialValues({'chat_immersion': true});
      final store = await previewStore();
      addTearDown(store.dispose);
      await tester.binding.setSurfaceSize(const Size(420, 1000));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      await tester.pumpWidget(
          MaterialApp(theme: buildAppTheme(), home: GameShell(store: store)));
      await tester.pumpAndSettle();
      final chat = tester.state(find.byType(ChatActionPage));
      final field = tester.widget<TextField>(find.byType(TextField));
      final messageList = find.descendant(
        of: find.byType(ChatActionPage),
        matching: find.byWidgetPredicate(
            (widget) => widget is ListView && widget.controller != null),
      );
      final scrolling =
          find.descendant(of: messageList, matching: find.byType(Scrollable));
      final scrollState = tester.state<ScrollableState>(scrolling);
      field.controller!.text = '保留草稿';
      final appBarHeight = tester.getSize(find.byType(ImmersionAppBar)).height;
      scrollState.position.jumpTo(40);
      await tester.pump();
      expect(scrollState.position.pixels, 40);
      await hideAfterIdle(tester);
      await tester.pump();
      expect(scrollState.position.pixels, 0);
      expect(tester.state(find.byType(ChatActionPage)), same(chat));
      expect(tester.state<ScrollableState>(scrolling), same(scrollState));
      expect(tester.widget<TextField>(find.byType(TextField)).controller,
          same(field.controller));
      expect(field.controller!.text, '保留草稿');
      final scaffold = tester.widget<Scaffold>(find.byType(Scaffold));
      if (platform == TargetPlatform.android) {
        expect(scaffold.appBar!.preferredSize.height, 0);
        expect(
            tester.getSize(find.byWidget(scaffold.bottomNavigationBar!)).height,
            0);
      } else {
        expect(
            tester.getSize(find.byType(ImmersionAppBar)).height, appBarHeight);
        expect(
            tester.getSize(find.byWidget(scaffold.bottomNavigationBar!)).height,
            greaterThan(0));
      }
      await tester.sendKeyEvent(LogicalKeyboardKey.arrowLeft);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 500));
      await tester.pump();
      expect(scrollState.position.pixels, closeTo(40, .01));
      await tester.pumpWidget(const SizedBox.shrink());
      debugDefaultTargetPlatformOverride = null;
    });
  }

  testWidgets('420×640 大字设置可滚动到底并立即关闭本机音频', (tester) async {
    SharedPreferences.setMockInitialValues({'chat_immersion': false});
    final store = await previewStore();
    addTearDown(store.dispose);
    await tester.binding.setSurfaceSize(const Size(420, 640));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(MaterialApp(
      theme: buildAppTheme(),
      builder: (context, child) => MediaQuery(
        data: MediaQuery.of(context).copyWith(
          textScaler: const TextScaler.linear(1.4),
        ),
        child: child!,
      ),
      home: GameShell(store: store),
    ));
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('聊天设置'));
    await tester.pumpAndSettle();
    expect(tester.takeException(), isNull);
    final audio = find.widgetWithText(SwitchListTile, '允许音频');
    final settingsScroll =
        find.ancestor(of: audio, matching: find.byType(SingleChildScrollView));
    final scrolling =
        find.descendant(of: settingsScroll, matching: find.byType(Scrollable));
    expect(tester.state<ScrollableState>(scrolling).position.maxScrollExtent,
        greaterThan(0));
    await tester.scrollUntilVisible(audio, 120, scrollable: scrolling);
    await tester.tap(audio);
    await tester.pumpAndSettle();
    expect(store.allowAudioEnabled, isFalse);
    expect(tester.widget<SwitchListTile>(audio).value, isFalse);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('宽屏沉浸保持状态、我的和全局标题栏空间', (tester) async {
    SharedPreferences.setMockInitialValues({'chat_immersion': true});
    final store = await previewStore();
    addTearDown(store.dispose);
    await tester.binding.setSurfaceSize(const Size(1600, 1000));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(
        MaterialApp(theme: buildAppTheme(), home: GameShell(store: store)));
    await tester.pumpAndSettle();
    final board = tester.getRect(find.byType(BoardPage));
    final profile = tester.getRect(find.byType(ProfilePage));
    final appBar = tester.getRect(find.byType(ImmersionAppBar));
    final chatHeight = tester.getSize(find.byType(ChatActionPage)).height;
    await hideAfterIdle(tester);
    expect(tester.getRect(find.byType(BoardPage)), board);
    expect(tester.getRect(find.byType(ProfilePage)), profile);
    expect(tester.getRect(find.byType(ImmersionAppBar)), appBar);
    expect(tester.getSize(find.byType(ChatActionPage)).height, chatHeight + 46);
    await tester.pumpWidget(const SizedBox.shrink());
  });
}
