import 'dart:io';

import 'package:clock/clock.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:seven_double_client/src/app_icons.dart';
import 'package:seven_double_client/src/design.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/picks.dart';
import 'package:seven_double_client/src/role_visuals.dart';
import 'package:seven_double_client/src/shell.dart';
import 'package:seven_double_client/src/store.dart';

/// 用真实界面渲染 golden 图：既能实际查看效果，也防止布局被改坏。

Map<String, dynamic> seatJson(
  String id, {
  required String name,
  required List<String> roles,
  bool alive = true,
  bool occupied = true,
}) =>
    {
      'id': id,
      'participant_id': occupied ? 'p$id' : null,
      'name': name,
      'avatar_role_id': roles.isEmpty ? null : roles.first,
      'previous_role_id': roles.length > 1 ? roles.last : null,
      'occupied': occupied,
      'ready': false,
      'alive': alive,
      'online': id == '1' || id == '3',
    };

Map<String, dynamic> cardJson(String id, String roleId, {bool alive = true}) =>
    {
      'id': id,
      'role_id': roleId,
      'alive': alive,
      'witch': false,
      'injured': false,
      'uses': <String, dynamic>{},
      'states': <String, dynamic>{},
    };

Map<String, dynamic> actionJson(
  String id,
  String short,
  String label, {
  String group = '流程',
  List<Map<String, dynamic>> fields = const [],
  bool danger = false,
}) =>
    {
      'id': id,
      'ui_version': 1,
      'short_label': short,
      'label': label,
      'description': '$label：这是完整说明文字，用来验证说明在弹窗中完整显示。',
      'group': group,
      'danger': danger,
      'payload': <String, dynamic>{},
      'fields': fields,
    };

List<Map<String, dynamic>> seatList() => [
      seatJson('1', name: '阿雪', roles: ['emma', 'coco']),
      seatJson('2', name: 'kiwi', roles: ['hiro', 'marg']),
      seatJson('3', name: '小满', roles: ['sherry', 'noah']),
      seatJson('4', name: '', roles: [], occupied: false),
      seatJson('5', name: '庭雨', roles: ['millia', 'annan'], alive: false),
      seatJson('6', name: '青岚', roles: ['arisa', 'leia']),
      seatJson('7', name: '临', roles: ['nanoka', 'honoka']),
    ];

Map<String, dynamic> playerViewJson() => {
      'ui_version': 1,
      'id': 'game-demo',
      'version': 12,
      'status': 'playing',
      'day': 2,
      'half': 'day',
      'phase': 'speech',
      'phase_label': '顺序发言',
      'deadline': null,
      'ready_count': 7,
      'seats': seatList(),
      'self': {
        'seat_id': '1',
        'cards': [cardJson('c1', 'emma'), cardJson('c2', 'coco')],
        'current_card_id': 'c1',
      },
      'actions': [
        actionJson('speech.done', '结束发言', '结束本轮发言'),
        actionJson(
          'day.skill',
          '技能',
          '声明白天技能',
          fields: [
            {
              'name': 'target',
              'label': '目标席位',
              'type': 'select',
              'required': true,
              'options': [
                {'value': '2', 'label': '2号 · kiwi（希罗）'},
                {'value': '3', 'label': '3号 · 小满（雪莉）'},
              ],
            },
          ],
        ),
        actionJson('day.challenge', '质疑', '质疑他人的技能声明'),
        actionJson('channel.create', '建私信', '创建一对一或多人私信', group: '私信'),
        actionJson('evidence.submit', '证物', '提交证物'),
      ],
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
        {
          'id': 'private:abc',
          'label': '私密 · 与主持人',
          'status': 'active',
          'creator_id': 'p1',
          'members': [
            {'id': 'p1', 'name': '阿雪', 'kind': 'player', 'seat_id': '1'},
            {'id': 'host', 'name': '主持人', 'kind': 'host', 'seat_id': null},
          ],
          'invited_ids': ['host'],
          'accepted_ids': ['p1', 'host'],
          'invitation': 'accepted',
          'can_send': true,
          'reason': '',
          'actions': [
            actionJson(
              'channel.end',
              '结束私信',
              '结束整个私信频道',
              group: '私信',
              danger: true,
            ),
          ],
        },
        {
          'id': 'system',
          'label': '系统与私密信息',
          'status': 'active',
          'creator_id': 'host',
          'members': <dynamic>[],
          'invited_ids': <dynamic>[],
          'accepted_ids': <dynamic>[],
          'invitation': 'none',
          'can_send': false,
          'reason': '系统信息只用于告知，不能在此发言',
          'actions': <dynamic>[],
        },
      ],
      'public': {
        'speaker': '1',
        'balloon': {'status': 'idle'},
        'votes': <String, dynamic>{},
      },
      'information': <dynamic>[],
      'result': null,
      'can_chat': true,
      'chat_reason': '',
    };

Map<String, dynamic> hostViewJson() {
  final view = playerViewJson();
  // 主持人视角能看到全席双牌；夹具必须补上，否则选择器只能显示「?」。
  view['seats'] = [
    for (final seat in (view['seats'] as List).cast<Map<String, dynamic>>())
      {
        ...seat,
        if (seat['occupied'] == true)
          'cards': [
            cardJson('${seat['id']}-c0', seat['avatar_role_id'] as String),
            cardJson('${seat['id']}-c1', seat['previous_role_id'] as String),
          ],
        if (seat['occupied'] == true) 'current_card_id': '${seat['id']}-c0',
      },
  ];
  view['actions'] = [
    actionJson('host.advance', '推进', '完成当前阶段 / 推进'),
    actionJson('host.auto', '自动', '暂停自动推进'),
    actionJson('host.warn', '警告', '警告：30秒后结束该玩家操作'),
    actionJson('host.resolve', '裁定', '裁决待办', group: '私密管理', danger: true),
    actionJson(
      'host.codex',
      '魔典',
      '重新确认魔典名单并随机顺序',
      group: '开局',
      fields: [
        {
          'name': 'roles',
          'label': '11名魔典角色',
          'type': 'multiselect',
          'required': true,
          'min': 11,
          'max': 11,
          'options': [
            for (final role in roleVisuals)
              {'value': role.id, 'label': role.name},
          ],
        },
      ],
    ),
    actionJson(
      'host.water',
      '交水',
      '私下交付唯一13水',
      group: '私密管理',
      fields: [
        {
          'name': 'seat_id',
          'label': '持有者',
          'type': 'select',
          'required': true,
          'options': [
            {'value': '1', 'label': '1号 · 阿雪'},
            {'value': '2', 'label': '2号 · kiwi'},
          ],
        },
      ],
    ),
    actionJson('room.open_join', '关闭加入', '关闭开放参局', group: '房间管理'),
    actionJson(
      'room.kick',
      '移出',
      '移出参与者 / 本局拉黑',
      group: '房间管理',
      danger: true,
      fields: [
        {
          'name': 'participant_id',
          'label': '参与者',
          'type': 'select',
          'required': true,
          'options': [
            {'value': 'p1', 'label': '阿雪（1号）'},
            {'value': 'p2', 'label': 'kiwi（2号）'},
            {'value': 'p5', 'label': '庭雨（5号）'},
            {'value': 's1', 'label': '旁观（观战）'},
          ],
        },
        {
          'name': 'block',
          'label': '同时在本局拉黑',
          'type': 'checkbox',
          'required': false,
          'default': false,
        },
      ],
    ),
  ];
  view['host'] = {
    'codex': [for (final role in roleVisuals.take(11)) role.id],
    'tasks': [
      {
        'id': 'advance',
        'kind': 'advance',
        'title': '完成当前阶段 / 推进',
        'detail': '顺序发言：先处理上方待办，或等待玩家完成行动',
        'seats': <String>[],
        'action': 'host.advance',
        'payload': <String, dynamic>{},
        'blocking': false,
      },
      {
        'id': 'night:4',
        'kind': 'night',
        'title': '4号尚未确认夜间行动',
        'detail': '',
        'seats': ['4'],
        'action': 'host.warn',
        'payload': {'seat_id': '4'},
        'blocking': true,
      },
      {
        'id': 'winner',
        'kind': 'winner',
        'title': '已满足胜利条件，等待确认宣判',
        'detail': '好人达成热气球条件',
        'seats': <String>[],
        'action': 'host.confirm_winner',
        'payload': <String, dynamic>{},
        'blocking': true,
      },
    ],
    'pending': <dynamic>[],
    'warnings': <String, dynamic>{},
    'votes': <String, dynamic>{},
    'deaths': <String, dynamic>{},
    'nominations': <dynamic>[],
    'snapshots': <dynamic>[],
    'water': {'holder': null, 'used': false},
    'night_actions': <dynamic>[],
    'night_confirmed': <dynamic>[],
    'balloon_choices': <String, dynamic>{},
    'balloon_proposal': null,
    'brainwash': <String, dynamic>{},
    'spiritual': <String, dynamic>{},
    'declarations': <dynamic>[],
    'vote_rounds': <dynamic>[],
    'photos': <dynamic>[],
    'gaze': null,
    'execution_rolls': <dynamic>[],
    'nomination_done': <dynamic>[],
    'speech_passed': <dynamic>[],
    'surrenders': <dynamic>[],
    'winner_candidate': null,
  };
  return view;
}

/// 夹具时间基准：固定「现在」，让时间文本与 golden 都不随运行时刻变化。
/// 偏移都取同一天内的近几分钟，显示为 HH:mm。
final fixedNow = DateTime.utc(2026, 9, 15, 12, 0);

String stampAgo(int minutes) =>
    fixedNow.subtract(Duration(minutes: minutes)).toIso8601String();

List<GameMessage> messagesJson() => [
      GameMessage.fromJson({
        'id': 1,
        'kind': 'notice',
        'sender_name': '主持人',
        'avatar_role_id': 'host',
        'channel_id': 'public',
        'text': '新对局已创建，等待主持人开放参局',
        'created_at': stampAgo(5),
      }),
      GameMessage.fromJson({
        'id': 2,
        'kind': 'chat',
        'sender_id': 'p2',
        'sender_name': 'kiwi',
        'avatar_role_id': 'hiro',
        'channel_id': 'public',
        'text': '我先说说昨晚的情况，3 号的动作有点奇怪。',
        'created_at': stampAgo(4),
      }),
      GameMessage.fromJson({
        'id': 3,
        'kind': 'chat',
        'sender_id': 'p1',
        'sender_name': '阿雪',
        'avatar_role_id': 'emma',
        'channel_id': 'public',
        'text': '我这边没有可以证明的信息，先听大家说。',
        'created_at': stampAgo(3),
      }),
      GameMessage.fromJson({
        'id': 4,
        'kind': 'chat',
        'sender_id': 'p1',
        'sender_name': '阿雪',
        'avatar_role_id': 'emma',
        'channel_id': 'private:abc',
        'text': '（私信）主持人，我想私下确认一件事。',
        'created_at': stampAgo(2),
      }),
      GameMessage.fromJson({
        'id': 5,
        'kind': 'information',
        'sender_name': '主持人',
        'avatar_role_id': 'host',
        'channel_id': 'information',
        'text': '系统信息：你已获得一次额外的信息授权。',
        'created_at': stampAgo(1),
      }),
    ];

Actor actorJson({required bool host}) => Actor.fromJson(
      host
          ? {
              'id': 'host',
              'account_id': null,
              'kind': 'host',
              'game_id': 'game-demo',
              'seat_id': null,
              'name': '主持人',
              'access_ids': ['host'],
            }
          : {
              'id': 'p1',
              'account_id': 'a1',
              'kind': 'player',
              'game_id': 'game-demo',
              'seat_id': '1',
              'name': '阿雪',
              'qq_id': '10001',
              'avatar_url': null,
              'access_ids': ['p1'],
            },
    );

Future<GameStore> previewStore({required bool host}) async {
  SharedPreferences.setMockInitialValues({});
  final preferences = await SharedPreferences.getInstance();
  return GameStore.forPreview(
    preferences: preferences,
    endpoint: ServerEndpoint.parse('http://127.0.0.1:8000'),
    actor: actorJson(host: host),
    view: GameView.fromJson(host ? hostViewJson() : playerViewJson()),
    gameId: 'game-demo',
    messages: messagesJson(),
  );
}

Future<void> pumpAt(WidgetTester tester, GameStore store, Size size) async {
  await tester.binding.setSurfaceSize(size);
  tester.view.physicalSize = size;
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

/// 测试环境默认没有可用字形（中文与图标都会渲染成方框），这里显式加载内置字体与
/// Material 图标字体，否则 golden 图无法反映真实观感。
Future<void> loadBundledFonts() async {
  TestWidgetsFlutterBinding.ensureInitialized();
  for (final weight in const [400, 500, 700]) {
    final name = weight == 400
        ? 'Regular'
        : weight == 500
            ? 'Medium'
            : 'Bold';
    final bytes = await rootBundle.load(
      'assets/fonts/HarmonyOS_Sans_SC_$name.ttf',
    );
    final loader = FontLoader(kAppFontFamily)..addFont(Future.value(bytes));
    await loader.load();
  }
  // MaterialIcons 不在应用的资源清单里，直接从 Flutter SDK 读取。
  final root = Platform.environment['FLUTTER_ROOT'];
  final iconPaths = <String>[
    if (root != null)
      '$root/bin/cache/artifacts/material_fonts/materialicons-regular.otf',
    r'C:\src\flutter\bin\cache\artifacts\material_fonts\materialicons-regular.otf',
  ];
  for (final path in iconPaths) {
    final file = File(path);
    if (file.existsSync()) {
      final bytes = ByteData.view(file.readAsBytesSync().buffer);
      await (FontLoader('MaterialIcons')..addFont(Future.value(bytes))).load();
      break;
    }
  }
}

void main() {
  setUpAll(loadBundledFonts);

  testWidgets('玩家端对局页渲染', (tester) async {
    await withClock(Clock.fixed(fixedNow), () async {
      final store = await previewStore(host: false);
      await pumpAt(tester, store, const Size(420, 880));
      await expectLater(
        find.byType(GameShell),
        matchesGoldenFile('goldens/player_chat.png'),
      );

      await tester.tap(find.text('状态'));
      await tester.pump(const Duration(milliseconds: 600));
      await expectLater(
        find.byType(GameShell),
        matchesGoldenFile('goldens/player_board.png'),
      );

      await tester.tap(find.text('我的'));
      await tester.pump(const Duration(milliseconds: 600));
      await expectLater(
        find.byType(GameShell),
        matchesGoldenFile('goldens/player_profile.png'),
      );
    });
  });

  testWidgets('主持人端管理页渲染', (tester) async {
    await withClock(Clock.fixed(fixedNow), () async {
      final store = await previewStore(host: true);
      await pumpAt(tester, store, const Size(1280, 800));
      await expectLater(
        find.byType(GameShell),
        matchesGoldenFile('goldens/host_chat.png'),
      );

      await tester.tap(find.text('管理'));
      await tester.pump(const Duration(milliseconds: 600));
      await expectLater(
        find.byType(GameShell),
        matchesGoldenFile('goldens/host_manage.png'),
      );
    });
  });

  testWidgets('自绘选择界面渲染', (tester) async {
    final store = await previewStore(host: true);
    await pumpAt(tester, store, const Size(520, 900));

    final players = playersFromOptions(
      [
        {'value': 'p1', 'label': '阿雪（1号）'},
        {'value': 'p2', 'label': 'kiwi（2号）'},
        {'value': 'p5', 'label': '庭雨（5号）'},
        {'value': 's1', 'label': '旁观（观战）'},
      ],
      seats: store.view!.seats,
    );
    expect(players[0].seatId, '1', reason: '选项必须能关联到席位');
    expect(players[0].roleId, 'emma', reason: '选项必须能关联到角色');

    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: Scaffold(
          body: Center(
            child: Builder(
              builder: (context) => FilledButton(
                onPressed: () => showPlayerPicker(
                  context,
                  title: '参与者',
                  subtitle: '选择一名参与者',
                  players: players,
                  multi: true,
                ),
                child: const Text('打开'),
              ),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('打开'));
    await tester.pumpAndSettle();
    await expectLater(
      find.byType(MaterialApp),
      matchesGoldenFile('goldens/picker_players.png'),
    );
  });

  testWidgets('魔典选择界面渲染', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: Scaffold(
          body: Center(
            child: Builder(
              builder: (context) => FilledButton(
                onPressed: () => showCodexPicker(
                  context,
                  initial: [for (final role in roleVisuals.take(11)) role.id],
                  requiredCount: 11,
                ),
                child: const Text('打开'),
              ),
            ),
          ),
        ),
      ),
    );
    await tester.tap(find.text('打开'));
    await tester.pumpAndSettle();
    await expectLater(
      find.byType(MaterialApp),
      matchesGoldenFile('goldens/picker_codex.png'),
    );
  });

  testWidgets('行动图标全表渲染', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: Scaffold(
          body: SingleChildScrollView(
            padding: const EdgeInsets.all(16),
            child: Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final id in ActionIcons.covered)
                  Column(
                    children: [
                      ActionIconBadge(actionId: id),
                      SizedBox(
                        width: 76,
                        child: Text(id, style: const TextStyle(fontSize: 8)),
                      ),
                    ],
                  ),
              ],
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await expectLater(
      find.byType(MaterialApp),
      matchesGoldenFile('goldens/icon_gallery.png'),
    );
  });
}
