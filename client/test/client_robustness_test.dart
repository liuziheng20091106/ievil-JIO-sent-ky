// 回归检查：客户端可靠性修复（与 6e98562 团队审查发现的修复配套）。
//
// 覆盖四个真实边界：
// 1. 实时连接握手被服务器拒绝（401/403）时必须停止重连——
//    身份类失败重试多少次都一样，无限退避只会让客户端永远空转。
// 2. 一帧损坏的事件不允许杀掉整条实时连接——否则一次畸形数据就造成
//    无感知的断连-重连循环。
// 3. 登出与离开对局必须清掉本机残留的明文草稿与已读游标——
//    私密草稿（发言预提交、夜间目标、手绘）不允许在 shared_preferences
//    （Windows 上是漫游目录）里永久累积。
// 4. GameStore.create() 的恢复路径不允许向 main() 抛异常——
//    否则应用启动即白屏退出且无法自愈。
//
// 运行方式（client 目录）：flutter test test/client_robustness_test.dart

import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:seven_double_client/src/api.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/store.dart';
import 'package:shared_preferences/shared_preferences.dart';

const endpoint = 'http://127.0.0.1';

Actor playerActor() => Actor.fromJson({
      'id': 'p1',
      'account_id': 'a1',
      'kind': 'player',
      'game_id': 'game-1',
      'seat_id': '1',
      'name': '阿雪',
      'qq_id': '10001',
      'avatar_url': null,
      'access_ids': ['p1'],
    });

Map<String, dynamic> playingViewJson() => {
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
        'cards': <dynamic>[],
        'current_card_id': null,
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
    actor: playerActor(),
    view: GameView.fromJson(playingViewJson()),
    gameId: 'game-1',
  );
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('LiveConnection', () {
    test('握手被 403 拒绝时停止重连，不再无限退避', () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      var attempts = 0;
      final statuses = <String>[];
      final subscription = server.listen((request) async {
        attempts++;
        await request.drain<void>();
        request.response.statusCode = 403;
        await request.response.close();
      });
      final connection = LiveConnection(
        endpoint: ServerEndpoint.parse('http://127.0.0.1:${server.port}'),
        token: 'token-abc',
        onEvent: (_) {},
        onConnected: () async {},
        onStatus: statuses.add,
      )..start();
      // 足够跑完两轮退避（1s + 2s）：如果还在重连，attempts 会超过 1。
      await Future<void>.delayed(const Duration(milliseconds: 4200));
      await connection.stop();
      await subscription.cancel();
      await server.close(force: true);
      expect(attempts, 1, reason: '身份类拒绝不应该重试');
      expect(statuses, contains('连接被服务器拒绝'));
    });

    test('一帧损坏的事件只丢这一帧，不杀掉连接', () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      final events = <Map<String, dynamic>>[];
      final statuses = <String>[];
      final received = Completer<void>();
      late StreamSubscription<HttpRequest> subscription;
      subscription = server.listen((request) async {
        final socket = await WebSocketTransformer.upgrade(request);
        socket.add('这条不是 JSON {{{');
        socket.add(jsonEncode({'type': 'sync', 'state': playingViewJson()}));
        await Future<void>.delayed(const Duration(milliseconds: 100));
        await socket.close();
      });
      final connection = LiveConnection(
        endpoint: ServerEndpoint.parse('http://127.0.0.1:${server.port}'),
        token: 'token-abc',
        onEvent: (event) {
          events.add(event);
          if (!received.isCompleted) received.complete();
        },
        onConnected: () async {},
        onStatus: statuses.add,
      )..start();
      await received.future.timeout(const Duration(seconds: 5));
      await connection.stop();
      await subscription.cancel();
      await server.close(force: true);
      // 毒帧被跳过，后续正常帧仍然送达。
      expect(events, isNotEmpty);
      expect(events.single['type'], 'sync');
      expect(statuses, isNot(contains('连接已中断')));
    });
  });

  group('本地草稿生命周期', () {
    test('登出清除该账号的明文草稿与已读游标', () async {
      final store = await previewStore();
      final preferences = await SharedPreferences.getInstance();
      final action = ActionDescriptor.fromJson({
        'id': 'speech.submit',
        'ui_version': 1,
        'short_label': '发言',
        'label': '提交发言',
        'payload': <String, dynamic>{},
        'fields': <dynamic>[],
      });
      await store.saveDraft(action, {'text': '夜里我是好人'});
      await preferences.setString(
          '$endpoint:game-1:a1:phase_seen', 'game-1:1:day:speech');
      await preferences.setInt('$endpoint:game-1:a1:messages_read_all', 9);
      // 另一个账号的草稿不能被误删。
      await preferences.setString(
          'draft:${jsonEncode([endpoint, 'game-1', 'a2', 'p2', 'speech.submit'])}',
          '{"text":"别人的草稿"}');

      await store.logout();

      expect(store.actor, isNull);
      expect(store.draftFor(action), isEmpty);
      expect(
        preferences.getString('$endpoint:game-1:a1:phase_seen'),
        isNull,
        reason: '登出后阶段已读基线不应残留',
      );
      expect(
        preferences.getInt('$endpoint:game-1:a1:messages_read_all'),
        isNull,
        reason: '登出后消息游标不应残留',
      );
      expect(
        preferences.getString(
            'draft:${jsonEncode([endpoint, 'game-1', 'a2', 'p2', 'speech.submit'])}'),
        isNotNull,
        reason: '其他账号的草稿必须保留',
      );
    });

    test('离开对局同样清掉本局草稿与角标残留', () async {
      final store = await previewStore();
      final preferences = await SharedPreferences.getInstance();
      final action = ActionDescriptor.fromJson({
        'id': 'speech.submit',
        'ui_version': 1,
        'short_label': '发言',
        'label': '提交发言',
        'payload': <String, dynamic>{},
        'fields': <dynamic>[],
      });
      await store.saveDraft(action, {'text': '还没发出去的发言'});
      store.newActionCount = 2;
      store.unreadMessageCount = 5;

      await store.returnToLobby();

      expect(store.gameId, isNull);
      expect(store.draftFor(action), isEmpty);
      expect(store.newActionCount, 0);
      expect(store.unreadMessageCount, 0);
      expect(preferences.getKeys().where((key) => key.startsWith('draft:')), isEmpty);
    });
  });

  group('启动恢复兜底', () {
    test('恢复路径的任何异常都不允许逃出 GameStore.create()', () async {
      SharedPreferences.setMockInitialValues({
        'server_endpoint': endpoint,
        'cached_actor': jsonEncode(playerActor().raw),
        'cached_game_id': 'game-1',
      });
      // 不设置令牌：secureStorage.read 正常返回 null。
      // 这里注入一个会把 me() 抛成非 ApiException 的假存储，
      // 模拟“服务器返回了客户端读不懂的形状”。
      final store = await GameStore.create(
        secureStorage: _BrokenSecureStorage(),
      );
      // 没有崩溃即通过；登录态可能不完整，但应用必须能起来。
      expect(store.restoring, isFalse);
    });
  });

  group('动作描述匹配与草稿隔离', () {
    ActionDescriptor descriptor(Map<String, dynamic> payload) =>
        ActionDescriptor.fromJson({
          'id': 'host.resolve',
          'ui_version': 1,
          'short_label': '裁定',
          'label': '裁定',
          'payload': payload,
          'fields': <dynamic>[],
        });

    test('多条同 id 待办按 payload 匹配各自的描述与草稿', () async {
      final store = await previewStore();
      final first = descriptor({'pending_id': 'p-1'});
      final second = descriptor({'pending_id': 'p-2'});
      final initial = {'pending_id': 'p-2', 'note': '目标B'};
      await store.saveDraft(second, {'note': '旧草稿'}, initial: initial);

      // 点 B 待办只能拿到 B 的草稿；A 待办与徒手打开（无预填）互不可见。
      expect(store.draftFor(second, initial: initial), {'note': '旧草稿'});
      expect(store.draftFor(first, initial: {'pending_id': 'p-1'}), isEmpty);
      expect(store.draftFor(first), isEmpty);

      // payload 不同的描述不允许共用草稿键，否则点 A 会提交成 B 的内容。
      expect(store.draftKey(first), isNot(store.draftKey(second)));
      expect(
        store.draftKey(second, initial: initial),
        isNot(store.draftKey(second)),
        reason: '显式预填值必须参与草稿键，目标 id 不同的草稿互相隔离',
      );
    });
  });

  group('实时连接终态', () {
    test('服务端以 4401 关闭（身份失效/被移出/换新局）时停止重连', () async {
      final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      var attempts = 0;
      final statuses = <String>[];
      final subscription = server.listen((request) async {
        attempts++;
        final socket = await WebSocketTransformer.upgrade(request);
        await socket.close(4401, '身份失效');
      });
      final connection = LiveConnection(
        endpoint: ServerEndpoint.parse('http://127.0.0.1:${server.port}'),
        token: 'token-abc',
        onEvent: (_) {},
        onConnected: () async {},
        onStatus: statuses.add,
      )..start();
      // 足够跑完两轮退避（1s + 2s）：如果还在重连，attempts 会超过 1。
      await Future<void>.delayed(const Duration(milliseconds: 4200));
      await connection.stop();
      await subscription.cancel();
      await server.close(force: true);
      expect(attempts, 1, reason: '4401 是身份终态，不允许无限重连');
      expect(statuses, contains('登录状态已失效，请重新进入'));
    });
  });
}

/// read 抛出存储层异常（PlatformException 一类），恢复路径必须整体兜住。
class _BrokenSecureStorage extends FlutterSecureStorage {
  @override
  Future<String?> read({
    required String key,
    IOSOptions? iOptions,
    AndroidOptions? aOptions,
    LinuxOptions? lOptions,
    WebOptions? webOptions,
    MacOsOptions? mOptions,
    WindowsOptions? wOptions,
  }) async {
    throw Exception('storage unavailable');
  }
}
