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
  late final List<ActionDescriptor> actions;

  bool get isPrivate =>
      id != 'public' && id != 'system' && !id.startsWith('host:');
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
    mimicSeatId = raw['mimic_seat_id']?.toString();
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
  late final String? mimicSeatId;
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
  Map<String, dynamic> get host =>
      raw['host'] == null ? const {} : jsonObject(raw['host'], 'state.host');

  Iterable<ActionDescriptor> get channelActions =>
      channels.expand((item) => item.actions);
  Iterable<ActionDescriptor> get allActions => [...actions, ...channelActions];
}
