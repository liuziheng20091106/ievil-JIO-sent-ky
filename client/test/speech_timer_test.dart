// 顺序发言的30秒倒计时横幅回归检查。
//
// 服务端在 action_prompt 里下发绝对截止时间（speech_deadline，Unix 秒）与总时长
// （speech_seconds），横幅据此在本地逐秒刷新剩余秒数——不需要服务端每秒推状态。
// 本人发言或继续输入后服务端会拨满倒计时并补推状态帧，横幅随之跳回 30 秒。
//
// 运行方式（client 目录）：flutter test test/speech_timer_test.dart
import 'package:clock/clock.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:seven_double_client/src/design.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/shell.dart';
import 'package:seven_double_client/src/store.dart';

/// 倒计时基准时刻：固定下来，让「现在」完全由 withClock 决定。
final DateTime base = DateTime.fromMillisecondsSinceEpoch(1771234567000);

Map<String, dynamic> viewJson({Map<String, dynamic>? prompt}) => {
      'ui_version': 1,
      'id': 'game-1',
      'version': 1,
      'status': 'playing',
      'day': 1,
      'half': 'day',
      'phase': 'speech',
      'phase_label': '顺序发言',
      'seats': <dynamic>[],
      // 席位号必须与 actor 一致：不一致会触发一次「重新核对身份」的网络请求，
      // 测试环境里那次请求必然失败并把会话清掉，界面就只剩转圈。
      'self': <String, dynamic>{'seat_id': '1'},
      'actions': <dynamic>[],
      'public': <String, dynamic>{},
      if (prompt != null) 'action_prompt': prompt,
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

/// 当前发言人的催办框：服务端在顺序发言阶段会带上公开倒计时。
Map<String, dynamic> promptJson({required double deadline, int seconds = 30}) =>
    {
      'title': '轮到你顺序发言',
      'text': '发言、打断，或点「本轮不发言」跳过你的顺序。',
      'hint': null,
      'speech_deadline': deadline,
      'speech_seconds': seconds,
    };

Actor actorJson() => Actor.fromJson({
      'id': 'p1',
      'account_id': 'a1',
      'kind': 'player',
      'seat_id': '1',
      'name': '一号',
    });

Future<GameStore> previewStore(Map<String, dynamic> view) async {
  SharedPreferences.setMockInitialValues({});
  final preferences = await SharedPreferences.getInstance();
  return GameStore.forPreview(
    preferences: preferences,
    endpoint: ServerEndpoint.parse('http://127.0.0.1:8000'),
    actor: actorJson(),
    view: GameView.fromJson(view),
    gameId: 'game-1',
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

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('横幅按剩余秒数逐秒刷新，到点提示正在换人', (tester) async {
    var now = base;
    await withClock(Clock(() => now), () async {
      final store = await previewStore(
        viewJson(
          prompt: promptJson(
            deadline: base.millisecondsSinceEpoch / 1000 + 30,
          ),
        ),
      );
      await pumpShell(tester, store);
      expect(find.text('轮到你顺序发言'), findsOneWidget);
      expect(find.text('剩余 30 秒'), findsOneWidget);
      expect(find.text('发言或继续输入会重新计时'), findsNothing);

      // 本地时钟走到第 7 秒：只靠横幅自己的定时刷新，服务端没有再推状态。
      now = base.add(const Duration(seconds: 7));
      await tester.pump(const Duration(milliseconds: 600));
      expect(find.text('剩余 23 秒'), findsOneWidget);
      expect(find.text('剩余 30 秒'), findsNothing);

      // 到点后服务端会在1秒内换人：横幅先给出「正在轮到下一位」的提示。
      now = base.add(const Duration(seconds: 31));
      await tester.pump(const Duration(milliseconds: 600));
      expect(find.text('时间到，正在轮到下一位…'), findsOneWidget);

      // 本人发言/继续输入后服务端补推一帧状态：倒计时应当跳回满格。
      // 走真实的实时事件入口（applyView 是构造期的测试钩子，不会通知界面重建）。
      store.applyLiveEvent({
        'type': 'state',
        'state': viewJson(
          prompt: promptJson(
            deadline: now.millisecondsSinceEpoch / 1000 + 30,
          ),
        ),
      });
      await tester.pump(const Duration(milliseconds: 600));
      expect(find.text('剩余 30 秒'), findsOneWidget);
    });
  });

  testWidgets('没有倒计时字段的横幅不显示任何计时', (tester) async {
    await withClock(Clock(() => base), () async {
      final store = await previewStore(
        viewJson(
          prompt: {
            'title': '请提交提名或放弃',
            'text': '同一人可以被多人提名；提交即生效。',
            'hint': null,
          },
        ),
      );
      await pumpShell(tester, store);
      expect(find.text('请提交提名或放弃'), findsOneWidget);
      expect(find.textContaining('剩余'), findsNothing);
      expect(find.textContaining('重新计时'), findsNothing);
    });
  });
}
