import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:seven_double_client/src/history_pages.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/store.dart';

import 'golden_harness.dart';

/// 历史对局界面的 golden：列表与单局详情是本轮新增的界面，渲染出来便于核对观感。

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
          'name': '阿雪',
          'kind': 'player',
          'seat_id': '2',
          'role_ids': ['hiro', 'coco'],
          'active': false,
          'blocked': false,
        },
      ],
    };

Map<String, dynamic> abortedJson() => {
      ...matchJson(),
      'id': 'game-0',
      'winner': '',
      'source': 'aborted',
      'reason': '',
      'ended_at': '2026-09-25T12:00:00+00:00',
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

void main() {
  setUpAll(loadBundledFonts);

  testWidgets('历史对局列表渲染', (tester) async {
    final store = await previewStore();
    await pumpPhone(
      tester,
      MatchHistoryPage(
        store: store,
        loader: ({String? before, int limit = 20}) async => (
          matches: [
            MatchSummary.fromJson(matchJson()),
            MatchSummary.fromJson(abortedJson()),
          ],
          hasMore: false,
        ),
      ),
    );
    expect(find.text('第 3 日 · 好人获胜'), findsOneWidget);
    await expectLater(
      find.byType(MatchHistoryPage),
      matchesGoldenFile('goldens/history_list.png'),
    );
  });

  testWidgets('历史对局详情渲染', (tester) async {
    final store = await previewStore();
    await pumpPhone(
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
              'text': '我这边没有可以证明的信息，先听大家说。',
              'created_at': '2026-09-26T01:30:00+00:00',
            },
            {
              'seq': 2,
              'kind': 'alert',
              'sender_name': '主持人',
              'text': '3号玩家一张角色牌出局。',
              'created_at': '2026-09-26T01:40:00+00:00',
            },
          ],
        }),
      ),
    );
    expect(find.text('公开时间线'), findsOneWidget);
    await expectLater(
      find.byType(MatchDetailPage),
      matchesGoldenFile('goldens/history_detail.png'),
    );
  });
}
