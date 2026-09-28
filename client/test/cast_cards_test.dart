import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:seven_double_client/src/design.dart';
import 'package:seven_double_client/src/game_dialog.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/shell.dart';
import 'package:seven_double_client/src/store.dart';

/// 被动技能卡片与角色卡死亡卡片：两种新看板的渲染与「用哪张卡」的分派。
///
/// 载荷由服务端按收件人裁剪，客户端只负责按 mode/type 选样式：
/// 主动技能＝紫边「使用技能」，被动技能＝绿边「被动技能」＋本次结算结果，
/// 角色卡死亡＝红边「出局公告」＋公开头像与角色名。真实牌、死因与私密目标
/// 根本不会出现在载荷里，所以这里也没有可测的泄漏面。

Map<String, dynamic> viewJson() => {
      'ui_version': 1,
      'id': 'game-cast',
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
      'dialogs': <dynamic>[],
    };

/// 处决幻视：奈乃香的被动技能，结果只发给她本人。
Map<String, dynamic> passiveMessage() => {
      'id': 41,
      'kind': 'information',
      'channel_id': 'information',
      'sender_id': 'host',
      'sender_name': '主持人',
      'avatar_role_id': 'host',
      'text': '本日处决名单不含魔女。',
      'created_at': '2026-09-26T02:00:00+00:00',
      'payload': {
        'type': 'skill',
        'mode': 'passive',
        'ability': 'gaze',
        'ability_name': '处决幻视',
        'role_id': 'nanoka',
        'role_name': '奈乃香',
        'intro': '处决名单一定下来就自动幻视本日名单是否含魔女，结果只发给你；'
            '这是被动技能，不必也不能声明发动。',
        'effect': '本日处决名单不含魔女。',
        'effect_public': false,
        'seat_id': '7',
        'actor_participant_id': 'p7',
        'actor_name': 'kiwi',
        'challengeable': false,
        'target_public': false,
        'target': null,
      },
    };

Map<String, dynamic> deathMessage({
  List<Map<String, dynamic>>? deaths,
  String half = 'day',
}) =>
    {
      'id': 42,
      'kind': 'alert',
      'channel_id': 'public',
      'sender_id': 'host',
      'sender_name': '主持人',
      'avatar_role_id': 'host',
      'text': '3号 · 梅露露一张角色牌出局。',
      'created_at': '2026-09-26T02:01:00+00:00',
      'payload': {
        'type': 'death',
        'day': 2,
        'half': half,
        'deaths': deaths ??
            [
              {
                'seat_id': '3',
                'player_name': '庭雨',
                'avatar_role_id': 'meruru',
                'role_name': '梅露露',
                'water': false,
              },
            ],
      },
    };

Future<GameStore> storeWith(List<GameMessage> messages) async {
  SharedPreferences.setMockInitialValues({});
  final preferences = await SharedPreferences.getInstance();
  return GameStore.forPreview(
    preferences: preferences,
    endpoint: ServerEndpoint.parse('http://127.0.0.1:8000'),
    actor: Actor.fromJson({
      'id': 'p7',
      'kind': 'player',
      'name': 'kiwi',
      'seat_id': '7',
    }),
    view: GameView.fromJson(viewJson()),
    gameId: 'game-cast',
    messages: messages,
    roles: [
      RoleInfo.fromJson({
        'id': 'nanoka',
        'name': '奈乃香',
        'normal': '6颗子弹，仅在即将被处决时开枪；处决名单一定下来就自动幻视本日名单是否含魔女，'
            '结果只发给你（被动技能，不必也不能声明发动）。',
        'witch': '每夜获知全员当前魔女化状态。',
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
  testWidgets('被动技能渲染成被动卡片，并按公开头像取立绘', (tester) async {
    final store = await storeWith([GameMessage.fromJson(passiveMessage())]);
    await pumpShell(tester, store);

    expect(find.byType(SkillCastCard), findsOneWidget);
    expect(find.text('处决幻视'), findsOneWidget);
    expect(find.text('被动技能'), findsOneWidget);
    expect(find.text('被动'), findsOneWidget);
    expect(find.text('自动生效 · 不必也不能声明'), findsOneWidget);
    expect(find.text('本日处决名单不含魔女。'), findsOneWidget);
    // 被动技能没有声明与质疑入口，不能显示成主动技能。
    expect(find.text('使用技能'), findsNothing);
    expect(find.text('其他玩家可质疑'), findsNothing);
    expect(find.text('该技能不可质疑'), findsNothing);
    final avatar = tester.widget<Image>(find.descendant(
      of: find.byType(SkillCastCard),
      matching: find.byType(Image),
    ));
    expect((avatar.image as AssetImage).assetName, 'assets/avatars/nanoka.png');
  });

  testWidgets('被动卡片点开详情：无质疑标签，另列本次生效', (tester) async {
    final store = await storeWith([GameMessage.fromJson(passiveMessage())]);
    await pumpShell(tester, store);

    await tester.tap(find.text('处决幻视'));
    await tester.pumpAndSettle();
    expect(find.text('技能详情'), findsOneWidget);
    expect(find.text('被动技能'), findsWidgets);
    expect(find.text('本次生效'), findsOneWidget);
    expect(find.textContaining('本日处决名单不含魔女。'), findsWidgets);
    expect(find.text('可质疑'), findsNothing);
    expect(find.text('不可质疑'), findsNothing);
    expect(find.textContaining('被动技能由系统自动结算'), findsOneWidget);
  });

  testWidgets('角色卡死亡渲染成卡片，原始文本不再走灰条', (tester) async {
    final store = await storeWith([GameMessage.fromJson(deathMessage())]);
    await pumpShell(tester, store);

    expect(find.byType(DeathCastCard), findsOneWidget);
    expect(find.text('出局公告'), findsOneWidget);
    expect(find.text('3号 庭雨'), findsOneWidget);
    expect(find.text('梅露露'), findsOneWidget);
    expect(find.text('这张角色牌出局。'), findsOneWidget);
    expect(find.textContaining('梅露露一张角色牌出局。'), findsNothing);
    final avatar = tester.widget<Image>(find.descendant(
      of: find.byType(DeathCastCard),
      matching: find.byType(Image),
    ));
    expect((avatar.image as AssetImage).assetName, 'assets/avatars/meruru.png');
  });

  testWidgets('夜间多人出局合并成一张卡', (tester) async {
    final store = await storeWith([
      GameMessage.fromJson(
        deathMessage(
          half: 'night',
          deaths: [
            {
              'seat_id': '3',
              'player_name': '庭雨',
              'avatar_role_id': 'meruru',
              'role_name': '梅露露',
              'water': false,
            },
            {
              'seat_id': '5',
              'player_name': 'kiwi',
              'avatar_role_id': 'leia',
              'role_name': '蕾雅',
              'water': false,
            },
          ],
        ),
      ),
    ]);
    await pumpShell(tester, store);

    expect(find.byType(DeathCastCard), findsOneWidget);
    expect(find.text('第2夜 · 出局公告'), findsOneWidget);
    expect(find.text('3号 庭雨'), findsOneWidget);
    expect(find.text('5号 kiwi'), findsOneWidget);
    expect(find.text('这张角色牌出局。'), findsNWidgets(2));
  });

  testWidgets('13水毒杀的死亡卡片写明死因，隐藏死因时退回普通出局', (tester) async {
    final store = await storeWith([
      GameMessage.fromJson(
        deathMessage(
          deaths: [
            {
              'seat_id': '3',
              'player_name': '庭雨',
              'avatar_role_id': 'meruru',
              'role_name': '梅露露',
              'water': true,
            },
          ],
        ),
      ),
    ]);
    await pumpShell(tester, store);
    expect(find.text('这张角色牌被13水毒杀。'), findsOneWidget);

    final hidden = await storeWith([
      GameMessage.fromJson(deathMessage()),
    ]);
    await pumpShell(tester, hidden);
    expect(find.text('这张角色牌出局。'), findsOneWidget);
    expect(find.textContaining('13水'), findsNothing);
  });

  testWidgets('载荷为空时不画卡片，交回原来的文本条', (tester) async {
    final store = await storeWith([
      GameMessage.fromJson({
        'id': 43,
        'kind': 'notice',
        'channel_id': 'public',
        'text': '第2夜是平安夜。',
        'created_at': '2026-09-26T02:00:00+00:00',
      }),
    ]);
    await pumpShell(tester, store);
    expect(find.byType(DeathCastCard), findsNothing);
    expect(find.byType(SkillCastCard), findsNothing);
    expect(find.textContaining('第2夜是平安夜。'), findsOneWidget);
  });
}
