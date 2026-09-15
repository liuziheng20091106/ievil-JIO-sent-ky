import 'package:flutter/material.dart';

import 'app_icons.dart';
import 'design.dart';
import 'models.dart';
import 'role_visuals.dart';

/// 自绘选择界面：选玩家显示「头像 + 名字 + 角色」，选行动显示图标。

class PickedPlayer {
  const PickedPlayer(
      {required this.id,
      required this.name,
      this.seatId,
      this.roleId,
      this.dead = false,
      this.subtitle});

  final String id;
  final String name;
  final String? seatId;
  final String? roleId;
  final bool dead;
  final String? subtitle;
}

/// 从服务端字段选项构造玩家条目；角色取自当前牌桌视图。
///
/// 行动选项的 value 是参与者 id，座位视图用 participant_id 关联；
/// 玩家视角拿不到别人的牌，因此角色会在界面上显示为「角色未公开」。
List<PickedPlayer> playersFromOptions(
  List<Map<String, dynamic>> options, {
  List<Map<String, dynamic>>? seats,
}) {
  final byParticipant = <String, Map<String, dynamic>>{};
  for (final seat in seats ?? const <Map<String, dynamic>>[]) {
    final participantId =
        seat['participant_id']?.toString() ?? seat['occupant_id']?.toString();
    if (participantId == null) continue;
    byParticipant[participantId] = seat;
  }
  return [
    for (final option in options)
      () {
        final id = option['value'].toString();
        final seat = byParticipant[id];
        final cards = seat?['cards'];
        final roleId = cards is List && cards.isNotEmpty && cards.first is Map
            ? (cards.first as Map)['role_id']?.toString()
            : null;
        return PickedPlayer(
          id: id,
          name: option['label'].toString(),
          seatId: seat?['id']?.toString(),
          roleId: roleId,
          dead: seat?['alive'] == false,
        );
      }(),
  ];
}

/// 选玩家：头像 + 名字 + 角色；单选用列表，多选用可勾选列表。
Future<List<String>?> showPlayerPicker(
  BuildContext context, {
  required String title,
  String? subtitle,
  required List<PickedPlayer> players,
  List<String> selected = const [],
  bool multi = false,
  int? min,
  int? max,
}) =>
    showModalBottomSheet<List<String>>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (context) => _PlayerPickerSheet(
        title: title,
        subtitle: subtitle,
        players: players,
        initial: selected,
        multi: multi,
        min: min,
        max: max,
      ),
    );

class _PlayerPickerSheet extends StatefulWidget {
  const _PlayerPickerSheet({
    required this.title,
    required this.players,
    required this.initial,
    required this.multi,
    this.subtitle,
    this.min,
    this.max,
  });

  final String title;
  final String? subtitle;
  final List<PickedPlayer> players;
  final List<String> initial;
  final bool multi;
  final int? min;
  final int? max;

  @override
  State<_PlayerPickerSheet> createState() => _PlayerPickerSheetState();
}

class _PlayerPickerSheetState extends State<_PlayerPickerSheet> {
  late List<String> chosen = [...widget.initial];

  @override
  Widget build(BuildContext context) {
    final max = widget.max;
    return SizedBox(
      height: MediaQuery.sizeOf(context).height * .72,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(
                AppSpacing.xl, 0, AppSpacing.xl, AppSpacing.sm),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  widget.title,
                  style: const TextStyle(
                      fontSize: 20,
                      fontWeight: FontWeight.w600,
                      color: AppColors.text),
                ),
                if (widget.subtitle != null) ...[
                  const SizedBox(height: AppSpacing.xs),
                  Text(
                    widget.subtitle!,
                    style: const TextStyle(
                        fontSize: 13, color: AppColors.textTertiary),
                  ),
                ],
                if (max != null) ...[
                  const SizedBox(height: AppSpacing.xs),
                  Text(
                    '已选 ${chosen.length} / $max',
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: chosen.length > max
                          ? AppColors.danger
                          : AppColors.accent,
                    ),
                  ),
                ],
              ],
            ),
          ),
          Expanded(
            child: widget.players.isEmpty
                ? const EmptyState(
                    icon: Icons.person_off_outlined, title: '当前没有可选对象')
                : ListView.separated(
                    padding: const EdgeInsets.fromLTRB(
                        AppSpacing.lg, 0, AppSpacing.lg, AppSpacing.lg),
                    itemCount: widget.players.length,
                    separatorBuilder: (_, __) =>
                        const SizedBox(height: AppSpacing.sm),
                    itemBuilder: (context, index) {
                      final player = widget.players[index];
                      final picked = chosen.contains(player.id);
                      final blocked =
                          !picked && max != null && chosen.length >= max;
                      return _PlayerRow(
                        player: player,
                        picked: picked,
                        disabled: blocked,
                        onTap: () {
                          setState(() {
                            if (widget.multi) {
                              picked
                                  ? chosen.remove(player.id)
                                  : chosen.add(player.id);
                            } else {
                              chosen = [player.id];
                            }
                          });
                          if (!widget.multi) Navigator.pop(context, chosen);
                        },
                      );
                    },
                  ),
          ),
          if (widget.multi)
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.lg, 0, AppSpacing.lg, AppSpacing.lg),
              child: SafeArea(
                top: false,
                child: FilledButton(
                  onPressed: chosen.isEmpty && (widget.min ?? 1) > 0
                      ? null
                      : () => Navigator.pop(context, chosen),
                  child: Text(chosen.isEmpty ? '请选择' : '确定（${chosen.length}）'),
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class _PlayerRow extends StatelessWidget {
  const _PlayerRow({
    required this.player,
    required this.picked,
    required this.onTap,
    this.disabled = false,
  });

  final PickedPlayer player;
  final bool picked;
  final bool disabled;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final role = roleVisual(player.roleId);
    return Opacity(
      opacity: disabled ? .45 : 1,
      child: Material(
        color: picked ? AppColors.accentSoft : AppColors.surface,
        borderRadius: BorderRadius.circular(AppRadius.card),
        child: InkWell(
          onTap: disabled ? null : onTap,
          borderRadius: BorderRadius.circular(AppRadius.card),
          child: Container(
            padding: const EdgeInsets.all(AppSpacing.md),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(AppRadius.card),
              border: Border.all(
                  color: picked ? AppColors.accent : AppColors.border,
                  width: picked ? 1.6 : 1),
            ),
            child: Row(
              children: [
                RoleAvatar(roleId: player.roleId, size: 44, dead: player.dead),
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        player.seatId != null
                            ? '${player.seatId}号 · ${player.name}'
                            : player.name,
                        style: const TextStyle(
                            fontSize: 15,
                            fontWeight: FontWeight.w600,
                            color: AppColors.text),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        role != null
                            ? '角色：${role.name}'
                            : (player.subtitle ?? '角色未公开'),
                        style: const TextStyle(
                            fontSize: 13, color: AppColors.textTertiary),
                      ),
                    ],
                  ),
                ),
                if (player.dead)
                  const Tag('已出局',
                      color: AppColors.textSecondary,
                      background: AppColors.surfaceMuted),
                if (picked) ...[
                  const SizedBox(width: AppSpacing.sm),
                  const Icon(Icons.check_circle,
                      size: 22, color: AppColors.accent),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// 选行动：图标 + 短名 + 完整说明。
Future<ActionDescriptor?> showActionPicker(
  BuildContext context, {
  required List<ActionDescriptor> actions,
  String title = '可用行动',
}) =>
    showModalBottomSheet<ActionDescriptor>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (context) => SizedBox(
        height: MediaQuery.sizeOf(context).height * .7,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.xl, 0, AppSpacing.xl, AppSpacing.md),
              child: Text(
                title,
                style: const TextStyle(
                    fontSize: 20,
                    fontWeight: FontWeight.w600,
                    color: AppColors.text),
              ),
            ),
            Expanded(
              child: ListView.separated(
                padding: const EdgeInsets.fromLTRB(
                    AppSpacing.lg, 0, AppSpacing.lg, AppSpacing.lg),
                itemCount: actions.length,
                separatorBuilder: (_, __) =>
                    const SizedBox(height: AppSpacing.sm),
                itemBuilder: (context, index) {
                  final action = actions[index];
                  final unsupported = action.unsupportedReason;
                  final danger = action.raw['danger'] == true;
                  return Material(
                    color: AppColors.surface,
                    borderRadius: BorderRadius.circular(AppRadius.card),
                    child: InkWell(
                      borderRadius: BorderRadius.circular(AppRadius.card),
                      onTap: () => Navigator.pop(context, action),
                      child: Container(
                        padding: const EdgeInsets.all(AppSpacing.md),
                        decoration: BoxDecoration(
                          borderRadius: BorderRadius.circular(AppRadius.card),
                          border: Border.all(color: AppColors.border),
                        ),
                        child: Row(
                          children: [
                            ActionIconBadge(
                              actionId: action.id,
                              group: action.group,
                              danger: danger,
                            ),
                            const SizedBox(width: AppSpacing.md),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Row(
                                    children: [
                                      Text(
                                        action.shortLabel,
                                        style: TextStyle(
                                          fontSize: 15,
                                          fontWeight: FontWeight.w600,
                                          color: danger
                                              ? AppColors.danger
                                              : AppColors.text,
                                        ),
                                      ),
                                      const SizedBox(width: AppSpacing.sm),
                                      Expanded(
                                        child: Text(
                                          action.group,
                                          style: const TextStyle(
                                              fontSize: 12,
                                              color: AppColors.textTertiary),
                                        ),
                                      ),
                                    ],
                                  ),
                                  const SizedBox(height: 2),
                                  Text(
                                    unsupported ?? action.label,
                                    style: TextStyle(
                                      fontSize: 13,
                                      color: unsupported != null
                                          ? AppColors.danger
                                          : AppColors.textSecondary,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                            if (unsupported != null)
                              const Icon(Icons.block,
                                  size: 20, color: AppColors.danger)
                            else
                              const Icon(Icons.chevron_right,
                                  color: AppColors.textTertiary),
                          ],
                        ),
                      ),
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );

/// 选魔典：13 张有立绘的角色卡，正好选 11 名。
Future<List<String>?> showCodexPicker(
  BuildContext context, {
  required List<String> initial,
  required int requiredCount,
}) =>
    showModalBottomSheet<List<String>>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (context) =>
          _CodexPickerSheet(initial: initial, requiredCount: requiredCount),
    );

class _CodexPickerSheet extends StatefulWidget {
  const _CodexPickerSheet({required this.initial, required this.requiredCount});

  final List<String> initial;
  final int requiredCount;

  @override
  State<_CodexPickerSheet> createState() => _CodexPickerSheetState();
}

class _CodexPickerSheetState extends State<_CodexPickerSheet> {
  late List<String> chosen = [...widget.initial];

  @override
  Widget build(BuildContext context) {
    final complete = chosen.length == widget.requiredCount;
    return SizedBox(
      height: MediaQuery.sizeOf(context).height * .8,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(
                AppSpacing.xl, 0, AppSpacing.xl, AppSpacing.sm),
            child: Row(
              children: [
                const Expanded(
                  child: Text(
                    '选择本局魔典',
                    style: TextStyle(
                        fontSize: 20,
                        fontWeight: FontWeight.w600,
                        color: AppColors.text),
                  ),
                ),
                Tag(
                  '${chosen.length} / ${widget.requiredCount}',
                  color: complete ? AppColors.success : AppColors.accent,
                  background:
                      complete ? AppColors.successSoft : AppColors.accentSoft,
                ),
              ],
            ),
          ),
          const Padding(
            padding: EdgeInsets.fromLTRB(
                AppSpacing.xl, 0, AppSpacing.xl, AppSpacing.md),
            child: Text(
              '必须正好选择 11 名角色，开场后随机排列。',
              style: TextStyle(fontSize: 13, color: AppColors.textTertiary),
            ),
          ),
          Expanded(
            child: GridView.builder(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.lg, 0, AppSpacing.lg, AppSpacing.lg),
              gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(
                maxCrossAxisExtent: 132,
                mainAxisSpacing: AppSpacing.md,
                crossAxisSpacing: AppSpacing.md,
                childAspectRatio: .82,
              ),
              itemCount: roleVisuals.length,
              itemBuilder: (context, index) {
                final role = roleVisuals[index];
                final picked = chosen.contains(role.id);
                final blocked =
                    !picked && chosen.length >= widget.requiredCount;
                return _CodexCard(
                  role: role,
                  picked: picked,
                  disabled: blocked,
                  onTap: () => setState(() {
                    picked ? chosen.remove(role.id) : chosen.add(role.id);
                  }),
                );
              },
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(
                AppSpacing.lg, 0, AppSpacing.lg, AppSpacing.lg),
            child: SafeArea(
              top: false,
              child: FilledButton(
                onPressed:
                    complete ? () => Navigator.pop(context, chosen) : null,
                child: Text(complete
                    ? '确定魔典（11）'
                    : '还需 ${widget.requiredCount - chosen.length} 名'),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _CodexCard extends StatelessWidget {
  const _CodexCard({
    required this.role,
    required this.picked,
    required this.onTap,
    this.disabled = false,
  });

  final RoleVisual role;
  final bool picked;
  final bool disabled;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Opacity(
        opacity: disabled ? .4 : 1,
        child: Material(
          color: AppColors.surface,
          borderRadius: BorderRadius.circular(AppRadius.card),
          child: InkWell(
            onTap: disabled ? null : onTap,
            borderRadius: BorderRadius.circular(AppRadius.card),
            child: Container(
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(AppRadius.card),
                border: Border.all(
                    color: picked ? AppColors.accent : AppColors.border,
                    width: picked ? 2 : 1),
              ),
              padding: const EdgeInsets.all(AppSpacing.sm),
              child: Column(
                children: [
                  Expanded(
                    child: Stack(
                      children: [
                        Center(child: RoleAvatar(roleId: role.id, size: 64)),
                        if (picked)
                          const Positioned(
                            right: 0,
                            top: 0,
                            child: Icon(Icons.check_circle,
                                size: 20, color: AppColors.accent),
                          ),
                      ],
                    ),
                  ),
                  const SizedBox(height: AppSpacing.xs),
                  Text(
                    role.name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: picked ? FontWeight.w600 : FontWeight.w500,
                      color: picked ? AppColors.accent : AppColors.text,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
}
