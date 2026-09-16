// 回归检查：Flutter 原生客户端在对局终止后必须能回到主界面（大厅）。
//
// 对应用户报告的缺陷：对局被主持人终止后，客户端仍停留在已结束的只读对局里，
// 本地缓存的 gameId 让重启后又回到这一局，没有任何入口回到大厅。
//
// 运行方式（client 目录）：flutter test test/game_end_test.dart

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:seven_double_client/main.dart';
import 'package:seven_double_client/src/design.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/store.dart';
import 'package:shared_preferences/shared_preferences.dart';

const endpoint = 'http://127.0.0.1:8000';

/// 服务端终止对局后 /api/games/{id}/state 的真实裁剪结果（只保留本检查用到的字段）。
Map<String, dynamic> endedViewJson() => {
      'ui_version': 1,
      'id': 'game-ended',
      'version': 42,
      'status': 'ended',
      'day': 3,
      'half': 'day',
      'phase': 'ended',
      'phase_label': '已结束',
      'deadline': null,
      'ready_count': 0,
      'actions': <dynamic>[],
      'channels': [
        {
          'id': 'public',
          'label': '公开讨论',
          'status': 'active',
          'creator_id': 'host',
          'members': <dynamic>[],
          'invited_ids': <dynamic>[],
          'accepted_ids': <dynamic>[],
          'invitation': 'none',
          'can_send': false,
          'reason': '对局已结束',
          'actions': <dynamic>[],
        },
      ],
      'seats': <dynamic>[],
      'self': {
        'cards': <dynamic>[],
        'current_card_id': null,
        'warning_deadline': null,
      },
      'result': {
        'winner': 'aborted',
        'reason': '主持人终止：人数不足以继续。',
        'personal_losses': <dynamic>[],
        'personal_results': <dynamic>[],
      },
      'can_chat': false,
      'chat_reason': '对局已结束',
      'information': <dynamic>[],
      'public': <String, dynamic>{},
    };

Actor playerActor() => Actor.fromJson({
      'id': 'p1',
      'account_id': 'a1',
      'kind': 'player',
      'game_id': 'game-ended',
      'seat_id': '1',
      'name': '阿雪',
      'qq_id': '10001',
      'avatar_url': null,
      'access_ids': ['p1'],
    });

Future<GameStore> endedStore({String? gameId = 'game-ended'}) async {
  SharedPreferences.setMockInitialValues({});
  final preferences = await SharedPreferences.getInstance();
  return GameStore.forPreview(
    preferences: preferences,
    endpoint: ServerEndpoint.parse(endpoint),
    actor: playerActor(),
    view: GameView.fromJson(endedViewJson()),
    gameId: gameId,
  );
}

Future<void> pumpShell(WidgetTester tester, GameStore store) async {
  await tester.binding.setSurfaceSize(const Size(430, 900));
  tester.view.physicalSize = const Size(430, 900);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: buildAppTheme(),
      // 与 main.dart 一致：store 变化驱动 AppGate 在“对局页 / 大厅”之间切换。
      home: AnimatedBuilder(
        animation: store,
        builder: (context, _) => AppGate(store: store),
      ),
    ),
  );
  await tester.pump();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('落幕不再被当成新的阶段变化（不弹阶段动画）', () async {
    final store = await endedStore();
    final preferences = await SharedPreferences.getInstance();
    await preferences
        .setString('$endpoint:game-ended:a1:phase_seen', 'game-ended:3:day:speech');
    store.applyView(GameView.fromJson({
      ...endedViewJson(),
      'status': 'playing',
      'phase': 'speech',
      'phase_label': '顺序发言',
    }));
    expect(store.pendingPhaseKey, isNull);
    // 对局被终止：不弹出“新阶段”整屏动画，直接进入只读结局。
    store.applyView(GameView.fromJson(endedViewJson()));
    expect(store.pendingPhaseKey, isNull);
    expect(store.view!.status, 'ended');
  });

  testWidgets('终止后的对局页给出「返回大厅」入口，点击后回到主界面', (tester) async {
    final store = await endedStore();
    await pumpShell(tester, store);

    // 已终止对局：页头必须有返回大厅入口。
    expect(find.text('返回大厅'), findsOneWidget);
    expect(store.gameId, 'game-ended');

    // 结算页（“状态”页签）同样给出返回主界面按钮。
    await tester.tap(find.text('状态'));
    await tester.pumpAndSettle();
    expect(find.text('本局已终止'), findsOneWidget);
    expect(find.text('返回主界面（大厅）'), findsOneWidget);

    await tester.tap(find.text('返回大厅'));
    await tester.pumpAndSettle();

    // 返回主界面后：本地不再绑定这一局，界面切到大厅。
    expect(store.gameId, isNull);
    expect(store.view, isNull);
    expect(find.text('大厅'), findsOneWidget);
  });

  testWidgets('未终止的对局不显示返回大厅入口，避免误退当前局', (tester) async {
    SharedPreferences.setMockInitialValues({});
    final preferences = await SharedPreferences.getInstance();
    final playing = endedViewJson()
      ..['status'] = 'playing'
      ..['phase'] = 'discussion'
      ..['phase_label'] = '自由讨论';
    final store = GameStore.forPreview(
      preferences: preferences,
      endpoint: ServerEndpoint.parse(endpoint),
      actor: playerActor(),
      view: GameView.fromJson(playing),
      gameId: 'game-demo',
    );
    await pumpShell(tester, store);

    expect(find.text('返回大厅'), findsNothing);
    expect(store.gameId, 'game-demo');
  });
}
