import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter/services.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:seven_double_client/src/design.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/shell.dart';
import 'package:seven_double_client/src/role_visuals.dart';
import 'package:seven_double_client/src/store.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('新增行动只弹一次服务端说明，描述变化不重弹', (tester) async {
    SharedPreferences.setMockInitialValues({});
    final base = {
      'ui_version': 1,
      'id': 'game-1',
      'version': 1,
      'status': 'playing',
      'day': 1,
      'half': 'day',
      'phase': 'discussion',
      'phase_label': '自由讨论',
      'seats': <dynamic>[],
      'self': {'seat_id': '1'},
      'actions': <dynamic>[],
      'public': <String, dynamic>{},
      'channels': <dynamic>[],
    };
    final store = GameStore.forPreview(
      preferences: await SharedPreferences.getInstance(),
      endpoint: ServerEndpoint.parse('http://127.0.0.1:8000'),
      actor: Actor.fromJson({
        'id': 'p1',
        'account_id': 'a1',
        'kind': 'player',
        'seat_id': '1',
        'name': '一号'
      }),
      view: GameView.fromJson(base),
      gameId: 'game-1',
    );
    store.applyView(GameView.fromJson(base));
    expect(store.takeActionTutorial(), isNull);
    final action = {
      'id': 'speech.done',
      'label': '结束发言',
      'short_label': '结束',
      'description': '请在轮到你时结束本轮发言。',
      'ui_version': 1
    };
    final updated = {
      ...base,
      'version': 2,
      'actions': [action]
    };
    store.applyLiveEvent({'type': 'state', 'state': updated});
    expect(store.newActionCount, 1);
    await tester.binding.setSurfaceSize(const Size(420, 880));
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
        MaterialApp(theme: buildAppTheme(), home: GameShell(store: store)));
    await tester.pump(const Duration(milliseconds: 600));
    await tester.pump(const Duration(milliseconds: 600));
    expect(find.text('请在轮到你时结束本轮发言。'), findsOneWidget);
    store.applyLiveEvent({
      'type': 'state',
      'state': {
        ...updated,
        'version': 3,
        'actions': [
          {...action, 'description': '新的服务端行动说明。'}
        ],
      }
    });
    await tester.binding.handlePopRoute();
    await tester.pump(const Duration(milliseconds: 600));
    await tester.pump(const Duration(milliseconds: 600));
    expect(find.text('新的服务端行动说明。'), findsNothing);
  });

  test('本局已看行动不重弹，准备和房间开关不弹', () async {
    SharedPreferences.setMockInitialValues({});
    final preferences = await SharedPreferences.getInstance();
    final actor = Actor.fromJson({
      'id': 'p1',
      'account_id': 'a1',
      'kind': 'player',
      'seat_id': '1',
      'name': '一号',
    });
    final endpoint = ServerEndpoint.parse('http://127.0.0.1:8000');
    Map<String, dynamic> state(String id, List<Map<String, dynamic>> actions) =>
        {
          'ui_version': 1,
          'id': id,
          'version': 1,
          'status': 'lobby',
          'day': 1,
          'half': 'night',
          'phase': 'lobby',
          'phase_label': '候场',
          'seats': <dynamic>[],
          'self': {'seat_id': '1'},
          'actions': actions,
          'public': <String, dynamic>{},
          'channels': <dynamic>[],
        };
    Map<String, dynamic> action(String id, String label) => {
          'id': id,
          'label': label,
          'short_label': '操作',
          'description': '行动说明',
          'ui_version': 1,
        };
    final empty = GameView.fromJson(state('game-1', []));
    final store = GameStore.forPreview(
      preferences: preferences,
      endpoint: endpoint,
      actor: actor,
      view: empty,
      gameId: 'game-1',
    );
    store.applyView(empty);
    final ready = action('lobby.ready', '准备发牌');
    final open = action('room.open_join', '允许加入');
    store.applyView(GameView.fromJson(state('game-1', [ready, open])));
    expect(store.takeActionTutorial(), isNull);
    store.applyView(GameView.fromJson(state('game-1', [
      action('lobby.ready', '取消准备'),
      action('room.open_join', '禁止加入'),
      action('host.auto', '暂停自动推进'),
      action('host.hanna_witch', '汉娜魔化：已开启'),
    ])));
    expect(store.takeActionTutorial(), isNull);

    final speech = action('speech.done', '结束发言');
    store.applyView(GameView.fromJson(state('game-1', [speech])));
    expect(store.takeActionTutorial()?.id, 'speech.done');
    store.applyView(GameView.fromJson(state('game-1', [])));
    store.applyView(GameView.fromJson(state('game-1', [
      {...speech, 'description': '变化后的说明'},
    ])));
    expect(store.takeActionTutorial(), isNull);

    final resumed = GameStore.forPreview(
      preferences: preferences,
      endpoint: endpoint,
      actor: actor,
      view: empty,
      gameId: 'game-1',
    );
    resumed.applyView(empty);
    resumed.applyView(GameView.fromJson(state('game-1', [speech])));
    expect(resumed.takeActionTutorial(), isNull);

    final otherGame = GameView.fromJson(state('game-2', []));
    final newStore = GameStore.forPreview(
      preferences: preferences,
      endpoint: endpoint,
      actor: actor,
      view: otherGame,
      gameId: 'game-2',
    );
    newStore.applyView(otherGame);
    newStore.applyView(GameView.fromJson(state('game-2', [speech])));
    expect(newStore.takeActionTutorial()?.id, 'speech.done');
  });

  testWidgets('公开顺序与当前席位随服务端状态更新', (tester) async {
    SharedPreferences.setMockInitialValues({});
    final store = GameStore.forPreview(
      preferences: await SharedPreferences.getInstance(),
      endpoint: ServerEndpoint.parse('http://127.0.0.1:8000'),
      actor: Actor.fromJson({
        'id': 'p1',
        'account_id': 'a1',
        'kind': 'player',
        'seat_id': '1',
        'name': '一号',
      }),
      view: GameView.fromJson({
        'ui_version': 1,
        'id': 'game-1',
        'version': 1,
        'status': 'playing',
        'day': 1,
        'half': 'day',
        'phase': 'speech',
        'phase_label': '顺序发言',
        'seats': [
          {'id': '1', 'avatar_role_id': 'anna', 'occupied': true},
          {'id': '2', 'avatar_role_id': 'millia', 'occupied': true},
        ],
        'self': {'seat_id': '1'},
        'actions': [],
        'public': {
          'speech_order': ['2', '1'],
          'speaker': '2'
        },
        'channels': [
          {
            'id': 'public',
            'label': '公开讨论',
            'status': 'active',
            'can_send': true,
            'reason': '',
            'actions': []
          },
        ],
      }),
      gameId: 'game-1',
    );
    await tester.binding.setSurfaceSize(const Size(420, 880));
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
        MaterialApp(theme: buildAppTheme(), home: GameShell(store: store)));
    await tester.pump(const Duration(milliseconds: 600));
    expect(find.text('1. 2号'), findsOneWidget);
    expect(find.text('2. 1号'), findsOneWidget);
    expect(find.text('2号'), findsWidgets);
    expect(find.byType(RoleAvatar), findsWidgets);
  });
  testWidgets('正文长按区分本人菜单，复制与撤回占位', (tester) async {
    String? copied;
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, (call) async {
      if (call.method == 'Clipboard.setData') {
        copied = (call.arguments as Map)['text']?.toString();
      }
      return null;
    });
    addTearDown(() => TestDefaultBinaryMessengerBinding
        .instance.defaultBinaryMessenger
        .setMockMethodCallHandler(SystemChannels.platform, null));
    SharedPreferences.setMockInitialValues({});
    final store = GameStore.forPreview(
      preferences: await SharedPreferences.getInstance(),
      endpoint: ServerEndpoint.parse('http://127.0.0.1:8000'),
      actor: Actor.fromJson({
        'id': 'p1',
        'account_id': 'a1',
        'kind': 'player',
        'seat_id': '1',
        'name': '一号'
      }),
      view: GameView.fromJson({
        'ui_version': 1,
        'id': 'game-1',
        'version': 1,
        'status': 'playing',
        'day': 1,
        'half': 'day',
        'phase': 'discussion',
        'seats': [],
        'self': {'seat_id': '1'},
        'actions': [],
        'channels': []
      }),
      gameId: 'game-1',
    );
    final own = GameMessage.fromJson({
      'id': 1,
      'kind': 'chat',
      'text': '请 @2号 [微笑]',
      'sender_id': 'p1',
      'sender_name': '一号',
      'channel_id': 'public',
    });
    final other = GameMessage.fromJson({
      'id': 2,
      'kind': 'chat',
      'text': '对方消息',
      'sender_id': 'p2',
      'sender_name': '二号',
      'channel_id': 'public',
    });
    await tester.pumpWidget(MaterialApp(
      theme: buildAppTheme(),
      home: Scaffold(
          body: Column(children: [
        MessageBubble(message: own, self: 'p1', store: store),
        MessageBubble(message: other, self: 'p1', store: store),
      ])),
    ));
    await tester.longPress(find.textContaining('对方消息'));
    await tester.pumpAndSettle();
    expect(find.text('复制'), findsOneWidget);
    expect(find.text('撤回'), findsNothing);
    await tester.tap(find.text('复制'));
    await tester.pumpAndSettle();
    expect(copied, '对方消息');
    final body = tester.widget<Text>(find.textContaining('请 @2号'));
    final mention = (body.textSpan! as TextSpan)
        .children!
        .whereType<TextSpan>()
        .singleWhere((span) => span.text == '@2号');
    expect(mention.style!.fontWeight, FontWeight.bold);
    await tester.longPress(find.textContaining('请 @2号'));
    await tester.pumpAndSettle();
    expect(find.text('撤回'), findsOneWidget);
    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    final recalled = GameMessage.fromJson({
      'id': 1,
      'kind': 'chat',
      'text': '',
      'recalled': true,
      'sender_id': 'p1',
      'sender_name': '一号',
      'channel_id': 'public',
    });
    await tester.pumpWidget(MaterialApp(
      theme: buildAppTheme(),
      home: Scaffold(body: MessageBubble(message: recalled, self: 'p1')),
    ));
    expect(find.text('你撤回了一条消息'), findsOneWidget);
    expect(find.textContaining('请 @2号'), findsNothing);
  });

  testWidgets('从公开席位选择稳定 @ 标签并积累专用未读', (tester) async {
    SharedPreferences.setMockInitialValues({});
    final view = GameView.fromJson({
      'ui_version': 1,
      'id': 'game-1',
      'version': 1,
      'status': 'playing',
      'day': 1,
      'half': 'day',
      'phase': 'discussion',
      'phase_label': '自由讨论',
      'seats': [
        {
          'id': '1',
          'participant_id': 'p1',
          'occupied': true,
          'avatar_role_id': 'anna'
        },
        {
          'id': '2',
          'participant_id': 'p2',
          'occupied': true,
          'avatar_role_id': 'millia'
        },
      ],
      'self': {'seat_id': '1'},
      'actions': [],
      'public': {},
      'channels': [
        {
          'id': 'public',
          'label': '公开讨论',
          'status': 'active',
          'can_send': true,
          'reason': '',
          'actions': []
        },
      ],
    });
    final store = GameStore.forPreview(
      preferences: await SharedPreferences.getInstance(),
      endpoint: ServerEndpoint.parse('http://127.0.0.1:8000'),
      actor: Actor.fromJson({
        'id': 'p1',
        'account_id': 'a1',
        'kind': 'player',
        'seat_id': '1',
        'name': '一号'
      }),
      view: view,
      gameId: 'game-1',
    );
    await tester.binding.setSurfaceSize(const Size(420, 880));
    addTearDown(tester.view.reset);
    await tester.pumpWidget(
        MaterialApp(theme: buildAppTheme(), home: GameShell(store: store)));
    await tester.pump(const Duration(milliseconds: 600));
    await tester.enterText(find.byType(TextField).first, '@');
    await tester.pumpAndSettle();
    expect(find.text('@ 玩家'), findsOneWidget);
    await tester.tap(find.textContaining('2号').last);
    await tester.pumpAndSettle();
    expect(find.byType(TextField).first, findsOneWidget);
    expect(
        tester.widget<TextField>(find.byType(TextField).first).controller!.text,
        '@2号 ');
    store.applyLiveEvent({
      'type': 'message',
      'message': {
        'id': 10,
        'kind': 'chat',
        'text': '@1号 快看',
        'channel_id': 'public',
        'sender_id': 'p2',
        'mention_ids': ['p1'],
      }
    });
    await tester.pump(const Duration(milliseconds: 300));
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.text('有人 @ 你'), findsOneWidget);
    expect(store.unreadMentionCount, 1);
    expect(find.text('@'), findsWidgets);
    store.applyLiveEvent({
      'type': 'message',
      'message': {
        'id': 10,
        'kind': 'chat',
        'text': '',
        'recalled': true,
        'channel_id': 'public',
        'sender_id': 'p2',
        'mention_ids': [],
      }
    });
    expect(store.unreadMentionCount, 0);
    await store.markMessagesRead();
    expect(store.unreadMentionCount, 0);
  });
}
