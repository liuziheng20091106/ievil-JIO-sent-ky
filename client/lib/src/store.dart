import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api.dart';
import 'keepalive.dart';
import 'models.dart';
import 'player_marks.dart';

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

  /// 已读公告的内容哈希（sha256）：跨重启保留，公告改了内容就重新算未读。
  static const _announcementReadKey = 'announcement_read_hashes';

  /// 已同意的用户协议：键按服务地址隔离，值是协议内容的 sha256。
  static const _agreementKeyPrefix = 'agreement_accepted:';

  final SharedPreferences preferences;
  final FlutterSecureStorage secureStorage;

  ServerEndpoint? endpoint;
  GameApi? api;
  Actor? actor;
  LobbyGame? lobbyGame;
  String? gameId;
  GameView? view;
  LiveConnection? live;

  /// 返回大厅期间置位：服务器仍把已终止的对局当作当前局返回（被移出者
  /// 的 me() 也可能带旧绑定），此时本地已明确离开，_consumeSession 与
  /// refreshLobby 都不得用服务器的当前局 gameId 把用户拉回对局。
  bool _stayingInLobby = false;

  /// 正在向服务器核对当前参与身份（观战接管席位后的兜底），避免重复请求。
  bool _reconcilingActor = false;

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

  /// 傀儡代发身份与频道：选中某个受控傀儡席位的频道后，发送身份切到该席位。
  /// 与自己的 [selectedChannelId] 分开存放，两条身份的频道选择与草稿永不互相串用。
  String? puppetSeatId;
  String selectedPuppetChannelId = 'public';

  /// 在线账号（不含自己的过滤在界面层做）与发给我的待处理邀请。
  List<OnlineAccount> online = const <OnlineAccount>[];
  List<LobbyInvite> invites = const <LobbyInvite>[];

  /// 公告：大厅轮询顺带更新。已读状态按每条公告的 sha256 记在本地偏好里，
  /// 公告内容一变（哈希变）就会重新算作未读。
  List<Announcement> announcements = const <Announcement>[];
  String announcementsVersion = '';
  Set<String> readAnnouncementHashes = <String>{};

  List<Announcement> get unreadAnnouncements => [
        for (final item in announcements)
          if (!readAnnouncementHashes.contains(item.hash)) item,
      ];

  /// 服务端下发的用户协议：连接某个服务地址后拉一次，正文为空表示服务端没配协议。
  /// 同意记录按「服务地址 + 协议内容哈希」存在本机，协议改过就要重新同意。
  Agreement agreement = const Agreement();
  bool agreementLoading = false;

  /// 服务端在 `/api/online` 里回报的「有更新」：为真时 [updateFlag] 自增一次，
  /// 由 main.dart 转成「重新请求 /api/health 取版本字段」。
  bool updateAvailable = false;
  int updateFlag = 0;

  List<GameMessage> messages = [];
  Map<String, dynamic>? challengeInfo;
  String? pendingPhaseKey;

  /// 新到的私密信息：由外壳弹一条醒目横幅后清空。
  /// 私密信息不随筛选范围丢弃，登录/刷新时的历史也不重复提醒。
  GameMessage? pendingPrivateInfo;
  int? _privateInfoCursor;

  /// 本进程里被「稍后」掉的悬浮对话框 id：服务端仍会下发这条，客户端不再自动弹。
  /// 只放在内存：换局清空，重开应用会重新提醒一次未处理的内容。
  final Set<String> _dismissedDialogs = <String>{};

  /// 当前该弹的悬浮对话框（服务端下发、去掉本机已忽略的），第一条优先。
  List<DialogItem> get activeDialogs => [
        for (final item in view?.dialogs ?? const <DialogItem>[])
          if (!_dismissedDialogs.contains(item.id)) item,
      ];

  /// 「稍后」：本条对话框不再自动弹，内容本身仍留在状态页与频道列表里。
  void dismissDialog(String id) {
    if (!_dismissedDialogs.add(id)) return;
    notifyListeners();
  }

  /// 本局各参与身份佩戴的成就，以及参与者 id 到账号 id 的映射。
  /// 服务端单独下发（成就是独立于对局规则的库），取不到就当没有徽章。
  /// 主持人也占一行（id 固定为 "host"，成就与它的玩家身份同源）。
  Map<String, EquippedAchievement> equippedAchievements = const {};
  Map<String, String> participantAccounts = const {};

  /// 主持人是否已确认进入本局管理界面：每一局都要主持人自己确认一次，
  /// 启动应用或换局都不会自动进管理界面。
  bool hostAdminEntered = false;

  /// 进入管理界面后服务端给的提示：不是建局主持人时说明已发本局系统公告。
  String? hostAdminNotice;

  /// 主动离开观战期间置位：服务端解除身份后会把旧连接按 4401 终结，
  /// 但那是本人主动退出，不该被当成身份失效而清掉会话。
  bool _leavingByChoice = false;

  /// 上一次为哪批参与身份取过佩戴信息：候场期间陆续有人入席就再补一次，
  /// 避免为同一批人反复请求。
  Set<String> _equippedRequested = const {};

  /// 下层牌刚登场（下层登场、复活、换牌）或开局锁定上层牌时，
  /// 待展示的角色 id；由 GameShell 弹一次角色卡介绍后清空。
  String? pendingRoleId;

  /// [pendingRoleId] 要展示的是「开局 · 上层牌」教程还是「新角色登场」介绍；
  /// 与它同时被 GameShell 取走，不留给下一帧。
  bool pendingRoleIntroOpening = false;

  /// 玩家标记（参与者 id → 标记）：只是本机笔记，见 [PlayerMark]。
  /// 不落盘、不上传，登出或回大厅即清空。
  Map<String, PlayerMark> playerMarks = const {};

  /// 本局是否已经展示过「如何标记他人」教程：同一局只固定展示一次。
  bool marksTutorialShown = false;

  /// 首个非平安夜结束后置位，由 GameShell 弹一次教程并清空。
  bool pendingMarksTutorial = false;

  /// 教程判定所属的对局：换局时要重新固定展示一次。
  String? _marksGameId;
  int newActionCount = 0;
  int warningCount = 0;
  int privateStateCount = 0;
  int unreadMessageCount = 0;

  Set<String>? _actionBaseline;
  String? _privateStateBaseline;
  String? _loadedPhaseKey;
  String? _ownCardBaseline;

  /// 上一次同步的对局状态：用来认出「候场 → 开局」这一刻（上层牌刚锁定）。
  String? _statusBaseline;
  Set<String>? _inviteBaseline;
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
    // 已读公告的哈希跨重启保留：重启后不该把看过的公告又标成未读。
    readAnnouncementHashes =
        (preferences.getStringList(_announcementReadKey) ?? const <String>[])
            .toSet();
    final savedEndpoint = preferences.getString(_endpointKey);
    if (savedEndpoint != null) {
      try {
        _useEndpoint(ServerEndpoint.parse(savedEndpoint));
        // 恢复期间就顺带把协议拉回来：登录前才会用到，这里不阻塞下面恢复会话。
        unawaited(loadAgreement());
      } on FormatException {
        await preferences.remove(_endpointKey);
        agreementLoading = false;
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
    // 换服务器要重新过协议门：先把新地址的协议拉回来（拉到之前门显示加载中）。
    unawaited(loadAgreement());
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

  /// 「取消连接」：清掉已保存的服务地址并回到地址输入页；不写任何同意记录。
  Future<void> clearEndpoint() async {
    await live?.stop();
    api?.close();
    await preferences.remove(_endpointKey);
    endpoint = null;
    api = null;
    agreement = const Agreement();
    agreementLoading = false;
    error = null;
    notifyListeners();
  }

  void _useEndpoint(ServerEndpoint value) {
    endpoint = value;
    api = GameApi(value);
    // 协议还没拉回来之前先让协议门显示加载中，避免先闪一下登录页。
    agreement = const Agreement();
    agreementLoading = true;
  }

  /// 拉取服务端用户协议。取不到时按「没有协议」放行：不能因为服务端没配好就进不去。
  Future<void> loadAgreement() async {
    final client = api;
    if (client == null) {
      agreementLoading = false;
      notifyListeners();
      return;
    }
    agreementLoading = true;
    notifyListeners();
    try {
      agreement = await client.agreement();
    } on ApiException {
      agreement = const Agreement();
    } on FormatException {
      agreement = const Agreement();
    }
    agreementLoading = false;
    notifyListeners();
  }

  /// 协议门是否需要拦下用户：只有「登录前 + 服务端配了协议 + 这一版还没同意」才拦。
  /// 已经登录的用户不再被协议打断（对局中尤其不能）。
  bool get agreementPending =>
      actor == null &&
      (agreementLoading ||
          (!agreement.isEmpty && !agreement.acceptedBy(_acceptedAgreementHash)));

  /// 已经同意过的协议哈希（按服务地址隔离）。
  String? get _acceptedAgreementHash {
    final current = endpoint;
    if (current == null) return null;
    return preferences.getString('$_agreementKeyPrefix$current');
  }

  /// 「同意并继续」：记住这个服务地址下已经同意的协议版本。
  Future<void> acceptAgreement() async {
    final current = endpoint;
    if (current == null || agreement.isEmpty) return;
    await preferences.setString('$_agreementKeyPrefix$current', agreement.hash);
    notifyListeners();
  }

  Future<void> startPlayerLogin() => _startLogin(host: false);

  /// 主持人登录：与玩家同一套群登录码，只是走主持人挑战端点。
  /// 没有授权的账号会在核销后被服务端拒绝，并在这里显示原因。
  Future<void> startHostLogin() => _startLogin(host: true);

  Future<void> _startLogin({required bool host}) async {
    if (api == null) return;
    final generation = ++_challengeGeneration;
    error = null;
    Map<String, dynamic> info;
    try {
      info = host ? await api!.createHostChallenge() : await api!.createChallenge();
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
        final result =
            host ? await api!.hostChallenge(id) : await api!.challenge(id);
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

  Future<void> _consumeSession(Map<String, dynamic> result,
      {required String token}) async {
    final value = result['actor'];
    actor = value == null ? null : Actor.fromJson(value);
    // 返回大厅期间不采纳服务器的当前局绑定，否则会被拉回已离开的对局。
    gameId = _stayingInLobby ? null : result['game_id']?.toString();
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
      invites = jsonArray(result['invites'] ?? const <dynamic>[], 'lobby.invites')
          .map(LobbyInvite.fromJson)
          .toList(growable: false);
      // 大厅轮询顺带取公告：版本号变了才重建列表，避免每 5 秒刷新一次列表状态。
      final version = result['announcements_version']?.toString() ?? '';
      if (version != announcementsVersion) {
        announcementsVersion = version;
        announcements = jsonArray(
                result['announcements'] ?? const <dynamic>[],
                'lobby.announcements')
            .map(Announcement.fromJson)
            .toList(growable: false);
      }
      _announceNewInvites();
      final participation = result['participation'];
      if (participation != null) {
        actor = Actor.fromJson(participation);
        // 返回大厅期间不重新绑定对局：被移出/已离开的用户应留在大厅，
        // 不被服务器的当前局参与身份拉回。
        gameId = _stayingInLobby ? null : lobbyGame?.id;
        await preferences.setString(_actorKey, jsonEncode(actor!.raw));
        if (gameId != null) {
          await preferences.setString(_gameKey, gameId!);
        } else {
          await preferences.remove(_gameKey);
        }
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

  /// 拉一次公告列表（公告页与公告管理页用）；大厅轮询也会顺带更新它。
  Future<void> loadAnnouncements() async {
    final client = api;
    if (client == null || actor == null) return;
    try {
      final result = await client.announcements();
      announcementsVersion = result.version;
      announcements = result.announcements;
      notifyListeners();
    } on ApiException {
      // 公告取不到不影响对局与大厅的其它功能。
    } on FormatException {
      // 同上。
    }
  }

  /// 记一条公告为已读：只存内容哈希，不保存公告正文。
  Future<void> markAnnouncementRead(Announcement item) async {
    if (item.hash.isEmpty || readAnnouncementHashes.contains(item.hash)) return;
    readAnnouncementHashes = {...readAnnouncementHashes, item.hash};
    notifyListeners();
    await preferences.setStringList(
      _announcementReadKey,
      readAnnouncementHashes.toList(growable: false),
    );
  }

  Future<void> markAllAnnouncementsRead() async {
    final hashes = {
      ...readAnnouncementHashes,
      for (final item in announcements)
        if (item.hash.isNotEmpty) item.hash,
    };
    if (hashes.length == readAnnouncementHashes.length) return;
    readAnnouncementHashes = hashes;
    notifyListeners();
    await preferences.setStringList(
      _announcementReadKey,
      readAnnouncementHashes.toList(growable: false),
    );
  }

  /// 新到的邀请发一次系统通知（仅 Android 生效，其他平台是空操作）。
  void _announceNewInvites() {
    for (final invite in freshInvites(_inviteBaseline, invites)) {
      KeepAlive.notifyInvite(invite.fromName);
    }
    _inviteBaseline = invites.map((invite) => invite.id).toSet();
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

  /// 在线名单是辅助信息：取不到时保留上一次结果，不打断对局界面。
  /// 顺带收下服务端回报的「有更新」：为真时由 main.dart 去重新请求 /api/health。
  Future<void> loadOnline({String? gameId}) async {
    if (api == null || actor == null) return;
    try {
      final result = await api!.online(gameId: gameId);
      online = jsonArray(result['accounts'] ?? const <dynamic>[], 'online.accounts')
          .map(OnlineAccount.fromJson)
          .toList(growable: false);
      _noteUpdateFlag(
          jsonBool(result['update_available'], 'online.update_available'));
    } on ApiException {
      // 忽略：下个轮询周期会重试。
    } on FormatException {
      online = const <OnlineAccount>[];
    }
    notifyListeners();
  }

  /// 「有更新」只在 false→true 的跳变时自增一次：大厅每 5 秒轮询一次，
  /// 每轮都自增会让上层反复请求 health。
  void _noteUpdateFlag(bool value) {
    if (value == updateAvailable) return;
    updateAvailable = value;
    if (value) updateFlag++;
  }

  Future<void> inviteAccount(String accountId) async {
    final id = view?.id ?? lobbyGame?.id;
    if (api == null || id == null || writeBusy) return;
    writeBusy = true;
    error = null;
    notifyListeners();
    try {
      await api!.invite(id, accountId);
      await loadOnline(gameId: id);
    } on ApiException catch (failure) {
      error = failure.message;
      rethrow;
    } finally {
      writeBusy = false;
      notifyListeners();
    }
  }

  /// 接受邀请：服务端仍会校验是否已「开放加入」，被拒时按失败提示。
  Future<void> acceptInvite(String inviteId) async {
    if (api == null || writeBusy) return;
    writeBusy = true;
    error = null;
    notifyListeners();
    try {
      final result = await api!.acceptInvite(inviteId);
      actor = Actor.fromJson(result['actor']);
      gameId = jsonString(result['game_id'], 'accept.game_id');
      invites = const <LobbyInvite>[];
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

  Future<void> rejectInvite(String inviteId) async {
    if (api == null || writeBusy) return;
    writeBusy = true;
    error = null;
    notifyListeners();
    try {
      await api!.rejectInvite(inviteId);
      await refreshLobby();
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
    // 换局要重新确认进入管理界面：上一局的确认不能带到这一局。
    if (gameId != id) {
      hostAdminEntered = false;
      hostAdminNotice = null;
      // 上一局的标记与教程也不属于这一局。
      _resetPlayerMarks();
    }
    // 上一轮主动退出的 4401 已经过去，重新进局后恢复正常判定。
    _leavingByChoice = false;
    gameId = id;
    try {
      await loadCatalog();
      _applyView(await api!.state(id));
      await loadMessages('all');
      await _startLive();
      error = null;
    } on ApiException catch (failure) {
      if (failure.statusCode == 401) {
        // 身份失效/被移出对局：清会话回登录页，保留提示说明原因。
        await _clearSession();
        error = failure.message;
      } else {
        error = failure.message;
      }
    } on FormatException catch (failure) {
      error = failure.message;
    }
    notifyListeners();
  }

  /// 本局某参与身份佩戴的成就；没有佩戴或还没取到时为 null。
  EquippedAchievement? equippedFor(String? participantId) =>
      participantId == null ? null : equippedAchievements[participantId];

  /// 主持人确认进入本局管理界面。管理界面含全部私密信息与席位代操作，
  /// 而且不是建立这一局的主持人进入时服务端会发本局系统公告，所以必须由主持人
  /// 自己确认一次：确认成功才真正展开管理页，失败时返回错误文案。
  Future<String?> enterHostAdmin() async {
    final client = api;
    final id = gameId;
    if (client == null || id == null) return '当前没有可进入的对局';
    try {
      final result = await client.enterHostAdmin(id);
      hostAdminEntered = true;
      hostAdminNotice = result.owner
          ? null
          : '你不是本局的建局主持人（${result.ownerName}）；本次进入已向本局发布系统公告，'
              '管理操作请交给本局主持人。';
      notifyListeners();
      return null;
    } on ApiException catch (failure) {
      return failure.message;
    } on FormatException catch (failure) {
      return failure.message;
    }
  }

  /// 观战席主动退出：先断开实时连接（服务端解除身份后会把旧连接按 4401 终结，
  /// 而 4401 在客户端语义里等于「身份失效」），再让服务端解除观战身份并回大厅。
  /// 占席玩家的退出仍由主持人裁量，服务端会拒绝这里。
  Future<void> leaveGame() async {
    final client = api;
    final id = gameId;
    if (client == null || id == null) return;
    // 关闭连接的回执可能晚于这次退出流程本身，所以标记留到下一次进局再清。
    _leavingByChoice = true;
    await live?.stop();
    live = null;
    await client.leaveGame(id);
    await returnToLobby();
  }

  /// 参与者 id 对应的账号 id：点头像看成就摘要时用它查公开摘要。
  String? accountFor(String? participantId) =>
      participantId == null ? null : participantAccounts[participantId];

  /// 某个参与身份的标记；没标记过返回 null。
  PlayerMark? markFor(String? participantId) =>
      participantId == null ? null : playerMarks[participantId];

  /// 设置或清除（[mark] 为 null）某个参与身份的标记。
  /// 只改本机内存，不发任何请求，也不触发规则判定。
  void setMark(String participantId, PlayerMark? mark) {
    final next = Map<String, PlayerMark>.from(playerMarks);
    if (mark == null) {
      next.remove(participantId);
    } else {
      next[participantId] = mark;
    }
    playerMarks = next;
    notifyListeners();
  }

  /// 取出「首个非平安夜」的教程展示请求：同一个对局只给一次。
  bool takeMarksTutorial() {
    if (!pendingMarksTutorial) return false;
    pendingMarksTutorial = false;
    marksTutorialShown = true;
    return true;
  }

  /// 标记与教程都只属于当前这一局：换局、回大厅、登出都清空。
  void _resetPlayerMarks() {
    playerMarks = const {};
    marksTutorialShown = false;
    pendingMarksTutorial = false;
    _marksGameId = null;
  }

  /// 拉取本局各参与身份佩戴的成就。失败只影响徽章与摘要，不打扰对局。
  Future<void> loadGameAchievements() async {
    final id = gameId;
    final client = api;
    if (client == null || id == null) return;
    try {
      final rows = await client.gameEquipped(id);
      final equipped = <String, EquippedAchievement>{};
      final accounts = <String, String>{};
      for (final row in rows) {
        if (row.accountId.isNotEmpty) {
          accounts[row.participantId] = row.accountId;
        }
        final badge = row.equipped;
        if (badge != null) equipped[row.participantId] = badge;
      }
      equippedAchievements = equipped;
      participantAccounts = accounts;
      notifyListeners();
    } on ApiException {
      // 服务端暂时读不到：维持现状，不影响对局操作。
    } on FormatException {
      // 同上。
    } catch (_) {
      // 这一处是不 await 的补充请求，任何传输层异常都不能冒成未捕获错误。
    }
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
    puppetSeatId = null;
    selectedPuppetChannelId = 'public';
    online = const <OnlineAccount>[];
    invites = const <LobbyInvite>[];
    messageScope = 'all';
    announcements = const <Announcement>[];
    announcementsVersion = '';
    equippedAchievements = const {};
    participantAccounts = const {};
    _equippedRequested = const {};
    hostAdminEntered = false;
    hostAdminNotice = null;
    _resetPlayerMarks();
    newActionCount = 0;
    warningCount = 0;
    privateStateCount = 0;
    unreadMessageCount = 0;
    pendingPhaseKey = null;
    pendingPrivateInfo = null;
    _privateInfoCursor = null;
    _actionBaseline = null;
    _privateStateBaseline = null;
    _loadedPhaseKey = null;
    pendingRoleId = null;
    pendingRoleIntroOpening = false;
    _ownCardBaseline = null;
    _statusBaseline = null;
    _inviteBaseline = null;
    error = null;
    await preferences.remove(_gameKey);
    // 本地已明确离开：接下来的会话/大厅刷新都不得用服务器的当前局
    // 绑定把用户拉回对局。
    _stayingInLobby = true;
    notifyListeners();
    try {
      // 回大厅前身份已失效（被移出/换了新局）：刷新只会再撞 401，
      // 直接清会话回登录页，由登录页展示身份失效提示。
      // 令牌读取失败（如预览/测试环境无安全存储插件）按无令牌处理。
      String? token;
      try {
        token = await secureStorage.read(key: _tokenKey);
      } catch (_) {
        token = null;
      }
      if (token == null || api == null) {
        if (api != null) {
          await _clearSession();
          error = '登录状态已失效，请重新登录';
        }
        return;
      }
      api!.token = token;
      try {
        await _consumeSession(await api!.me(), token: token);
      } on ApiException {
        await _clearSession();
        error = '登录状态已失效，请重新登录';
        return;
      }
      await refreshLobby();
    } finally {
      _stayingInLobby = false;
      notifyListeners();
    }
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
        // 服务端用 4401 终结身份（被移出对局/该局已换成新局/令牌作废），
        // 或握手期就 401/403：留在局里只会反复失败，清会话回登录页。
        // 大厅视图由 returnToLobby 的会话校验兜底。观战席自己退出时同样会收到
        // 4401，但那是有意为之，不能把用户踢回登录页。
        if (!_leavingByChoice &&
            (status.startsWith('登录状态已失效') || status == '登录已失效，请重新登录')) {
          error = '身份已失效（可能被移出对局或该局已结束），请重新登录';
          unawaited(_clearSession());
        }
        notifyListeners();
      },
    )..start();
  }

  void _onLiveEvent(Map<String, dynamic> event) {
    try {
      switch (event['type']) {
        case 'sync':
          final incoming = GameView.fromJson(event['state']);
          // 换局窗口期旧连接的事件可能晚于新局的首次同步到达：
          // 不属于当前对局的状态与消息一律丢弃，避免旧局覆盖新局状态。
          if (incoming.id != gameId) return;
          _applyView(incoming);
          final messages = jsonArray(event['messages'], 'sync.messages')
              .map(GameMessage.fromJson);
          _mergeMessages(messages);
        case 'state':
          final incoming = GameView.fromJson(event['state']);
          if (incoming.id != gameId) return;
          _applyView(incoming);
        case 'message':
          final message = GameMessage.fromJson(event['message']);
          if (_matchesScope(message, messageScope)) {
            _mergeMessages([message]);
          } else {
            // 私密信息与夜终公告都不随筛选范围丢弃：玩家停在公屏时也要收到。
            _noteIncoming([message]);
          }
          // 自己的发言本地已合并且已读，不该再加未读角标。
          if (message.id > _readCursor && message.senderId != actor?.id) {
            unreadMessageCount++;
          }
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
    // 换局（或本进程第一次看到这一局）：上一局「稍后」掉的对话框不该压住新局的内容。
    if (view != null && view!.id != next.id) {
      _dismissedDialogs.clear();
    }
    // 「确认进入管理界面」一律以服务端为准：本局这个账号只要确认过一次
    // （换令牌、重新登录、重开应用都算），服务端就不再要求确认，客户端直接展开
    // 管理页；只有服务端明确要求时才显示确认页，本地不记这件事。
    if (actor?.isHost == true) {
      hostAdminEntered = !next.hostEntryRequired;
    }
    // 观战者被主持人安排接管席位（room.replace）后，服务端的参与身份已经变成玩家，
    // 但本地缓存的 actor 仍是「观战」：行动区会被过滤成只剩私信（表现为看不到
    //「准备」），「我的」页也仍写观战者。座位号与缓存对不上时重新核对一次身份。
    if (actor != null &&
        !actor!.isHost &&
        next.self['seat_id']?.toString() != actor!.seatId) {
      unawaited(_reconcileActor());
    }
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

    // 红标只数阻塞项：主持人待办里还有非阻塞的阶段推进提醒，
    // 按全长统计会让红点常亮，失去提醒意义。
    final tasks = next.host['tasks'];
    warningCount = next.self['warning_deadline'] != null
        ? 1
        : (tasks is List
            ? tasks.where((task) => task is Map && task['blocking'] == true)
                .length
            : 0);

    final privateKey = jsonEncode({
      'cards': next.self['cards'],
      'current_card_id': next.self['current_card_id'],
    });
    if (_privateStateBaseline == null) {
      _privateStateBaseline = privateKey;
    } else if (_privateStateBaseline != privateKey) {
      privateStateCount = 1;
    }

    // 自己当前的下层牌换人（下层登场、复活、换牌）就弹一次角色卡介绍；
    // 候场转入开局时上层牌刚锁定，另弹一次「开局 · 上层牌」教程。
    // 四条边界：调序阶段的上下交换也会改 current_card_id，但那时还没开局，
    // 每换一次弹一个窗口只是噪音；发牌是「没有当前牌」到「有当前牌」，也不是登场；
    // 基线的第一次观察（刷新、重连、替补入席）同样不弹，否则恢复对局 = 重播一次介绍。
    final ownCardId = next.self['current_card_id']?.toString();
    final previousCardId = _ownCardBaseline;
    final previousStatus = _statusBaseline;
    _ownCardBaseline = ownCardId;
    _statusBaseline = next.status;
    if (next.status == 'playing' && ownCardId != null) {
      // 开局这一刻自己用的就是上层牌：这是本局第一次确定要用哪张牌。
      final opening = previousStatus == 'lobby';
      final entered = previousCardId != null && previousCardId != ownCardId;
      if (opening || entered) {
        final cards = next.self['cards'];
        if (cards is List) {
          for (final card in cards) {
            if (card is Map && card['id']?.toString() == ownCardId) {
              final roleId = card['role_id']?.toString();
              if (roleId != null) {
                pendingRoleId = roleId;
                pendingRoleIntroOpening = opening;
              }
              break;
            }
          }
        }
      }
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
    // 候场期间陆续有人入席：参与身份变了就补一次佩戴信息，后入席的玩家也有徽章。
    final participants = next.participantIds;
    if (participants.isNotEmpty && !setEquals(participants, _equippedRequested)) {
      _equippedRequested = participants;
      loadGameAchievements();
    }
    // 频道结束或消失都要回到公屏：结束的频道不再出现在频道列表里。
    if (next.channels.every(
        (item) => item.id != selectedChannelId || item.status == 'ended')) {
      selectedChannelId = 'public';
    }
    // 观战者进入对局后默认落在观战频道：服务端只下发观战频道与系统频道。
    if (actor?.isSpectator == true && selectedChannelId == 'public') {
      selectedChannelId = 'spectator';
    }
    // 傀儡控制关系解除或频道失效同样要退回公屏：留着旧的 as_seat 会让下一次
    // 发送落到服务端已拒绝的身份上。
    if (puppetSeatId != null) {
      final puppetChannels = channelsFor(puppetSeatId);
      // 控制关系仍在，只是选中的频道结束了：留在该身份上，退回它的公屏。
      if (puppetChannels.every((item) =>
          item.id != selectedPuppetChannelId || item.status == 'ended')) {
        puppetSeatId = null;
        selectedPuppetChannelId = 'public';
      }
    }
  }

  /// 向服务器重新核对当前参与身份并覆盖本地缓存。
  ///
  /// 只在状态推送里的座位号与缓存不一致时调用：观战接管席位后服务端身份变成玩家，
  /// 本地不刷新就会一直按观战者分支渲染（行动区只剩私信、「我的」页写观战者）。
  /// 失败不打断对局，下一次状态推送会再试。
  Future<void> _reconcileActor() async {
    final client = api;
    if (client == null || _reconcilingActor) return;
    _reconcilingActor = true;
    try {
      final value = (await client.me())['actor'];
      if (value == null) return;
      final next = Actor.fromJson(value);
      final current = actor;
      if (current != null &&
          current.id == next.id &&
          current.kind == next.kind &&
          current.seatId == next.seatId) {
        return;
      }
      actor = next;
      await preferences.setString(_actorKey, jsonEncode(actor!.raw));
      notifyListeners();
    } on ApiException {
      // 身份核对失败时保留旧身份：服务端仍是权威，下一次状态推送会重试。
    } on FormatException {
      // 同上。
    } finally {
      _reconcilingActor = false;
    }
  }

  /// 夜终公告：天亮时服务端公布「第X夜是平安夜。」或「第X夜：<当夜出局的角色牌>」。
  ///
  /// 「如何标记他人」教程就固定挂在第一条非平安夜的公告上：是不是平安夜由服务端
  /// 说了算（它会把「只死一张牌、下层接着登场」也算作当夜出局），客户端不再从席位
  /// 状态里自己重算一遍。实时连接把公告推给每个在场客户端，与当前消息筛选无关；
  /// 掉线期间错过的公告会在下次取「全部/系统」历史时补上。
  static final _deadlyNightNotice = RegExp(r'^第\d+夜：');

  void _noteNightReports(Iterable<GameMessage> incoming) {
    for (final message in incoming) {
      _noteNightReport(message);
    }
  }

  void _noteNightReport(GameMessage message) {
    final game = view?.id;
    if (game == null) return;
    if (game != _marksGameId) {
      // 换局（或本进程第一次看到这一局）：教程要在这一局重新固定展示一次。
      _marksGameId = game;
      marksTutorialShown = false;
      pendingMarksTutorial = false;
    }
    if (marksTutorialShown || pendingMarksTutorial) return;
    // 只认全场公告：聊天、私密信息与主持人的定向广播都不算夜终公告。
    if (message.kind != 'alert') return;
    if (!_deadlyNightNotice.hasMatch(message.text.trim())) return;
    // 已落幕的对局只读，不再教学。
    if (view?.status != 'playing') return;
    // 主持人知道全部底牌，不需要这份面向玩家的教程。
    if (actor?.isHost == true) {
      marksTutorialShown = true;
      return;
    }
    pendingMarksTutorial = true;
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
      // 首批历史只用来定私密信息的基线：登录、刷新、切筛选都不该弹横幅。
      _noteIncoming(page.messages);
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

  /// 同一参与者新的在场消息到达后，此人更早的「已掉线 / 重新连接」提醒全部隐藏：
  /// 断连刷屏只留下最新一条状态，历史不再占屏（服务端记录不动）。
  static final _presenceActor = RegExp(r'【(.+)】(已连接 / 重新连接|已掉线)$');

  static String? _presenceKey(GameMessage message) {
    if (message.kind != 'presence') return null;
    final match = _presenceActor.firstMatch(message.text);
    if (match != null) return 'named:${match.group(1)}';
    if (message.text.startsWith('主持人')) return 'host';
    return null;
  }

  static List<GameMessage> _hideStalePresence(List<GameMessage> merged) {
    final latestPresence = <String, int>{};
    for (final item in merged) {
      final key = _presenceKey(item);
      if (key == null) continue;
      final current = latestPresence[key];
      if (current == null || item.id > current) latestPresence[key] = item.id;
    }
    if (latestPresence.isEmpty) return merged;
    return merged
        .where((item) =>
            _presenceKey(item) == null ||
            item.id == latestPresence[_presenceKey(item)])
        .toList();
  }

  /// 回归检查入口：与实时事件/历史补齐完全同一条合并路径。
  void mergeMessagesForTest(Iterable<GameMessage> incoming) =>
      _mergeMessages(incoming);

  static String? presenceKeyForTest(GameMessage message) =>
      _presenceKey(message);

  void _mergeMessages(Iterable<GameMessage> incoming) {
    final indexed = {for (final item in messages) item.id: item};
    for (final item in incoming) {
      if (_matchesScope(item, messageScope)) indexed[item.id] = item;
    }
    messages = _hideStalePresence(indexed.values.toList())
      ..sort((a, b) => a.id.compareTo(b.id));
    _noteIncoming(incoming);
  }

  /// 记录新到的私密信息并准备一条横幅提醒。
  ///
  /// 游标按 id 单调前进，因此切换筛选范围、重连补齐都不会重复提醒；
  /// 首次拿到的历史（登录、刷新、首屏）只用来定基线，不弹横幅。
  /// 所有新到消息的统一入口：记私密信息横幅，并认一下夜终公告。
  /// 三个入口（首次取历史、重连补齐、实时单条）都走这里，筛选范围不影响判定。
  void _noteIncoming(Iterable<GameMessage> incoming) {
    _notePrivateInfo(incoming);
    _noteNightReports(incoming);
  }

  void _notePrivateInfo(Iterable<GameMessage> incoming) {
    final infos = incoming.where((item) => item.kind == 'information').toList()
      ..sort((a, b) => a.id.compareTo(b.id));
    if (infos.isEmpty) return;
    final cursor = _privateInfoCursor;
    if (cursor == null) {
      _privateInfoCursor = infos.last.id;
      return;
    }
    for (final item in infos) {
      if (item.id <= cursor) continue;
      _privateInfoCursor = item.id;
      pendingPrivateInfo = item;
    }
  }

  /// 关掉「新私密信息」横幅；记录本身仍在对话与「私密情报记录」里。
  void acknowledgePrivateInfo() {
    if (pendingPrivateInfo == null) return;
    pendingPrivateInfo = null;
    notifyListeners();
  }

  bool _matchesScope(GameMessage message, String scope) {
    // 观战者独享观战频道：聊天消息只认观战频道，公屏/私信筛选统一映射过去。
    final spectatorChat =
        actor?.isSpectator == true && message.kind == 'chat';
    if (spectatorChat && message.channelId != 'spectator') return false;
    return switch (scope) {
      'public' => message.kind == 'chat' &&
          message.channelId == (actor?.isSpectator == true ? 'spectator' : 'public'),
      'system' => message.channelId == 'system' || message.kind != 'chat',
      'host' => message.channelId != 'public' &&
          message.channelId != 'system' &&
          message.channelId != 'spectator' &&
          (view?.channels.any((channel) =>
                  channel.id == message.channelId &&
                  channel.members.any((member) => member['id'] == 'host')) ??
              false),
      'private' => message.channelId != 'public' &&
          message.channelId != 'system' &&
          message.channelId != 'spectator' &&
          !(view?.channels.any((channel) =>
                  channel.id == message.channelId &&
                  channel.members.any((member) => member['id'] == 'host')) ??
              false),
      _ => true,
    };
  }

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

  /// 选择发送频道；带 [asSeat] 表示以该受控傀儡席位的身份发言。
  /// 两条身份的频道选择分开存放：写给傀儡私信的内容不可能落到自己的频道上。
  void selectChannel(String channelId, {String? asSeat}) {
    if (asSeat == null) {
      puppetSeatId = null;
      selectedChannelId = channelId;
    } else {
      puppetSeatId = asSeat;
      selectedPuppetChannelId = channelId;
    }
    notifyListeners();
  }

  /// 当前发言身份：非空时要把它作为 `as_seat` 一起提交。
  String? get activeAsSeat => puppetSeatId;

  String get activeChannelId =>
      puppetSeatId == null ? selectedChannelId : selectedPuppetChannelId;

  /// 全部发送目标：自己的频道在前，梅露露的傀儡频道在后（标签已带 `*`）。
  /// 频道 id 可能重复（傀儡与自己可能是同一频道），身份靠 [asSeat] 区分。
  List<({GameChannel channel, String? asSeat})> get sendTargets => [
        for (final channel in view?.channels ?? const <GameChannel>[])
          (channel: channel, asSeat: null),
        for (final panel in view?.puppetControls ?? const <PuppetPanel>[])
          for (final channel in panel.channels)
            (channel: channel, asSeat: panel.seatId),
      ];

  /// 某个发言身份可见的频道；`asSeat` 为空表示自己的视角。
  List<GameChannel> channelsFor(String? asSeat) => [
        for (final target in sendTargets)
          if (target.asSeat == asSeat) target.channel,
      ];

  GameChannel? get selectedChannel {
    for (final target in sendTargets) {
      if (target.asSeat == activeAsSeat && target.channel.id == activeChannelId) {
        return target.channel;
      }
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
      final message = await api!
          .sendMessage(id, activeChannelId, text.trim(), asSeat: puppetSeatId);
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
    Map<String, dynamic>? initial,
  }) async {
    final id = gameId;
    final current = view;
    // 静默 return 会让表单把“没提交”当成“已提交”直接关闭，
    // 用户以为行动已生效。不可用必须显式报错，由表单提示并保留草稿。
    if (api == null || id == null || current == null) {
      throw const ApiException('对局状态尚未就绪，请刷新后重试');
    }
    if (writeBusy) {
      throw const ApiException('有操作正在提交，请稍候再试');
    }
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
        await clearDraft(action, asSeat: asSeat, initial: initial);
      } catch (_) {
        // 草稿清理是尽力而为。
      }
    } on ApiException catch (failure) {
      if (failure.statusCode == 401) {
        // 令牌已失效：继续留在对局里只会反复 401，清会话回登录页。
        await _clearSession();
      } else {
        error = failure.message;
        await _reconcileAfterWriteFailure();
      }
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

  /// 草稿按对局、参与身份、频道/表单与动作目标隔离：同一动作针对不同
  /// 席位/待办的预填草稿互不覆盖（快捷入口的目标 id 体现在 action.payload 里）。
  String draftKey(
    ActionDescriptor action, {
    String? asSeat,
    Map<String, dynamic>? initial,
  }) {
    final current = view;
    return jsonEncode([
      endpoint.toString(),
      gameId,
      actor?.accountId,
      asSeat ?? actor?.id,
      action.id.startsWith('channel.')
          ? (asSeat == null ? selectedChannelId : selectedPuppetChannelId)
          : action.id,
      current?.day,
      current?.half,
      current?.phase,
      action.id,
      action.payload,
      initial ?? const <String, dynamic>{},
    ]);
  }

  Map<String, dynamic> draftFor(
    ActionDescriptor action, {
    String? asSeat,
    Map<String, dynamic>? initial,
  }) {
    // 显式预填值（快捷入口按目标带出）使用独立草稿键，与徒手打开表单的草稿隔离。
    final encoded = preferences.getString(
        'draft:${draftKey(action, asSeat: asSeat, initial: initial)}');
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
    Map<String, dynamic>? initial,
  }) async {
    await preferences.setString(
      'draft:${draftKey(action, asSeat: asSeat, initial: initial)}',
      jsonEncode(values),
    );
  }

  Future<void> clearDraft(
    ActionDescriptor action, {
    String? asSeat,
    Map<String, dynamic>? initial,
  }) async {
    await preferences.remove(
        'draft:${draftKey(action, asSeat: asSeat, initial: initial)}');
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
    pendingRoleId = null;
    pendingRoleIntroOpening = false;
    _ownCardBaseline = null;
    _statusBaseline = null;
    _inviteBaseline = null;
    // 登出后 1.45 秒内重登不该凭空重播旧对局的阶段动画，
    // 角标计数也不该带着旧对局的残留进入新会话。
    pendingPhaseKey = null;
    pendingPrivateInfo = null;
    _privateInfoCursor = null;
    newActionCount = 0;
    warningCount = 0;
    privateStateCount = 0;
    unreadMessageCount = 0;
    hasMoreMessages = false;
    messageScope = 'all';
    selectedChannelId = 'public';
    puppetSeatId = null;
    selectedPuppetChannelId = 'public';
    online = const <OnlineAccount>[];
    invites = const <LobbyInvite>[];
    announcements = const <Announcement>[];
    announcementsVersion = '';
    equippedAchievements = const {};
    participantAccounts = const {};
    _equippedRequested = const {};
    hostAdminEntered = false;
    hostAdminNotice = null;
    _leavingByChoice = false;
    _resetPlayerMarks();
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

/// 这次刷新相对上次基线新到的邀请。
/// 基线为 null（本次会话第一次刷新）时不提醒：登录后大厅里已经堆着的
/// 旧邀请不该在启动瞬间连着弹一串系统通知。
List<LobbyInvite> freshInvites(
  Set<String>? baseline,
  List<LobbyInvite> current,
) {
  if (baseline == null) return const <LobbyInvite>[];
  return [
    for (final invite in current)
      if (!baseline.contains(invite.id)) invite,
  ];
}
