import 'package:flutter/material.dart';

import 'app_icons.dart';
import 'design.dart';
import 'models.dart';
import 'predictive_sheet.dart';
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
/// 选项的 value 既可能是参与者 id（房间管理、私信），也可能是席位号（对局内选目标），
/// 两种都按各自的键关联到席位。`byRole` 为真时（服务端在座位类字段上标了
/// options_kind=seat）用「角色名」当显示名：对局内选择界面一律以角色卡标识席位，
/// 不显示玩家昵称；候场阶段服务端不下发角色，因此会自然退回公开称呼。
List<PickedPlayer> playersFromOptions(
  List<Map<String, dynamic>> options, {
  List<Map<String, dynamic>>? seats,
  bool byRole = false,
}) {
  final byParticipant = <String, Map<String, dynamic>>{};
  final bySeat = <String, Map<String, dynamic>>{};
  for (final seat in seats ?? const <Map<String, dynamic>>[]) {
    final seatId = seat['id']?.toString();
    if (seatId != null) {
      bySeat[seatId] = seat;
    }
    final participantId =
        seat['participant_id']?.toString() ?? seat['occupant_id']?.toString();
    if (participantId == null) continue;
    byParticipant[participantId] = seat;
  }
  return [
    for (final option in options)
      () {
        final id = option['value'].toString();
        final seat = byParticipant[id] ?? bySeat[id];
        final seatId = seat?['id']?.toString();
        // 头像与服务端 avatar_role_id 对齐：上层牌出局后 cards.first 是死人，
        // 穗乃香示人时也不等于展示角色；avatar_role_id 未给出时回退到上层牌。
        var roleId = seat?['avatar_role_id']?.toString();
        if (roleId == null) {
          final cards = seat?['cards'];
          if (cards is List && cards.isNotEmpty) {
            roleId = cards.first['role_id']?.toString();
          }
        }
        final role = roleVisual(roleId);
        return PickedPlayer(
          id: id,
          name: byRole && role != null
              ? role.name
              : _withoutSeatPrefix(option['label'].toString(), seatId),
          seatId: seatId,
          roleId: roleId,
          dead: seat?['alive'] == false,
        );
      }(),
  ];
}

/// 去掉服务端标签里已经带上的「N号 · 」前缀：行里会自己拼座位号，否则会写两遍。
String _withoutSeatPrefix(String label, String? seatId) {
  if (seatId == null) return label;
  final prefix = '$seatId号 · ';
  return label.startsWith(prefix) ? label.substring(prefix.length) : label;
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
    showPredictiveSheet<List<String>>(
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
                  style:  TextStyle(
                      fontSize: 20,
                      fontWeight: FontWeight.w600,
                      color: context.palette.text),
                ),
                if (widget.subtitle != null) ...[
                   SizedBox(height: AppSpacing.xs),
                  Text(
                    widget.subtitle!,
                    style:  TextStyle(
                        fontSize: 13, color: context.palette.textTertiary),
                  ),
                ],
                if (max != null) ...[
                   SizedBox(height: AppSpacing.xs),
                  Text(
                    '已选 ${chosen.length} / $max',
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: chosen.length > max
                          ? context.palette.danger
                          : context.palette.accent,
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
        color: picked ? context.palette.accentSoft : context.palette.surface,
        borderRadius: BorderRadius.circular(AppRadius.card),
        child: InkWell(
          onTap: disabled ? null : onTap,
          borderRadius: BorderRadius.circular(AppRadius.card),
          child: Container(
            padding:  EdgeInsets.all(AppSpacing.md),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(AppRadius.card),
              border: Border.all(
                  color: picked ? context.palette.accent : context.palette.border,
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
                        style:  TextStyle(
                            fontSize: 15,
                            fontWeight: FontWeight.w600,
                            color: context.palette.text),
                      ),
                      // 主标题已经是角色名时（对局内按角色卡标识席位）不再重复写一行
                      // 「角色：X」，也不显示玩家昵称；其余情况照旧显示角色或「角色未公开」。
                      if (player.subtitle != null ||
                          role == null ||
                          role.name != player.name) ...[
                         SizedBox(height: 2),
                        Text(
                          role != null
                              ? '角色：${role.name}'
                              : (player.subtitle ?? '角色未公开'),
                          style:  TextStyle(
                              fontSize: 13, color: context.palette.textTertiary),
                        ),
                      ],
                    ],
                  ),
                ),
                if (player.dead)
                   Tag('已出局',
                      color: context.palette.textSecondary,
                      background: context.palette.surfaceMuted),
                if (picked) ...[
                   SizedBox(width: AppSpacing.sm),
                   Icon(Icons.check_circle,
                      size: 22, color: context.palette.accent),
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
    showPredictiveSheet<ActionDescriptor>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      builder: (context) => SizedBox(
        height: MediaQuery.sizeOf(context).height * .7,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding:  EdgeInsets.fromLTRB(
                  AppSpacing.xl, 0, AppSpacing.xl, AppSpacing.md),
              child: Text(
                title,
                style:  TextStyle(
                    fontSize: 20,
                    fontWeight: FontWeight.w600,
                    color: context.palette.text),
              ),
            ),
            Expanded(
              child: ListView.separated(
                padding: const EdgeInsets.fromLTRB(
                    AppSpacing.lg, 0, AppSpacing.lg, AppSpacing.lg),
                itemCount: actions.length,
                separatorBuilder: (_, __) =>
                     SizedBox(height: AppSpacing.sm),
                itemBuilder: (context, index) {
                  final action = actions[index];
                  final unsupported = action.unsupportedReason;
                  final danger = action.raw['danger'] == true;
                  return Material(
                    color: context.palette.surface,
                    borderRadius: BorderRadius.circular(AppRadius.card),
                    child: InkWell(
                      borderRadius: BorderRadius.circular(AppRadius.card),
                      onTap: () => Navigator.pop(context, action),
                      child: Container(
                        padding:  EdgeInsets.all(AppSpacing.md),
                        decoration: BoxDecoration(
                          borderRadius: BorderRadius.circular(AppRadius.card),
                          border: Border.all(color: context.palette.border),
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
                                              ? context.palette.danger
                                              : context.palette.text,
                                        ),
                                      ),
                                       SizedBox(width: AppSpacing.sm),
                                      Expanded(
                                        child: Text(
                                          action.group,
                                          style:  TextStyle(
                                              fontSize: 12,
                                              color: context.palette.textTertiary),
                                        ),
                                      ),
                                    ],
                                  ),
                                   SizedBox(height: 2),
                                  Text(
                                    unsupported ??
                                        (action.description.isEmpty
                                            ? action.label
                                            : action.description),
                                    maxLines: 2,
                                    overflow: TextOverflow.ellipsis,
                                    style: TextStyle(
                                      fontSize: 13,
                                      color: unsupported != null
                                          ? context.palette.danger
                                          : context.palette.textSecondary,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                            if (unsupported != null)
                               Icon(Icons.block,
                                  size: 20, color: context.palette.danger)
                            else
                               Icon(Icons.chevron_right,
                                  color: context.palette.textTertiary),
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
    showPredictiveSheet<List<String>>(
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
            padding:  EdgeInsets.fromLTRB(
                AppSpacing.xl, 0, AppSpacing.xl, AppSpacing.sm),
            child: Row(
              children: [
                 Expanded(
                  child: Text(
                    '选择本局魔典',
                    style: TextStyle(
                        fontSize: 20,
                        fontWeight: FontWeight.w600,
                        color: context.palette.text),
                  ),
                ),
                Tag(
                  '${chosen.length} / ${widget.requiredCount}',
                  color: complete ? context.palette.success : context.palette.accent,
                  background:
                      complete ? context.palette.successSoft : context.palette.accentSoft,
                ),
              ],
            ),
          ),
           Padding(
            padding: EdgeInsets.fromLTRB(
                AppSpacing.xl, 0, AppSpacing.xl, AppSpacing.md),
            child: Text(
              '必须正好选择 11 名角色，开场后随机排列。',
              style: TextStyle(fontSize: 13, color: context.palette.textTertiary),
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
          color: context.palette.surface,
          borderRadius: BorderRadius.circular(AppRadius.card),
          child: InkWell(
            onTap: disabled ? null : onTap,
            borderRadius: BorderRadius.circular(AppRadius.card),
            child: Container(
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(AppRadius.card),
                border: Border.all(
                    color: picked ? context.palette.accent : context.palette.border,
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
                           Positioned(
                            right: 0,
                            top: 0,
                            child: Icon(Icons.check_circle,
                                size: 20, color: context.palette.accent),
                          ),
                      ],
                    ),
                  ),
                   SizedBox(height: AppSpacing.xs),
                  Text(
                    role.name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: picked ? FontWeight.w600 : FontWeight.w500,
                      color: picked ? context.palette.accent : context.palette.text,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      );
}
