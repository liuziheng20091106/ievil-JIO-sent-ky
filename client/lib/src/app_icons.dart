import 'package:flutter/material.dart';
import 'package:flutter_svg/flutter_svg.dart';

import 'design.dart';
import 'role_visuals.dart';

/// 渲染某个行动的图标：优先自绘 SVG，其次 Material 图标，最后兜底图形。
class ActionIcon extends StatelessWidget {
   ActionIcon(
      {super.key, required this.actionId, this.size = 22, this.color});

  final String actionId;
  final double size;
  final Color? color;

  @override
  Widget build(BuildContext context) {
    final tint = color ?? context.palette.textSecondary;
    final svg = ActionIcons.svgFor(actionId);
    if (svg != null) {
      return SvgPicture.asset(
        svg.asset,
        width: size,
        height: size,
        colorFilter: ColorFilter.mode(tint, BlendMode.srcIn),
      );
    }
    return Icon(ActionIcons.materialFor(actionId) ?? ActionIcons.fallback,
        size: size, color: tint);
  }
}

/// 行动分区的主色，用于图标底色。
Color actionTint(BuildContext context, String group, {bool danger = false}) {
  if (danger) return context.palette.danger;
  return switch (group) {
    '开局' || '准备' => context.palette.host,
    '私密管理' || '私密信息' => context.palette.host,
    '投票' => context.palette.accent,
    '热气球' => context.palette.info,
    '房间管理' => context.palette.textSecondary,
    '私信' => context.palette.info,
    '流程' => context.palette.accent,
    _ => context.palette.accent,
  };
}

/// 圆角方形图标底板 + 图标，行动卡片与选择器共用。
class ActionIconBadge extends StatelessWidget {
  const ActionIconBadge({
    super.key,
    required this.actionId,
    this.group = '行动',
    this.danger = false,
    this.size = 44,
  });

  final String actionId;
  final String group;
  final bool danger;
  final double size;

  @override
  Widget build(BuildContext context) {
    final tint = actionTint(context, group, danger: danger);
    return Container(
      width: size,
      height: size,
      decoration: BoxDecoration(
        color: tint.withValues(alpha: .10),
        borderRadius: BorderRadius.circular(size * .32),
      ),
      alignment: Alignment.center,
      child: ActionIcon(actionId: actionId, size: size * .5, color: tint),
    );
  }
}

/// 应用标志：月代雪立绘。
class AppLogo extends StatelessWidget {
  const AppLogo({super.key, this.size = 56, this.rounded = false});

  final double size;
  final bool rounded;

  @override
  Widget build(BuildContext context) => ClipRRect(
        borderRadius: BorderRadius.circular(rounded ? size * .28 : size / 2),
        child: Image.asset(
          'assets/logo.png',
          width: size,
          height: size,
          fit: BoxFit.cover,
          errorBuilder: (context, error, stack) => Container(
            width: size,
            height: size,
            color: context.palette.accentSoft,
            alignment: Alignment.center,
            child: Icon(Icons.local_florist_outlined,
                size: size * .5, color: context.palette.accent),
          ),
        ),
      );
}
