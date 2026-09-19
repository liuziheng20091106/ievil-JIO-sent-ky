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
    'marg.mimic': Icons.masks_outlined,
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
    'hiro.rewind': Icons.settings_backup_restore_outlined,
    'hiro.decline': Icons.arrow_forward_outlined,
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

  /// 自绘 SVG 的行动；覆盖 Material 表里语义不贴合的四个。
  static const Map<String, AppSvg> svg = {
    'balloon.choose': AppSvg.balloon,
    'balloon.propose': AppSvg.balloon,
    'balloon.agree': AppSvg.balloonCheck,
    'balloon.decline': AppSvg.balloonCross,
  };

  static const fallback = Icons.circle_outlined;

  static IconData? materialFor(String actionId) => material[actionId];

  static AppSvg? svgFor(String actionId) => svg[actionId];

  /// 表里登记过的行动 id（含 SVG 项）。
  static Set<String> get covered => {...material.keys, ...svg.keys};
}

/// 自绘 SVG 图标。
enum AppSvg {
  /// 热气球。
  balloon,

  /// 热气球 + 对勾（同意名单）。
  balloonCheck,

  /// 热气球 + 叉（否决名单）。
  balloonCross,

  /// 应用标志（月代雪立绘的替代图形，用于无图场景）。
  seal,
}

extension AppSvgPath on AppSvg {
  String get asset => switch (this) {
        AppSvg.balloon => 'assets/icons/balloon.svg',
        AppSvg.balloonCheck => 'assets/icons/balloon_check.svg',
        AppSvg.balloonCross => 'assets/icons/balloon_cross.svg',
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

/// 角色圆形头像；无立绘时用名称首字占位。
class RoleAvatar extends StatelessWidget {
  const RoleAvatar({
    super.key,
    required this.roleId,
    this.size = 40,
    this.dead = false,
    this.border,
  });

  final String? roleId;
  final double size;
  final bool dead;
  final BoxBorder? border;

  @override
  Widget build(BuildContext context) {
    final role = roleVisual(roleId);
    final content = role == null || !role.hasArt
        ? Container(
            width: size,
            height: size,
            alignment: Alignment.center,
            color: AppColors.surfaceStrong,
            child: Text(
              role == null
                  ? '?'
                  : String.fromCharCodes(role.name.runes.take(1)),
              style: TextStyle(
                fontSize: size * 0.4,
                fontWeight: FontWeight.w600,
                color: AppColors.textSecondary,
              ),
            ),
          )
        : Image.asset(
            role.avatarAsset,
            width: size,
            height: size,
            fit: BoxFit.cover,
            errorBuilder: (context, error, stack) => Container(
              width: size,
              height: size,
              color: AppColors.surfaceStrong,
              alignment: Alignment.center,
              child: Text(
                role.name.characters.first,
                style: TextStyle(
                    fontSize: size * 0.4, color: AppColors.textSecondary),
              ),
            ),
          );
    final avatar = ClipOval(
      child: SizedBox(
        width: size,
        height: size,
        child: dead
            ? ColorFiltered(
                colorFilter: const ColorFilter.mode(
                    AppColors.dead, BlendMode.saturation),
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
              color: dead ? AppColors.dead : AppColors.border,
              width: 1.5,
            ),
      ),
      clipBehavior: Clip.antiAlias,
      child: avatar,
    );
  }
}
