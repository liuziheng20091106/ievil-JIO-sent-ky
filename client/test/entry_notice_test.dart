// 回归检查：两条「主动提醒」的判定边界。
//
// 1. 自己当前的下层牌换人就弹一次角色卡介绍；首次同步只记基线，
//    否则每次刷新/重连都会刷一个介绍窗口。
// 2. 只有这次刷新新到的对局邀请才发系统通知；登录后已堆着的旧邀请不重复提醒。
//
// 运行方式（client 目录）：flutter test test/entry_notice_test.dart

import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/store.dart';
import 'package:shared_preferences/shared_preferences.dart';

const endpoint = 'http://127.0.0.1';

Map<String, dynamic> viewJson({
  required Object? currentCardId,
  List<Map<String, dynamic>> cards = const [],
}) =>
    {
      'ui_version': 1,
      'id': 'game-1',
      'version': 3,
      'status': 'playing',
      'day': 1,
      'half': 'day',
      'phase': 'speech',
      'phase_label': '顺序发言',
      'deadline': null,
      'ready_count': 0,
      'actions': <dynamic>[],
      'channels': <dynamic>[],
      'seats': <dynamic>[],
      'self': {
        'cards': cards,
        'current_card_id': currentCardId,
        'warning_deadline': null,
      },
      'public': <String, dynamic>{},
    };

Future<GameStore> previewStore() async {
  SharedPreferences.setMockInitialValues({});
  final preferences = await SharedPreferences.getInstance();
  return GameStore.forPreview(
    preferences: preferences,
    endpoint: ServerEndpoint.parse(endpoint),
    actor: Actor.fromJson({
      'id': 'p1',
      'account_id': 'a1',
      'kind': 'player',
      'game_id': 'game-1',
      'seat_id': '1',
      'name': '阿雪',
    }),
    view: GameView.fromJson(viewJson(currentCardId: null)),
    gameId: 'game-1',
    secureStorage: const FlutterSecureStorage(),
  );
}

LobbyInvite invite(String id, String from) => LobbyInvite.fromJson({
      'id': id,
      'game_id': 'game-1',
      'from_name': from,
    });

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('角色登场介绍', () {
    test('首次同步只记基线，之后换牌才弹出新角色的介绍', () async {
      final store = await previewStore();
      final cards = [
        {'id': 'c-1', 'role_id': 'emma', 'alive': true},
        {'id': 'c-2', 'role_id': 'millia', 'alive': true},
      ];

      store.applyView(GameView.fromJson(viewJson(
        currentCardId: 'c-1',
        cards: cards,
      )));
      expect(
        store.pendingRoleId,
        isNull,
        reason: '刷新/重连时已有角色不该再弹一次介绍',
      );

      // 只换了私密内容（如剩余次数），当前牌没变：同样不弹。
      store.applyView(GameView.fromJson(viewJson(
        currentCardId: 'c-1',
        cards: cards,
      )));
      expect(store.pendingRoleId, isNull);

      // 下层登场：current_card_id 换到第二张牌，弹出该角色。
      store.applyView(GameView.fromJson(viewJson(
        currentCardId: 'c-2',
        cards: cards,
      )));
      expect(store.pendingRoleId, 'millia');

      // 介绍由界面取走一次后不再重播。
      store.pendingRoleId = null;
      store.applyView(GameView.fromJson(viewJson(
        currentCardId: 'c-2',
        cards: cards,
      )));
      expect(store.pendingRoleId, isNull);
    });

    test('发牌只是第一次看到当前牌，不额外弹一次介绍', () async {
      final store = await previewStore();
      // 候场与发牌是两次状态自动同步，发牌时玩家正在决定上下牌，
      // 不该被介绍窗口盖住；真正的登场发生在之后 current_card_id 变化时。
      store.applyView(GameView.fromJson(viewJson(currentCardId: null)));
      store.applyView(GameView.fromJson(viewJson(
        currentCardId: 'c-1',
        cards: [
          {'id': 'c-1', 'role_id': 'hiro', 'alive': true},
        ],
      )));
      expect(store.pendingRoleId, isNull);

      // 调序把这张牌换下去（下层登场）才弹。
      store.applyView(GameView.fromJson(viewJson(
        currentCardId: 'c-2',
        cards: [
          {'id': 'c-1', 'role_id': 'hiro', 'alive': true},
          {'id': 'c-2', 'role_id': 'emma', 'alive': true},
        ],
      )));
      expect(store.pendingRoleId, 'emma');
    });

    test('登出后重登的首次同步只记基线，不补弹旧角色的介绍', () async {
      final store = await previewStore();
      await store.logout();
      store.applyView(GameView.fromJson(viewJson(
        currentCardId: 'c-1',
        cards: [
          {'id': 'c-1', 'role_id': 'hiro', 'alive': true},
        ],
      )));
      expect(store.pendingRoleId, isNull);
    });

    test('离开大厅后基线清零，重新进入不沿用上一局', () async {
      final store = await previewStore();
      final cards = [
        {'id': 'c-1', 'role_id': 'emma', 'alive': true},
      ];
      store.applyView(GameView.fromJson(viewJson(
        currentCardId: 'c-1',
        cards: cards,
      )));
      await store.returnToLobby();
      expect(store.pendingRoleId, isNull);
    });
  });

  group('新邀请提醒', () {
    test('第一次刷新只记基线，之后新到的邀请才提醒', () {
      final first = invite('i-1', '阿雪');
      final second = invite('i-2', '小雫');

      expect(freshInvites(null, [first]), isEmpty, reason: '登录时已有的邀请不重复提醒');
      expect(freshInvites({'i-1'}, [first]), isEmpty);
      expect(
        [for (final item in freshInvites({'i-1'}, [first, second])) item.id],
        ['i-2'],
      );
      expect(
        [for (final item in freshInvites({}, [first, second])) item.id],
        ['i-1', 'i-2'],
      );
    });
  });
}
