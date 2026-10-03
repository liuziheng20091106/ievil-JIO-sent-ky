// 成就系统的客户端边界：色板、优先展示上限与失败恢复、稀有度文案、消息徽章。
//
// 成就的授权、撤销、排序等规则由后端 checks/test_achievements.py 守着；
// 这里只验证客户端的解码与呈现。
//
// 运行方式（client 目录）：flutter test test/achievement_test.dart

import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:seven_double_client/src/achievement_pages.dart';
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
    HttpOverrides? savedOverrides;
    var myRarities = <int>[2];
    var priorityGrantIds = <String>[];
    var rejectPriority = false;

    setUp(() async {
      calls.clear();
      myRarities = [2];
      priorityGrantIds = [];
      rejectPriority = false;
      // flutter_test 默认替换 HttpClient；这里用真实回环请求驱动页面状态。
      savedOverrides = HttpOverrides.current;
      HttpOverrides.global = null;
      server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      server.listen((request) async {
        calls.add('${request.method} ${request.uri.path}');
        final raw = request.method == 'POST'
            ? await utf8.decoder.bind(request).join()
            : '';
        final path = request.uri.path;
        Object payload;
        if (path == '/api/achievements/catalog') {
          payload = {
            // 两个定义：ach-2 已授权给 a1，ach-5 还没有——一览必须把两个都列出来。
            'achievements': [definitionJson(2), definitionJson(5)],
            'max_rarity': 10,
          };
        } else if (path == '/api/achievements/me') {
          payload = {
            'achievements': [
              for (final rarity in myRarities) grantJson('g$rarity', rarity),
            ],
            'equipped': null,
            'priority_grant_ids': priorityGrantIds,
            'max_rarity': 10,
          };
        } else if (path == '/api/achievements/me/priority') {
          if (rejectPriority) {
            request.response.statusCode = 403;
            request.response.headers.contentType = ContentType.json;
            request.response.write(jsonEncode({'detail': '成就授权已撤销'}));
            await request.response.close();
            return;
          }
          priorityGrantIds = List<String>.from(jsonDecode(raw)['grant_ids']);
          payload = {'ok': true, 'priority_grant_ids': priorityGrantIds};
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
        } else {
          request.response.statusCode = 404;
          await request.response.close();
          return;
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

    testWidgets('优先展示选满后禁选第六个，取消后可选；保存失败保留原选择', (tester) async {
      myRarities = [1, 2, 3, 4, 5, 6];
      final store = await previewStore();
      store.api = GameApi(endpoint, token: 'token-abc');
      await tester.binding.setSurfaceSize(const Size(800, 1800));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      await tester.runAsync(() async {
        await tester.pumpWidget(MaterialApp(
          theme: buildAppTheme(),
          home: MyAchievementsPage(store: store),
        ));
        await Future<void>.delayed(const Duration(milliseconds: 100));
      });
      await tester.pump();

      Future<void> choose(int index) async {
        await tester.runAsync(() async {
          await tester.tap(find.byType(CheckboxListTile).at(index));
          await Future<void>.delayed(const Duration(milliseconds: 100));
        });
        await tester.pump();
      }

      for (var index = 0; index < 5; index++) {
        await choose(index);
      }
      CheckboxListTile choice(int index) =>
          tester.widget(find.byType(CheckboxListTile).at(index));
      expect(choice(5).onChanged, isNull);
      expect(choice(0).onChanged, isNotNull);
      expect(find.text('优先展示 5/5'), findsOneWidget);

      await choose(0);
      expect(choice(5).onChanged, isNotNull);
      rejectPriority = true;
      await choose(5);
      expect(choice(5).value, isFalse);
      expect(find.text('优先展示 4/5'), findsOneWidget);
      expect(find.text('成就授权已撤销'), findsOneWidget);

      rejectPriority = false;
      await choose(5);
      expect(choice(5).value, isTrue);
      expect(choice(0).onChanged, isNull);
      await tester.pumpWidget(const SizedBox.shrink());
      store.dispose();
    });

    testWidgets('玩家的已获得与未获得高等级成就只显示特殊或专属', (tester) async {
      myRarities = [5, 6, 7, 8, 9, 10];
      final store = await previewStore();
      store.api = GameApi(endpoint, token: 'token-abc');
      await tester.binding.setSurfaceSize(const Size(800, 1800));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      await tester.runAsync(() async {
        await tester.pumpWidget(MaterialApp(
          theme: buildAppTheme(),
          home: MyAchievementsPage(store: store),
        ));
        await Future<void>.delayed(const Duration(milliseconds: 100));
      });
      await tester.pump();
      expect(find.text('特殊'), findsNWidgets(5));
      expect(find.text('专属'), findsNWidgets(2));
      for (var rarity = 5; rarity <= 10; rarity++) {
        expect(find.text('稀有度 $rarity'), findsNothing);
      }
      expect(find.text('稀有度 2'), findsOneWidget);
      await tester.pumpWidget(const SizedBox.shrink());
      store.dispose();
    });
  });

  group('成就徽章', () {
    testWidgets('明亮底色保持白字轮廓，青银金反光可关闭和恢复', (tester) async {
      final keys = [for (var value = 1; value <= 10; value++) GlobalKey()];
      const animatedRarities = {4, 9, 10};
      Future<void> mount({bool reduceMotion = false}) =>
          tester.pumpWidget(MaterialApp(
            theme: buildAppTheme(),
            home: MediaQuery(
              data: MediaQueryData(disableAnimations: reduceMotion),
              child: Scaffold(
                body: Column(
                  children: [
                    for (var index = 0; index < keys.length; index++)
                      RepaintBoundary(
                        key: keys[index],
                        child: AchievementBadge(
                          name: 'M',
                          rarity: index + 1,
                        ),
                      ),
                  ],
                ),
              ),
            ),
          ));
      Future<List<int>> pixels(GlobalKey key) async {
        final boundary =
            key.currentContext!.findRenderObject()! as RenderRepaintBoundary;
        final image = await boundary.toImage();
        final data = await image.toByteData();
        image.dispose();
        return data!.buffer.asUint8List(data.offsetInBytes, data.lengthInBytes);
      }

      Future<List<List<int>>> snapshot() async => [
            for (final key in keys) (await tester.runAsync(() => pixels(key)))!,
          ];

      await mount();
      final before = await snapshot();
      for (var index = 0; index < keys.length; index++) {
        final boundary = keys[index].currentContext!.findRenderObject()!
            as RenderRepaintBoundary;
        final width = boundary.size.width.ceil();
        final height = boundary.size.height.ceil();
        var whiteInk = false;
        var outlineLuminance = 1.0;
        // 包含文字周围的轮廓，但避开青银金徽章的亮色边框。
        for (var y = 3; y < height - 3; y++) {
          for (var x = 8; x < width - 8; x++) {
            final offset = (y * width + x) * 4;
            final red = before[index][offset];
            final green = before[index][offset + 1];
            final blue = before[index][offset + 2];
            whiteInk |= red >= 245 && green >= 245 && blue >= 245;
            final luminance =
                Color.fromARGB(255, red, green, blue).computeLuminance();
            if (luminance < outlineLuminance) outlineLuminance = luminance;
          }
        }
        expect(whiteInk, isTrue, reason: '第 ${index + 1} 档名称必须是白字');
        expect(1.05 / (outlineLuminance + .05), greaterThanOrEqualTo(4.5),
            reason: '第 ${index + 1} 档明亮底色上的白字必须有可读轮廓');
      }
      await tester.pump(const Duration(milliseconds: 800));
      final moving = await snapshot();
      for (var index = 0; index < keys.length; index++) {
        expect(
          moving[index],
          animatedRarities.contains(index + 1)
              ? isNot(orderedEquals(before[index]))
              : orderedEquals(before[index]),
          reason: '只有青、银、金三档有反光',
        );
      }

      await mount(reduceMotion: true);
      final still = await snapshot();
      await tester.pump(const Duration(milliseconds: 800));
      final disabled = await snapshot();
      for (var index = 0; index < keys.length; index++) {
        expect(disabled[index], orderedEquals(still[index]));
      }
      expect(tester.binding.hasScheduledFrame, isFalse);

      await mount();
      await tester.pump(const Duration(milliseconds: 800));
      final resumed = await snapshot();
      for (final rarity in animatedRarities) {
        expect(resumed[rarity - 1], isNot(orderedEquals(still[rarity - 1])));
      }
      await tester.pumpWidget(const SizedBox.shrink());
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
