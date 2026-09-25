import 'package:flutter/material.dart';

import 'design.dart';

/// 玩家标记：玩家在脑子里对别人的阵营判断，只是本机的笔记。
///
/// 三条边界（和「私密草稿」同级）：
///  * 只存在客户端内存里，既不上传服务端，也不写进本地偏好，退出应用即清空；
///  * 标记按参与身份 id 存放，换局、踢人、替补换身份都不会把标记串到别人身上；
///  * 标记不参与任何规则判定，服务端不知道它的存在，界面只拿它给名字上色。
enum PlayerMark {
  witch('魔女', '判断为魔女阵营', Icons.local_fire_department_outlined),
  good('好人', '判断为好人阵营', Icons.verified_outlined),
  suspectedWitch('疑似魔女', '怀疑是魔女阵营，但还不确定', Icons.help_outline),
  suspectedGood('疑似好人', '倾向是好人阵营，但还不确定', Icons.thumb_up_outlined);

  const PlayerMark(this.label, this.description, this.icon);

  final String label;
  final String description;
  final IconData icon;

  /// 名字与色点用的颜色：四种标记各一色（清除标记用默认文字色，见 [kPlayerMarkClearedColor]）。
  Color colorOf(AppPalette palette) => switch (this) {
        PlayerMark.witch => palette.danger,
        PlayerMark.good => palette.success,
        PlayerMark.suspectedWitch => palette.warning,
        PlayerMark.suspectedGood => palette.info,
      };
}

/// 「清除标记」在色板里的颜色：第五种颜色，等于回到默认文字色。
Color clearedMarkColorOf(AppPalette palette) => palette.textTertiary;

/// 名字该用的颜色：有标记才是标记色，没有标记返回 null，由调用方决定默认色。
Color? playerMarkColorOf(BuildContext context, PlayerMark? mark) =>
    mark?.colorOf(context.palette);

/// 标记色点：菜单、教程与名字前缀共用同一套颜色，避免各处说法不一致。
class PlayerMarkDot extends StatelessWidget {
  const PlayerMarkDot({
    super.key,
    required this.color,
    this.size = 14,
    this.icon,
  });

  final Color color;
  final double size;
  final IconData? icon;

  @override
  Widget build(BuildContext context) => Container(
        width: size,
        height: size,
        alignment: Alignment.center,
        decoration: BoxDecoration(color: color, shape: BoxShape.circle),
        child: icon == null
            ? null
            : Icon(icon, size: size * .68, color: context.palette.onAccent),
      );
}
