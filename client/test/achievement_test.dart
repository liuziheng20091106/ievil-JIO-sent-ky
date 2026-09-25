// 成就系统的客户端边界：
// 1. 稀有度 1-10 对应十种不同底色，越界值收敛到两端（服务端换了档位也不能崩）。
// 2. 成就接口的路径、方法与请求体（佩戴/取消佩戴、授权、撤销）。
// 3. 对局内昵称右边显示佩戴的成就徽章，没有佩戴就不显示。
//
// 成就的授权、撤销、排序等规则由后端 checks/test_achievements.py 守着；
// 这里只验证客户端的解码与呈现。
//
// 运行方式（client 目录）：flutter test test/achievement_test.dart

import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:seven_double_client/src/achievements.dart';
import 'package:seven_double_client/src/api.dart';
import 'package:seven_double_client/src/design.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/shell.dart';
import 'package:seven_double_client/src/store.dart';

Map<String, dynamic> definitionJson(int rarity, {String? id, String? name}) => {
      'id': id ?? 'ach-$rarity',
      'name': name ?? '成就$rarity',
      'detail': '内容$rarity',
      'rarity': rarity,
      'created_at': '2026-09-24T10:00:00',
      'updated_at': '2026-09-24T10:00:00',
      'granted_count': 1,
    };

Map<String, dynamic> grantJson(String id, int rarity, {String? name}) => {
      'id': id,
      'account_id': 'a1',
      'achievement_id': 'ach-$rarity',
      'name': name ?? '成就$rarity',
      'detail': '内容$rarity',
      'rarity': rarity,
      'granted_at': '2026-09-24T10:00:00',
    };

Map<String, dynamic> viewJson({List<String> participants = const []}) => {
      'ui_version': 1,
      'id': 'game-1',
      'version': 1,
      'status': 'playing',
      'day': 1,
      'half': 'day',
      'phase': 'speech',
      'phase_label': '顺序发言',
      'actions': <dynamic>[],
      'channels': <dynamic>[],
      'seats': [
        for (var index = 0; index < participants.length; index++)
          {
            'id': '${index + 1}',
            'participant_id': participants[index],
            'name': '玩家${index + 1}',
            'occupied': true,
            'alive': true,
          },
      ],
      'self': <String, dynamic>{},
      'public': <String, dynamic>{},
    };

Future<GameStore> previewStore() async {
  SharedPreferences.setMockInitialValues({});
  final preferences = await SharedPreferences.getInstance();
  return GameStore.forPreview(
    preferences: preferences,
    endpoint: ServerEndpoint.parse('http://127.0.0.1:8000'),
    actor: Actor.fromJson({
      'id': 'p1',
      'account_id': 'a1',
      'kind': 'player',
      'seat_id': '1',
      'name': '阿雪',
    }),
    view: GameView.fromJson(viewJson()),
  );
}

GameMessage chatMessage(String senderId, String senderName) =>
    GameMessage.fromJson({
      'id': 1,
      'kind': 'chat',
      'text': '我先说说昨晚的情况。',
      'channel_id': 'public',
      'sender_id': senderId,
      'sender_name': senderName,
      'created_at': '2026-09-24T10:00:00',
    });

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('稀有度色板', () {
    test('十档颜色互不相同，越界收敛到 1 与 10', () {
      final colors = [
        for (var value = 1; value <= achievementRarityMax; value++)
          AchievementRarity.of(value).background,
      ];
      expect(colors.toSet(), hasLength(achievementRarityMax));
      expect(AchievementRarity.of(0).background,
          AchievementRarity.of(1).background);
      expect(AchievementRarity.of(-3).background,
          AchievementRarity.of(1).background);
      expect(
        AchievementRarity.of(achievementRarityMax + 5).background,
        AchievementRarity.of(achievementRarityMax).background,
      );
      // 数字越大越稀有：最高档与最低档必须是不同的颜色。
      expect(
        AchievementRarity.of(achievementRarityMax).background,
        isNot(AchievementRarity.of(1).background),
      );
    });

    test('获得时间与参赛时间按本机时区显示，解析失败给空串', () {
      expect(achievementStamp('2026-09-24T12:34:56'), '2026-09-24');
      expect(achievementStamp('2026-09-24T12:34:56', withTime: true),
          '2026-09-24 12:34');
      expect(achievementStamp(''), '');
      expect(achievementStamp('不是时间'), '');
    });
  });

  group('成就接口', () {
    late HttpServer server;
    late ServerEndpoint endpoint;
    final calls = <String>[];
    final bodies = <String>[];
    HttpOverrides? savedOverrides;

    setUp(() async {
      calls.clear();
      bodies.clear();
      // flutter_test 默认把 HttpClient 换成「一律 400」的桩；这一组用真实
      // 回环服务器验证请求路径与解码，临时恢复真实 HttpClient。
      savedOverrides = HttpOverrides.current;
      HttpOverrides.global = null;
      server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      server.listen((request) async {
        calls.add('${request.method} ${request.uri.path}');
        final raw = request.method == 'POST'
            ? await utf8.decoder.bind(request).join()
            : '';
        if (raw.isNotEmpty) bodies.add(raw);
        final path = request.uri.path;
        Object payload;
        if (path == '/api/achievements/catalog') {
          payload = {
            'achievements': [definitionJson(2)],
            'max_rarity': 10,
          };
        } else if (path == '/api/achievements/me') {
          payload = {
            'achievements': [grantJson('grant-1', 2)],
            'equipped': null,
            'max_rarity': 10,
          };
        } else if (path == '/api/achievements/me/equip') {
          final grant = jsonDecode(raw)['grant_id']?.toString();
          payload = {
            'ok': true,
            'equipped': grant == null
                ? null
                : {'id': grant, 'name': '成就2', 'rarity': 2},
          };
        } else if (path == '/api/achievements/players') {
          payload = {
            'players': [
              {
                'account_id': 'a1',
                'name': '阿雪',
                'avatar_url': '',
                'last_played_at': '2026-09-24T12:00:00',
                'achievement_count': 1,
                'equipped': {'id': 'grant-1', 'name': '成就2', 'rarity': 2},
                'achievements': [grantJson('grant-1', 2)],
              },
              {
                'account_id': 'a2',
                'name': 'kiwi',
                'avatar_url': '',
                'last_played_at': null,
                'achievement_count': 0,
                'equipped': null,
                'achievements': <dynamic>[],
              },
            ],
            'max_rarity': 10,
          };
        } else if (path.startsWith('/api/achievements/accounts/')) {
          payload = {
            'account_id': 'a1',
            'name': '阿雪',
            'total': 7,
            'equipped': {'id': 'grant-1', 'name': '成就9', 'rarity': 9},
            'top': [
              for (var rarity = 9; rarity >= 5; rarity--)
                grantJson('g$rarity', rarity)
            ],
            'max_rarity': 10,
          };
        } else if (path.endsWith('/equipped')) {
          payload = {
            'participants': [
              {
                'participant_id': 'p1',
                'account_id': 'a1',
                'equipped': {'id': 'grant-1', 'name': '成就9', 'rarity': 9},
              },
              {'participant_id': 'p2', 'account_id': 'a2', 'equipped': null},
              // 主持人不是参与身份，但账号与它的玩家身份共用成就。
              {
                'participant_id': 'host',
                'account_id': 'a-host',
                'equipped': {'id': 'grant-host', 'name': '成就7', 'rarity': 7},
              },
            ],
          };
        } else if (path == '/api/achievements/defs') {
          payload = definitionJson(3, id: 'ach-new', name: '神秘黑幕女');
        } else if (path.startsWith('/api/achievements/defs/')) {
          payload = request.method == 'DELETE'
              ? {'ok': true, 'removed_grants': 2}
              : definitionJson(3, id: 'ach-new', name: '神秘黑幕女');
        } else {
          payload = grantJson('grant-new', 3, name: '神秘黑幕女');
        }
        request.response.statusCode = 200;
        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode(payload));
        await request.response.close();
      });
      endpoint = ServerEndpoint.parse('http://127.0.0.1:${server.port}');
    });

    tearDown(() async {
      await server.close(force: true);
      HttpOverrides.global = savedOverrides;
    });

    test('目录、我的成就与佩戴/取消佩戴', () async {
      final api = GameApi(endpoint, token: 'token-abc');
      final catalog = await api.achievementCatalog();
      expect(catalog.single.name, '成就2');
      expect(catalog.single.rarity, 2);
      expect(catalog.single.grantedCount, 1);

      final mine = await api.myAchievements();
      expect(mine.achievements.single.id, 'grant-1');
      expect(mine.equipped, isNull);

      final equipped = await api.equipAchievement('grant-1');
      expect(equipped!.name, '成就2');
      expect(equipped.rarity, 2);
      expect(await api.equipAchievement(null), isNull);

      expect(
        calls,
        containsAll(<String>[
          'GET /api/achievements/catalog',
          'GET /api/achievements/me',
          'POST /api/achievements/me/equip',
        ]),
      );
      expect(bodies, contains('{"grant_id":"grant-1"}'));
      expect(bodies, contains('{"grant_id":null}'));
    });

    test('玩家列表、摘要与本局佩戴映射', () async {
      final api = GameApi(endpoint, token: 'token-abc');
      final players = await api.achievementPlayers();
      expect(players.map((item) => item.name), ['阿雪', 'kiwi']);
      expect(players.first.equipped!.name, '成就2');
      expect(players.first.lastPlayedAt, '2026-09-24T12:00:00');
      expect(players.last.lastPlayedAt, isNull);
      expect(players.last.achievementCount, 0);

      final summary = await api.achievementSummary('a1');
      expect(summary.total, 7);
      expect(summary.top.map((item) => item.rarity), [9, 8, 7, 6, 5]);
      expect(summary.equipped!.rarity, 9);

      final equipped = await api.gameEquipped('game-1');
      expect(equipped, hasLength(3));
      expect(equipped.first.participantId, 'p1');
      expect(equipped.first.accountId, 'a1');
      expect(equipped.first.equipped!.name, '成就9');
      expect(equipped[1].equipped, isNull);
      // 主持人固定占最后一行，accountId 是它的 QQ 账号。
      expect(equipped.last.participantId, 'host');
      expect(equipped.last.equipped!.rarity, 7);
    });

    test('新建、编辑与删除定义，授权与撤销', () async {
      final api = GameApi(endpoint, token: 'token-abc');
      final created = await api.createAchievement(
        name: '神秘黑幕女',
        detail: '在一局内控制傀儡未被识破',
        rarity: 3,
      );
      expect(created.id, 'ach-new');
      expect(created.name, '神秘黑幕女');

      await api.updateAchievement(
        'ach-new',
        name: '神秘黑幕女',
        detail: '改了内容',
        rarity: 6,
      );
      expect(await api.deleteAchievement('ach-new'), 2);

      final granted = await api.grantAchievement('a1', 'ach-new');
      expect(granted.name, '神秘黑幕女');
      await api.revokeAchievement('grant-new');

      expect(
        calls,
        containsAll(<String>[
          'POST /api/achievements/defs',
          'POST /api/achievements/defs/ach-new',
          'DELETE /api/achievements/defs/ach-new',
          'POST /api/achievements/players/a1/grants',
          'DELETE /api/achievements/grants/grant-new',
        ]),
      );
      expect(
        bodies.first,
        '{"name":"神秘黑幕女","detail":"在一局内控制傀儡未被识破","rarity":3}',
      );
    });

    test('对局内佩戴信息写进 store，供昵称徽章使用', () async {
      final store = await previewStore();
      store.api = GameApi(endpoint, token: 'token-abc');
      store.gameId = 'game-1';
      await store.loadGameAchievements();
      expect(store.equippedFor('p1')!.name, '成就9');
      expect(store.equippedFor('p2'), isNull);
      expect(store.accountFor('p2'), 'a2');
      expect(store.accountFor('missing'), isNull);
      // 主持人的徽章也进 store：昵称旁显示，点头像能看同一个账号的成就摘要。
      expect(store.equippedFor('host')!.name, '成就7');
      expect(store.accountFor('host'), 'a-host');
    });

    test('没有玩家入席时也要为主持人拉一次佩戴信息', () async {
      final store = await previewStore();
      store.api = GameApi(endpoint, token: 'token-abc');
      store.gameId = 'game-1';
      calls.clear();

      // 空席对局：参与身份为空，但主持人固定占 "host"，所以仍然要拉一次。
      store.applyView(GameView.fromJson(viewJson()));
      await Future<void>.delayed(const Duration(milliseconds: 60));
      expect(calls.where((item) => item.endsWith('/equipped')), hasLength(1));
      expect(store.equippedFor('host')!.name, '成就7');
    });

    test('参与身份变化才补拉佩戴信息，候场期间后入席的玩家也有徽章', () async {
      final store = await previewStore();
      store.api = GameApi(endpoint, token: 'token-abc');
      store.gameId = 'game-1';
      calls.clear();

      List<String> equippedCalls() =>
          calls.where((item) => item.endsWith('/equipped')).toList();

      store.applyView(GameView.fromJson(viewJson(participants: ['p1'])));
      await Future<void>.delayed(const Duration(milliseconds: 60));
      expect(equippedCalls(), hasLength(1));

      // 同一批参与身份不重复请求。
      store.applyView(GameView.fromJson(viewJson(participants: ['p1'])));
      await Future<void>.delayed(const Duration(milliseconds: 60));
      expect(equippedCalls(), hasLength(1));

      // 有人新入席：再拉一次，新玩家的佩戴徽章才显示得出来。
      store.applyView(
        GameView.fromJson(viewJson(participants: ['p1', 'p2'])),
      );
      await Future<void>.delayed(const Duration(milliseconds: 60));
      expect(equippedCalls(), hasLength(2));
    });
  });

  group('成就徽章', () {
    testWidgets('徽章用稀有度底色显示成就名', (tester) async {
      await tester.pumpWidget(MaterialApp(
        theme: buildAppTheme(),
        home: const Scaffold(
          body: Center(child: AchievementBadge(name: '神秘黑幕女', rarity: 7)),
        ),
      ));
      expect(find.text('神秘黑幕女'), findsOneWidget);
      final container = tester
          .widgetList<Container>(
            find.ancestor(
              of: find.text('神秘黑幕女'),
              matching: find.byType(Container),
            ),
          )
          .first;
      expect(
        (container.decoration as BoxDecoration).color,
        AchievementRarity.of(7).background,
        reason: '徽章底色必须来自稀有度色板',
      );
    });

    testWidgets('对局内昵称右边显示佩戴的成就', (tester) async {
      final store = await previewStore();
      store.equippedAchievements = {
        'p1': EquippedAchievement.fromJson(
          {'id': 'grant-1', 'name': '神秘黑幕女', 'rarity': 9},
        ),
      };
      await tester.pumpWidget(MaterialApp(
        theme: buildAppTheme(),
        home: Scaffold(
          body: MessageBubble(
            message: chatMessage('p1', '阿雪'),
            self: 'p9',
            store: store,
          ),
        ),
      ));
      expect(find.text('阿雪'), findsOneWidget);
      expect(find.text('神秘黑幕女'), findsOneWidget);

      // 没有佩戴成就的发送者不显示徽章。
      await tester.pumpWidget(MaterialApp(
        theme: buildAppTheme(),
        home: Scaffold(
          body: MessageBubble(
            message: chatMessage('p2', 'kiwi'),
            self: 'p9',
            store: store,
          ),
        ),
      ));
      expect(find.text('kiwi'), findsOneWidget);
      expect(find.text('神秘黑幕女'), findsNothing);
    });
  });
}
