// 玩家标记（只存在客户端内存）：
// 1. 五种标记各有各的颜色，标记按参与身份 id 存放，可设置也可清除。
// 2. 对局中该玩家的名字在聊天与牌桌上都染成标记色，没标记的人保持默认色。
// 3. 长按头像弹出快速标记面板，选中即生效，不用二次确认。
// 4. 「如何标记他人」教程固定在首个非平安夜结束后弹一次，是不是平安夜完全听
//    服务端的夜终公告（「第X夜：<出局名单>」）：平安夜公告、聊天、私密信息都不弹。
//
// 标记不上传服务端，所以后端没有对应检查；这里守的是客户端的呈现与展示时机。
//
// 运行方式（client 目录）：flutter test test/player_mark_test.dart

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:seven_double_client/src/design.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/player_marks.dart';
import 'package:seven_double_client/src/shell.dart';
import 'package:seven_double_client/src/store.dart';

const playerNames = ['阿雪', 'kiwi', '小满', '庭雨', '青岚', '临', '星野'];

/// 服务端天亮时的两种夜终公告，与 backend/app/game/engine.py 的文案一致。
const peacefulNightNotice = '第1夜是平安夜。';
const deadlyNightNotice = '第1夜：2号玩家一张角色牌出局。';

List<Map<String, dynamic>> seatsJson({
  Set<String> dead = const {},
  Set<String> empty = const {},
}) =>
    [
      for (var index = 1; index <= 7; index++)
        {
          'id': '$index',
          'participant_id': empty.contains('$index') ? null : 'p$index',
          'name': playerNames[index - 1],
          'avatar_role_id': empty.contains('$index') ? null : 'emma',
          'previous_role_id': null,
          'occupied': !empty.contains('$index'),
          'ready': false,
          'alive': !dead.contains('$index'),
        },
    ];

Map<String, dynamic> viewJson({
  String status = 'playing',
  int day = 1,
  String half = 'day',
  String phase = 'speech',
  List<Map<String, dynamic>>? seats,
}) =>
    {
      'ui_version': 1,
      'id': 'game-marks',
      'version': 1,
      'status': status,
      'day': day,
      'half': half,
      'phase': phase,
      'phase_label': phase,
      'ready_count': 7,
      'seats': seats ?? seatsJson(),
      'self': <String, dynamic>{},
      'actions': <dynamic>[],
      'channels': <dynamic>[],
      'public': <String, dynamic>{},
      'information': <dynamic>[],
      'result': null,
    };

GameMessage chatMessage(String senderId, String senderName, {int id = 1}) =>
    GameMessage.fromJson({
      'id': id,
      'kind': 'chat',
      'sender_id': senderId,
      'sender_name': senderName,
      'avatar_role_id': 'emma',
      'channel_id': 'public',
      'text': '我先说说昨晚的情况。',
      'created_at': '2026-09-25T10:00:00',
    });

/// 全场公告：夜终公告就是这一种（kind=alert、发信人是主持人、没有指定收件人）。
GameMessage alertMessage(int id, String text) => GameMessage.fromJson({
      'id': id,
      'kind': 'alert',
      'sender_id': 'host',
      'sender_name': '主持人',
      'avatar_role_id': 'host',
      'channel_id': 'public',
      'text': text,
      'created_at': '2026-09-25T10:00:00',
    });

GameMessage privateInfoMessage(int id, String text) => GameMessage.fromJson({
      'id': id,
      'kind': 'information',
      'sender_id': 'host',
      'sender_name': '主持人',
      'avatar_role_id': 'host',
      'channel_id': 'information',
      'text': text,
      'created_at': '2026-09-25T10:00:00',
    });

/// 玩家视角的预览对局：不带 gameId，避免测试里真的去请求成就接口。
Future<GameStore> markStore(
    {String kind = 'player', String status = 'playing'}) async {
  SharedPreferences.setMockInitialValues({});
  final preferences = await SharedPreferences.getInstance();
  return GameStore.forPreview(
    preferences: preferences,
    endpoint: ServerEndpoint.parse('http://127.0.0.1:8000'),
    actor: Actor.fromJson({
      'id': kind == 'host' ? 'host' : 'p1',
      'account_id': kind == 'host' ? null : 'a1',
      'kind': kind,
      'seat_id': kind == 'host' ? null : '1',
      'name': kind == 'host' ? '主持人' : '阿雪',
      'access_ids': kind == 'host' ? ['host'] : ['p1'],
    }),
    view: GameView.fromJson(viewJson(status: status)),
  );
}

Future<void> pumpShell(WidgetTester tester, GameStore store) async {
  await tester.binding.setSurfaceSize(const Size(420, 880));
  tester.view.physicalSize = const Size(420, 880);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: buildAppTheme(),
      home: GameShell(store: store),
    ),
  );
  await tester.pump(const Duration(milliseconds: 600));
}

/// 面板与 SnackBar 的计时器都要跑完，测试结束时不留挂起的 Timer。
Future<void> settleSheets(WidgetTester tester) async {
  await tester.pumpAndSettle();
  await tester.pump(const Duration(seconds: 5));
  await tester.pumpAndSettle();
}

/// 先确认刚弹的 SnackBar 文案，再把它的计时器跑完。
Future<void> expectFlushSnack(WidgetTester tester, String text) async {
  await tester.pumpAndSettle();
  expect(find.textContaining(text), findsOneWidget);
  await tester.pump(const Duration(seconds: 5));
  await tester.pumpAndSettle();
}

void main() {
  test('五种标记各有各的颜色，标记可设置可清除', () async {
    final store = await markStore();
    expect(store.markFor('p2'), isNull);

    store.setMark('p2', PlayerMark.witch);
    expect(store.markFor('p2'), PlayerMark.witch);
    expect(store.playerMarks.keys, ['p2']);

    // 菜单顺序就是需求里的顺序：魔女、好人、疑似魔女、疑似好人。
    expect(
      PlayerMark.values.map((mark) => mark.label),
      ['魔女', '好人', '疑似魔女', '疑似好人'],
    );
    // 连清除标记在内正好五种互不相同的颜色。
    final colors = {
      for (final mark in PlayerMark.values) mark.colorOf(AppPalette.light),
      clearedMarkColorOf(AppPalette.light),
    };
    expect(colors.length, 5);
    expect(PlayerMark.witch.colorOf(AppPalette.light), AppPalette.light.danger);
    expect(PlayerMark.good.colorOf(AppPalette.light), AppPalette.light.success);
    expect(
      PlayerMark.suspectedWitch.colorOf(AppPalette.light),
      AppPalette.light.warning,
    );
    expect(
      PlayerMark.suspectedGood.colorOf(AppPalette.light),
      AppPalette.light.info,
    );

    store.setMark('p2', null);
    expect(store.markFor('p2'), isNull);
    expect(store.markFor(null), isNull);
    expect(store.playerMarks, isEmpty);
  });

  testWidgets('对局中的名字按标记着色（聊天与牌桌）', (tester) async {
    final store = await markStore();
    store.messages = [
      chatMessage('p2', 'kiwi'),
      chatMessage('p3', '小满', id: 2)
    ];
    store.setMark('p2', PlayerMark.witch);
    await pumpShell(tester, store);

    final chatName = tester.widget<Text>(find.descendant(
      of: find.byType(MessageBubble),
      matching: find.text('kiwi'),
    ));
    expect(chatName.style?.color, AppPalette.light.danger);
    expect(chatName.style?.fontWeight, FontWeight.w600);

    // 没有标记的玩家保持原来的默认色。
    final plain = tester.widget<Text>(find.descendant(
      of: find.byType(MessageBubble),
      matching: find.text('小满'),
    ));
    expect(plain.style?.color, AppPalette.light.textTertiary);
    expect(plain.style?.fontWeight, isNull);

    // 牌桌席位上的名字同样用标记色。
    await tester.tap(find.text('状态'));
    await tester.pump(const Duration(milliseconds: 600));
    final seatName = tester.widget<Text>(find.descendant(
      of: find.byType(SeatCard),
      matching: find.text('kiwi'),
    ));
    expect(seatName.style?.color, AppPalette.light.danger);

    await settleSheets(tester);
  });

  testWidgets('长按头像弹出快速标记面板并立即生效', (tester) async {
    final store = await markStore();
    store.messages = [chatMessage('p2', 'kiwi')];
    await pumpShell(tester, store);

    await tester.longPress(find.descendant(
      of: find.byType(MessageBubble),
      matching: find.text('kiwi'),
    ));
    await tester.pumpAndSettle();
    expect(find.text('快速标记 · 只保存在本机'), findsOneWidget);
    expect(find.text('魔女'), findsOneWidget);
    expect(find.text('清除标记'), findsOneWidget);

    await tester.tap(find.text('疑似魔女'));
    await expectFlushSnack(tester, '仅本机可见');
    expect(store.markFor('p2'), PlayerMark.suspectedWitch);

    // 有标记时再次长按，面板里能直接清除。
    await tester.longPress(find.descendant(
      of: find.byType(MessageBubble),
      matching: find.text('kiwi'),
    ));
    await tester.pumpAndSettle();
    await tester.tap(find.text('清除标记'));
    await expectFlushSnack(tester, '已清除');
    expect(store.markFor('p2'), isNull);

    // 主持人不是玩家，没有可标记的阵营判断。
    store.messages = [...store.messages, chatMessage('host', '主持人', id: 3)];
    await pumpShell(tester, store);
    await tester.longPress(find.descendant(
      of: find.byType(MessageBubble),
      matching: find.text('主持人'),
    ));
    await expectFlushSnack(tester, '只有入席玩家可以标记');
    expect(store.markFor('host'), isNull);
  });

  test('夜终公告里的非平安夜才置位教程', () async {
    final store = await markStore();
    // 平安夜公告：不弹。
    store.mergeMessagesForTest([alertMessage(1, peacefulNightNotice)]);
    expect(store.pendingMarksTutorial, isFalse);
    expect(store.marksTutorialShown, isFalse);

    // 有人出局的公告：置位一次，之后同一局不再置位。
    store.mergeMessagesForTest([alertMessage(2, deadlyNightNotice)]);
    expect(store.pendingMarksTutorial, isTrue);
    expect(store.takeMarksTutorial(), isTrue);
    expect(store.marksTutorialShown, isTrue);
    store.mergeMessagesForTest([alertMessage(3, '第2夜：5号玩家一张角色牌出局。')]);
    expect(store.pendingMarksTutorial, isFalse);
  });

  test('只死一张牌、下层接着登场的夜晚同样由公告判定为非平安夜', () async {
    final store = await markStore();
    // 席位状态上看不出任何变化（2 号还活着），但服务端的公告已经把它算作出局；
    // 教程只听公告，所以这种夜晚也要弹。
    store.mergeMessagesForTest([
      alertMessage(1, '第1夜：2号玩家一张角色牌出局。'),
    ]);
    expect(store.pendingMarksTutorial, isTrue);
  });

  test('聊天与私密信息里的相似文本不算夜终公告', () async {
    final store = await markStore();
    store.mergeMessagesForTest([chatMessage('p2', 'kiwi', id: 1)]);
    store.mergeMessagesForTest([
      privateInfoMessage(2, '第1夜：2号玩家一张角色牌出局。'),
    ]);
    // 主持人自己打的、恰好长得像公告的聊天也要排除。
    store.mergeMessagesForTest([
      GameMessage.fromJson({
        'id': 3,
        'kind': 'chat',
        'sender_id': 'p2',
        'sender_name': 'kiwi',
        'channel_id': 'public',
        'text': '第1夜：2号玩家一张角色牌出局。',
        'created_at': '2026-09-25T10:00:00',
      }),
    ]);
    expect(store.pendingMarksTutorial, isFalse);
  });

  test('已落幕的对局不再教学', () async {
    final store = await markStore(status: 'ended');
    store.mergeMessagesForTest([alertMessage(1, deadlyNightNotice)]);
    expect(store.pendingMarksTutorial, isFalse);
  });

  test('主持人不需要这份教程', () async {
    final store = await markStore(kind: 'host');
    store.mergeMessagesForTest([alertMessage(1, deadlyNightNotice)]);
    expect(store.pendingMarksTutorial, isFalse);
    expect(store.marksTutorialShown, isTrue, reason: '算过就不必反复判定');
  });

  test('换局后教程重新固定展示一次', () async {
    final store = await markStore();
    store.mergeMessagesForTest([alertMessage(1, deadlyNightNotice)]);
    expect(store.takeMarksTutorial(), isTrue);

    // 换到新的一局：标记与教程状态都重来。
    store.applyView(GameView.fromJson({...viewJson(), 'id': 'game-next'}));
    store.mergeMessagesForTest([alertMessage(2, '第3夜：4号玩家一张角色牌出局。')]);
    expect(store.pendingMarksTutorial, isTrue);
  });

  testWidgets('教程在首个非平安夜后由外壳弹一次', (tester) async {
    final store = await markStore();
    store.mergeMessagesForTest([alertMessage(1, deadlyNightNotice)]);
    expect(store.pendingMarksTutorial, isTrue);

    await pumpShell(tester, store);
    await tester.pumpAndSettle();
    expect(find.text('如何标记他人'), findsOneWidget);
    expect(find.text('清除标记'), findsOneWidget);
    expect(store.pendingMarksTutorial, isFalse);
    expect(store.marksTutorialShown, isTrue);

    await tester.tap(find.text('知道了'));
    await tester.pumpAndSettle();
    expect(find.text('如何标记他人'), findsNothing);

    // 之后再收到多少条公告都不会重弹。
    store.mergeMessagesForTest([alertMessage(2, '第2夜：4号玩家一张角色牌出局。')]);
    await settleSheets(tester);
    expect(find.text('如何标记他人'), findsNothing);
  });
}
