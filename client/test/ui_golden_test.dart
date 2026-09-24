import 'dart:io';

import 'package:clock/clock.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:seven_double_client/src/action_sheet.dart';
import 'package:seven_double_client/src/app_icons.dart';
import 'package:seven_double_client/src/design.dart';
import 'package:seven_double_client/src/emoji_picker.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/participant_menu.dart';
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
        'detail': '好人达成胜利条件',
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

/// 角色目录夹具：与后端 catalog 的字段一致（id/name/normal/witch）。
List<RoleInfo> catalogRoles() => [
      RoleInfo.fromJson({
        'id': 'emma',
        'name': '艾玛',
        'normal': '每个白天可打断一次他人发言；顺序发言时可改为最后发言。',
        'witch': '第三天或更晚时，夜里可杀死所有其他角色。',
      }),
      RoleInfo.fromJson({
        'id': 'hiro',
        'name': '希罗',
        'normal': '好人希罗即将死亡时，可回溯一次至前一天同一时点。',
        'witch': '魔女希罗另有一次回溯额度，保留自身魔女化。',
      }),
      RoleInfo.fromJson({
        'id': 'millia',
        'name': '米莉亚',
        'normal': '临死换牌：预结算一旦会出局就直接换上层牌重算。',
        'witch': '魔女化后额外获得一次换牌。',
      }),
    ];

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
    roles: catalogRoles(),
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

  testWidgets('催办框与新私密信息横幅渲染', (tester) async {
    await withClock(Clock.fixed(fixedNow), () async {
      final store = await previewStore(host: false);
      store.applyView(
        GameView.fromJson({
          ...playerViewJson(),
          'action_prompt': {
            'title': '请提交提名或放弃',
            'text': '同一人可以被多人提名；提交即生效。',
            'hint': '你正在私聊中：先结束私聊，才能执行上面的操作。',
          },
        }),
      );
      // 第一次只是定基线（登录/刷新不弹），第二次才是新到的私密信息。
      store.mergeMessagesForTest(messagesJson());
      store.mergeMessagesForTest([
        GameMessage.fromJson({
          'id': 99,
          'kind': 'information',
          'sender_name': '主持人',
          'avatar_role_id': 'host',
          'channel_id': 'information',
          'text': '四名疑似凶手：梅露露、汉娜、可可、诺亚。',
          'created_at': stampAgo(0),
        }),
      ]);
      await pumpAt(tester, store, const Size(420, 880));
      expect(find.text('请提交提名或放弃'), findsOneWidget);
      expect(find.textContaining('先结束私聊'), findsOneWidget);
      expect(find.text('新的私密信息'), findsOneWidget);
      await expectLater(
        find.byType(GameShell),
        matchesGoldenFile('goldens/player_action_prompt.png'),
      );
    });
  });

  testWidgets('主持人端管理页渲染', (tester) async {
    await withClock(Clock.fixed(fixedNow), () async {
      final store = await previewStore(host: true);
      // 宽屏改成同屏多栏、「管理」不再是底栏页签，单页 golden 用窄屏渲染；
      // 窗口仍要够高，让页尾的「席位代操作」入口也进入 golden。
      await pumpAt(tester, store, const Size(480, 1500));
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

  testWidgets('软键盘打开时对局页只留输入区', (tester) async {
    await withClock(Clock.fixed(fixedNow), () async {
      final store = await previewStore(host: false);
      await pumpAt(tester, store, const Size(420, 880));
      expect(find.byType(NavigationBar), findsOneWidget);
      expect(find.byType(FilterChip), findsWidgets);

      // 模拟软键盘弹出：物理像素与逻辑像素在 pumpAt 里是 1:1。
      tester.view.viewInsets = const FakeViewPadding(bottom: 320);
      await tester.pump(const Duration(milliseconds: 300));

      // 标题栏、筛选、快捷工具与底栏全部让位，只留消息与输入区。
      expect(find.byType(AppBar), findsNothing);
      expect(find.byType(NavigationBar), findsNothing);
      expect(find.byType(FilterChip), findsNothing);
      expect(find.byType(MessageBubble), findsWidgets, reason: '消息列表仍在');
      expect(find.byType(TextField), findsOneWidget);
      expect(find.text('公开讨论'), findsOneWidget, reason: '发送频道入口属于输入区');

      // 收起键盘后回到原来的完整布局。
      tester.view.viewInsets = FakeViewPadding.zero;
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.byType(AppBar), findsOneWidget);
      expect(find.byType(NavigationBar), findsOneWidget);
      expect(find.byType(FilterChip), findsWidgets);
    });
  });

  // 回归：键盘弹出会切到「只留输入区」布局。曾经这一支把 IndexedStack 换成
  // SafeArea(IndexedStack)，元素类型改变导致整棵子树重建，输入框 controller 与焦点
  // 一起被销毁——草稿被清空、键盘刚弹出又收起，在手机上根本没法输入。
  testWidgets('键盘弹出与收起都不清空输入框草稿', (tester) async {
    await withClock(Clock.fixed(fixedNow), () async {
      final store = await previewStore(host: false);
      await pumpAt(tester, store, const Size(420, 880));
      await tester.enterText(find.byType(TextField), '打了一半的草稿');
      await tester.pump();
      expect(find.text('打了一半的草稿'), findsOneWidget);

      tester.view.viewInsets = const FakeViewPadding(bottom: 320);
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.text('打了一半的草稿'), findsOneWidget, reason: '弹键盘不能清草稿');

      tester.view.viewInsets = FakeViewPadding.zero;
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.text('打了一半的草稿'), findsOneWidget, reason: '收键盘不能清草稿');
    });
  });

  // 表情面板：开面板、搜索点选把 token 插进输入框、再点一次收起。
  // 输入框内部始终是纯文本 token，所以发送格式与长度校验都不受影响。
  testWidgets('输入区的表情面板能展开并插入 token', (tester) async {
    await withClock(Clock.fixed(fixedNow), () async {
      final store = await previewStore(host: false);
      await pumpAt(tester, store, const Size(420, 880));
      expect(find.byType(EmojiPicker), findsNothing);

      await tester.tap(find.byIcon(Icons.emoji_emotions_outlined));
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.byType(EmojiPicker), findsOneWidget);
      // 面板占位与软键盘同权：标题栏、筛选与底栏一起让位，聊天区域才不被挤没。
      expect(find.byType(AppBar), findsNothing);
      expect(find.byType(NavigationBar), findsNothing);
      expect(find.byType(MessageBubble), findsWidgets, reason: '消息列表仍在');
      expect(find.text('公开讨论'), findsOneWidget, reason: '发送频道入口属于输入区');

      await tester.enterText(
        find.descendant(
          of: find.byType(EmojiPicker),
          matching: find.byType(TextField),
        ),
        '微笑',
      );
      await tester.pump();
      await tester.tap(find.descendant(
        of: find.byType(GridView),
        matching: find.byType(InkWell),
      ));
      await tester.pump();
      expect(find.text('[/微笑]'), findsOneWidget);
      // 富文本输入的实证：输入框内部把这个 token 真的画成了表情图，
      // 但 controller 里存的仍是纯文本。
      expect(
        find.descendant(
          of: find.byType(EditableText),
          matching: find.byType(Image),
        ),
        findsOneWidget,
      );

      // 收起面板后草稿内容不变，消息正文会把它画成表情图。
      await tester.tap(find.byIcon(Icons.emoji_emotions_outlined));
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.byType(EmojiPicker), findsNothing);
      expect(find.byType(AppBar), findsOneWidget, reason: '收起面板要恢复完整布局');
      expect(find.byType(NavigationBar), findsOneWidget);
      expect(find.text('[/微笑]'), findsOneWidget);
    });
  });

  // 顺序发言（speech.speak）就是多行字段：插入的表情必须自己写回表单值与草稿，
  // 因为程序改 controller 不触发 onChanged，否则提交的还是插入前的旧内容。
  testWidgets('行动表单的多行字段能插入表情并写回表单值', (tester) async {
    final store = await previewStore(host: false);
    final action = ActionDescriptor.fromJson({
      'id': 'speech.speak',
      'label': '提前写发言（轮到你时公开）',
      'short_label': '发言',
      'ui_version': 1,
      'fields': [
        {'name': 'text', 'label': '发言内容', 'type': 'textarea'},
      ],
    });
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: Scaffold(body: ActionFormSheet(store: store, action: action)),
      ),
    );
    await tester.pump();
    expect(find.widgetWithText(TextButton, '表情'), findsOneWidget);

    await tester.tap(find.widgetWithText(TextButton, '表情'));
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.byType(EmojiPicker), findsOneWidget);

    await tester.enterText(
      find.descendant(
        of: find.byType(EmojiPicker),
        matching: find.byType(TextField),
      ),
      '微笑',
    );
    await tester.pump();
    await tester.tap(find.descendant(
      of: find.byType(GridView),
      matching: find.byType(InkWell),
    ));
    await tester.pump();

    final field = tester.widget<TextFormField>(find.byType(TextFormField));
    expect(field.controller!.text, '[/微笑]');
    expect(store.draftFor(action)['text'], '[/微笑]', reason: '草稿要跟着更新');
  });

  testWidgets('屏幕够宽时同屏显示多个界面，窄屏仍是一次一页', (tester) async {
    await withClock(Clock.fixed(fixedNow), () async {
      // 电脑宽屏：状态、对局、管理三栏同屏，悬浮底栏不再出现。
      final desktop = await previewStore(host: true);
      await pumpAt(tester, desktop, const Size(1440, 1000));
      expect(find.byType(PaneFrame), findsNWidgets(3));
      expect(find.byType(NavigationBar), findsNothing);
      expect(find.byType(BoardPage).hitTestable(), findsOneWidget);
      expect(find.byType(ChatActionPage).hitTestable(), findsOneWidget);
      expect(find.byType(HostManagementPage).hitTestable(), findsOneWidget);
      await expectLater(
        find.byType(GameShell),
        matchesGoldenFile('goldens/wide_host_panes.png'),
      );

      // 平板横屏：状态与对局两栏，「我的/管理」收进右侧抽屉。
      final tablet = await previewStore(host: true);
      await pumpAt(tester, tablet, const Size(1024, 800));
      expect(find.byType(PaneFrame), findsNWidgets(2));
      expect(find.byType(NavigationBar), findsNothing);
      expect(find.byType(BoardPage).hitTestable(), findsOneWidget);
      expect(find.byType(ChatActionPage).hitTestable(), findsOneWidget);
      expect(find.byType(HostManagementPage), findsNothing);
      await expectLater(
        find.byType(GameShell),
        matchesGoldenFile('goldens/wide_host_tablet.png'),
      );

      await tester.tap(find.byTooltip('管理'));
      await tester.pumpAndSettle();
      expect(find.byType(HostManagementPage).hitTestable(), findsOneWidget);

      // 窄屏（手机/平板竖屏）保持单页加底栏，不强行塞多栏。
      final phone = await previewStore(host: false);
      await pumpAt(tester, phone, const Size(420, 880));
      expect(find.byType(PaneFrame), findsNothing);
      expect(find.byType(NavigationBar).hitTestable(), findsOneWidget);
      expect(find.byType(ProfilePage).hitTestable(), findsNothing);
      await tester.tap(find.text('我的'));
      await tester.pump(const Duration(milliseconds: 600));
      expect(find.byType(ProfilePage).hitTestable(), findsOneWidget);
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

  test('发送者 id 能解析出席位、角色与禁言状态', () async {
    final host = await previewStore(host: true);
    // 主持人视图能拿到参与者名单：p1 是 1 号，角色取当前上层牌。
    final first = participantRefFor(host, 'p1');
    expect(first, isNotNull);
    expect(first!.seatId, '1');
    expect(first.roleId, 'emma');
    expect(first.dead, isFalse);
    // p5 在夹具里已出局。
    final fifth = participantRefFor(host, 'p5');
    expect(fifth!.seatId, '5');
    expect(fifth.dead, isTrue);
    // 主持人自己。
    final hostRef = participantRefFor(host, 'host');
    expect(hostRef!.isHost, isTrue);
    // 未知发送者返回 null，不猜。
    expect(participantRefFor(host, 'nobody'), isNull);
    expect(participantRefFor(host, null), isNull);

    // 玩家视角没有参与者名单，但可用席位里的 participant_id 关联。
    final player = await previewStore(host: false);
    final mine = participantRefFor(player, 'p1');
    expect(mine, isNotNull);
    expect(mine!.seatId, '1');
  });

  testWidgets('头像菜单与角色详情渲染', (tester) async {
    final store = await previewStore(host: true);
    await pumpAt(tester, store, const Size(520, 900));
    final ref = participantRefFor(store, 'p2')!;

    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: Scaffold(
          body: Center(
            child: Builder(
              builder: (context) => FilledButton(
                onPressed: () => showAvatarMenu(context, store, ref),
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
      matchesGoldenFile('goldens/avatar_menu_host.png'),
    );

    // 角色详情：公开技能说明与状态。
    await tester.tap(find.text('查看角色技能与状态'));
    await tester.pumpAndSettle();
    await expectLater(
      find.byType(MaterialApp),
      matchesGoldenFile('goldens/role_detail.png'),
    );
  });

  testWidgets('下层牌登场介绍渲染', (tester) async {
    final store = await previewStore(host: false);
    await pumpAt(tester, store, const Size(520, 900));

    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: Scaffold(
          body: Center(
            child: Builder(
              builder: (context) => FilledButton(
                onPressed: () => showRoleIntro(context, store, 'millia'),
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
      matchesGoldenFile('goldens/role_intro.png'),
    );
  });
}
