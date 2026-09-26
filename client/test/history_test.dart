import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:seven_double_client/src/design.dart';
import 'package:seven_double_client/src/history_pages.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/role_visuals.dart';
import 'package:seven_double_client/src/store.dart';

/// 历史对局页面：列表、单局详情（身份与公开时间线）与空状态。
///
/// 页面自己不发请求：数据走注入的 loader（widget 测试里真实 HTTP 会被测试框架拦掉），
/// 接口本身的路径、查询与字段解析由 `game_api_test.dart` 覆盖。

Map<String, dynamic> matchJson() => {
      'id': 'game-1',
      'ended_at': '2026-09-26T02:00:00+00:00',
      'day': 3,
      'winner': 'good',
      'reason': '魔女阵营A、B两席出局',
      'source': 'ended',
      'host_name': '主持人(阿雪)',
      'player_count': 2,
      'players': [
        {
          'participant_id': 'p1',
          'account_id': 'acc1',
          'name': 'kiwi',
          'kind': 'player',
          'seat_id': '1',
          'role_ids': ['marg', 'sherry'],
          'active': true,
          'blocked': false,
        },
        {
          'participant_id': 'p2',
          'account_id': 'acc2',
          'name': '被移出的人',
          'kind': 'player',
          'seat_id': '2',
          'role_ids': <dynamic>[],
          'active': false,
          'blocked': false,
        },
      ],
    };

Map<String, dynamic> viewJson() => {
      'ui_version': 1,
      'id': 'game-1',
      'version': 1,
      'status': 'ended',
      'day': 3,
      'half': 'day',
      'phase': 'dusk',
      'phase_label': '天黑与胜负确认',
      'seats': <dynamic>[],
      'self': <String, dynamic>{},
      'actions': <dynamic>[],
      'channels': <dynamic>[],
      'public': <String, dynamic>{},
      'information': <dynamic>[],
      'result': null,
      'dialogs': <dynamic>[],
    };

Future<GameStore> previewStore() async {
  SharedPreferences.setMockInitialValues({});
  final preferences = await SharedPreferences.getInstance();
  return GameStore.forPreview(
    preferences: preferences,
    endpoint: ServerEndpoint.parse('http://127.0.0.1:8000'),
    actor: Actor.fromJson({
      'id': 'acc1',
      'kind': 'player',
      'name': 'kiwi',
      'seat_id': '1',
    }),
    view: GameView.fromJson(viewJson()),
    gameId: 'game-1',
  );
}

Future<void> pump(WidgetTester tester, Widget page) async {
  await tester.binding.setSurfaceSize(const Size(420, 880));
  tester.view.physicalSize = const Size(420, 880);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(
    MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: buildAppTheme(),
      home: page,
    ),
  );
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('历史列表渲染胜负与参与席位，点开看详情', (tester) async {
    final store = await previewStore();
    final summary = MatchSummary.fromJson(matchJson());
    await pump(
      tester,
      MatchHistoryPage(
        store: store,
        loader: ({String? before, int limit = 20}) async =>
            (matches: [summary], hasMore: false),
      ),
    );

    expect(find.text('第 3 日 · 好人获胜'), findsOneWidget);
    expect(find.textContaining('魔女阵营A、B两席出局'), findsOneWidget);
    expect(find.textContaining('主持人(阿雪)'), findsOneWidget);
    expect(find.textContaining('kiwi、被移出的人'), findsOneWidget);

    await tester.tap(find.text('第 3 日 · 好人获胜'));
    await tester.pumpAndSettle();

    // 点开就是单局详情页（详情内容由下面那条用例注入数据后验证）。
    expect(find.byType(MatchDetailPage), findsOneWidget);
    expect(find.text('对局记录'), findsOneWidget);
  });

  testWidgets('单局详情渲染身份、公开时间线与隐私说明', (tester) async {
    final store = await previewStore();
    await pump(
      tester,
      MatchDetailPage(
        store: store,
        matchId: 'game-1',
        loader: (matchId) async => MatchDetail.fromJson({
          ...matchJson(),
          'events': [
            {
              'seq': 0,
              'kind': 'notice',
              'sender_name': '主持人',
              'text': '新对局已创建，等待主持人开放参局',
              'created_at': '2026-09-26T01:00:00+00:00',
            },
            {
              'seq': 1,
              'kind': 'chat',
              'sender_name': 'kiwi',
              'avatar_role_id': 'marg',
              'text': '公屏上说过的话',
              'created_at': '2026-09-26T01:30:00+00:00',
            },
            {
              'seq': 2,
              'kind': 'chat',
              'sender_name': '主持人(阿雪)',
              'avatar_role_id': 'host',
              'text': '主持人公屏上说过的话',
              'created_at': '2026-09-26T01:35:00+00:00',
            },
          ],
        }),
      ),
    );
    expect(find.text('kiwi'), findsWidgets);
    expect(find.text('玛格'), findsOneWidget);
    expect(find.text('雪莉'), findsOneWidget);
    expect(find.text('已移出'), findsOneWidget);
    expect(find.textContaining('新对局已创建'), findsOneWidget);
    expect(find.text('公屏上说过的话'), findsOneWidget);
    expect(find.text('公开时间线'), findsOneWidget);
    expect(find.textContaining('私信与只发给个人的情报不入库'), findsOneWidget);

    // 回归：主持人消息的头像是月代雪立绘，不能退化成「?」占位。
    final hostAvatar = tester.widget<RoleAvatar>(
      find.descendant(
        of: find.widgetWithText(Row, '主持人公屏上说过的话').first,
        matching: find.byType(RoleAvatar),
      ).last,
    );
    expect(hostAvatar.host, isTrue);
    expect(hostAvatar.roleId, 'host');
    expect(find.text('?'), findsNothing);
  });

  testWidgets('没有历史对局时显示空状态', (tester) async {
    final store = await previewStore();
    await pump(
      tester,
      MatchHistoryPage(
        store: store,
        loader: ({String? before, int limit = 20}) async =>
            (matches: const <MatchSummary>[], hasMore: false),
      ),
    );
    expect(find.text('还没有历史对局'), findsOneWidget);
  });

  testWidgets('终止（未宣判）的对局显示为已终止', (tester) async {
    final store = await previewStore();
    final aborted = MatchSummary.fromJson({
      ...matchJson(),
      'winner': '',
      'source': 'aborted',
      'reason': '',
    });
    await pump(
      tester,
      MatchHistoryPage(
        store: store,
        loader: ({String? before, int limit = 20}) async =>
            (matches: [aborted], hasMore: false),
      ),
    );
    expect(find.textContaining('本局已终止（未宣判）'), findsOneWidget);
  });

  testWidgets('4 级主持能看到删除入口，确认后就地移除这一局', (tester) async {
    final store = await previewStore();
    store.actor = Actor.fromJson({
      'id': 'host',
      'account_id': 'a-host',
      'kind': 'host',
      'name': '主持人',
      'host_level': 4,
    });
    final deleted = <String>[];
    await pump(
      tester,
      MatchHistoryPage(
        store: store,
        loader: ({String? before, int limit = 20}) async =>
            (matches: [MatchSummary.fromJson(matchJson())], hasMore: false),
        deleter: (matchId) async => deleted.add(matchId),
      ),
    );
    expect(find.byTooltip('删除这条历史对局'), findsOneWidget);

    await tester.tap(find.byTooltip('删除这条历史对局'));
    await tester.pumpAndSettle();
    // 确认弹窗写清后果，取消不删。
    expect(find.text('删除这条历史对局？'), findsOneWidget);
    await tester.tap(find.text('取消'));
    await tester.pumpAndSettle();
    expect(deleted, isEmpty);
    expect(find.text('第 3 日 · 好人获胜'), findsOneWidget);

    await tester.tap(find.byTooltip('删除这条历史对局'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('删除'));
    await tester.pumpAndSettle();
    expect(deleted, ['game-1']);
    expect(find.text('还没有历史对局'), findsOneWidget);
  });

  testWidgets('普通玩家与低级主持看不到删除入口', (tester) async {
    final store = await previewStore();
    await pump(
      tester,
      MatchHistoryPage(
        store: store,
        loader: ({String? before, int limit = 20}) async =>
            (matches: [MatchSummary.fromJson(matchJson())], hasMore: false),
      ),
    );
    expect(find.byTooltip('删除这条历史对局'), findsNothing);

    // 3 级主持（能管成就）也不给删除历史对局。
    store.actor = Actor.fromJson({
      'id': 'host',
      'account_id': 'a-host',
      'kind': 'host',
      'name': '主持人',
      'host_level': 3,
    });
    await pump(
      tester,
      MatchHistoryPage(
        store: store,
        loader: ({String? before, int limit = 20}) async =>
            (matches: [MatchSummary.fromJson(matchJson())], hasMore: false),
      ),
    );
    expect(find.byTooltip('删除这条历史对局'), findsNothing);
  });

  testWidgets('详情页里删除成功后退出详情页', (tester) async {
    final store = await previewStore();
    store.actor = Actor.fromJson({
      'id': 'host',
      'account_id': 'a-host',
      'kind': 'host',
      'name': '主持人',
      'host_level': 5,
    });
    final deleted = <String>[];
    await pump(
      tester,
      MatchDetailPage(
        store: store,
        matchId: 'game-1',
        loader: (matchId) async => MatchDetail.fromJson({
          ...matchJson(),
          'events': <dynamic>[],
        }),
        deleter: (matchId) async => deleted.add(matchId),
      ),
    );
    expect(find.byTooltip('删除这条历史对局'), findsOneWidget);
    await tester.tap(find.byTooltip('删除这条历史对局'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('删除'));
    await tester.pumpAndSettle();
    expect(deleted, ['game-1']);
  });
}
