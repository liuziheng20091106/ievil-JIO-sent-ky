import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api.dart';
import 'models.dart';

/// Windows 下 shared_preferences 与 flutter_secure_storage 的存放目录都取自
/// exe 版本资源里的 ProductName（缺失时才回退到 exe 文件名）。应用显示名从
/// seven_double_client 改成“魔法裁判”后，目录名随之改变，旧登录数据会留在旧目录。
/// 这里把旧目录的数据一次性搬到当前目录，避免用户重新填写服务器并重新登录。
/// 只补齐缺失的文件，不覆盖、不删除，因此可以重复执行。
/// [currentDirectory] 与 [legacyDirectory] 仅用于测试注入。
Future<void> migrateLegacyWindowsData({
  Directory? currentDirectory,
  Directory? legacyDirectory,
}) async {
  if (currentDirectory == null && !Platform.isWindows) return;
  const files = ['shared_preferences.json', 'flutter_secure_storage.dat'];
  try {
    final current = currentDirectory ?? await getApplicationSupportDirectory();
    // 调用 getApplicationSupportDirectory 会创建当前目录，因此用它来探测旧目录。
    final legacy = legacyDirectory ??
        Directory(p.join(current.parent.path, 'seven_double_client'));
    if (legacy.path == current.path || !legacy.existsSync()) return;
    for (final name in files) {
      final source = File(p.join(legacy.path, name));
      final target = File(p.join(current.path, name));
      if (source.existsSync() && !target.existsSync()) {
        await source.copy(target.path);
        debugPrint('已迁移旧登录数据：$name');
      }
    }
  } catch (failure) {
    // 迁移失败不应阻止启动；用户仍可重新填写服务器地址并登录。
    debugPrint('旧登录数据迁移跳过：$failure');
  }
}

class GameStore extends ChangeNotifier {
  GameStore._(this.preferences, this.secureStorage);

  static const _endpointKey = 'server_endpoint';
  static const _tokenKey = 'login_token';
  static const _actorKey = 'cached_actor';
  static const _gameKey = 'cached_game_id';

  final SharedPreferences preferences;
  final FlutterSecureStorage secureStorage;

  ServerEndpoint? endpoint;
  GameApi? api;
  Actor? actor;
  LobbyGame? lobbyGame;
  String? gameId;
  GameView? view;
  LiveConnection? live;

  /// 角色目录（id → 名称、好人技能、魔女化技能）；公开信息，用于角色详情与魔典说明。
  List<RoleInfo> roles = const <RoleInfo>[];
  List<String> defaultCodex = const <String>[];
  String connectionStatus = '未连接';
  String? error;
  bool restoring = true;
  bool writeBusy = false;
  bool hasMoreMessages = false;
  String messageScope = 'all';
  String selectedChannelId = 'public';
  List<GameMessage> messages = [];
  Map<String, dynamic>? challengeInfo;
  String? pendingPhaseKey;
  int newActionCount = 0;
  int warningCount = 0;
  int privateStateCount = 0;
  int unreadMessageCount = 0;

  Set<String>? _actionBaseline;
  String? _privateStateBaseline;
  String? _loadedPhaseKey;
  int _challengeGeneration = 0;

  /// 仅供测试与界面预览：直接注入已经准备好的状态，不触发网络与本地存储。
  static GameStore forPreview({
    required SharedPreferences preferences,
    required ServerEndpoint endpoint,
    required Actor actor,
    required GameView view,
    String? gameId,
    List<GameMessage> messages = const [],
    List<RoleInfo> roles = const [],
    List<String> defaultCodex = const [],
    LobbyGame? lobbyGame,
    FlutterSecureStorage? secureStorage,
  }) {
    final store = GameStore._(
      preferences,
      secureStorage ?? const FlutterSecureStorage(),
    );
    store._useEndpoint(endpoint);
    store.actor = actor;
    store.gameId = gameId;
    store.view = view;
    store.messages = [...messages];
    store.roles = roles;
    store.defaultCodex = defaultCodex;
    store.lobbyGame = lobbyGame;
    store.restoring = false;
    return store;
  }

  static Future<GameStore> create({
    SharedPreferences? preferences,
    FlutterSecureStorage? secureStorage,
  }) async {
    await migrateLegacyWindowsData();
    final store = GameStore._(
      preferences ?? await SharedPreferences.getInstance(),
      secureStorage ??
          const FlutterSecureStorage(
            aOptions: AndroidOptions(encryptedSharedPreferences: true),
          ),
    );
    await store._restore();
    return store;
  }

  Future<void> _restore() async {
    final savedEndpoint = preferences.getString(_endpointKey);
    if (savedEndpoint != null) {
      try {
        _useEndpoint(ServerEndpoint.parse(savedEndpoint));
      } on FormatException {
        await preferences.remove(_endpointKey);
      }
    }
    final cachedActor = preferences.getString(_actorKey);
    if (cachedActor != null) {
      try {
        actor = Actor.fromJson(jsonDecode(cachedActor));
        gameId = preferences.getString(_gameKey);
      } on FormatException {
        await preferences.remove(_actorKey);
      }
    }
    final token = await secureStorage.read(key: _tokenKey);
    if (api != null && token != null) {
      api!.token = token;
      try {
        final result = await api!.me();
        await _consumeSession(result, token: token);
      } on ApiException catch (failure) {
        if (failure.statusCode == 401) {
          await _clearSession();
        } else {
          error = failure.message;
        }
      }
    }
    restoring = false;
    notifyListeners();
    if (actor != null && gameId != null) {
      await enterGame(gameId!);
    } else if (actor != null) {
      await refreshLobby();
    }
  }

  /// 角色目录只读一次即可：它是服务端的静态公开信息。
  Future<void> loadCatalog() async {
    if (api == null || roles.isNotEmpty) {
      return;
    }
    try {
      final catalog = RoleCatalog.fromJson(await api!.catalog());
      roles = catalog.roles;
      defaultCodex = catalog.defaultCodex;
      notifyListeners();
    } catch (_) {
      // 目录取不到只影响角色详情与说明，不阻塞对局流程。
    }
  }

  RoleInfo? roleInfo(String? roleId) {
    if (roleId == null) return null;
    for (final role in roles) {
      if (role.id == roleId) return role;
    }
    return null;
  }

  Future<void> setEndpoint(String value) async {
    final parsed = ServerEndpoint.parse(value);
    await live?.stop();
    api?.close();
    _useEndpoint(parsed);
    await preferences.setString(_endpointKey, parsed.toString());
    error = null;
    notifyListeners();
    final token = await secureStorage.read(key: _tokenKey);
    if (token == null) return;
    api!.token = token;
    try {
      await _consumeSession(await api!.me(), token: token);
    } on ApiException catch (failure) {
      if (failure.statusCode == 401) await _clearSession();
      error = failure.message;
      notifyListeners();
    }
  }

  void _useEndpoint(ServerEndpoint value) {
    endpoint = value;
    api = GameApi(value);
  }

  Future<void> startPlayerLogin() async {
    if (api == null) return;
    final generation = ++_challengeGeneration;
    error = null;
    challengeInfo = await api!.createChallenge();
    notifyListeners();
    final id = jsonString(challengeInfo!['id'], 'challenge.id');
    while (generation == _challengeGeneration && challengeInfo != null) {
      await Future<void>.delayed(const Duration(seconds: 2));
      try {
        final result = await api!.challenge(id);
        if (generation != _challengeGeneration) return;
        if (result['status'] == 'completed') {
          final token =
              jsonString(result['session_token'], 'challenge.session_token');
          api!.token = token;
          await _consumeSession(
              jsonObject(result['session'], 'challenge.session'),
              token: token);
          challengeInfo = null;
          notifyListeners();
          await refreshLobby();
          return;
        }
        challengeInfo = {...challengeInfo!, ...result};
        final expiresAt =
            DateTime.tryParse(result['expires_at']?.toString() ?? '');
        if (result['status'] == 'expired' ||
            (expiresAt != null &&
                DateTime.now().toUtc().isAfter(expiresAt.toUtc()))) {
          error = '登录码已过期，请重新获取';
          challengeInfo = null;
          notifyListeners();
          return;
        }
        notifyListeners();
      } on ApiException catch (failure) {
        error = failure.message;
        notifyListeners();
        if (failure.statusCode == 404 || failure.statusCode == 410) {
          challengeInfo = null;
          return;
        }
      }
    }
  }

  Future<void> hostLogin(String password) async {
    if (api == null) return;
    error = null;
    try {
      final result = await api!.hostLogin(password);
      final token = jsonString(result['session_token'], 'login.session_token');
      api!.token = token;
      await _consumeSession(jsonObject(result['session'], 'login.session'),
          token: token);
      if (gameId != null) {
        await enterGame(gameId!);
      } else {
        await refreshLobby();
      }
    } on ApiException catch (failure) {
      error = failure.message;
      notifyListeners();
      rethrow;
    }
  }

  Future<void> _consumeSession(Map<String, dynamic> result,
      {required String token}) async {
    final value = result['actor'];
    actor = value == null ? null : Actor.fromJson(value);
    gameId = result['game_id']?.toString();
    await secureStorage.write(key: _tokenKey, value: token);
    if (actor != null) {
      await preferences.setString(_actorKey, jsonEncode(actor!.raw));
    } else {
      await preferences.remove(_actorKey);
    }
    if (gameId != null) {
      await preferences.setString(_gameKey, gameId!);
    } else {
      await preferences.remove(_gameKey);
    }
    notifyListeners();
  }

  Future<void> refreshLobby() async {
    if (api == null || actor == null) return;
    await loadCatalog();
    try {
      final result = await api!.lobby();
      lobbyGame =
          result['game'] == null ? null : LobbyGame.fromJson(result['game']);
      final participation = result['participation'];
      if (participation != null) {
        actor = Actor.fromJson(participation);
        gameId = lobbyGame?.id;
        await preferences.setString(_actorKey, jsonEncode(actor!.raw));
        if (gameId != null) await preferences.setString(_gameKey, gameId!);
      }
      error = null;
    } on ApiException catch (failure) {
      error = failure.message;
    }
    notifyListeners();
    if (gameId != null && view == null) await enterGame(gameId!);
  }

  /// 建局必须由主持人先确认 11 名魔典角色。
  Future<void> createGame(List<String> codex) async {
    if (api == null || !actor!.isHost || writeBusy) return;
    writeBusy = true;
    error = null;
    notifyListeners();
    try {
      final created = await api!.createGame(codex);
      gameId = created.id;
      view = created;
      await preferences.setString(_gameKey, gameId!);
      await enterGame(gameId!);
    } on ApiException catch (failure) {
      error = failure.message;
      rethrow;
    } finally {
      writeBusy = false;
      notifyListeners();
    }
  }

  Future<void> participate(String kind) async {
    final game = lobbyGame;
    if (api == null || game == null || writeBusy) return;
    writeBusy = true;
    error = null;
    notifyListeners();
    try {
      final result = await api!.participate(game.id, kind);
      actor = Actor.fromJson(result['actor']);
      gameId = jsonString(result['game_id'], 'participation.game_id');
      await preferences.setString(_actorKey, jsonEncode(actor!.raw));
      await preferences.setString(_gameKey, gameId!);
      await enterGame(gameId!);
    } on ApiException catch (failure) {
      error = failure.message;
      rethrow;
    } finally {
      writeBusy = false;
      notifyListeners();
    }
  }

  Future<void> enterGame(String id) async {
    if (api == null) return;
    gameId = id;
    try {
      await loadCatalog();
      _applyView(await api!.state(id));
      await loadMessages('all');
      await _startLive();
      error = null;
    } on ApiException catch (failure) {
      error = failure.message;
    } on FormatException catch (failure) {
      error = failure.message;
    }
    notifyListeners();
  }

  Future<void> _startLive() async {
    final endpoint = this.endpoint;
    final token = api?.token;
    if (endpoint == null || token == null) return;
    await live?.stop();
    live = LiveConnection(
      endpoint: endpoint,
      token: token,
      onEvent: _onLiveEvent,
      onConnected: catchUpMessages,
      onStatus: (status) {
        connectionStatus = status;
        notifyListeners();
      },
    )..start();
  }

  void _onLiveEvent(Map<String, dynamic> event) {
    try {
      switch (event['type']) {
        case 'sync':
          _applyView(GameView.fromJson(event['state']));
          final incoming = jsonArray(event['messages'], 'sync.messages')
              .map(GameMessage.fromJson);
          _mergeMessages(incoming);
        case 'state':
          _applyView(GameView.fromJson(event['state']));
        case 'message':
          final message = GameMessage.fromJson(event['message']);
          if (_matchesScope(message, messageScope)) _mergeMessages([message]);
          if (message.id > _readCursor) unreadMessageCount++;
      }
    } on FormatException catch (failure) {
      error = failure.message;
    }
    notifyListeners();
  }

  void _applyView(GameView next) {
    final actionKeys = next.allActions.map((item) => item.protocolKey).toSet();
    final actionPreference = _preferenceKey('actions_seen');
    if (_actionBaseline == null) {
      final saved = preferences.getStringList(actionPreference);
      _actionBaseline = saved?.toSet() ?? actionKeys;
      if (saved == null) {
        preferences.setStringList(actionPreference, actionKeys.toList());
      }
    } else {
      newActionCount = actionKeys.difference(_actionBaseline!).length;
    }

    final warning = next.self['warning_deadline'] != null
        ? 1
        : (next.host['tasks'] is List
            ? (next.host['tasks'] as List).length
            : 0);
    warningCount = warning;

    final privateKey = jsonEncode({
      'cards': next.self['cards'],
      'current_card_id': next.self['current_card_id'],
    });
    if (_privateStateBaseline == null) {
      _privateStateBaseline = privateKey;
    } else if (_privateStateBaseline != privateKey) {
      privateStateCount = 1;
    }

    final phaseKey = '${next.id}:${next.day}:${next.half}:${next.phase}';
    final phasePreference = _preferenceKey('phase_seen');
    final seenPhase = preferences.getString(phasePreference);
    if (seenPhase == null || _loadedPhaseKey == null) {
      // 首次同步或重连：只建立基线，不把当前阶段当成刚发生的变化。
      _loadedPhaseKey = phaseKey;
      if (seenPhase != phaseKey) {
        preferences.setString(phasePreference, phaseKey);
      }
    } else if (seenPhase != phaseKey && pendingPhaseKey != phaseKey) {
      pendingPhaseKey = phaseKey;
    }

    view = next;
    if (next.channels.every((item) => item.id != selectedChannelId)) {
      selectedChannelId = 'public';
    }
  }

  Future<void> acknowledgePhase() async {
    final key = pendingPhaseKey;
    if (key == null) return;
    await preferences.setString(_preferenceKey('phase_seen'), key);
    pendingPhaseKey = null;
    notifyListeners();
  }

  Future<void> markActionsViewed() async {
    final keys = view?.allActions.map((item) => item.protocolKey).toSet() ?? {};
    _actionBaseline = keys;
    newActionCount = 0;
    await preferences.setStringList(
        _preferenceKey('actions_seen'), keys.toList());
    notifyListeners();
  }

  void markPrivateViewed() {
    _privateStateBaseline = jsonEncode({
      'cards': view?.self['cards'],
      'current_card_id': view?.self['current_card_id'],
    });
    privateStateCount = 0;
    notifyListeners();
  }

  Future<void> loadMessages(String scope) async {
    final id = gameId;
    if (api == null || id == null) return;
    messageScope = scope;
    try {
      final page = await api!.messages(id, scope: scope);
      messages = page.messages;
      hasMoreMessages = page.hasMore;
      error = null;
    } on ApiException catch (failure) {
      error = failure.message;
    }
    notifyListeners();
  }

  Future<void> loadOlderMessages() async {
    if (!hasMoreMessages || messages.isEmpty || gameId == null) return;
    try {
      final page = await api!.messages(
        gameId!,
        scope: messageScope,
        before: messages.first.id,
      );
      _mergeMessages(page.messages);
      hasMoreMessages = page.hasMore;
    } on ApiException catch (failure) {
      error = failure.message;
    }
    notifyListeners();
  }

  Future<void> catchUpMessages() async {
    if (api == null || gameId == null) return;
    final after = messages.isEmpty ? 0 : messages.last.id;
    try {
      final page =
          await api!.messages(gameId!, scope: messageScope, after: after);
      _mergeMessages(page.messages);
    } on ApiException catch (failure) {
      error = failure.message;
    }
    notifyListeners();
  }

  void _mergeMessages(Iterable<GameMessage> incoming) {
    final indexed = {for (final item in messages) item.id: item};
    for (final item in incoming) {
      if (_matchesScope(item, messageScope)) indexed[item.id] = item;
    }
    messages = indexed.values.toList()..sort((a, b) => a.id.compareTo(b.id));
  }

  bool _matchesScope(GameMessage message, String scope) => switch (scope) {
        'public' => message.channelId == 'public',
        'system' => message.channelId == 'system' || message.kind != 'chat',
        'host' => message.channelId != 'public' &&
            message.channelId != 'system' &&
            (view?.channels.any((channel) =>
                    channel.id == message.channelId &&
                    channel.members.any((member) => member['id'] == 'host')) ??
                false),
        'private' => message.channelId != 'public' &&
            message.channelId != 'system' &&
            !(view?.channels.any((channel) =>
                    channel.id == message.channelId &&
                    channel.members.any((member) => member['id'] == 'host')) ??
                false),
        _ => true,
      };

  Future<void> markMessagesRead() async {
    if (messages.isNotEmpty) {
      await preferences.setInt(
          _preferenceKey('messages_read_$messageScope'), messages.last.id);
    }
    unreadMessageCount = 0;
    notifyListeners();
  }

  int get _readCursor =>
      preferences.getInt(_preferenceKey('messages_read_$messageScope')) ?? 0;

  void selectChannel(String channelId) {
    selectedChannelId = channelId;
    notifyListeners();
  }

  GameChannel? get selectedChannel {
    for (final channel in view?.channels ?? const <GameChannel>[]) {
      if (channel.id == selectedChannelId) return channel;
    }
    return null;
  }

  Future<void> sendMessage(String text) async {
    final id = gameId;
    if (api == null || id == null || writeBusy || text.trim().isEmpty) return;
    writeBusy = true;
    error = null;
    notifyListeners();
    try {
      final message =
          await api!.sendMessage(id, selectedChannelId, text.trim());
      _mergeMessages([message]);
    } on ApiException catch (failure) {
      error = failure.message;
      await _reconcileAfterWriteFailure();
      rethrow;
    } finally {
      writeBusy = false;
      notifyListeners();
    }
  }

  Future<GameView> seatPerspective(String seatId) async {
    final id = gameId;
    if (api == null || id == null) throw const ApiException('当前没有可读取的对局');
    return api!.seatPerspective(id, seatId);
  }

  Future<void> execute(
    ActionDescriptor action,
    Map<String, dynamic> values, {
    String? asSeat,
  }) async {
    final id = gameId;
    final current = view;
    if (api == null || id == null || current == null || writeBusy) return;
    final unsupported = action.unsupportedReason;
    if (unsupported != null) throw ApiException(unsupported);
    writeBusy = true;
    error = null;
    notifyListeners();
    try {
      final payload = <String, dynamic>{...action.payload, ...values};
      _applyView(await api!.command(
        id,
        expectedVersion: current.version,
        action: action.id,
        payload: payload,
        asSeat: asSeat,
      ));
      await clearDraft(action, asSeat: asSeat);
    } on ApiException catch (failure) {
      error = failure.message;
      await _reconcileAfterWriteFailure();
      rethrow;
    } finally {
      writeBusy = false;
      notifyListeners();
    }
  }

  Future<void> _reconcileAfterWriteFailure() async {
    if (api == null || gameId == null) return;
    try {
      _applyView(await api!.state(gameId!));
      await catchUpMessages();
    } catch (_) {
      // Keep the original write error and never replay an uncertain write.
    }
  }

  String draftKey(ActionDescriptor action, {String? asSeat}) {
    final current = view;
    return jsonEncode([
      endpoint.toString(),
      gameId,
      actor?.accountId,
      asSeat ?? actor?.id,
      action.id.startsWith('channel.') ? selectedChannelId : action.id,
      current?.day,
      current?.half,
      current?.phase,
      action.id,
      action.payload,
    ]);
  }

  Map<String, dynamic> draftFor(ActionDescriptor action, {String? asSeat}) {
    final encoded =
        preferences.getString('draft:${draftKey(action, asSeat: asSeat)}');
    if (encoded == null) return {};
    try {
      return jsonObject(jsonDecode(encoded), 'draft');
    } on FormatException {
      return {};
    }
  }

  Future<void> saveDraft(
    ActionDescriptor action,
    Map<String, dynamic> values, {
    String? asSeat,
  }) async {
    await preferences.setString(
        'draft:${draftKey(action, asSeat: asSeat)}', jsonEncode(values));
  }

  Future<void> clearDraft(ActionDescriptor action, {String? asSeat}) async {
    await preferences.remove('draft:${draftKey(action, asSeat: asSeat)}');
  }

  String _preferenceKey(String suffix) =>
      '${endpoint ?? ''}:${gameId ?? ''}:${actor?.accountId ?? ''}:$suffix';

  Future<void> logout() async {
    _challengeGeneration++;
    try {
      await api?.logout();
    } catch (_) {
      // Local logout still removes the credential when the server is unreachable.
    }
    await _clearSession();
    notifyListeners();
  }

  Future<void> _clearSession() async {
    await live?.stop();
    live = null;
    api?.token = null;
    await secureStorage.delete(key: _tokenKey);
    await preferences.remove(_actorKey);
    await preferences.remove(_gameKey);
    actor = null;
    gameId = null;
    lobbyGame = null;
    view = null;
    messages = [];
    challengeInfo = null;
    _actionBaseline = null;
    _privateStateBaseline = null;
    _loadedPhaseKey = null;
    connectionStatus = '未连接';
  }

  @override
  void dispose() {
    _challengeGeneration++;
    live?.stop();
    api?.close();
    super.dispose();
  }
}
