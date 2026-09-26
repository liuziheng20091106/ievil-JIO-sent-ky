import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'client_version.dart';
import 'models.dart';
import 'pow.dart';

class GameApi {
  GameApi(this.endpoint, {this.token}) {
    _client.connectionTimeout = const Duration(seconds: 25);
    // 版本号写在 UA 里：后端据此下发更新信息、并只对「过旧客户端加入对局」设限。
    _client.userAgent = clientUserAgent();
  }

  final ServerEndpoint endpoint;
  final HttpClient _client = HttpClient();
  String? token;

  Future<Map<String, dynamic>> createChallenge() async =>
      jsonObject(await _createChallenge('/api/native/auth/challenges'));

  Future<Map<String, dynamic>> challenge(String id) async => jsonObject(
        await _request(
            'GET', '/api/native/auth/challenges/${Uri.encodeComponent(id)}'),
      );

  /// 领取 PoW 谜题并在本地求解后创建登录挑战。
  ///
  /// 服务端未开启工作量验证时 /api/pow/challenges 返回 required=false，
  /// 直接转发创建请求，行为与旧版完全一致；开启后旧服务端没有领题接口，
  /// 领题 404 同样按「无防护」处理，两端版本错开也不会挡登录。
  Future<Map<String, dynamic>> _createChallenge(String path) async {
    Map<String, dynamic>? proof;
    try {
      final puzzle = PowPuzzle.fromJson(
        jsonObject(await _request('POST', '/api/pow/challenges')),
      );
      final nonce = await puzzle.solve();
      if (nonce != null) {
        proof = {'token': puzzle.token, 'nonce': nonce};
      }
    } on ApiException catch (failure) {
      if (failure.statusCode != 404) rethrow;
      // 旧服务端：没有 PoW 领题接口，视为未开启防护。
    }
    return jsonObject(await _request('POST', path, body: proof));
  }

  Future<Map<String, dynamic>> health() async =>
      jsonObject(await _request('GET', '/api/health'));

  /// 用户协议（Markdown）：客户端首次连接服务器时展示；服务端未配置时正文为空。
  Future<Agreement> agreement() async =>
      Agreement.fromJson(await _request('GET', '/api/agreement'));

  /// 更新包地址：`/releases/x.zip` 这类相对地址按当前服务根地址解析，
  /// 绝对地址只接受 HTTP(S)（协议之外的 scheme 一律拒绝）。
  Uri resolveDownloadUrl(String url) {
    final value = url.trim();
    if (value.isEmpty) throw const ApiException('服务端没有下发更新包地址');
    final parsed = Uri.tryParse(value);
    if (parsed == null) throw ApiException('更新包地址不合法：$value');
    if (!parsed.hasScheme) return endpoint.httpUri.resolve(value);
    if (parsed.scheme != 'http' && parsed.scheme != 'https') {
      throw ApiException('更新包地址必须是 HTTP(S)：$value');
    }
    if (parsed.host.isEmpty) throw ApiException('更新包地址不合法：$value');
    return parsed;
  }

  /// 把更新包流式下载到 [file]（调用方自己负责先写临时文件再改名）。
  /// [onProgress] 收到已下载字节与总字节（服务端没给 Content-Length 时 total 为 -1）；
  /// [isCancelled] 返回真时中断下载并抛 [ApiException]（HTTP 连接随之关闭）。
  Future<int> downloadTo(
    String url,
    File file, {
    void Function(int received, int total)? onProgress,
    bool Function()? isCancelled,
  }) async {
    final uri = resolveDownloadUrl(url);
    try {
      final request =
          await _client.getUrl(uri).timeout(const Duration(seconds: 25));
      // 与其它请求一致：不跟随重定向，避免把下载引到协议外的地址。
      request.followRedirects = false;
      request.headers.set(HttpHeaders.acceptHeader, '*/*');
      final response = await request.close().timeout(const Duration(seconds: 25));
      if (response.statusCode < 200 || response.statusCode >= 300) {
        throw ApiException('下载失败 (${response.statusCode})',
            statusCode: response.statusCode);
      }
      final total = response.contentLength;
      final sink = file.openWrite();
      var received = 0;
      try {
        await for (final chunk in response) {
          if (isCancelled?.call() ?? false) {
            throw const ApiException('已取消下载');
          }
          sink.add(chunk);
          received += chunk.length;
          onProgress?.call(received, total);
        }
      } finally {
        await sink.close();
      }
      return received;
    } on TimeoutException {
      throw const ApiException('下载超时');
    } on SocketException catch (error) {
      throw ApiException('无法连接服务器：${error.message}');
    } on HandshakeException {
      throw const ApiException('TLS 证书验证失败');
    }
  }

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

  /// 主持人确认进入本局管理界面：服务端据此登记，并在非建局主持人时向本局发一条系统公告。
  Future<HostEntryResult> enterHostAdmin(String gameId) async =>
      HostEntryResult.fromJson(await _request(
        'POST',
        '/api/games/${Uri.encodeComponent(gameId)}/host/enter',
      ));

  /// 观战席主动退出本局：服务端只解除观战参与身份，之后仍可再次入席观战。
  Future<void> leaveGame(String gameId) async {
    await _request('POST', '/api/games/${Uri.encodeComponent(gameId)}/leave');
  }

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

  /// 主持人也是 QQ 账号：与玩家同一个群登录码，只是换成主持人挑战端点。
  Future<Map<String, dynamic>> createHostChallenge() async =>
      jsonObject(await _createChallenge('/api/native/auth/host/challenges'));

  Future<Map<String, dynamic>> hostChallenge(String id) async => jsonObject(
        await _request(
            'GET', '/api/native/auth/host/challenges/${Uri.encodeComponent(id)}'),
      );

  /// 公告列表（任何已登录身份可读）。
  Future<({List<Announcement> announcements, String version})>
      announcements() async {
    final body = jsonObject(await _request('GET', '/api/announcements'));
    return (
      announcements: jsonArray(body['announcements'], 'announcements')
          .map(Announcement.fromJson)
          .toList(growable: false),
      version: body['announcements_version']?.toString() ?? '',
    );
  }

  Future<Announcement> createAnnouncement({
    required String title,
    required String body,
  }) async =>
      Announcement.fromJson(await _request(
        'POST',
        '/api/announcements',
        body: {'title': title, 'body': body},
      ));

  Future<Announcement> updateAnnouncement(
    String announcementId, {
    required String title,
    required String body,
  }) async =>
      Announcement.fromJson(await _request(
        'POST',
        '/api/announcements/${Uri.encodeComponent(announcementId)}',
        body: {'title': title, 'body': body},
      ));

  Future<void> deleteAnnouncement(String announcementId) async {
    await _request(
      'DELETE',
      '/api/announcements/${Uri.encodeComponent(announcementId)}',
    );
  }

  /// 主持授权名单（4 级及以上）；grantable 是当前身份最多能授到的等级。
  Future<({List<HostAccount> hosts, int grantable})> hosts() async {
    final body = jsonObject(await _request('GET', '/api/hosts'));
    return (
      hosts: jsonArray(body['hosts'], 'hosts')
          .map(HostAccount.fromJson)
          .toList(growable: false),
      grantable: jsonInt(body['grantable'], 'grantable'),
    );
  }

  /// 按昵称或 QQ 号找账号。
  Future<List<HostAccount>> hostAccounts(String query) async => jsonArray(
        jsonObject(await _request('GET', '/api/hosts/accounts',
            query: {'q': query}))['accounts'],
        'accounts',
      ).map(HostAccount.fromJson).toList(growable: false);

  Future<HostAccount> authorizeHost(String accountId, int level) async =>
      HostAccount.fromJson(await _request(
        'POST',
        '/api/hosts/${Uri.encodeComponent(accountId)}',
        body: {'level': level},
      ));

  Future<void> revokeHost(String accountId) async {
    await _request('DELETE', '/api/hosts/${Uri.encodeComponent(accountId)}');
  }

  /// 成就目录：玩家用它对照自己获得的成就，主持人用它挑要授权的成就。
  Future<List<AchievementDef>> achievementCatalog() async => jsonArray(
        jsonObject(await _request('GET', '/api/achievements/catalog'))[
            'achievements'],
        'achievements',
      ).map(AchievementDef.fromJson).toList(growable: false);

  Future<AchievementDef> createAchievement({
    required String name,
    required String detail,
    required int rarity,
  }) async =>
      AchievementDef.fromJson(await _request(
        'POST',
        '/api/achievements/defs',
        body: {'name': name, 'detail': detail, 'rarity': rarity},
      ));

  Future<AchievementDef> updateAchievement(
    String achievementId, {
    required String name,
    required String detail,
    required int rarity,
  }) async =>
      AchievementDef.fromJson(await _request(
        'POST',
        '/api/achievements/defs/${Uri.encodeComponent(achievementId)}',
        body: {'name': name, 'detail': detail, 'rarity': rarity},
      ));

  /// 删除定义会连同授权一起删掉，返回被移除的授权条数。
  Future<int> deleteAchievement(String achievementId) async {
    final body = jsonObject(await _request(
      'DELETE',
      '/api/achievements/defs/${Uri.encodeComponent(achievementId)}',
    ));
    return jsonInt(body['removed_grants'], 'removed_grants');
  }

  /// 总玩家列表（主持人）：最近的参赛顺序在前。
  Future<List<AchievementPlayer>> achievementPlayers() async => jsonArray(
        jsonObject(await _request('GET', '/api/achievements/players'))[
            'players'],
        'players',
      ).map(AchievementPlayer.fromJson).toList(growable: false);

  Future<AchievementGrant> grantAchievement(
    String accountId,
    String achievementId,
  ) async =>
      AchievementGrant.fromJson(await _request(
        'POST',
        '/api/achievements/players/${Uri.encodeComponent(accountId)}/grants',
        body: {'achievement_id': achievementId},
      ));

  Future<void> revokeAchievement(String grantId) async {
    await _request(
      'DELETE',
      '/api/achievements/grants/${Uri.encodeComponent(grantId)}',
    );
  }

  /// 自己获得的成就与佩戴中的那一个。
  Future<({List<AchievementGrant> achievements, EquippedAchievement? equipped})>
      myAchievements() async {
    final body = jsonObject(await _request('GET', '/api/achievements/me'));
    return (
      achievements: jsonArray(body['achievements'], 'achievements')
          .map(AchievementGrant.fromJson)
          .toList(growable: false),
      equipped: body['equipped'] == null
          ? null
          : EquippedAchievement.fromJson(body['equipped']),
    );
  }

  /// 佩戴成就；[grantId] 为空表示取消佩戴。返回佩戴后的结果。
  Future<EquippedAchievement?> equipAchievement(String? grantId) async {
    final body = jsonObject(await _request(
      'POST',
      '/api/achievements/me/equip',
      body: {'grant_id': grantId},
    ));
    return body['equipped'] == null
        ? null
        : EquippedAchievement.fromJson(body['equipped']);
  }

  /// 任何账号的公开摘要：总成就数 + 最稀有的 5 个。
  Future<AchievementSummary> achievementSummary(String accountId) async =>
      AchievementSummary.fromJson(await _request(
        'GET',
        '/api/achievements/accounts/${Uri.encodeComponent(accountId)}',
      ));

  /// 本局每个参与身份佩戴的成就：对局内昵称旁直接显示。
  Future<List<GameEquipped>> gameEquipped(String gameId) async => jsonArray(
        jsonObject(await _request(
          'GET',
          '/api/achievements/games/${Uri.encodeComponent(gameId)}/equipped',
        ))['participants'],
        'participants',
      ).map(GameEquipped.fromJson).toList(growable: false);

  /// 历史对局列表：最近结束的在前；[before] 传上一页最后一条的 ended_at。
  Future<({List<MatchSummary> matches, bool hasMore})> history({
    String? before,
    int limit = 20,
  }) async {
    final body = jsonObject(await _request(
      'GET',
      '/api/history',
      query: {'limit': '$limit', 'before': before},
    ));
    return (
      matches: jsonArray(body['matches'], 'history.matches')
          .map(MatchSummary.fromJson)
          .toList(growable: false),
      hasMore: jsonBool(body['has_more'], 'history.has_more'),
    );
  }

  /// 单局历史详情：结算、七个席位的两张角色牌与公开时间线。
  Future<MatchDetail> match(String matchId) async => MatchDetail.fromJson(
        await _request('GET', '/api/history/${Uri.encodeComponent(matchId)}'),
      );

  /// 删除一条历史对局；服务端只放行 4 级及以上的主持人。
  Future<void> deleteMatch(String matchId) async {
    await _request('DELETE', '/api/history/${Uri.encodeComponent(matchId)}');
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
          headers: {
            HttpHeaders.authorizationHeader: 'Bearer $token',
            // 实时长连接同样带版本 UA；入局门槛只依赖 REST，这里失败也不影响使用。
            HttpHeaders.userAgentHeader: clientUserAgent(),
          },
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
