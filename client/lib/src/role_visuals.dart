import 'dart:math';

import 'package:flutter/material.dart';

import 'design.dart';

/// 行动与角色的图标映射。每个行动都必须有图标：优先使用 Material 图标，
/// 语义不贴合的自绘 SVG（见 [AppSvg]）。
///
/// 测试会断言这一张表覆盖后端给出的全部行动 id，避免新增行动时漏配图标。
class ActionIcons {
  const ActionIcons._();

  static const Map<String, IconData> material = {
    // 流程与阶段
    'host.advance': Icons.play_circle_outline,
    'host.auto': Icons.motion_photos_auto_outlined,
    'host.start': Icons.rocket_launch_outlined,
    'host.speech': Icons.record_voice_over_outlined,
    'speech.speak': Icons.edit_note_outlined,
    'speech.done': Icons.skip_next_outlined,
    'discussion.request_end': Icons.how_to_vote_outlined,
    'host.warn': Icons.timer_outlined,
    'host.resolve': Icons.gavel_outlined,
    'host.confirm_winner': Icons.emoji_events_outlined,
    'host.end': Icons.stop_circle_outlined,
    'player.surrender': Icons.flag_outlined,
    'host.surrender': Icons.handshake_outlined,

    // 开局与准备
    'host.codex': Icons.menu_book_outlined,
    'host.codex_order': Icons.reorder_outlined,
    'lobby.order': Icons.layers_outlined,
    'lobby.ready': Icons.check_circle_outline,
    'player.profile': Icons.badge_outlined,

    // 夜间与白天技能
    'night.submit': Icons.nightlight_outlined,
    'night.confirm': Icons.done_all_outlined,
    'night.clear': Icons.backspace_outlined,
    'day.skill': Icons.auto_awesome_outlined,
    'day.challenge': Icons.help_outline,
    'honoka.disguise': Icons.theater_comedy_outlined,
    'honoka.witness': Icons.visibility_outlined,
    'photo.permission': Icons.photo_camera_outlined,
    'water.use': Icons.water_drop_outlined,
    'meruru.revive': Icons.favorite_outline,
    'execution.shoot': Icons.my_location_outlined,
    'execution.confirm': Icons.do_not_disturb_on_outlined,

    // 归票
    'vote.nominate': Icons.how_to_vote_outlined,
    'vote.pass': Icons.block_outlined,
    'vote.cast': Icons.ballot_outlined,

    // 主持人裁定
    'host.damage': Icons.heart_broken_outlined,
    'host.state': Icons.tune_outlined,
    'host.information': Icons.mail_outline,
    'host.madness': Icons.psychology_alt_outlined,
    'host.rewind': Icons.history_outlined,
    'host.water': Icons.opacity_outlined,
    'hiro.exit': Icons.logout_outlined,

    // 房间与私信
    'room.open_join': Icons.person_add_alt_outlined,
    'room.kick': Icons.person_remove_outlined,
    'room.mute': Icons.volume_off_outlined,
    'room.replace': Icons.swap_horiz_outlined,
    'channel.create': Icons.forum_outlined,
    'channel.accept': Icons.check_outlined,
    'channel.reject': Icons.close_outlined,
    'channel.end': Icons.power_settings_new_outlined,

    // 证物
    'evidence.submit': Icons.attach_file_outlined,
  };

  /// 自绘 SVG 的行动；当前没有语义不贴合 Material 图标的行动，保留空表作为扩展位。
  static const Map<String, AppSvg> svg = {};

  static const fallback = Icons.circle_outlined;

  static IconData? materialFor(String actionId) => material[actionId];

  static AppSvg? svgFor(String actionId) => svg[actionId];

  /// 表里登记过的行动 id（含 SVG 项）。
  static Set<String> get covered => {...material.keys, ...svg.keys};
}

/// 自绘 SVG 图标。
enum AppSvg {
  /// 应用标志（月代雪立绘的替代图形，用于无图场景）。
  seal,
}

extension AppSvgPath on AppSvg {
  String get asset => switch (this) {
        AppSvg.seal => 'assets/icons/seal.svg',
      };
}

/// 角色 id → 名称与头像；与后端 catalog 的 id 一一对应。
class RoleVisual {
  const RoleVisual(this.id, this.name, {this.hasArt = true});

  final String id;
  final String name;
  final bool hasArt;

  String get avatarAsset => 'assets/avatars/$id.png';
}

const roleVisuals = <RoleVisual>[
  RoleVisual('emma', '艾玛'),
  RoleVisual('hiro', '希罗'),
  RoleVisual('hanna', '汉娜'),
  RoleVisual('sherry', '雪莉'),
  RoleVisual('meruru', '梅露露'),
  RoleVisual('noah', '诺亚'),
  RoleVisual('annan', '安安'),
  RoleVisual('millia', '米莉亚'),
  RoleVisual('coco', '可可'),
  RoleVisual('nanoka', '奈乃香'),
  RoleVisual('arisa', '亚里沙'),
  RoleVisual('marg', '玛格'),
  RoleVisual('leia', '蕾雅'),
  // 穗乃香没有立绘，按规则用「穗」字占位。
  RoleVisual('honoka', '穗乃香', hasArt: false),
];

RoleVisual? roleVisual(String? roleId) {
  if (roleId == null) return null;
  for (final role in roleVisuals) {
    if (role.id == roleId) return role;
  }
  return null;
}

/// 对局中主持人的固定头像：月代雪立绘，与应用标志同一张图。
const hostAvatarAsset = 'assets/logo.png';

/// 大厅里主持人那一行的头像：每次启动应用从有立绘的角色牌里随机挑一张。
///
/// 主持人只在对局中固定成月代雪（见 [RoleAvatar.host]），大厅阶段顶一个随机
/// 角色立绘；其他身份在大厅仍是中性占位，不借角色图暗示未公开的身份。
final String lobbyAvatarRoleId = _pickLobbyAvatarRoleId();

String _pickLobbyAvatarRoleId() {
  final pool = [for (final role in roleVisuals) if (role.hasArt) role.id];
  return pool[Random().nextInt(pool.length)];
}

/// 圆形头像；无立绘时用名称首字占位，[host] 为真时固定月代雪。
///
/// [imageUrl] 是账号头像（QQ 头像，服务端随 actor 下发）；给出时优先于角色立绘，
/// 用于大厅这类还没发牌、只代表登录账号的地方。
class RoleAvatar extends StatelessWidget {
  const RoleAvatar({
    super.key,
    required this.roleId,
    this.size = 40,
    this.dead = false,
    this.border,
    this.host = false,
    this.imageUrl,
  });

  final String? roleId;
  final double size;
  final bool dead;
  final BoxBorder? border;

  /// 主持人头像：对局中始终显示月代雪，与消息里的 `avatar_role_id == host` 对应。
  final bool host;

  /// 账号（QQ）头像地址；为空时按角色立绘或首字占位显示。
  final String? imageUrl;

  @override
  Widget build(BuildContext context) {
    final role = roleVisual(roleId);
    final remote = (imageUrl ?? '').trim();
    final asset = host
        ? hostAvatarAsset
        : role != null && role.hasArt
            ? role.avatarAsset
            : null;
    final fallback = host
        ? '月'
        : role == null
            ? '?'
            : String.fromCharCodes(role.name.runes.take(1));
    final placeholder = Container(
      width: size,
      height: size,
      alignment: Alignment.center,
      color: context.palette.surfaceStrong,
      child: Text(
        fallback,
        style: TextStyle(
          fontSize: size * 0.4,
          fontWeight: FontWeight.w600,
          color: context.palette.textSecondary,
        ),
      ),
    );
    // 图片没网、被墙或返回错误都退回占位：加载中也先显示占位，避免空圆洞。
    final Widget content;
    if (remote.isNotEmpty) {
      content = Image.network(
        remote,
        width: size,
        height: size,
        fit: BoxFit.cover,
        loadingBuilder: (context, child, progress) =>
            progress == null ? child : placeholder,
        errorBuilder: (context, error, stack) => placeholder,
      );
    } else if (asset == null) {
      content = placeholder;
    } else {
      content = Image.asset(
        asset,
        width: size,
        height: size,
        fit: BoxFit.cover,
        errorBuilder: (context, error, stack) => placeholder,
      );
    }
    final avatar = ClipOval(
      child: SizedBox(
        width: size,
        height: size,
        child: dead
            ? ColorFiltered(
                colorFilter:  ColorFilter.mode(
                    context.palette.dead, BlendMode.saturation),
                child: content,
              )
            : content,
      ),
    );
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        border: border ??
            Border.all(
              color: dead ? context.palette.dead : context.palette.border,
              width: 1.5,
            ),
      ),
      clipBehavior: Clip.antiAlias,
      child: avatar,
    );
  }
}
