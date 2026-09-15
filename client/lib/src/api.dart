import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'models.dart';

class GameApi {
  GameApi(this.endpoint, {this.token}) {
    _client.connectionTimeout = const Duration(seconds: 25);
    _client.userAgent = 'seven-double-flutter/1';
  }

  final ServerEndpoint endpoint;
  final HttpClient _client = HttpClient();
  String? token;

  Future<Map<String, dynamic>> createChallenge() async =>
      jsonObject(await _request('POST', '/api/native/auth/challenges'));

  Future<Map<String, dynamic>> challenge(String id) async => jsonObject(
        await _request('GET', '/api/native/auth/challenges/${Uri.encodeComponent(id)}'),
      );

  Future<Map<String, dynamic>> hostLogin(String password) async => jsonObject(
        await _request('POST', '/api/native/host/login', body: {'password': password}),
      );

  Future<Map<String, dynamic>> me() async =>
      jsonObject(await _request('GET', '/api/me'));

  Future<Map<String, dynamic>> lobby() async =>
      jsonObject(await _request('GET', '/api/lobby'));

  Future<GameView> createGame() async {
    final catalog = jsonObject(await _request('GET', '/api/catalog'));
    final codex = jsonArray(catalog['default_codex'], 'catalog.default_codex');
    return GameView.fromJson(await _request('POST', '/api/games', body: {'codex': codex}));
  }

  Future<Map<String, dynamic>> participate(String gameId, String kind) async => jsonObject(
        await _request(
          'POST',
          '/api/games/${Uri.encodeComponent(gameId)}/participations',
          body: {'kind': kind},
        ),
      );

  Future<GameView> state(String gameId) async => GameView.fromJson(
        await _request('GET', '/api/games/${Uri.encodeComponent(gameId)}/state'),
      );

  Future<GameView> seatPerspective(String gameId, String seatId) async {
    final body = jsonObject(await _request(
      'GET',
      '/api/games/${Uri.encodeComponent(gameId)}/seats/${Uri.encodeComponent(seatId)}/view',
    ));
    return GameView.fromJson(body['view']);
  }

  Future<GameView> command(
    String gameId, {
    required int expectedVersion,
    required String action,
    required Map<String, dynamic> payload,
    String? asSeat,
  }) async =>
      GameView.fromJson(await _request(
        'POST',
        '/api/games/${Uri.encodeComponent(gameId)}/commands',
        body: {
          'expected_version': expectedVersion,
          'action': action,
          'payload': payload,
          if (asSeat != null) 'as_seat': asSeat,
        },
      ));

  Future<({List<GameMessage> messages, bool hasMore})> messages(
    String gameId, {
    String scope = 'all',
    int? before,
    int? after,
    String? channelId,
  }) async {
    final body = jsonObject(await _request(
      'GET',
      '/api/games/${Uri.encodeComponent(gameId)}/messages',
      query: {
        'scope': scope,
        'before': before?.toString(),
        'after': after?.toString(),
        'channel_id': channelId,
      },
    ));
    return (
      messages: jsonArray(body['messages'], 'messages')
          .map(GameMessage.fromJson)
          .toList(growable: false),
      hasMore: jsonBool(body['has_more'], 'has_more'),
    );
  }

  Future<GameMessage> sendMessage(String gameId, String channelId, String text) async =>
      GameMessage.fromJson(await _request(
        'POST',
        '/api/games/${Uri.encodeComponent(gameId)}/messages',
        body: {'channel_id': channelId, 'text': text},
      ));

  Future<String> uploadEvidence(String gameId, {String text = '', String? image}) async {
    final body = jsonObject(await _request(
      'POST',
      '/api/games/${Uri.encodeComponent(gameId)}/evidence',
      body: {'text': text, 'image': image},
    ));
    return jsonString(body['id'], 'evidence.id');
  }

  Future<List<int>> evidence(String gameId, String evidenceId) async {
    final response = await _open(
      'GET',
      '/api/games/${Uri.encodeComponent(gameId)}/evidence/${Uri.encodeComponent(evidenceId)}',
    );
    final bytes = await response.fold<List<int>>(<int>[], (all, part) => all..addAll(part));
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiException(utf8.decode(bytes, allowMalformed: true), statusCode: response.statusCode);
    }
    return bytes;
  }

  Future<void> logout() async {
    await _request('POST', '/api/logout');
  }

  Future<Object?> _request(
    String method,
    String path, {
    Map<String, String?> query = const {},
    Map<String, dynamic>? body,
  }) async {
    final response = await _open(method, path, query: query, body: body);
    final text = await response.transform(utf8.decoder).join();
    Object? decoded;
    if (text.isNotEmpty) {
      try {
        decoded = jsonDecode(text);
      } on FormatException {
        throw ApiException('服务器返回了无效 JSON', statusCode: response.statusCode);
      }
    }
    if (response.statusCode < 200 || response.statusCode >= 300) {
      var detail = '请求失败 (${response.statusCode})';
      if (decoded is Map && decoded['detail'] != null) detail = decoded['detail'].toString();
      throw ApiException(detail, statusCode: response.statusCode);
    }
    return decoded ?? <String, dynamic>{};
  }

  Future<HttpClientResponse> _open(
    String method,
    String path, {
    Map<String, String?> query = const {},
    Map<String, dynamic>? body,
  }) async {
    try {
      final request = await _client.openUrl(method, endpoint.api(path, query)).timeout(
            const Duration(seconds: 25),
          );
      request.headers.set(HttpHeaders.acceptHeader, 'application/json');
      final token = this.token;
      if (token != null) request.headers.set(HttpHeaders.authorizationHeader, 'Bearer $token');
      if (body != null) {
        request.headers.contentType = ContentType.json;
        request.write(jsonEncode(body));
      }
      return await request.close().timeout(const Duration(seconds: 25));
    } on TimeoutException {
      throw const ApiException('服务器请求超时');
    } on SocketException catch (error) {
      throw ApiException('无法连接服务器：${error.message}');
    } on HandshakeException {
      throw const ApiException('TLS 证书验证失败');
    }
  }

  void close() => _client.close(force: true);
}

class LiveConnection {
  LiveConnection({
    required this.endpoint,
    required this.token,
    required this.onEvent,
    required this.onConnected,
    required this.onStatus,
  });

  final ServerEndpoint endpoint;
  final String token;
  final void Function(Map<String, dynamic>) onEvent;
  final Future<void> Function() onConnected;
  final void Function(String) onStatus;

  static const _delays = [1, 2, 4, 8, 15];
  bool _stopped = true;
  WebSocket? _socket;
  Timer? _watchdog;
  DateTime _lastEvent = DateTime.now();
  Future<void>? _runner;

  void start() {
    if (!_stopped) return;
    _stopped = false;
    _runner = _loop();
  }

  Future<void> _loop() async {
    var attempt = 0;
    while (!_stopped) {
      try {
        onStatus(attempt == 0 ? '连接中' : '重连中');
        final socket = await WebSocket.connect(
          endpoint.liveUri.toString(),
          headers: {HttpHeaders.authorizationHeader: 'Bearer $token'},
        ).timeout(const Duration(seconds: 25));
        if (_stopped) {
          await socket.close();
          return;
        }
        _socket = socket;
        _lastEvent = DateTime.now();
        onStatus('已连接');
        await onConnected();
        _watchdog = Timer.periodic(const Duration(seconds: 10), (_) {
          if (DateTime.now().difference(_lastEvent) > const Duration(seconds: 65)) {
            _socket?.close(4000, 'event timeout');
          }
        });
        await for (final value in socket) {
          _lastEvent = DateTime.now();
          attempt = 0;
          if (value is! String) continue;
          final decoded = jsonDecode(value);
          if (decoded is! Map) continue;
          final event = decoded.map((key, value) => MapEntry(key.toString(), value));
          if (event['type'] == 'ping') {
            socket.add(jsonEncode({'type': 'pong'}));
          } else {
            onEvent(event);
          }
        }
      } on HandshakeException {
        onStatus('TLS 证书验证失败');
      } catch (_) {
        if (!_stopped) onStatus('连接已中断');
      } finally {
        _watchdog?.cancel();
        _watchdog = null;
        _socket = null;
      }
      if (_stopped) break;
      final seconds = _delays[attempt < _delays.length ? attempt : _delays.length - 1];
      if (attempt < _delays.length - 1) attempt++;
      await Future<void>.delayed(Duration(seconds: seconds));
    }
  }

  Future<void> stop() async {
    _stopped = true;
    _watchdog?.cancel();
    await _socket?.close(1000, 'logout');
    await _runner;
    onStatus('未连接');
  }
}
