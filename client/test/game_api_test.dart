import 'dart:convert';
import 'dart:io';

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
  var status = 200;
  var body = stateJson();

  setUp(() async {
    requests.clear();
    status = 200;
    body = stateJson();
    server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    server.listen((request) async {
      requests.add(request.headers);
      if (request.method == 'POST') {
        // 读空请求体，避免客户端等待写入完成。
        await request.drain<void>();
      }
      request.response.statusCode = status;
      request.response.headers.contentType = ContentType.json;
      request.response.write(jsonEncode(body));
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
    expect(requests.single.value(HttpHeaders.authorizationHeader), 'Bearer token-abc');
    expect(requests.single.value(HttpHeaders.acceptHeader), 'application/json');
    api.close();
  });

  test('requests without a token send no Authorization header', () async {
    final api = GameApi(endpoint);
    await api.createChallenge();
    expect(requests.single.value(HttpHeaders.authorizationHeader), isNull);
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

  test('live connection carries the bearer token and forwards events', () async {
    final events = <Map<String, dynamic>>[];
    final connected = <String>[];
    final live = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    live.listen((request) async {
      expect(request.uri.path, '/api/live');
      expect(request.headers.value(HttpHeaders.authorizationHeader), 'Bearer token-abc');
      final socket = await WebSocketTransformer.upgrade(request);
      socket.add(jsonEncode({'type': 'sync', 'state': stateJson(), 'messages': <dynamic>[]}));
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
