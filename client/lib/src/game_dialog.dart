import 'package:flutter/material.dart';

import 'action_sheet.dart';
import 'design.dart';
import 'history_pages.dart';
import 'models.dart';
import 'participant_menu.dart';
import 'predictive_sheet.dart';
import 'role_visuals.dart';
import 'store.dart';

/// 对局内的两件「看板」：技能播报卡片与悬浮对话框。
///
/// 两者都由服务端下发的结构化载荷 / `dialogs` 投影驱动，客户端不做可见性判断：
/// 私密目标与伪装标记在服务端就已经被裁掉（见 storage.project_message_payload）。

/// 技能播报：[角色头像] 3号 kiwi · 使用技能 爱上/移情 → 5号 庭雨。
/// 整卡可点，点开技能详细（技能说明 + 使用者 + 可见时显示目标）。
///
/// 被动技能（处决幻视、时间回溯、替死、爱人庇护……）复用同一张卡，只换边框颜色
/// （被动＝绿、主动＝紫）与措辞（「被动技能」＋本次结算结果），一眼能区分。
/// 卡片内容完全由服务端载荷决定：不会看到不该看到的玩家才看得到这条消息，
/// 载荷里也只带该收件人有权知道的字段（见 storage.project_message_payload）。
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
    // 被动技能：自动生效、不可声明也不可质疑，样式与主动技能区分开。
    final passive = payload['mode']?.toString() == 'passive';
    final effect = payload['effect']?.toString() ?? '';
    final tint = passive ? palette.success : palette.accent;
    final soft = passive ? palette.successSoft : palette.accentSoft;
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
                    color: tint.withValues(alpha: .45),
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
                                  if (passive) ...[
                                    const SizedBox(width: AppSpacing.xs),
                                    Tag(
                                      '被动',
                                      color: palette.success,
                                      background: palette.successSoft,
                                    ),
                                  ],
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
                                    passive ? '被动技能' : '使用技能',
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
                                        color: tint,
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
                    // 被动技能没有「声明」这一步，卡片补一行本次自动结算的结果。
                    if (passive && effect.isNotEmpty) ...[
                      const SizedBox(height: AppSpacing.sm),
                      Container(
                        width: double.infinity,
                        padding: const EdgeInsets.symmetric(
                          horizontal: AppSpacing.sm,
                          vertical: 6,
                        ),
                        decoration: BoxDecoration(
                          color: soft,
                          borderRadius: BorderRadius.circular(AppRadius.field),
                        ),
                        child: Text(
                          effect,
                          style: TextStyle(
                            fontSize: 13,
                            height: 1.45,
                            color: palette.text,
                          ),
                        ),
                      ),
                    ],
                    const SizedBox(height: AppSpacing.xs),
                    Row(
                      children: [
                        Icon(
                          passive
                              ? Icons.bolt_outlined
                              : challengeable
                                  ? Icons.help_outline
                                  : Icons.verified_outlined,
                          size: 13,
                          color: palette.textTertiary,
                        ),
                        const SizedBox(width: 4),
                        Text(
                          passive
                              ? '自动生效 · 不必也不能声明'
                              : challengeable
                                  ? '其他玩家可质疑'
                                  : '该技能不可质疑',
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
                              color: tint,
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

/// 情报只展示公开署名与全文，不携带角色或技能声明。
class IntelligenceCastCard extends StatelessWidget {
  const IntelligenceCastCard({super.key, required this.message});

  final GameMessage message;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final payload = message.payload ?? const <String, dynamic>{};
    final day = payload['day']?.toString() ?? '';
    final seatId = payload['seat_id']?.toString() ?? '';
    final actorName = payload['actor_name']?.toString() ?? '';
    final text = payload['text']?.toString() ?? '';
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 460),
          child: Container(
            width: double.infinity,
            decoration: BoxDecoration(
              color: palette.surface,
              borderRadius: BorderRadius.circular(AppRadius.card),
              border: Border.all(
                color: palette.accent.withValues(alpha: .45),
                width: 1.2,
              ),
            ),
            padding: const EdgeInsets.all(AppSpacing.md),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon(Icons.article_outlined, size: 38,
                        color: palette.accent),
                    const SizedBox(width: AppSpacing.sm),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text('第$day天 · 情报', style: TextStyle(
                              fontSize: 16, fontWeight: FontWeight.w600,
                              color: palette.accent)),
                          const SizedBox(height: 3),
                          Text('$seatId号 $actorName', style: TextStyle(
                              fontSize: 12, color: palette.textTertiary)),
                        ],
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: AppSpacing.sm),
                Text(text, softWrap: true, style: TextStyle(
                    fontSize: 15, height: 1.5, color: palette.text)),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// 开局插件公告沿用技能播报卡片外观；说明只在点开后展示。
class PluginCastCard extends StatelessWidget {
  const PluginCastCard({super.key, required this.payload});

  final Map<String, dynamic> payload;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final name = payload['name'] as String;
    final version = payload['version'].toString();
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
              onTap: () => showPredictiveSheet<void>(
                context: context,
                useSafeArea: true,
                isScrollControlled: true,
                builder: (context) => SafeArea(
                  top: false,
                  child: SingleChildScrollView(
                    padding: const EdgeInsets.fromLTRB(
                      AppSpacing.xl, 0, AppSpacing.xl, AppSpacing.xl,
                    ),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Icon(Icons.extension_outlined, size: 38,
                                color: palette.accent),
                            const SizedBox(width: AppSpacing.md),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text('规则插件详情', style: TextStyle(
                                      fontSize: 12, color: palette.accent)),
                                  Text(name, style: TextStyle(fontSize: 18,
                                      fontWeight: FontWeight.w600,
                                      color: palette.text)),
                                ],
                              ),
                            ),
                            IconButton(
                              tooltip: '关闭',
                              onPressed: () => Navigator.pop(context),
                              icon: const Icon(Icons.close, size: 20),
                            ),
                          ],
                        ),
                        const SizedBox(height: AppSpacing.md),
                        Text('版本 v$version', style: TextStyle(
                            fontSize: 13, color: palette.textSecondary)),
                        const SizedBox(height: AppSpacing.lg),
                        Text('规则介绍', style: TextStyle(
                            fontSize: 13, fontWeight: FontWeight.w600,
                            color: palette.accent)),
                        const SizedBox(height: AppSpacing.sm),
                        Text(payload['description'] as String,
                            style: TextStyle(fontSize: 15, height: 1.5,
                                color: palette.text)),
                      ],
                    ),
                  ),
                ),
              ),
              child: Container(
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(AppRadius.card),
                  border: Border.all(
                    color: palette.accent.withValues(alpha: .45), width: 1.2,
                  ),
                ),
                padding: const EdgeInsets.fromLTRB(
                  AppSpacing.md, AppSpacing.md, AppSpacing.md, AppSpacing.sm,
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Icon(Icons.extension_outlined, size: 38,
                            color: palette.accent),
                        const SizedBox(width: AppSpacing.sm),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text('本局规则插件', style: TextStyle(
                                  fontSize: 12, color: palette.textTertiary)),
                              const SizedBox(height: 3),
                              Text('$name · v$version',
                                  overflow: TextOverflow.ellipsis,
                                  style: TextStyle(fontSize: 16,
                                      fontWeight: FontWeight.w600,
                                      color: palette.accent)),
                            ],
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: AppSpacing.xs),
                    Align(
                      alignment: Alignment.centerRight,
                      child: Text('点击查看规则详细', style: TextStyle(
                          fontSize: 11, color: palette.accent)),
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

/// 角色卡死亡卡片：[头像] N号 昵称 · 角色名，一张角色牌出局。
///
/// 夜间出局与天亮汇总同一条消息，一夜多人都出局时合并成一张卡（与「天亮只发一条
/// 死亡汇总」同一口径）。载荷里只有公开信息：席位、展示名、死亡时的**公开头像**与
/// 是否13水毒杀——真实牌、死因、殉情与替死都不在这里，也不该在这里。
class DeathCastCard extends StatelessWidget {
  const DeathCastCard({super.key, required this.message});

  final GameMessage message;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final payload = message.payload ?? const <String, dynamic>{};
    final deaths = (payload['deaths'] as List?)
            ?.whereType<Map>()
            .map((item) => item.map((key, value) => MapEntry(key.toString(), value)))
            .toList() ??
        const <Map<String, dynamic>>[];
    if (deaths.isEmpty) return const SizedBox.shrink();
    final night = payload['half']?.toString() == 'night';
    final day = payload['day']?.toString() ?? '';
    final title = night && day.isNotEmpty ? '第$day夜 · 出局公告' : '出局公告';
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 460),
          child: Container(
            decoration: BoxDecoration(
              color: palette.dangerSoft,
              borderRadius: BorderRadius.circular(AppRadius.card),
              border: Border.all(
                color: palette.danger.withValues(alpha: .55),
                width: 1.2,
              ),
            ),
            padding: const EdgeInsets.fromLTRB(
              AppSpacing.md,
              AppSpacing.sm,
              AppSpacing.md,
              AppSpacing.md,
            ),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(
                      Icons.style_outlined,
                      size: 14,
                      color: palette.danger,
                    ),
                    const SizedBox(width: 5),
                    Text(
                      title,
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                        color: palette.danger,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: AppSpacing.sm),
                for (final entry in deaths)
                  Padding(
                    padding: EdgeInsets.only(
                      bottom: entry == deaths.last ? 0 : AppSpacing.sm,
                    ),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.center,
                      children: [
                        RoleAvatar(
                          roleId: entry['avatar_role_id']?.toString(),
                          size: 36,
                        ),
                        const SizedBox(width: AppSpacing.sm),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                children: [
                                  Flexible(
                                    child: Text(
                                      '${entry['seat_id'] ?? ''}号'
                                      ' ${entry['player_name'] ?? ''}'.trimRight(),
                                      overflow: TextOverflow.ellipsis,
                                      style: TextStyle(
                                        fontSize: 12,
                                        color: palette.textTertiary,
                                      ),
                                    ),
                                  ),
                                  if ((entry['role_name']?.toString() ?? '')
                                      .isNotEmpty) ...[
                                    const SizedBox(width: AppSpacing.xs),
                                    Tag(
                                      entry['role_name'].toString(),
                                      color: palette.danger,
                                      background: palette.dangerSoft,
                                    ),
                                  ],
                                ],
                              ),
                              const SizedBox(height: 3),
                              Text(
                                entry['water'] == true
                                    ? '这张角色牌被13水毒杀。'
                                    : '这张角色牌出局。',
                                style: TextStyle(
                                  fontSize: 14,
                                  fontWeight: FontWeight.w600,
                                  color: palette.text,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
              ],
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
