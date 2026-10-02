import 'package:clock/clock.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:seven_double_client/src/history_pages.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/store.dart';

import 'golden_harness.dart';

/// 历史对局界面的 golden：列表与单局详情是本轮新增的界面，渲染出来便于核对观感。

/// 夹具时间基准：固定「现在」，让时间文本与 golden 都不随运行日期变化。
///
/// 时间文本对当天只显示 HH:mm、跨天才补日期，所以夹具时间必须与「现在」一起钉死，
/// 否则 golden 只在生成当天通过。基准取 UTC 正午；列表里那条「已中止」的对局故意
/// 取前一天，用来覆盖跨天时补日期的分支。
final fixedNow = DateTime.utc(2026, 9, 15, 12, 0);

String stampAgo(int minutes) =>
    fixedNow.subtract(Duration(minutes: minutes)).toIso8601String();

String stampDaysAgo(int days) =>
    fixedNow.subtract(Duration(days: days)).toIso8601String();

Map<String, dynamic> matchJson() => {
      'id': 'game-1',
      'ended_at': stampAgo(0),
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
      'ended_at': stampDaysAgo(1),
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
    await withClock(Clock.fixed(fixedNow), () async {
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
      expectClockPinned(fixedNow);
    });
  });

}
