import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:seven_double_client/src/design.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/shell.dart';
import 'package:seven_double_client/src/store.dart';

/// 对局内悬浮对话框：内容与时机由服务端下发，客户端只渲染与提交标准行动。

Map<String, dynamic> action(
  String id,
  String short,
  String label, {
  bool danger = false,
}) =>
    {
      'id': id,
      'ui_version': 1,
      'short_label': short,
      'label': label,
      'description': '$label 的完整说明。',
      'group': '私信',
      'danger': danger,
      'payload': {'channel_id': 'private:abc'},
      'fields': <dynamic>[],
    };

Map<String, dynamic> inviteDialog() => {
      'id': 'channel:private:abc',
      'kind': 'channel_invite',
      'title': '私聊申请',
      'text': '3号 庭雨 邀请你加入私信；同意后双方才能发言。',
      'dismissible': true,
      'actions': [
        action('channel.accept', '同意', '同意加入私信'),
        action('channel.reject', '拒绝', '拒绝加入并取消本次私信', danger: true),
      ],
    };

Map<String, dynamic> witnessDialog() => {
      'id': 'witness:game-dialog:2',
      'kind': 'witness',
      'title': '当日目击名单',
      'text': '四名疑似凶手：梅露露、汉娜、可可、诺亚。',
      'dismissible': true,
      'actions': <dynamic>[],
    };

Map<String, dynamic> resultDialog() => {
      'id': 'result:game-dialog',
      'kind': 'result',
      'title': '本局已结束 · 好人获胜',
      'text': '魔女阵营A、B两席出局',
      'dismissible': true,
      'actions': <dynamic>[],
      'match_id': 'game-dialog',
    };

Map<String, dynamic> viewJson(List<dynamic> dialogs) => {
      'ui_version': 1,
      'id': 'game-dialog',
      'version': 9,
      'status': 'playing',
      'day': 2,
      'half': 'day',
      'phase': 'discussion',
      'phase_label': '自由发言',
      'seats': <dynamic>[],
      'self': <String, dynamic>{},
      'actions': <dynamic>[],
      'channels': <dynamic>[],
      'public': <String, dynamic>{},
      'information': <dynamic>[],
      'result': null,
      'dialogs': dialogs,
    };

Future<GameStore> storeWith(List<dynamic> dialogs) async {
  SharedPreferences.setMockInitialValues({});
  final preferences = await SharedPreferences.getInstance();
  return GameStore.forPreview(
    preferences: preferences,
    endpoint: ServerEndpoint.parse('http://127.0.0.1:8000'),
    actor: Actor.fromJson({
      'id': 'p1',
      'kind': 'player',
      'name': '阿雪',
      'seat_id': '1',
    }),
    view: GameView.fromJson(viewJson(dialogs)),
    gameId: 'game-dialog',
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
  await tester.pump(const Duration(milliseconds: 400));
}

void main() {
  testWidgets('私聊申请弹悬浮卡，同意走统一的行动表单', (tester) async {
    final store = await storeWith([inviteDialog()]);
    await pumpShell(tester, store);

    expect(find.text('私聊申请'), findsOneWidget);
    expect(find.textContaining('邀请你加入私信'), findsOneWidget);
    await tester.tap(find.text('同意'));
    await tester.pumpAndSettle();
    // 与其它行动完全同一条提交路径：表单 + 一次确认。
    expect(find.text('确认提交'), findsOneWidget);
    expect(find.textContaining('完整说明'), findsOneWidget);
  });

  testWidgets('目击名单弹卡，知道了之后本进程不再自动弹', (tester) async {
    final store = await storeWith([witnessDialog()]);
    await pumpShell(tester, store);

    expect(find.text('当日目击名单'), findsOneWidget);
    expect(find.textContaining('四名疑似凶手'), findsOneWidget);
    await tester.tap(find.text('知道了'));
    await tester.pump(const Duration(milliseconds: 400));
    expect(find.text('当日目击名单'), findsNothing);
    // 内容仍在状态页的常驻卡片里（这里只验证悬浮卡消失）。
    expect(store.activeDialogs, isEmpty);
  });

  testWidgets('对局结束信息弹卡并给出历史记录入口', (tester) async {
    final store = await storeWith([resultDialog()]);
    await pumpShell(tester, store);

    expect(find.text('本局已结束 · 好人获胜'), findsOneWidget);
    expect(find.text('魔女阵营A、B两席出局'), findsOneWidget);
    expect(find.text('查看本局记录'), findsOneWidget);
  });

  testWidgets('多条待办时只弹第一条并提示还有几条', (tester) async {
    final store = await storeWith([resultDialog(), witnessDialog()]);
    await pumpShell(tester, store);
    expect(find.text('本局已结束 · 好人获胜'), findsOneWidget);
    expect(find.text('还有 1 条'), findsOneWidget);
    expect(find.text('当日目击名单'), findsNothing);
  });

  testWidgets('没有对话框时不渲染悬浮卡', (tester) async {
    final store = await storeWith(const []);
    await pumpShell(tester, store);
    expect(find.text('私聊申请'), findsNothing);
    expect(find.text('知道了'), findsNothing);
  });
}
