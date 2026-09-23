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
        await _request(
            'GET', '/api/native/auth/challenges/${Uri.encodeComponent(id)}'),
      );

  Future<Map<String, dynamic>> hostLogin(String password) async => jsonObject(
        await _request('POST', '/api/native/host/login',
            body: {'password': password}),
      );

  Future<Map<String, dynamic>> health() async =>
      jsonObject(await _request('GET', '/api/health'));

  Future<Map<String, dynamic>> me() async =>
      jsonObject(await _request('GET', '/api/me'));

  Future<Map<String, dynamic>> lobby() async =>
      jsonObject(await _request('GET', '/api/lobby'));

  Future<Map<String, dynamic>> catalog() async =>
      jsonObject(await _request('GET', '/api/catalog'));

  /// 主持人建局必须显式给出 11 名魔典角色；不再静默使用默认名单。
  Future<GameView> createGame(List<String> codex) async => GameView.fromJson(
        await _request('POST', '/api/games', body: {'codex': codex}),
      );

  Future<Map<String, dynamic>> participate(String gameId, String kind) async =>
      jsonObject(
        await _request(
          'POST',
          '/api/games/${Uri.encodeComponent(gameId)}/participations',
          body: {'kind': kind},
        ),
      );

  /// 在线账号名单；带 gameId 时服务端额外给出能否邀请与是否已邀请。
  Future<Map<String, dynamic>> online({String? gameId}) async => jsonObject(
        await _request('GET', '/api/online', query: {'game_id': gameId}),
      );

  Future<Map<String, dynamic>> invite(String gameId, String accountId) async =>
      jsonObject(
        await _request(
          'POST',
          '/api/games/${Uri.encodeComponent(gameId)}/invites',
          body: {'account_id': accountId},
        ),
      );

  Future<Map<String, dynamic>> acceptInvite(String inviteId) async => jsonObject(
        await _request(
            'POST', '/api/invites/${Uri.encodeComponent(inviteId)}/accept'),
      );

  Future<void> rejectInvite(String inviteId) async {
    await _request('POST', '/api/invites/${Uri.encodeComponent(inviteId)}/reject');
  }

  Future<GameView> state(String gameId) async => GameView.fromJson(
        await _request(
            'GET', '/api/games/${Uri.encodeComponent(gameId)}/state'),
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

  Future<GameMessage> sendMessage(
    String gameId,
    String channelId,
    String text, {
    String? asSeat,
  }) async =>
      GameMessage.fromJson(await _request(
        'POST',
        '/api/games/${Uri.encodeComponent(gameId)}/messages',
        body: {
          'channel_id': channelId,
          'text': text,
          if (asSeat != null) 'as_seat': asSeat,
        },
      ));

  Future<String> uploadEvidence(String gameId,
      {String text = '', String? image}) async {
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
    final bytes = await response
        .fold<List<int>>(<int>[], (all, part) => all..addAll(part));
    if (response.statusCode < 200 || response.statusCode >= 300) {
      throw ApiException(utf8.decode(bytes, allowMalformed: true),
          statusCode: response.statusCode);
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
    // 头到了不代表体会来：慢速或挂起的响应体也要受超时约束。
    final text = await response
        .transform(utf8.decoder)
        .join()
        .timeout(const Duration(seconds: 25), onTimeout: () {
      throw const ApiException('服务器响应超时');
    });
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
      if (decoded is Map && decoded['detail'] != null) {
        detail = decoded['detail'].toString();
      }
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
      final request =
          await _client.openUrl(method, endpoint.api(path, query)).timeout(
                const Duration(seconds: 25),
              );
      // 不自动跟随重定向：ServerEndpoint 只校验用户填写的根地址，
      // 一条 3xx 就能把带令牌的 GET 降到任意 http:// 明文主机。
      request.followRedirects = false;
      request.headers.set(HttpHeaders.acceptHeader, 'application/json');
      final token = this.token;
      if (token != null) {
        request.headers.set(HttpHeaders.authorizationHeader, 'Bearer $token');
      }
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

  void start() {
    if (!_stopped) return;
    _stopped = false;
    // 循环内部已兜住所有异常路径；这里再挂一层兜底，
    // 保证任何遗漏都不会变成未处理的异步错误。
    unawaited(_loop().catchError((Object failure) {
      onStatus('连接任务终止：$failure');
    }));
  }

  /// Dart 的 [WebSocket.connect] 把握手被拒折叠成 WebSocketException 文本。
  /// 实测（Dart 3.13）异常的 [WebSocketException.message] 只写目标地址，
  /// 状态码只出现在 toString 里（“… was not upgraded to websocket, HTTP
  /// status code: 403”），因此这里解析 toString 而不是 message。
  /// 身份类失败（401/403）重试多少次都一样，
  /// 停止循环把状态交给上层引导用户重新登录；解析不出状态码时维持重连。
  static int? _handshakeStatus(Object failure) {
    if (failure is! WebSocketException) return null;
    final match = RegExp('status code:\\s*(\\d{3})', caseSensitive: false)
        .firstMatch(failure.toString());
    if (match == null) return null;
    return int.tryParse(match.group(1)!);
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
        try {
          await onConnected();
        } catch (failure) {
          // 补齐失败不应杀掉刚建立的连接：实时事件流本身还活着，
          // 下次重连或用户切筛选时会再补。
          onStatus('消息补齐失败：$failure');
        }
        _watchdog = Timer.periodic(const Duration(seconds: 10), (_) {
          if (DateTime.now().difference(_lastEvent) >
              const Duration(seconds: 65)) {
            _socket?.close(4000, 'event timeout');
          }
        });
        await for (final value in socket) {
          _lastEvent = DateTime.now();
          attempt = 0;
          if (value is! String) continue;
          // 单帧损坏只丢这一帧：异常如果漏出到 await for 会直接杀掉连接，
          // 造成无感知的断连-重连循环。回调同理，逐个隔离。
          try {
            final decoded = jsonDecode(value);
            if (decoded is! Map) continue;
            final event =
                decoded.map((key, value) => MapEntry(key.toString(), value));
            if (event['type'] == 'ping') {
              socket.add(jsonEncode({'type': 'pong'}));
            } else {
              onEvent(event);
            }
          } on FormatException {
            // 服务器不会发坏帧；万一出现说明在测试或代理篡改场景，跳过即可。
          } catch (failure) {
            onStatus('事件处理失败：$failure');
          }
        }
        // 4401 是服务端主动终结身份：未登录/被移出对局/该局已被新局替换。
        // 与握手期的 401/403 同为终态，重连只会无限空转。
        if (socket.closeCode == 4401) {
          onStatus('登录状态已失效，请重新进入');
          return;
        }
      } on HandshakeException {
        onStatus('TLS 证书验证失败');
      } catch (failure) {
        final status = _handshakeStatus(failure);
        if (status == 401 || status == 403) {
          // 永久性拒绝：令牌过期或被服务端明确拒绝，重连只会无限空转。
          onStatus(status == 401 ? '登录已失效，请重新登录' : '连接被服务器拒绝');
          return;
        }
        if (!_stopped) onStatus('连接已中断');
      } finally {
        _watchdog?.cancel();
        _watchdog = null;
        _socket = null;
      }
      if (_stopped) break;
      final seconds =
          _delays[attempt < _delays.length ? attempt : _delays.length - 1];
      if (attempt < _delays.length - 1) attempt++;
      await Future<void>.delayed(Duration(seconds: seconds));
    }
  }

  Future<void> stop() async {
    _stopped = true;
    _watchdog?.cancel();
    await _socket?.close(1000, 'logout');
    // 不等待 _runner：它可能正卡在 25 秒连接超时或 15 秒退避上，
    // await 它会让登出界面无反馈地悬挂半分钟。循环每轮都会检查
    // _stopped，孤儿任务会自行退出，close 之后也没有资源可泄漏。
    onStatus('未连接');
  }
}
