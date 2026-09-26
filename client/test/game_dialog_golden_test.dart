import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/shell.dart';
import 'package:seven_double_client/src/store.dart';

import 'golden_harness.dart';

/// 技能播报卡与悬浮对话框的 golden：这两块是本轮新增的主要视觉，
/// 用真实界面渲染出来既方便肉眼确认，也防止后续布局被改坏。

Map<String, dynamic> action(String id, String short, String label) => {
      'id': id,
      'ui_version': 1,
      'short_label': short,
      'label': label,
      'description': '$label。',
      'group': '私信',
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
        action('channel.reject', '拒绝', '拒绝加入并取消本次私信'),
      ],
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

Map<String, dynamic> skillMessage() => {
      'id': 21,
      'kind': 'alert',
      'channel_id': 'public',
      'sender_id': 'host',
      'sender_name': '主持人',
      'avatar_role_id': 'host',
      'text': '4号声明发动「宣布爱上或移情」，该技能不可质疑。',
      'created_at': '2026-09-26T02:00:00+00:00',
      'payload': {
        'type': 'skill',
        'ability': 'love',
        'ability_name': '爱上/移情',
        'role_id': 'marg',
        'role_name': '玛格',
        'intro': '白天可宣布爱上一人或移情（从当天夜里开始生效）。',
        'seat_id': '4',
        'actor_participant_id': 'p4',
        'actor_name': '庭雨',
        'challengeable': false,
        'target_public': false,
        'target': {'seat_id': '2', 'name': 'kiwi'},
      },
    };

Map<String, dynamic> noticeMessage() => {
      'id': 22,
      'kind': 'alert',
      'channel_id': 'public',
      'sender_name': '主持人',
      'avatar_role_id': 'host',
      'text': '第2夜：2号玩家一张角色牌出局。',
      'created_at': '2026-09-26T02:01:00+00:00',
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

Future<GameStore> store({
  List<GameMessage> messages = const [],
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
    view: GameView.fromJson(viewJson(dialogs)),
    gameId: 'game-dialog',
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

Future<void> pumpAt(WidgetTester tester, GameStore value) => pumpPhone(
      tester,
      GameShell(store: value),
    );

void main() {
  setUpAll(loadBundledFonts);

  testWidgets('技能播报卡片渲染', (tester) async {
    final value = await store(
      messages: [
        GameMessage.fromJson(noticeMessage()),
        GameMessage.fromJson(skillMessage()),
      ],
    );
    await pumpAt(tester, value);
    expect(find.text('爱上/移情'), findsOneWidget);
    await expectLater(
      find.byType(GameShell),
      matchesGoldenFile('goldens/player_skill_cast.png'),
    );
  });

  testWidgets('私聊申请悬浮对话框渲染', (tester) async {
    final value = await store(dialogs: [inviteDialog()]);
    await pumpAt(tester, value);
    expect(find.text('私聊申请'), findsOneWidget);
    await expectLater(
      find.byType(GameShell),
      matchesGoldenFile('goldens/player_dialog_invite.png'),
    );
  });

  testWidgets('对局结束悬浮对话框渲染', (tester) async {
    final value = await store(dialogs: [resultDialog()]);
    await pumpAt(tester, value);
    expect(find.text('本局已结束 · 好人获胜'), findsOneWidget);
    await expectLater(
      find.byType(GameShell),
      matchesGoldenFile('goldens/player_dialog_result.png'),
    );
  });
}
