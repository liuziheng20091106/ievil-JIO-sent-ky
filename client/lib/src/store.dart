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
    // 这里是应用启动路径：任何异常（存储读取失败、服务器响应形状异常、
    // 网络栈抛出的非预期类型）都不允许漏到 GameStore.create() 之外，
    // 否则 main() 里 await create() 会直接白屏退出且无法自愈。
    try {
      await _restoreInner();
    } catch (failure) {
      error = '恢复登录状态失败：$failure';
      restoring = false;
      notifyListeners();
    }
  }

  Future<void> _restoreInner() async {
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
      } on FormatException catch (failure) {
        // 服务器返回了客户端不认识的形状：宁可当作未登录处理也不崩溃，
        // 但保留本地绑定，下一次手动刷新还能恢复。
        error = '登录状态异常：${failure.message}';
      }
    }
    // 上次已经回到主界面的对局，不该在重启后被重新拉回：服务器那边这一局仍是
    // 当前局，只有本客户端知道用户已经离开，所以在这里按服务器的当前局清掉绑定。
    if (actor != null && gameId != null && await lobbyHasNoGame()) {
      gameId = null;
      await preferences.remove(_gameKey);
    }
    restoring = false;
    notifyListeners();
    if (actor != null && gameId != null) {
      await enterGame(gameId!);
    } else if (actor != null) {
      await refreshLobby();
    }
  }

  /// 服务器是否已经没有进行中的对局（已结束、被初始化，或尚未建局）。
  /// 离线或取不到大厅时返回 false，宁可保留本地绑定也不误清。
  Future<bool> lobbyHasNoGame() async {
    if (api == null) return false;
    try {
      final result = await api!.lobby();
      if (result['game'] == null) return true;
      return jsonString(
            jsonObject(result['game'], 'lobby.game')['status'],
            'lobby.game.status',
            fallback: '',
          ) ==
          'ended';
    } on ApiException {
      return false;
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
    Map<String, dynamic> info;
    try {
      info = await api!.createChallenge();
    } on ApiException catch (failure) {
      // 获取登录码是用户直接点击的动作：失败必须当场反馈，
      // 否则按钮恢复原状而界面毫无变化（此前该异常会被 main 吞掉）。
      if (generation == _challengeGeneration) {
        error = failure.message;
        notifyListeners();
      }
      return;
    } on FormatException catch (failure) {
      if (generation == _challengeGeneration) {
        error = '登录码响应异常：${failure.message}';
        notifyListeners();
      }
      return;
    }
    if (generation != _challengeGeneration) return;
    challengeInfo = info;
    notifyListeners();
    String id;
    try {
      id = jsonString(info['id'], 'challenge.id');
    } on FormatException catch (failure) {
      error = '登录码响应异常：${failure.message}';
      challengeInfo = null;
      notifyListeners();
      return;
    }
    // 网络持续故障时不能以 2 秒间隔无限轮询：连续失败 5 次、
    // 或总时长超过 10 分钟（远长于挑战有效期）就停下来报错。
    var consecutiveFailures = 0;
    final deadline = DateTime.now().add(const Duration(minutes: 10));
    while (generation == _challengeGeneration && challengeInfo != null) {
      if (DateTime.now().isAfter(deadline)) {
        error = '登录等待超时，请重新获取登录码';
        challengeInfo = null;
        notifyListeners();
        return;
      }
      await Future<void>.delayed(const Duration(seconds: 2));
      try {
        final result = await api!.challenge(id);
        consecutiveFailures = 0;
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
        if (generation != _challengeGeneration) return;
        error = failure.message;
        notifyListeners();
        if (failure.statusCode == 404 || failure.statusCode == 410) {
          challengeInfo = null;
          return;
        }
        if (++consecutiveFailures >= 5) {
          error = '网络持续异常，已停止等待登录码，请稍后重试';
          challengeInfo = null;
          notifyListeners();
          return;
        }
      } on FormatException catch (failure) {
        if (generation != _challengeGeneration) return;
        error = '登录码状态响应异常：${failure.message}';
        challengeInfo = null;
        notifyListeners();
        return;
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
    } on FormatException catch (failure) {
      // 主持人登录成功但响应形状异常：同样要反馈给界面而不是被 main 吞掉。
      error = '登录响应异常：${failure.message}';
      notifyListeners();
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
    } on FormatException catch (failure) {
      error = '服务器返回了无法解析的名单：${failure.message}';
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
    } on FormatException catch (failure) {
      error = '服务器返回了无法解析的对局：${failure.message}';
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
    } on FormatException catch (failure) {
      error = '服务器返回了无法解析的参与信息：${failure.message}';
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

  /// 从已终止的对局返回主界面：断开本局的只读视图与实时连接，回到大厅。
  /// 不改动服务器上的参与身份与记录，主持人建下一局时由服务器统一清空。
  Future<void> returnToLobby() async {
    await live?.stop();
    live = null;
    // 离开对局即清掉本机残留：草稿是明文（Windows 上还在漫游目录），
    // 角标与已读游标属于这一局，没有跨局保留的价值。
    await _purgeLocalData();
    gameId = null;
    view = null;
    messages = [];
    hasMoreMessages = false;
    selectedChannelId = 'public';
    messageScope = 'all';
    newActionCount = 0;
    warningCount = 0;
    privateStateCount = 0;
    unreadMessageCount = 0;
    pendingPhaseKey = null;
    _actionBaseline = null;
    _privateStateBaseline = null;
    _loadedPhaseKey = null;
    error = null;
    await preferences.remove(_gameKey);
    notifyListeners();
    await refreshLobby();
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

  /// 把一份可见状态当作刚刚同步进来的结果处理：与实时事件和命令返回走同一路径。
  /// 供回归检查使用，界面代码只调用 enterGame / execute 等动作入口。
  void applyView(GameView next) => _applyView(next);

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
    if (next.status == 'ended') {
      // 落幕不是新阶段：不再弹出阶段动画，也不留下待确认的阶段性提醒。
      _loadedPhaseKey = phaseKey;
      pendingPhaseKey = null;
      preferences.setString(phasePreference, phaseKey);
    } else if (seenPhase == null || _loadedPhaseKey == null) {
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
    } on FormatException catch (failure) {
      error = '服务器返回了无法解析的消息：${failure.message}';
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
      // 命令已被服务端接受：之后的本地清理失败不能把“已成功”呈现成失败，
      // 否则用户会重开表单再提交一次，造成重复行动。残留的草稿无害，
      // 下次打开表单时还能看到并手动清掉。
      try {
        await clearDraft(action, asSeat: asSeat);
      } catch (_) {
        // 草稿清理是尽力而为。
      }
    } on ApiException catch (failure) {
      error = failure.message;
      await _reconcileAfterWriteFailure();
      rethrow;
    } on FormatException catch (failure) {
      // 命令可能已经生效，但返回的形状客户端读不懂：刷新状态并提示，
      // 不允许异常漏出去把表单卡在提交中。
      error = '服务器返回了无法解析的状态：${failure.message}';
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
    await _purgeLocalData();
    await _clearSession();
    notifyListeners();
  }

  /// 删除本端点上该账号遗留在本机的数据：私密草稿、阶段/行动已读基线与
  /// 消息游标。草稿只应在“提交成功”时清除是写入侧的规则；登出与对局结束
  /// 属于会话终结，此时把残留的明文草稿一并清掉，避免在
  /// shared_preferences（Windows 上是漫游目录）里永久累积私密内容。
  /// 替换者（不同的 accountId）的键本来就不同，不受影响。
  ///
  /// 键形状：draft 键是 `draft:<json [endpoint, gameId, accountId, …]>`；
  /// 偏好键是 `endpoint:gameId:account:suffix`（gameId/account 不含冒号）。
  /// 按端点 + 账号匹配、跨对局清理：账号登出时他在任何对局的残留都不该留。
  Future<void> _purgeLocalData({String? accountId}) async {
    final account = accountId ?? actor?.accountId;
    final origin = endpoint?.toString();
    if (account == null || origin == null) return;
    final doomed = <String>[];
    for (final key in preferences.getKeys()) {
      if (key.startsWith('draft:')) {
        try {
          final parts = jsonDecode(key.substring('draft:'.length));
          if (parts is List &&
              parts.length >= 3 &&
              parts[0].toString() == origin &&
              parts[2]?.toString() == account) {
            doomed.add(key);
          }
        } on FormatException {
          // 键损坏：一并清掉。
          doomed.add(key);
        }
      } else {
        // origin 自身含冒号（http://…），gameId/account 不含，因此贪婪的
        // 第一组能吃下完整 origin，随后两组分别对上 gameId 与 account。
        final match =
            RegExp('^(.+):([^:]*):([^:]*):(.+)\$').firstMatch(key);
        if (match != null &&
            match.group(1) == origin &&
            match.group(3) == account) {
          doomed.add(key);
        }
      }
    }
    for (final key in doomed) {
      try {
        await preferences.remove(key);
      } catch (_) {
        // 单个键删除失败不影响其余清理。
      }
    }
  }

  Future<void> _clearSession() async {
    await live?.stop();
    live = null;
    api?.token = null;
    // 存储层故障（或测试环境的插件桩）不允许中断登出：
    // 令牌删不掉时宁可让本地状态先恢复一致，下一次启动仍会重试删除。
    try {
      await secureStorage.delete(key: _tokenKey);
    } catch (_) {
      // 登出仍要继续。
    }
    try {
      await preferences.remove(_actorKey);
      await preferences.remove(_gameKey);
    } catch (_) {
      // 本地偏好删除失败不阻塞登出。
    }
    actor = null;
    gameId = null;
    lobbyGame = null;
    view = null;
    messages = [];
    challengeInfo = null;
    _actionBaseline = null;
    _privateStateBaseline = null;
    _loadedPhaseKey = null;
    // 登出后 1.45 秒内重登不该凭空重播旧对局的阶段动画，
    // 角标计数也不该带着旧对局的残留进入新会话。
    pendingPhaseKey = null;
    newActionCount = 0;
    warningCount = 0;
    privateStateCount = 0;
    unreadMessageCount = 0;
    hasMoreMessages = false;
    messageScope = 'all';
    selectedChannelId = 'public';
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
