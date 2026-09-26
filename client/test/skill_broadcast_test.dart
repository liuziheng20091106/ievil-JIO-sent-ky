import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:seven_double_client/src/design.dart';
import 'package:seven_double_client/src/game_dialog.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/shell.dart';
import 'package:seven_double_client/src/store.dart';

/// 技能播报：结构化载荷渲染成「[头像] N号 昵称 · 使用技能 X [→ N号]」，
/// 点开可看技能详细；服务端没给载荷时退回原来的灰条文本。

Map<String, dynamic> viewJson({List<dynamic> dialogs = const []}) => {
      'ui_version': 1,
      'id': 'game-skill',
      'version': 7,
      'status': 'playing',
      'day': 2,
      'half': 'day',
      'phase': 'discussion',
      'phase_label': '自由发言',
      'seats': <dynamic>[],
      'self': <String, dynamic>{},
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
          'can_send': true,
          'reason': '',
          'actions': <dynamic>[],
        },
      ],
      'public': <String, dynamic>{},
      'information': <dynamic>[],
      'result': null,
      'dialogs': dialogs,
    };

Map<String, dynamic> skillMessage({
  required bool withTarget,
  bool fake = false,
}) =>
    {
      'id': 11,
      'kind': 'alert',
      'channel_id': 'public',
      'sender_id': 'host',
      'sender_name': '主持人',
      'avatar_role_id': 'host',
      'text': '3号声明发动「宣布爱上或移情」，该技能不可质疑。',
      'created_at': '2026-09-26T02:00:00+00:00',
      'payload': {
        'type': 'skill',
        'ability': 'love',
        'ability_name': '爱上/移情',
        'role_id': 'marg',
        'role_name': '玛格',
        'intro': '白天可宣布爱上一人或移情（从当天夜里开始生效）。',
        'seat_id': '3',
        'actor_participant_id': 'p3',
        'actor_name': 'kiwi',
        'challengeable': false,
        'target_public': false,
        if (withTarget) 'target': {'seat_id': '5', 'name': '庭雨'},
        if (fake) 'fake': true,
      },
    };

GameMessage plainNotice() => GameMessage.fromJson({
      'id': 12,
      'kind': 'notice',
      'channel_id': 'public',
      'text': '第2夜是平安夜。',
      'created_at': '2026-09-26T02:00:00+00:00',
    });

Future<GameStore> storeWith(
  List<GameMessage> messages, {
  List<dynamic> dialogs = const [],
}) async {
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
    view: GameView.fromJson(viewJson(dialogs: dialogs)),
    gameId: 'game-skill',
    messages: messages,
    roles: [
      RoleInfo.fromJson({
        'id': 'marg',
        'name': '玛格',
        'normal': '白天可宣布爱上一人或移情；每夜令爱人席当前牌负伤一次。',
        'witch': '无额外魔女化技能；魔女可独立使用魔女刀。',
      }),
    ],
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
  testWidgets('技能播报渲染头像卡与技能名，点击打开技能详细', (tester) async {
    final store = await storeWith([
      GameMessage.fromJson(skillMessage(withTarget: true)),
    ]);
    await pumpShell(tester, store);

    expect(find.text('爱上/移情'), findsOneWidget);
    expect(find.text('使用技能'), findsOneWidget);
    expect(find.text('3号 kiwi'), findsOneWidget);
    expect(find.text('→ 5号'), findsOneWidget);
    expect(find.text('点击查看技能详细'), findsOneWidget);
    // 原文本不再作为灰条出现：结构化载荷优先。
    expect(find.textContaining('声明发动'), findsNothing);
    // 头像必须是技能所属角色的立绘，而不是占位。
    final avatar = tester.widget<Image>(find.descendant(
      of: find.byType(SkillCastCard),
      matching: find.byType(Image),
    ));
    expect((avatar.image as AssetImage).assetName, 'assets/avatars/marg.png');

    await tester.tap(find.text('爱上/移情'));
    await tester.pumpAndSettle();
    expect(find.text('技能详情'), findsOneWidget);
    expect(find.textContaining('白天可宣布爱上一人或移情'), findsWidgets);
    expect(find.textContaining('使用者：3号 kiwi'), findsOneWidget);
    expect(find.textContaining('目标：5号'), findsOneWidget);
    expect(find.text('不可质疑'), findsWidgets);
  });

  testWidgets('目标不可见时卡片不显示目标', (tester) async {
    final store = await storeWith([
      GameMessage.fromJson(skillMessage(withTarget: false)),
    ]);
    await pumpShell(tester, store);
    expect(find.text('爱上/移情'), findsOneWidget);
    expect(find.textContaining('→'), findsNothing);
  });

  testWidgets('没有载荷的消息仍是原来的居中文本条', (tester) async {
    final store = await storeWith([plainNotice()]);
    await pumpShell(tester, store);
    expect(find.textContaining('第2夜是平安夜。'), findsOneWidget);
    expect(find.text('点击查看技能详细'), findsNothing);
  });
}
