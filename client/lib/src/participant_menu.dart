import 'package:flutter/material.dart';

import 'action_sheet.dart';
import 'design.dart';
import 'models.dart';
import 'role_visuals.dart';
import 'store.dart';

/// 点击头像后的快捷操作，以及角色技能与公开状态查看。

/// 某条消息发送者对应的参与者与席位信息。
class ParticipantRef {
  const ParticipantRef({
    required this.participantId,
    required this.name,
    this.seatId,
    this.roleId,
    this.dead = false,
    this.muted = false,
    this.online = false,
  });

  final String participantId;
  final String name;
  final String? seatId;
  final String? roleId;
  final bool dead;
  final bool muted;
  final bool online;

  bool get isHost => participantId == 'host';
}

/// 从当前视图解析出发送者的参与者信息；解析不到时返回 null。
ParticipantRef? participantRefFor(GameStore store, String? senderId) {
  if (senderId == null || senderId.isEmpty) {
    return null;
  }
  if (senderId == 'host') {
    return const ParticipantRef(
      participantId: 'host',
      name: '主持人',
      online: true,
    );
  }
  final view = store.view;
  if (view == null) {
    return null;
  }
  // 主持人视图能直接拿到参与者名单，信息最全。
  final participants = view.host['participants'];
  if (participants is List) {
    for (final raw in participants) {
      if (raw is! Map) continue;
      if (raw['id']?.toString() != senderId) continue;
      final seatId = raw['seat_id']?.toString();
      return ParticipantRef(
        participantId: senderId,
        name: raw['name']?.toString() ?? '',
        seatId: seatId,
        roleId: _roleIdOf(store, seatId),
        dead: _deadOf(store, seatId),
        muted: raw['muted'] == true,
        online: raw['online'] == true,
      );
    }
  }
  // 玩家与观战者用席位里的 participant_id 关联。
  for (final seat in view.seats) {
    if (seat['participant_id']?.toString() != senderId) continue;
    return ParticipantRef(
      participantId: senderId,
      name: seat['name']?.toString() ?? '',
      seatId: seat['id']?.toString(),
      roleId: _roleIdOf(store, seat['id']?.toString()),
      dead: seat['alive'] == false,
      online: seat['online'] == true,
    );
  }
  return null;
}

String? _roleIdOf(GameStore store, String? seatId) {
  if (seatId == null) return null;
  for (final seat in store.view?.seats ?? const <Map<String, dynamic>>[]) {
    if (seat['id']?.toString() != seatId) continue;
    // 头像必须与服务端的 avatar_role_id 一致（上层牌已死/穗乃香示人时
    // 它与 cards.first 的 role_id 不同）；玩家视角没有 cards 也靠它。
    return seat['avatar_role_id']?.toString();
  }
  return null;
}

bool _deadOf(GameStore store, String? seatId) {
  if (seatId == null) return false;
  for (final seat in store.view?.seats ?? const <Map<String, dynamic>>[]) {
    if (seat['id']?.toString() == seatId) return seat['alive'] == false;
  }
  return false;
}

/// 角色技能详情：公开的角色说明 + 该席位当前公开状态。
Future<void> showRoleDetail(
  BuildContext context,
  GameStore store,
  ParticipantRef ref,
) =>
    showModalBottomSheet<void>(
      context: context,
      useSafeArea: true,
      builder: (context) => _RoleDetailSheet(store: store, ref: ref),
    );

class _RoleDetailSheet extends StatelessWidget {
  const _RoleDetailSheet({required this.store, required this.ref});

  final GameStore store;
  final ParticipantRef ref;

  @override
  Widget build(BuildContext context) {
    final role = store.roleInfo(ref.roleId);
    final visual = roleVisual(ref.roleId);
    return SafeArea(
      top: false,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(
          AppSpacing.xl,
          0,
          AppSpacing.xl,
          AppSpacing.xl,
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                RoleAvatar(roleId: ref.roleId, size: 52, dead: ref.dead),
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        ref.seatId != null
                            ? '${ref.seatId} 号 · ${ref.name}'
                            : ref.name,
                        style: const TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.w600,
                          color: AppColors.text,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        role == null ? '公开角色未显示' : '公开身份：${role.name}',
                        style: const TextStyle(
                          fontSize: 13,
                          color: AppColors.textTertiary,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.md),
            Wrap(
              spacing: AppSpacing.sm,
              runSpacing: AppSpacing.sm,
              children: [
                Tag(
                  ref.dead ? '已出局' : '存活',
                  color: ref.dead ? AppColors.textSecondary : AppColors.success,
                  background:
                      ref.dead ? AppColors.surfaceMuted : AppColors.successSoft,
                ),
                if (ref.online)
                  const Tag('在线',
                      icon: Icons.wifi_tethering, color: AppColors.info),
                if (ref.muted)
                  const Tag(
                    '已禁言',
                    color: AppColors.warning,
                    background: AppColors.warningSoft,
                  ),
                if (ref.isHost)
                  const Tag(
                    '主持人',
                    color: AppColors.host,
                    background: AppColors.hostSoft,
                  ),
              ],
            ),
            if (role != null) ...[
              const SizedBox(height: AppSpacing.lg),
              _SkillBlock(title: '好人方技能', body: role.normal),
              if (role.witch.isNotEmpty) ...[
                const SizedBox(height: AppSpacing.md),
                _SkillBlock(
                  title: '魔女化后',
                  body: role.witch,
                  danger: true,
                ),
              ],
            ] else if (visual != null) ...[
              const SizedBox(height: AppSpacing.lg),
              Text(
                '该角色的技能说明尚未从服务器读取到（${visual.name}）。',
                style: const TextStyle(
                  fontSize: 13,
                  color: AppColors.textTertiary,
                ),
              ),
            ],
            const SizedBox(height: AppSpacing.md),
            const Text(
              '技能说明是公开规则；此人的下层牌、剩余次数等私密信息不会在这里显示。',
              style: TextStyle(fontSize: 12, color: AppColors.textTertiary),
            ),
          ],
        ),
      ),
    );
  }
}

class _SkillBlock extends StatelessWidget {
  const _SkillBlock({
    required this.title,
    required this.body,
    this.danger = false,
  });

  final String title;
  final String body;
  final bool danger;

  @override
  Widget build(BuildContext context) => Container(
        width: double.infinity,
        padding: const EdgeInsets.all(AppSpacing.md),
        decoration: BoxDecoration(
          color: danger ? AppColors.dangerSoft : AppColors.surfaceMuted,
          borderRadius: BorderRadius.circular(AppRadius.field),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  danger
                      ? Icons.local_fire_department_outlined
                      : Icons.auto_awesome_outlined,
                  size: 15,
                  color: danger ? AppColors.danger : AppColors.accent,
                ),
                const SizedBox(width: AppSpacing.xs),
                Text(
                  title,
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: danger ? AppColors.danger : AppColors.accent,
                  ),
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.xs),
            Text(
              body,
              style: const TextStyle(
                fontSize: 14,
                height: 1.6,
                color: AppColors.text,
              ),
            ),
          ],
        ),
      );
}

/// 点击头像的快捷菜单：玩家可快捷私信/看技能，主持人另有本席管理动作。
Future<void> showAvatarMenu(
  BuildContext context,
  GameStore store,
  ParticipantRef ref,
) async {
  final isHost = store.actor?.isHost == true;
  final entries = <_MenuEntry>[
    _MenuEntry(
      icon: Icons.badge_outlined,
      label: '查看角色技能与状态',
      onTap: () => showRoleDetail(context, store, ref),
    ),
    if (!ref.isHost)
      _MenuEntry(
        icon: Icons.forum_outlined,
        label: '发起私信',
        onTap: () => _quickPrivate(context, store, ref),
      ),
    if (isHost && !ref.isHost) ...[
      _MenuEntry(
        icon: ref.muted ? Icons.volume_up_outlined : Icons.volume_off_outlined,
        label: ref.muted ? '解除该玩家禁言' : '一键禁言该玩家',
        onTap: () => _toggleMute(context, store, ref),
      ),
      if (ref.seatId != null)
        _MenuEntry(
          icon: Icons.warning_amber_rounded,
          label: '警告该席位',
          onTap: () => _warnSeat(context, store, ref),
        ),
      _MenuEntry(
        icon: Icons.person_remove_outlined,
        label: '移出本局 / 拉黑',
        danger: true,
        onTap: () => _runHostAction(
          context,
          store,
          'room.kick',
          {'participant_id': ref.participantId},
        ),
      ),
    ],
  ];

  await showModalBottomSheet<void>(
    context: context,
    useSafeArea: true,
    builder: (sheetContext) => SafeArea(
      top: false,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(
              AppSpacing.xl,
              0,
              AppSpacing.xl,
              AppSpacing.md,
            ),
            child: Row(
              children: [
                RoleAvatar(roleId: ref.roleId, size: 44, dead: ref.dead),
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        ref.seatId != null
                            ? '${ref.seatId} 号 · ${ref.name}'
                            : ref.name,
                        style: const TextStyle(
                          fontSize: 17,
                          fontWeight: FontWeight.w600,
                          color: AppColors.text,
                        ),
                      ),
                      Text(
                        ref.muted
                            ? '已禁言'
                            : ref.isHost
                                ? '主持人'
                                : '选择要执行的操作',
                        style: const TextStyle(
                          fontSize: 12,
                          color: AppColors.textTertiary,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          for (final entry in entries)
            ListTile(
              leading: Icon(
                entry.icon,
                color:
                    entry.danger ? AppColors.danger : AppColors.textSecondary,
              ),
              title: Text(
                entry.label,
                style: TextStyle(
                  fontSize: 15,
                  color: entry.danger ? AppColors.danger : AppColors.text,
                ),
              ),
              onTap: () {
                Navigator.pop(sheetContext);
                entry.onTap();
              },
            ),
          const SizedBox(height: AppSpacing.lg),
        ],
      ),
    ),
  );
}

class _MenuEntry {
  const _MenuEntry({
    required this.icon,
    required this.label,
    required this.onTap,
    this.danger = false,
  });

  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final bool danger;
}

/// 找到服务端给出的 channel.create 描述，用它打开创建私信表单并带上目标。
Future<void> _quickPrivate(
  BuildContext context,
  GameStore store,
  ParticipantRef ref,
) async {
  final create = (store.view?.allActions ?? const <ActionDescriptor>[])
      .where((action) => action.id == 'channel.create')
      .toList();
  if (create.isEmpty) {
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('当前不能创建私信（可能你已在其他私信中，或对局已结束）')),
      );
    }
    return;
  }
  await showActionForm(
    context,
    store,
    create.first,
    initial: {
      'participant_ids': [ref.participantId],
      'name': '与${ref.name}的私信',
    },
  );
}

Future<void> _toggleMute(
  BuildContext context,
  GameStore store,
  ParticipantRef ref,
) =>
    _runHostAction(
      context,
      store,
      'room.mute',
      {'participant_id': ref.participantId, 'muted': !ref.muted},
    );

Future<void> _warnSeat(
  BuildContext context,
  GameStore store,
  ParticipantRef ref,
) =>
    _runHostAction(context, store, 'host.warn', {'seat_id': ref.seatId});

/// 用服务端给出的动作描述执行快捷操作：先按 payload 找到对应描述，
/// 再把 payload 作为初始值交给统一的行动表单（仍然只有一次确认提交）。
Future<void> _runHostAction(
  BuildContext context,
  GameStore store,
  String actionId,
  Map<String, dynamic> payload,
) async {
  final candidates = (store.view?.allActions ?? const <ActionDescriptor>[])
      .where((action) => action.id == actionId)
      .toList();
  if (candidates.isEmpty) {
    if (context.mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('该操作当前不可用，请刷新状态后重试')),
      );
    }
    return;
  }
  // 同一动作可能按选项拆成多个描述（例如警告按席位、禁言按参与者）。
  // 先找 payload 完全匹配的；没有就退到第一个，并把 payload 作为表单初值，
  // 由表单里的选项校验兜底（选项已失效时会提示重新选择）。
  final matched = candidates.firstWhere(
    (action) => payload.entries.every(
      (entry) => action.payload[entry.key] == entry.value,
    ),
    orElse: () => candidates.first,
  );
  await showActionForm(context, store, matched, initial: payload);
}
