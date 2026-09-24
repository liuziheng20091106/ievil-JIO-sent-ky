import 'dart:convert';
import 'dart:io';

Map<String, dynamic> jsonObject(Object? value, [String name = 'object']) {
  if (value is! Map) throw FormatException('$name must be a JSON object');
  return value.map((key, value) => MapEntry(key.toString(), value));
}

List<dynamic> jsonArray(Object? value, [String name = 'array']) {
  if (value is! List) throw FormatException('$name must be a JSON array');
  return value;
}

String jsonString(Object? value, String name, {String fallback = ''}) {
  if (value == null && fallback.isNotEmpty) return fallback;
  if (value is! String) throw FormatException('$name must be a string');
  return value;
}

int jsonInt(Object? value, String name, {int fallback = 0}) {
  if (value == null) return fallback;
  if (value is! int) throw FormatException('$name must be an integer');
  return value;
}

bool jsonBool(Object? value, String name, {bool fallback = false}) {
  if (value == null) return fallback;
  if (value is! bool) throw FormatException('$name must be a boolean');
  return value;
}

class ServerEndpoint {
  ServerEndpoint._(this.httpUri);

  final Uri httpUri;

  static ServerEndpoint parse(String input) {
    final value = input.trim();
    final uri = Uri.tryParse(value);
    if (uri == null ||
        !uri.hasScheme ||
        (uri.scheme != 'http' && uri.scheme != 'https') ||
        uri.host.isEmpty ||
        uri.userInfo.isNotEmpty ||
        (uri.path.isNotEmpty && uri.path != '/') ||
        uri.hasQuery ||
        uri.hasFragment) {
      throw const FormatException('请输入不含路径、查询或片段的 HTTP(S) 服务根地址');
    }
    if (uri.scheme == 'http' && !_isPrivateHost(uri.host)) {
      throw const FormatException('公网服务必须使用 HTTPS');
    }
    return ServerEndpoint._(Uri(
      scheme: uri.scheme,
      host: uri.host,
      port: uri.hasPort ? uri.port : null,
    ));
  }

  static bool _isPrivateHost(String host) {
    if (host.toLowerCase() == 'localhost') return true;
    final address = InternetAddress.tryParse(host);
    if (address == null) return false;
    if (address.isLoopback) return true;
    if (address.type == InternetAddressType.IPv4) {
      final octets = address.rawAddress;
      return octets[0] == 10 ||
          (octets[0] == 172 && octets[1] >= 16 && octets[1] <= 31) ||
          (octets[0] == 192 && octets[1] == 168);
    }
    return false;
  }

  Uri api(String path, [Map<String, String?> query = const {}]) {
    if (!path.startsWith('/')) throw ArgumentError.value(path, 'path');
    final cleanQuery = <String, String>{
      for (final entry in query.entries)
        if (entry.value != null && entry.value!.isNotEmpty)
          entry.key: entry.value!,
    };
    return httpUri.resolve(path).replace(
          queryParameters: cleanQuery.isEmpty ? null : cleanQuery,
        );
  }

  Uri get liveUri => httpUri.replace(
        scheme: httpUri.scheme == 'https' ? 'wss' : 'ws',
        path: '/api/live',
      );

  @override
  String toString() => httpUri.toString();
}

class ApiException implements Exception {
  const ApiException(this.message, {this.statusCode});

  final String message;
  final int? statusCode;
  bool get isConflict => statusCode == HttpStatus.conflict;

  @override
  String toString() => message;
}

class Actor {
  Actor.fromJson(Object? value) : raw = jsonObject(value, 'actor') {
    id = jsonString(raw['id'] ?? raw['account_id'], 'actor.id');
    kind = jsonString(raw['kind'], 'actor.kind');
    name = jsonString(raw['name'] ?? raw['nickname'], 'actor.name');
    seatId = raw['seat_id']?.toString();
    accountId = (raw['account_id'] ?? raw['id']).toString();
    avatarUrl = raw['avatar_url']?.toString();
  }

  final Map<String, dynamic> raw;
  late final String id;
  late final String accountId;
  late final String kind;
  late final String name;
  late final String? seatId;
  late final String? avatarUrl;

  bool get isHost => kind == 'host';
  bool get isSpectator => kind == 'spectator';
}

class LobbyGame {
  LobbyGame.fromJson(Object? value) : raw = jsonObject(value, 'lobby.game');

  final Map<String, dynamic> raw;
  String get id => jsonString(raw['id'], 'game.id');
  String get status => jsonString(raw['status'], 'game.status');
  String get phase => jsonString(raw['phase'], 'game.phase');
  bool get joinOpen => jsonBool(raw['join_open'], 'game.join_open');
  int get seatsAvailable =>
      jsonInt(raw['player_seats_available'], 'game.player_seats_available');
  bool get canJoinPlayer =>
      jsonBool(raw['can_join_player'], 'game.can_join_player');
  bool get canJoinSpectator =>
      jsonBool(raw['can_join_spectator'], 'game.can_join_spectator');
}

/// 在线账号：只用于展示与邀请，不含任何 QQ 号或令牌。
class OnlineAccount {
  OnlineAccount.fromJson(Object? value) : raw = jsonObject(value, 'online.account');

  final Map<String, dynamic> raw;
  String get id => jsonString(raw['id'], 'online.account.id');
  String get name => jsonString(raw['name'], 'online.account.name');
  bool get available =>
      jsonBool(raw['available'], 'online.account.available', fallback: true);
  bool get invited => jsonBool(raw['invited'], 'online.account.invited');
}

/// 别人发给我的对局邀请；game 为空表示那一局已经不存在。
class LobbyInvite {
  LobbyInvite.fromJson(Object? value) : raw = jsonObject(value, 'lobby.invite');

  final Map<String, dynamic> raw;
  String get id => jsonString(raw['id'], 'invite.id');
  String get gameId => jsonString(raw['game_id'], 'invite.game_id');
  String get fromName => jsonString(raw['from_name'], 'invite.from_name');
  LobbyGame? get game =>
      raw['game'] == null ? null : LobbyGame.fromJson(raw['game']);
}

class ActionField {
  ActionField.fromJson(Object? value) : raw = jsonObject(value, 'field') {
    name = jsonString(raw['name'], 'field.name');
    label = jsonString(raw['label'], 'field.label');
    type = jsonString(raw['type'], 'field.type');
    required = raw['required'] == null
        ? true
        : jsonBool(raw['required'], 'field.required');
    options = raw['options'] == null
        ? const []
        : jsonArray(raw['options'], 'field.options')
            .map((item) => jsonObject(item, 'option'))
            .toList(growable: false);
  }

  static const supportedTypes = {
    'text',
    'textarea',
    'number',
    'select',
    'multiselect',
    'checkbox',
    'drawing',
  };

  final Map<String, dynamic> raw;
  late final String name;
  late final String label;
  late final String type;
  late final bool required;
  late final List<Map<String, dynamic>> options;

  String? get unsupportedReason =>
      supportedTypes.contains(type) ? null : '客户端版本不支持字段类型“$type”，请升级';
}

class ActionDescriptor {
  ActionDescriptor.fromJson(Object? value) : raw = jsonObject(value, 'action') {
    id = jsonString(raw['id'], 'action.id');
    label = jsonString(raw['label'], 'action.label');
    shortLabel = jsonString(raw['short_label'], 'action.short_label');
    description = raw['description']?.toString() ?? '';
    group = raw['group']?.toString() ?? '行动';
    uiVersion = jsonInt(raw['ui_version'], 'action.ui_version');
    asSeat = raw['as_seat']?.toString();
    payload = raw['payload'] == null
        ? const <String, dynamic>{}
        : jsonObject(raw['payload'], 'action.payload');
    fields = raw['fields'] == null
        ? const []
        : jsonArray(raw['fields'], 'action.fields')
            .map(ActionField.fromJson)
            .toList(growable: false);
  }

  final Map<String, dynamic> raw;
  late final String id;
  late final String label;
  late final String shortLabel;
  late final String description;
  late final String group;
  late final int uiVersion;

  /// 梅露露代操作傀儡席时服务端给出的目标席位；提交时必须原样回传。
  late final String? asSeat;
  late final Map<String, dynamic> payload;
  late final List<ActionField> fields;

  String? get unsupportedReason {
    if (uiVersion != 1) return '客户端版本不支持此行动，请升级';
    final length = shortLabel.runes.length;
    if (length < 2 || length > 4) return '行动短名不符合协议，已禁止提交';
    for (final field in fields) {
      final reason = field.unsupportedReason;
      if (reason != null) return reason;
    }
    return null;
  }

  String get protocolKey => jsonEncode(raw);
}

class GameChannel {
  GameChannel.fromJson(Object? value) : raw = jsonObject(value, 'channel') {
    id = jsonString(raw['id'], 'channel.id');
    label = jsonString(raw['label'], 'channel.label');
    status = raw['status']?.toString() ?? 'active';
    creatorId = raw['creator_id']?.toString();
    members = raw['members'] == null
        ? const []
        : jsonArray(raw['members'], 'channel.members')
            .map((item) => jsonObject(item, 'channel.member'))
            .toList(growable: false);
    invitedIds = _strings(raw['invited_ids']);
    acceptedIds = _strings(raw['accepted_ids']);
    invitation = raw['invitation']?.toString() ?? 'none';
    canSend = jsonBool(raw['can_send'], 'channel.can_send');
    asSeat = raw['as_seat']?.toString();
    reason = raw['reason']?.toString() ?? '';
    actions = raw['actions'] == null
        ? const []
        : jsonArray(raw['actions'], 'channel.actions')
            .map(ActionDescriptor.fromJson)
            .toList(growable: false);
  }

  static List<String> _strings(Object? value) => value == null
      ? const []
      : jsonArray(value).map((item) => item.toString()).toList(growable: false);

  final Map<String, dynamic> raw;
  late final String id;
  late final String label;
  late final String status;
  late final String? creatorId;
  late final List<Map<String, dynamic>> members;
  late final List<String> invitedIds;
  late final List<String> acceptedIds;
  late final String invitation;
  late final bool canSend;
  late final String reason;

  /// 傀儡视角频道：发送时必须以该席位身份发出（服务端 tags 每个傀儡频道）。
  late final String? asSeat;
  late final List<ActionDescriptor> actions;

  bool get isPrivate =>
      id != 'public' && id != 'system' && !id.startsWith('host:');
}

/// 梅露露控制的傀儡席面板：动作与频道都要以该席位的身份提交（as_seat）。
/// 服务端已把标签加 `*` 前缀，客户端只负责原样显示与提交。
class PuppetPanel {
  PuppetPanel.fromJson(Object? value) : raw = jsonObject(value, 'panel') {
    seatId = jsonString(raw['seat_id'], 'panel.seat_id');
    name = raw['name']?.toString() ?? '';
    actions = raw['actions'] == null
        ? const []
        : jsonArray(raw['actions'], 'panel.actions')
            .map(ActionDescriptor.fromJson)
            .toList(growable: false);
    channels = raw['channels'] == null
        ? const []
        : jsonArray(raw['channels'], 'panel.channels')
            .map(GameChannel.fromJson)
            .toList(growable: false);
  }

  final Map<String, dynamic> raw;
  late final String seatId;
  late final String name;
  late final List<ActionDescriptor> actions;
  late final List<GameChannel> channels;
}

class GameMessage {
  GameMessage.fromJson(Object? value) : raw = jsonObject(value, 'message') {
    id = jsonInt(raw['id'], 'message.id');
    kind = raw['kind']?.toString() ?? 'chat';
    text = jsonString(raw['text'], 'message.text');
    channelId = raw['channel_id']?.toString() ?? 'system';
    senderId = raw['sender_id']?.toString();
    senderName = raw['sender_name']?.toString();
    avatarRoleId = raw['avatar_role_id']?.toString();
    createdAt = raw['created_at']?.toString() ?? '';
  }

  final Map<String, dynamic> raw;
  late final int id;
  late final String kind;
  late final String text;
  late final String channelId;
  late final String? senderId;
  late final String? senderName;
  late final String? avatarRoleId;
  late final String createdAt;
}

/// 角色目录条目：服务端的公开信息，用于角色详情与魔典说明。
class RoleInfo {
  RoleInfo.fromJson(Object? value) : raw = jsonObject(value, 'role') {
    id = jsonString(raw['id'], 'role.id');
    name = jsonString(raw['name'], 'role.name');
    normal = raw['normal']?.toString() ?? '';
    witch = raw['witch']?.toString() ?? '';
    avatar = raw['avatar']?.toString();
  }

  final Map<String, dynamic> raw;
  late final String id;
  late final String name;
  late final String normal;
  late final String witch;
  late final String? avatar;
}

/// 成就定义：主持人自定义的名称、内容与稀有度（1-10，数字越大越稀有）。
class AchievementDef {
  AchievementDef.fromJson(Object? value)
      : raw = jsonObject(value, 'achievement') {
    id = jsonString(raw['id'], 'achievement.id');
    name = jsonString(raw['name'], 'achievement.name');
    detail = raw['detail']?.toString() ?? '';
    rarity = jsonInt(raw['rarity'], 'achievement.rarity');
    grantedCount = jsonInt(raw['granted_count'], 'achievement.granted_count');
  }

  final Map<String, dynamic> raw;
  late final String id;
  late final String name;
  late final String detail;
  late final int rarity;

  /// 已授予人数：主持人删除定义前用它判断影响面。
  late final int grantedCount;
}

/// 某个账号获得的一个成就。
class AchievementGrant {
  AchievementGrant.fromJson(Object? value) : raw = jsonObject(value, 'grant') {
    id = jsonString(raw['id'], 'grant.id');
    accountId = raw['account_id']?.toString() ?? '';
    achievementId = jsonString(raw['achievement_id'], 'grant.achievement_id');
    name = jsonString(raw['name'], 'grant.name');
    detail = raw['detail']?.toString() ?? '';
    rarity = jsonInt(raw['rarity'], 'grant.rarity');
    grantedAt = raw['granted_at']?.toString() ?? '';
  }

  final Map<String, dynamic> raw;
  late final String id;
  late final String accountId;
  late final String achievementId;
  late final String name;
  late final String detail;
  late final int rarity;
  late final String grantedAt;
}

/// 佩戴中的成就：列表与对局内徽章只用到名字与稀有度。
class EquippedAchievement {
  EquippedAchievement.fromJson(Object? value)
      : raw = jsonObject(value, 'equipped') {
    id = jsonString(raw['id'], 'equipped.id');
    name = jsonString(raw['name'], 'equipped.name');
    rarity = jsonInt(raw['rarity'], 'equipped.rarity');
  }

  final Map<String, dynamic> raw;
  late final String id;
  late final String name;
  late final int rarity;
}

/// 本局某个参与身份佩戴的成就：`/api/achievements/games/{id}/equipped` 的一行。
class GameEquipped {
  GameEquipped.fromJson(Object? value) : raw = jsonObject(value, 'equipped_row') {
    participantId = jsonString(raw['participant_id'], 'equipped_row.participant_id');
    accountId = raw['account_id']?.toString() ?? '';
    equipped = raw['equipped'] == null
        ? null
        : EquippedAchievement.fromJson(raw['equipped']);
  }

  final Map<String, dynamic> raw;
  late final String participantId;
  late final String accountId;
  late final EquippedAchievement? equipped;
}

/// 主持人视角的玩家条目：成就总数、佩戴、最近参赛时间与全部成就。
class AchievementPlayer {
  AchievementPlayer.fromJson(Object? value)
      : raw = jsonObject(value, 'achievement_player') {
    accountId = jsonString(raw['account_id'], 'player.account_id');
    name = raw['name']?.toString() ?? '';
    avatarUrl = raw['avatar_url']?.toString() ?? '';
    lastPlayedAt = raw['last_played_at']?.toString();
    achievementCount = jsonInt(raw['achievement_count'], 'player.achievement_count');
    equipped = raw['equipped'] == null
        ? null
        : EquippedAchievement.fromJson(raw['equipped']);
    achievements = raw['achievements'] == null
        ? const []
        : jsonArray(raw['achievements'], 'player.achievements')
            .map(AchievementGrant.fromJson)
            .toList(growable: false);
  }

  final Map<String, dynamic> raw;
  late final String accountId;
  late final String name;
  late final String avatarUrl;

  /// 最近一次以玩家身份参赛的时间；为空表示只被授权过成就、还没参赛。
  late final String? lastPlayedAt;
  late final int achievementCount;
  late final EquippedAchievement? equipped;
  late final List<AchievementGrant> achievements;
}

/// 头像摘要：总成就数 + 最稀有的 5 个（名 + 详细）。
class AchievementSummary {
  AchievementSummary.fromJson(Object? value)
      : raw = jsonObject(value, 'achievement_summary') {
    accountId = jsonString(raw['account_id'], 'summary.account_id');
    name = raw['name']?.toString() ?? '';
    total = jsonInt(raw['total'], 'summary.total');
    equipped = raw['equipped'] == null
        ? null
        : EquippedAchievement.fromJson(raw['equipped']);
    top = raw['top'] == null
        ? const []
        : jsonArray(raw['top'], 'summary.top')
            .map(AchievementGrant.fromJson)
            .toList(growable: false);
  }

  final Map<String, dynamic> raw;
  late final String accountId;
  late final String name;
  late final int total;
  late final EquippedAchievement? equipped;
  late final List<AchievementGrant> top;
}

/// 角色目录：`/api/catalog` 的裁剪结果。
class RoleCatalog {
  RoleCatalog.fromJson(Object? value) : raw = jsonObject(value, 'catalog') {
    roles = raw['roles'] == null
        ? const <RoleInfo>[]
        : jsonArray(raw['roles'], 'catalog.roles')
            .map(RoleInfo.fromJson)
            .toList(growable: false);
    defaultCodex = raw['default_codex'] == null
        ? const <String>[]
        : jsonArray(
            raw['default_codex'],
            'catalog.default_codex',
          ).map((item) => item.toString()).toList(growable: false);
  }

  final Map<String, dynamic> raw;
  late final List<RoleInfo> roles;
  late final List<String> defaultCodex;
}

class GameView {
  GameView.fromJson(Object? value) : raw = jsonObject(value, 'state') {
    uiVersion = jsonInt(raw['ui_version'], 'state.ui_version');
    if (uiVersion != 1) {
      throw const FormatException('客户端版本不支持此对局界面，请升级');
    }
    actions = raw['actions'] == null
        ? const []
        : jsonArray(raw['actions'], 'state.actions')
            .map(ActionDescriptor.fromJson)
            .toList(growable: false);
    channels = raw['channels'] == null
        ? const []
        : jsonArray(raw['channels'], 'state.channels')
            .map(GameChannel.fromJson)
            .toList(growable: false);
  }

  final Map<String, dynamic> raw;
  late final int uiVersion;
  late final List<ActionDescriptor> actions;
  late final List<GameChannel> channels;

  String get id => jsonString(raw['id'], 'state.id');
  int get version => jsonInt(raw['version'], 'state.version');
  int get day => jsonInt(raw['day'], 'state.day');
  String get half => raw['half']?.toString() ?? '';
  String get phase => raw['phase']?.toString() ?? '';
  String get phaseLabel => raw['phase_label']?.toString() ?? phase;
  String get status => raw['status']?.toString() ?? '';
  List<Map<String, dynamic>> get seats => raw['seats'] == null
      ? const []
      : jsonArray(raw['seats'], 'state.seats')
          .map((item) => jsonObject(item, 'seat'))
          .toList(growable: false);
  Map<String, dynamic> get self =>
      raw['self'] == null ? const {} : jsonObject(raw['self'], 'state.self');
  List<Map<String, dynamic>> get statuses => self['statuses'] == null
      ? const []
      : jsonArray(self['statuses'], 'state.self.statuses')
          .map((item) => jsonObject(item, 'status'))
          .toList(growable: false);
  Map<String, dynamic> get host =>
      raw['host'] == null ? const {} : jsonObject(raw['host'], 'state.host');

  /// 当前牌是傀儡的玩家：只读旁观，由魔女梅露露代为行动。
  bool get puppetSpectator =>
      jsonBool(self['puppet_spectator'], 'state.self.puppet_spectator');

  /// 控制傀儡的梅露露视角面板；无控制关系时为空。
  List<PuppetPanel> get puppetControls => self['puppet_controls'] == null
      ? const []
      : jsonArray(self['puppet_controls'], 'state.self.puppet_controls')
          .map(PuppetPanel.fromJson)
          .toList(growable: false);

  Map<String, dynamic> get public =>
      raw['public'] == null ? const {} : jsonObject(raw['public'], 'state.public');

  /// 视图里出现的参与身份 id：席位占位者，加上主持人视图的参与者名单。
  /// 成就是按参与身份下发佩戴徽章的，这里用来判断要不要重新拉一次。
  Set<String> get participantIds {
    final ids = <String>{};
    for (final seat in seats) {
      final id = seat['participant_id']?.toString();
      if (id != null && id.isNotEmpty) ids.add(id);
    }
    final participants = host['participants'];
    if (participants is List) {
      for (final raw in participants) {
        if (raw is! Map) continue;
        final id = raw['id']?.toString();
        if (id != null && id.isNotEmpty) ids.add(id);
      }
    }
    return ids;
  }

  /// 自由发言阶段已提交结束请求的席位 id。
  List<String> get discussionEndRequests => public['discussion_end_requests'] == null
      ? const []
      : jsonArray(public['discussion_end_requests'], 'public.discussion_end_requests')
          .map((item) => item.toString())
          .toList(growable: false);

  /// 系统自动推进的截止时间（Unix 秒）；为空表示没有倒计时。
  double? get autoAdvanceAt {
    final value = public['auto_advance_at'];
    if (value is num) return value.toDouble();
    return double.tryParse('$value');
  }

  Iterable<ActionDescriptor> get channelActions =>
      channels.expand((item) => item.actions);
  Iterable<ActionDescriptor> get allActions => [...actions, ...channelActions];
}
