// 「一键回底」与上下键滚消息的回归检查：离开最新消息（视口下方压着 10 条以上）时
// 按钮才出现，点一下回到最新一条；上下键每次滚约三分之一屏，输入框里有字时让给文本光标。
//
// 运行方式（client 目录）：flutter test test/chat_scroll_test.dart
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/shell.dart';
import 'package:seven_double_client/src/store.dart';

import 'golden_harness.dart';

/// 最小对局状态：公屏可发言，够 [ChatActionPage] 渲染消息列表与输入区即可。
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

/// 一长串公屏历史：一屏放不下，列表真的可以滚动。
List<GameMessage> history(int count) => [
      for (var index = 0; index < count; index++)
        GameMessage.fromJson({
          'id': index + 1,
          'kind': 'chat',
          'sender_id': 'p2',
          'sender_name': 'kiwi',
          'avatar_role_id': 'hiro',
          'channel_id': 'public',
          'text': '第 ${index + 1} 条公屏讨论内容',
          'created_at': '2026-09-15T12:00:00Z',
        }),
    ];

/// 直接注入历史的 store：不走网络，进局时消息已经在列表里（列表停在最上面）。
Future<GameStore> previewStore({int count = 30, bool hasMore = false}) async {
  SharedPreferences.setMockInitialValues({});
  final preferences = await SharedPreferences.getInstance();
  final store = GameStore.forPreview(
    preferences: preferences,
    endpoint: ServerEndpoint.parse('http://127.0.0.1:8000'),
    actor: actorJson(),
    view: GameView.fromJson(viewJson()),
    gameId: 'game-1',
    messages: history(count),
  );
  // 预览用不上服务端：留着会让界面真的去连一次网络。
  store.api = null;
  store.hasMoreMessages = hasMore;
  return store;
}

/// 渲染真实外壳并跑完「一键回底」的帧末量算（量算在帧末，setState 要再一帧才画出来）。
Future<void> pumpChat(WidgetTester tester, GameStore store) async {
  await pumpPhone(tester, GameShell(store: store));
  await tester.pumpAndSettle();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  /// 消息列表的滚动位置：取气泡所在的那个 Scrollable。
  ScrollPosition messages(WidgetTester tester) => tester
      .state<ScrollableState>(find.ancestor(
        of: find.byType(MessageBubble).first,
        matching: find.byType(Scrollable),
      ))
      .position;

  Finder jumpButton() => find.byIcon(Icons.keyboard_double_arrow_down_rounded);

  testWidgets('离开最新消息时出现一键回底，点一下回到最新一条', (tester) async {
    final store = await previewStore();
    await pumpChat(tester, store);

    // 一进局列表停在最上面：最新的十条一条都看不见，正是按钮该出现的状态。
    expect(jumpButton(), findsOneWidget);
    expect(messages(tester).pixels,
        lessThan(messages(tester).maxScrollExtent));

    await tester.tap(jumpButton());
    await tester.pumpAndSettle();

    expect(messages(tester).pixels,
        closeTo(messages(tester).maxScrollExtent, 1),
        reason: '一键回底要真的停在最新一条');
    expect(jumpButton(), findsNothing, reason: '停在最新消息后按钮收起');
  });

  testWidgets('消息本来就不够一屏（下方不足 10 条）时不出现', (tester) async {
    final store = await previewStore(count: 5);
    await pumpChat(tester, store);

    expect(store.messages.length, 5);
    expect(jumpButton(), findsNothing);
  });

  testWidgets('「加载更早消息」那一项不参与下方条数计算', (tester) async {
    final store = await previewStore(hasMore: true);
    await pumpChat(tester, store);

    expect(find.text('加载更早消息'), findsOneWidget);
    expect(jumpButton(), findsOneWidget);

    await tester.tap(jumpButton());
    await tester.pumpAndSettle();
    expect(jumpButton(), findsNothing);
  });

  testWidgets('上下键滚动消息列表，输入框里有字时让位给文本光标', (tester) async {
    final store = await previewStore();
    await pumpChat(tester, store);
    await tester.tap(jumpButton());
    await tester.pumpAndSettle();
    final bottom = messages(tester).pixels;

    // 进页焦点就在聊天页上，上下键直接生效。
    await tester.sendKeyEvent(LogicalKeyboardKey.arrowUp);
    await tester.pumpAndSettle();
    final afterUp = messages(tester).pixels;
    expect(afterUp, lessThan(bottom), reason: '上键往上翻');
    expect(bottom - afterUp, greaterThan(60),
        reason: '至少滚出肉眼可见的一段，不能只动一两像素');

    await tester.sendKeyEvent(LogicalKeyboardKey.arrowDown);
    await tester.pumpAndSettle();
    expect(messages(tester).pixels, greaterThan(afterUp), reason: '下键往下翻');

    // 输入框空着：焦点在输入框上，上下键还是滚消息。
    await tester.tap(find.byType(TextField));
    await tester.pump();
    final emptyField = messages(tester).pixels;
    await tester.sendKeyEvent(LogicalKeyboardKey.arrowUp);
    await tester.pumpAndSettle();
    expect(messages(tester).pixels, lessThan(emptyField));

    // 输入框里写了字：上下键归文本光标，消息列表不许再动。
    await tester.enterText(find.byType(TextField), '我这边没有可以证明的信息');
    await tester.pump();
    final withText = messages(tester).pixels;
    await tester.sendKeyEvent(LogicalKeyboardKey.arrowUp);
    await tester.pumpAndSettle();
    expect(messages(tester).pixels, withText,
        reason: '输入框里有字时上下键留给文本光标');
  });
}
