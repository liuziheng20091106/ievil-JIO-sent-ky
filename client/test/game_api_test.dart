import 'dart:convert';
import 'dart:io';

import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:seven_double_client/src/api.dart';
import 'package:seven_double_client/src/models.dart';

/// 最小状态：只包含客户端解码所需字段。
Map<String, dynamic> stateJson({int version = 3}) => {
      'ui_version': 1,
      'id': 'game-1',
      'version': version,
      'status': 'playing',
      'day': 1,
      'half': 'day',
      'phase': 'speech',
      'phase_label': '顺序发言',
      'seats': [
        {
          'id': '1',
          'name': '一号',
          'avatar_role_id': null,
          'previous_role_id': null,
          'occupied': true,
          'alive': true,
        },
      ],
      'self': <String, dynamic>{},
      'actions': [
        {
          'id': 'lobby.ready',
          'ui_version': 1,
          'short_label': '准备',
          'label': '准备发牌',
          'payload': <String, dynamic>{},
          'fields': <dynamic>[],
        },
      ],
      'channels': <dynamic>[],
      'public': <String, dynamic>{},
    };

void main() {
  late HttpServer server;
  late ServerEndpoint endpoint;
  final requests = <HttpHeaders>[];
  final calls = <String>[];
  final bodies = <String>[];
  var status = 200;
  var body = stateJson();
  // 按路径覆盖响应：模拟「PoW 领题」与「挑战创建」返回不同内容。
  final routes = <String, Object?>{};
  // 按路径覆盖状态码：模拟旧服务端没有 PoW 领题接口（404）。
  final statusByPath = <String, int>{};
  final redirects = <String, String>{};

  setUp(() async {
    requests.clear();
    calls.clear();
    bodies.clear();
    routes.clear();
    statusByPath.clear();
    redirects.clear();
    status = 200;
    body = stateJson();
    server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    server.listen((request) async {
      requests.add(request.headers);
      calls.add('${request.method} ${request.uri}');
      if (request.method == 'POST') {
        bodies.add(await utf8.decoder.bind(request).join());
      }
      final path = request.uri.path;
      final location = redirects[path];
      if (location != null) {
        request.response.statusCode = HttpStatus.found;
        request.response.headers.set(HttpHeaders.locationHeader, location);
        request.response.cookies.add(Cookie('session', 'private'));
        await request.response.close();
        return;
      }
      request.response.statusCode = statusByPath[path] ?? status;
      request.response.headers.contentType = ContentType.json;
      request.response.write(jsonEncode(routes[path] ?? body));
      await request.response.close();
    });
    endpoint = ServerEndpoint.parse('http://127.0.0.1:${server.port}');
  });

  tearDown(() async {
    await server.close(force: true);
  });

  test('sends the bearer token and decodes the trimmed state', () async {
    final api = GameApi(endpoint, token: 'token-abc');
    final view = await api.state('game-1');
    expect(view.version, 3);
    expect(view.actions.single.shortLabel, '准备');
    expect(view.actions.single.unsupportedReason, isNull);
    expect(requests.single.value(HttpHeaders.authorizationHeader),
        'Bearer token-abc');
    expect(requests.single.value(HttpHeaders.acceptHeader), 'application/json');
    api.close();
  });

  test('requests without a token send no Authorization header', () async {
    final api = GameApi(endpoint, token: null);
    // PoW 领题与挑战创建都是无令牌请求：两个请求都不该带 Authorization。
    await api.createChallenge();
    expect(
      requests.every(
          (headers) => headers.value(HttpHeaders.authorizationHeader) == null),
      isTrue,
    );
    expect(calls, contains('POST /api/native/auth/challenges'));
    api.close();
  });

  test('downloadTo follows CDN redirects without session headers', () async {
    final cdn = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    addTearDown(() => cdn.close(force: true));
    final cdnRequests = <HttpHeaders>[];
    final bytes = <int>[0, 255, 128, 10, 13, 42];
    cdn.listen((request) async {
      cdnRequests.add(request.headers);
      expect(request.uri.path, '/resource-md5');
      request.response.contentLength = bytes.length;
      request.response.add(bytes);
      await request.response.close();
    });
    redirects['/download'] = 'http://127.0.0.1:${cdn.port}/resource-md5';
    final directory = await Directory.systemTemp.createTemp('api-download-');
    addTearDown(() => directory.delete(recursive: true));
    final file = File('${directory.path}/resource');
    final api = GameApi(endpoint, token: 'private-token');
    addTearDown(api.close);
    await api.me();
    expect(requests.single.value(HttpHeaders.authorizationHeader),
        'Bearer private-token');
    requests.clear();
    final progress = <(int, int)>[];
    final received = await api.downloadTo('/download', file,
        onProgress: (received, total) => progress.add((received, total)));
    expect(received, bytes.length);
    expect(await file.readAsBytes(), bytes);
    expect(progress.last, (bytes.length, bytes.length));
    var previous = 0;
    for (final (received, total) in progress) {
      expect(received, greaterThan(previous));
      expect(received, lessThanOrEqualTo(bytes.length));
      expect(total, bytes.length);
      previous = received;
    }
    expect(requests, hasLength(1));
    expect(cdnRequests, hasLength(1));
    for (final headers in [...requests, ...cdnRequests]) {
      expect(headers.value(HttpHeaders.authorizationHeader), isNull);
      expect(headers.value(HttpHeaders.cookieHeader), isNull);
    }
  });

  test('downloadTo rejects redirect loops before writing a file', () async {
    redirects['/loop-a'] = '/loop-b';
    redirects['/loop-b'] = '/loop-a';
    final directory = await Directory.systemTemp.createTemp('api-download-');
    addTearDown(() => directory.delete(recursive: true));
    final file = File('${directory.path}/resource');
    final api = GameApi(endpoint);
    addTearDown(api.close);
    await expectLater(
      api.downloadTo('/loop-a', file),
      throwsA(isA<ApiException>().having((error) => error.message, 'message',
          contains('Redirect loop detected'))),
    );
    expect(await file.exists(), isFalse);
    expect(calls, ['GET /loop-a', 'GET /loop-b', 'GET /loop-a']);
  });

  test('downloadTo refuses non-HTTP redirect destinations', () async {
    redirects['/download'] = 'ftp://127.0.0.1:${server.port}/forbidden';
    final directory = await Directory.systemTemp.createTemp('api-download-');
    addTearDown(() => directory.delete(recursive: true));
    final file = File('${directory.path}/resource');
    final api = GameApi(endpoint);
    addTearDown(api.close);
    await expectLater(
      api.downloadTo('/download', file),
      throwsA(isA<ArgumentError>().having((error) => error.message, 'message',
          contains("Unsupported scheme 'ftp'"))),
    );
    expect(await file.exists(), isFalse);
    expect(calls, ['GET /download']);
  });

  test('PoW 开启：先领题求解，再把证明带进挑战创建请求', () async {
    const token = 'v1.123.4.abc.deadbeef';
    routes['/api/pow/challenges'] = {
      'required': true,
      'difficulty': 3,
      'token': token
    };
    final api = GameApi(endpoint);
    await api.createChallenge();
    expect(calls[0], 'POST /api/pow/challenges');
    expect(calls.last, 'POST /api/native/auth/challenges');
    final proof = jsonDecode(bodies.last) as Map<String, dynamic>;
    expect(proof['token'], token);
    // 提交的解必须真的满足前缀条件，而不是随便一个整数。
    final nonce = proof['nonce'] as int;
    expect(
      sha256.convert(utf8.encode('$token$nonce')).toString().substring(0, 3),
      '000',
    );
    api.close();
  });

  test('PoW 未开启：领题后跳过求解，创建挑战不带证明', () async {
    routes['/api/pow/challenges'] = {'required': false};
    final api = GameApi(endpoint);
    await api.createChallenge();
    expect(calls,
        ['POST /api/pow/challenges', 'POST /api/native/auth/challenges']);
    // 未开启防护：创建挑战不带证明字段（body 为空字符串，即无 JSON 体）。
    expect(bodies.last, isEmpty);
    api.close();
  });

  test('旧服务端没有领题接口（404）：回退为直接创建挑战', () async {
    statusByPath['/api/pow/challenges'] = 404;
    final api = GameApi(endpoint);
    await api.createChallenge();
    expect(calls,
        ['POST /api/pow/challenges', 'POST /api/native/auth/challenges']);
    // 回退时同样不带证明，行为与旧客户端一致。
    expect(bodies.last, isEmpty);
    api.close();
  });

  test('surfaces the server reason and keeps the status code', () async {
    status = 401;
    body = {'detail': '登录已失效'};
    final api = GameApi(endpoint, token: 'stale');
    await expectLater(
      api.me(),
      throwsA(
        isA<ApiException>()
            .having((error) => error.statusCode, 'statusCode', 401)
            .having((error) => error.message, 'message', '登录已失效'),
      ),
    );
    api.close();
  });

  test('rejects an unsupported ui_version instead of guessing', () async {
    body = stateJson()..['ui_version'] = 2;
    final api = GameApi(endpoint);
    await expectLater(api.state('game-1'), throwsA(isA<FormatException>()));
    api.close();
  });

  test('傀儡身份只在带 asSeat 时进入请求体', () async {
    final api = GameApi(endpoint, token: 'token-abc');
    // 梅露露代操作傀儡席：命令与消息都必须带上目标席位，服务端按它校验控制权。
    await api.command('g1',
        expectedVersion: 3,
        action: 'vote.cast',
        payload: {'target': '2'},
        asSeat: '2');
    expect(jsonDecode(bodies.last), {
      'expected_version': 3,
      'action': 'vote.cast',
      'payload': {'target': '2'},
      'as_seat': '2'
    });

    body = {
      'id': 7,
      'kind': 'chat',
      'text': '替傀儡发言',
      'channel_id': 'private:abc',
      'sender_id': 'p2',
      'sender_name': 'kiwi',
      'created_at': '2026-09-15T12:00:00Z',
    };
    await api.sendMessage('g1', 'private:abc', '替傀儡发言', asSeat: '2');
    expect(jsonDecode(bodies.last),
        {'channel_id': 'private:abc', 'text': '替傀儡发言', 'as_seat': '2'});

    // 自己的行动与发言不带 as_seat：服务端会把它当成代理请求拒绝。
    await api.sendMessage('g1', 'public', '我自己发言');
    expect(jsonDecode(bodies.last), {'channel_id': 'public', 'text': '我自己发言'});
    api.close();
  });

  test('傀儡代读：读消息带 as_seat，自己的消息不带', () async {
    routes['/api/games/g1/messages'] = {
      'messages': <dynamic>[],
      'has_more': false
    };
    final api = GameApi(endpoint, token: 'token-abc');
    // 控制者代读受控席位所在频道的聊天：服务端只认 as_seat 这一条只读口径。
    await api.messages('g1', asSeat: '2');
    expect(calls.last, 'GET /api/games/g1/messages?scope=all&as_seat=2');
    await api.messages('g1');
    expect(calls.last, 'GET /api/games/g1/messages?scope=all');
    api.close();
  });

  test('online/invite/accept/reject hit the invite endpoints', () async {
    body = {
      'accounts': [
        {'id': 'a1', 'name': '阿雪', 'available': true, 'invited': false}
      ],
      'host_online': true,
    };
    final api = GameApi(endpoint, token: 'token-abc');
    await api.online(gameId: 'g1');
    expect(calls.single, 'GET /api/online?game_id=g1');

    body = {'id': 'invite1', 'account_id': 'a1', 'status': 'pending'};
    await api.invite('g1', 'a1');
    expect(calls.last, 'POST /api/games/g1/invites');
    expect(jsonDecode(bodies.last), {'account_id': 'a1'});

    body = {'actor': stateJson()['self'], 'game_id': 'g1'};
    await api.acceptInvite('invite1');
    expect(calls.last, 'POST /api/invites/invite1/accept');

    await api.rejectInvite('invite2');
    expect(calls.last, 'POST /api/invites/invite2/reject');
    api.close();
  });

  test('invite conflict surfaces the server detail message', () async {
    status = 409;
    body = {'detail': '该玩家当前不在线'};
    final api = GameApi(endpoint, token: 'token-abc');
    await expectLater(
      api.invite('g1', 'a1'),
      throwsA(
        isA<ApiException>()
            .having((error) => error.statusCode, 'statusCode', 409)
            .having((error) => error.message, 'message', '该玩家当前不在线'),
      ),
    );
    api.close();
  });

  test('history list and detail hit the history endpoints', () async {
    final api = GameApi(endpoint, token: 'token-abc');
    body = {
      'matches': [
        {
          'id': 'game-1',
          'ended_at': '2026-09-26T02:00:00+00:00',
          'day': 3,
          'winner': 'witch',
          'reason': '米莉亚与亚里沙均出局',
          'source': 'ended',
          'host_name': '主持人(阿雪)',
          'player_count': 2,
          'players': [
            {
              'participant_id': 'p1',
              'name': 'kiwi',
              'kind': 'player',
              'seat_id': '1',
              'role_ids': ['marg', 'sherry'],
              'active': true,
              'blocked': false,
            },
          ],
        },
      ],
      'has_more': true,
    };
    final page =
        await api.history(before: '2026-09-26T03:00:00+00:00', limit: 5);
    expect(calls.last,
        'GET /api/history?limit=5&before=2026-09-26T03%3A00%3A00%2B00%3A00');
    expect(page.hasMore, isTrue);
    expect(page.matches.single.winner, 'witch');
    expect(page.matches.single.players.single.roleIds, ['marg', 'sherry']);

    body = {
      'id': 'game-1',
      'ended_at': '2026-09-26T02:00:00+00:00',
      'day': 3,
      'winner': 'witch',
      'reason': '米莉亚与亚里沙均出局',
      'source': 'ended',
      'host_name': '主持人(阿雪)',
      'players': <dynamic>[],
      'events': [
        {
          'seq': 0,
          'kind': 'chat',
          'sender_name': 'kiwi',
          'avatar_role_id': 'marg',
          'text': '公屏上说过的话',
          'created_at': '2026-09-26T01:30:00+00:00',
        },
      ],
    };
    final detail = await api.match('game-1');
    expect(calls.last, 'GET /api/history/game-1');
    expect(detail.match.winner, 'witch');
    expect(detail.events.single.text, '公屏上说过的话');

    // 删除历史对局：DELETE 请求打到同一资源的接口上（4 级主持由服务端校验）。
    body = {'ok': true};
    await api.deleteMatch('game-1');
    expect(calls.last, 'DELETE /api/history/game-1');
    api.close();
  });

  test('live connection carries the bearer token and forwards events',
      () async {
    final events = <Map<String, dynamic>>[];
    final connected = <String>[];
    final live = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    live.listen((request) async {
      expect(request.uri.path, '/api/live');
      expect(request.headers.value(HttpHeaders.authorizationHeader),
          'Bearer token-abc');
      final socket = await WebSocketTransformer.upgrade(request);
      socket.add(jsonEncode(
          {'type': 'sync', 'state': stateJson(), 'messages': <dynamic>[]}));
      await Future<void>.delayed(const Duration(milliseconds: 200));
      await socket.close();
    });
    final connection = LiveConnection(
      endpoint: ServerEndpoint.parse('http://127.0.0.1:${live.port}'),
      token: 'token-abc',
      onEvent: events.add,
      onConnected: () async => connected.add('connected'),
      onStatus: (_) {},
    )..start();
    await Future<void>.delayed(const Duration(milliseconds: 600));
    await connection.stop();
    await live.close(force: true);
    expect(connected, isNotEmpty);
    expect(events.single['type'], 'sync');
  });
}
