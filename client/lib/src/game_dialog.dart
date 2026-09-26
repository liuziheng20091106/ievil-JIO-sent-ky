import 'package:flutter/material.dart';

import 'action_sheet.dart';
import 'design.dart';
import 'history_pages.dart';
import 'models.dart';
import 'participant_menu.dart';
import 'role_visuals.dart';
import 'store.dart';

/// 对局内的两件「看板」：技能播报卡片与悬浮对话框。
///
/// 两者都由服务端下发的结构化载荷 / `dialogs` 投影驱动，客户端不做可见性判断：
/// 私密目标与伪装标记在服务端就已经被裁掉（见 storage.project_message_payload）。

/// 技能播报：[角色头像] 3号 kiwi · 使用技能 爱上/移情 → 5号 庭雨。
/// 整卡可点，点开技能详细（技能说明 + 使用者 + 可见时显示目标）。
class SkillCastCard extends StatelessWidget {
  const SkillCastCard({super.key, required this.message, this.store});

  final GameMessage message;

  /// 为空时只展示、不可点开详情（预览与测试里可能没有 store）。
  final GameStore? store;

  Map<String, dynamic> get payload => message.payload ?? const <String, dynamic>{};

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final roleId = payload['role_id']?.toString();
    final abilityName = payload['ability_name']?.toString() ?? '';
    final seatId = payload['seat_id']?.toString() ?? '';
    final actorName = payload['actor_name']?.toString() ?? '';
    final target = payload['target'];
    final targetSeat = target is Map ? target['seat_id']?.toString() : null;
    final fake = payload['fake'] == true;
    final challengeable = payload['challengeable'] != false;
    final store = this.store;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 460),
          child: Material(
            color: palette.surface,
            borderRadius: BorderRadius.circular(AppRadius.card),
            clipBehavior: Clip.antiAlias,
            child: InkWell(
              onTap: store == null
                  ? null
                  : () => showSkillDetail(context, store, payload),
              child: Container(
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(AppRadius.card),
                  border: Border.all(
                    color: palette.accent.withValues(alpha: .45),
                    width: 1.2,
                  ),
                ),
                padding: const EdgeInsets.fromLTRB(
                  AppSpacing.md,
                  AppSpacing.md,
                  AppSpacing.md,
                  AppSpacing.sm,
                ),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        RoleAvatar(roleId: roleId, size: 38),
                        const SizedBox(width: AppSpacing.sm),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                children: [
                                  Flexible(
                                    child: Text(
                                      seatId.isEmpty
                                          ? actorName
                                          : '$seatId号 $actorName',
                                      overflow: TextOverflow.ellipsis,
                                      style: TextStyle(
                                        fontSize: 12,
                                        color: palette.textTertiary,
                                      ),
                                    ),
                                  ),
                                  if (fake) ...[
                                    const SizedBox(width: AppSpacing.xs),
                                    Tag(
                                      '伪装声明',
                                      color: palette.danger,
                                      background: palette.dangerSoft,
                                    ),
                                  ],
                                ],
                              ),
                              const SizedBox(height: 3),
                              Row(
                                crossAxisAlignment: CrossAxisAlignment.baseline,
                                textBaseline: TextBaseline.alphabetic,
                                children: [
                                  Text(
                                    '使用技能',
                                    style: TextStyle(
                                      fontSize: 13,
                                      color: palette.textSecondary,
                                    ),
                                  ),
                                  const SizedBox(width: AppSpacing.xs),
                                  Flexible(
                                    child: Text(
                                      abilityName,
                                      overflow: TextOverflow.ellipsis,
                                      style: TextStyle(
                                        fontSize: 16,
                                        fontWeight: FontWeight.w600,
                                        color: palette.accent,
                                      ),
                                    ),
                                  ),
                                  if (targetSeat != null) ...[
                                    const SizedBox(width: AppSpacing.xs),
                                    Text(
                                      '→ $targetSeat号',
                                      style: TextStyle(
                                        fontSize: 13,
                                        fontWeight: FontWeight.w600,
                                        color: palette.text,
                                      ),
                                    ),
                                  ],
                                ],
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: AppSpacing.xs),
                    Row(
                      children: [
                        Icon(
                          challengeable
                              ? Icons.help_outline
                              : Icons.verified_outlined,
                          size: 13,
                          color: palette.textTertiary,
                        ),
                        const SizedBox(width: 4),
                        Text(
                          challengeable ? '其他玩家可质疑' : '该技能不可质疑',
                          style: TextStyle(
                            fontSize: 11,
                            color: palette.textTertiary,
                          ),
                        ),
                        const Spacer(),
                        if (store != null)
                          Text(
                            '点击查看技能详细',
                            style: TextStyle(
                              fontSize: 11,
                              color: palette.accent,
                            ),
                          ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// 对局内悬浮对话框：展示重要内容并支持及时交互。
///
/// 内容与时机都由服务端的 `dialogs` 投影决定（结束信息 / 私聊申请 / 当日目击名单），
/// 这里只负责渲染，并把服务端给出的标准行动描述交给统一的行动表单提交：
/// 同意/拒绝因此仍然只有一次确认，也仍然过服务端的行动白名单校验。
class GameDialogOverlay extends StatelessWidget {
  const GameDialogOverlay({
    super.key,
    required this.store,
    required this.item,
    this.pending = 0,
    this.bottomInset = AppSpacing.bottomBar,
  });

  final GameStore store;
  final DialogItem item;

  /// 除当前这条外还排着几条：只提示数量，不一次糊满屏幕。
  final int pending;
  final double bottomInset;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final (IconData icon, Color tint, Color soft) = switch (item.kind) {
      'channel_invite' => (Icons.forum_outlined, palette.accent, palette.accentSoft),
      'witness' => (Icons.visibility_outlined, palette.accent, palette.accentSoft),
      'result' => (Icons.emoji_events_outlined, palette.host, palette.hostSoft),
      _ => (Icons.info_outline, palette.accent, palette.accentSoft),
    };
    return Align(
      alignment: Alignment.bottomCenter,
      child: Padding(
        padding: EdgeInsets.fromLTRB(
          AppSpacing.lg,
          0,
          AppSpacing.lg,
          bottomInset,
        ),
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 520),
          child: Material(
            elevation: 12,
            shadowColor: Colors.black.withValues(alpha: .18),
            color: palette.surface,
            borderRadius: BorderRadius.circular(AppRadius.card),
            clipBehavior: Clip.antiAlias,
            child: Container(
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(AppRadius.card),
                border: Border.all(color: tint.withValues(alpha: .5), width: 1.4),
              ),
              padding: const EdgeInsets.fromLTRB(
                AppSpacing.lg,
                AppSpacing.md,
                AppSpacing.lg,
                AppSpacing.md,
              ),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Container(
                        width: 34,
                        height: 34,
                        decoration: BoxDecoration(color: soft, shape: BoxShape.circle),
                        child: Icon(icon, size: 18, color: tint),
                      ),
                      const SizedBox(width: AppSpacing.md),
                      Expanded(
                        child: Text(
                          item.title,
                          style: TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.w600,
                            color: palette.text,
                          ),
                        ),
                      ),
                      if (pending > 0)
                        Padding(
                          padding: const EdgeInsets.only(right: AppSpacing.xs),
                          child: Tag(
                            '还有 $pending 条',
                            color: palette.textSecondary,
                            background: palette.surfaceMuted,
                          ),
                        ),
                      if (item.dismissible)
                        IconButton(
                          tooltip: '稍后处理',
                          onPressed: () => store.dismissDialog(item.id),
                          icon: const Icon(Icons.close, size: 18),
                        ),
                    ],
                  ),
                  if (item.text.isNotEmpty) ...[
                    const SizedBox(height: AppSpacing.sm),
                    Text(
                      item.text,
                      style: TextStyle(
                        fontSize: 14,
                        height: 1.5,
                        color: palette.textSecondary,
                      ),
                    ),
                  ],
                  if (item.actions.isNotEmpty) ...[
                    const SizedBox(height: AppSpacing.md),
                    Row(
                      children: [
                        for (final action in item.actions) ...[
                          Expanded(
                            child: action.id == 'channel.accept'
                                ? FilledButton(
                                    onPressed: store.writeBusy
                                        ? null
                                        : () => showActionForm(context, store, action),
                                    child: Text(action.shortLabel),
                                  )
                                : OutlinedButton(
                                    onPressed: store.writeBusy
                                        ? null
                                        : () => showActionForm(context, store, action),
                                    child: Text(
                                      action.shortLabel,
                                      style: TextStyle(color: palette.danger),
                                    ),
                                  ),
                          ),
                          if (action != item.actions.last)
                            const SizedBox(width: AppSpacing.md),
                        ],
                      ],
                    ),
                  ],
                  if (item.kind == 'result' && item.matchId != null)
                    Align(
                      alignment: Alignment.centerLeft,
                      child: TextButton.icon(
                        onPressed: () => Navigator.of(context).push(
                          MaterialPageRoute(
                            builder: (_) => MatchDetailPage(
                              store: store,
                              matchId: item.matchId!,
                            ),
                          ),
                        ),
                        icon: const Icon(Icons.history_outlined, size: 18),
                        label: const Text('查看本局记录'),
                      ),
                    ),
                  if (item.actions.isEmpty && item.dismissible && item.kind != 'result')
                    Align(
                      alignment: Alignment.centerRight,
                      child: TextButton(
                        onPressed: () => store.dismissDialog(item.id),
                        child: const Text('知道了'),
                      ),
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
