import 'package:flutter/material.dart';

import 'achievements.dart';
import 'action_sheet.dart';
import 'design.dart';
import 'models.dart';
import 'player_marks.dart';
import 'predictive_sheet.dart';
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
    // 对局内的主持人一律显示「主持人(昵称)」；服务端没给名字时退回「主持人」。
    return ParticipantRef(
      participantId: 'host',
      name: store.view?.hostName ?? '主持人',
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
    // 它与 cards.first 的 role_id 不同）；avatar_role_id 未给出时回退到上层牌。
    final avatar = seat['avatar_role_id']?.toString();
    if (avatar != null) return avatar;
    final cards = seat['cards'];
    if (cards is List && cards.isNotEmpty) {
      return cards.first['role_id']?.toString();
    }
    return null;
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

/// 角色登场介绍：下层登场、复活、换牌时自动弹一次，
/// 内容就是该角色的公开技能说明，和点头像看到的角色详情同源。
/// [opening] 为真时是开局那一次：宿主在候场转入进行中时锁定上层牌，
/// 换的只是标题与收尾文案，技能说明仍与角色详情同源。
/// [headerLabel]/[footerText] 可覆盖默认的栏头与收尾文案；传值时视为一次
/// 主动查看（例如「我的」页点双牌打开教程卡片），不再用登场介绍的口吻。
/// 发牌不在此列——那时玩家正在「我的双牌」里自己选上下牌，不需要弹窗遮挡。
Future<void> showRoleIntro(
  BuildContext context,
  GameStore store,
  String roleId, {
  bool opening = false,
  String? headerLabel,
  String? footerText,
}) =>
    showPredictiveSheet<void>(
      context: context,
      useSafeArea: true,
      isScrollControlled: true,
      builder: (context) => _RoleIntroSheet(
        store: store,
        roleId: roleId,
        opening: opening,
        headerLabel: headerLabel,
        footerText: footerText,
      ),
    );

class _RoleIntroSheet extends StatelessWidget {
  const _RoleIntroSheet({
    required this.store,
    required this.roleId,
    this.opening = false,
    this.headerLabel,
    this.footerText,
  });

  final GameStore store;
  final String roleId;

  /// 开局的上层牌教程：说明这一张就是开局起使用的牌。
  final bool opening;

  /// 主动查看时的栏头与收尾文案；为空时按登场介绍口吻显示。
  final String? headerLabel;
  final String? footerText;

  @override
  Widget build(BuildContext context) {
    final role = store.roleInfo(roleId);
    final visual = roleVisual(roleId);
    return SafeArea(
      top: false,
      child: SingleChildScrollView(
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
                RoleAvatar(roleId: roleId, size: 52),
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        headerLabel ??
                            (opening ? '开局 · 上层牌' : '新角色登场'),
                        style: TextStyle(
                          fontSize: 12,
                          color: context.palette.accent,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        role?.name ?? visual?.name ?? roleId,
                        style: TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.w600,
                          color: context.palette.text,
                        ),
                      ),
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
            if (role == null) ...[
              Text(
                '该角色的技能说明尚未从服务器读取到，可在「状态」页重新查看。',
                style: TextStyle(
                  fontSize: 13,
                  color: context.palette.textTertiary,
                ),
              ),
            ] else ...[
              _SkillBlock(title: '好人方技能', body: role.normal),
              if (role.witch.isNotEmpty) ...[
                const SizedBox(height: AppSpacing.md),
                _SkillBlock(title: '魔女化后', body: role.witch, danger: true),
              ],
            ],
            const SizedBox(height: AppSpacing.md),
            Text(
              footerText ??
                  (opening
                      ? '开局起你使用上层牌；上层牌出局后，你才开始使用下层牌。私密信息只在本机显示。'
                      : '此刻起你使用这张牌的技能；私密信息只在本机显示。'),
              style: TextStyle(fontSize: 12, color: context.palette.textTertiary),
            ),
          ],
        ),
      ),
    );
  }
}

/// 角色技能详情：公开的角色说明 + 该席位当前公开状态。
Future<void> showRoleDetail(
  BuildContext context,
  GameStore store,
  ParticipantRef ref,
) =>
    showPredictiveSheet<void>(
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
                        style:  TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.w600,
                          color: context.palette.text,
                        ),
                      ),
                       SizedBox(height: 2),
                      Text(
                        role == null ? '公开角色未显示' : '公开身份：${role.name}',
                        style:  TextStyle(
                          fontSize: 13,
                          color: context.palette.textTertiary,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
             SizedBox(height: AppSpacing.md),
            Wrap(
              spacing: AppSpacing.sm,
              runSpacing: AppSpacing.sm,
              children: [
                Tag(
                  ref.dead ? '已出局' : '存活',
                  color: ref.dead ? context.palette.textSecondary : context.palette.success,
                  background:
                      ref.dead ? context.palette.surfaceMuted : context.palette.successSoft,
                ),
                if (ref.online)
                   Tag('在线',
                      icon: Icons.wifi_tethering, color: context.palette.info),
                if (ref.muted)
                   Tag(
                    '已禁言',
                    color: context.palette.warning,
                    background: context.palette.warningSoft,
                  ),
                if (ref.isHost)
                   Tag(
                    '主持人',
                    color: context.palette.host,
                    background: context.palette.hostSoft,
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
               SizedBox(height: AppSpacing.lg),
              Text(
                '该角色的技能说明尚未从服务器读取到（${visual.name}）。',
                style:  TextStyle(
                  fontSize: 13,
                  color: context.palette.textTertiary,
                ),
              ),
            ],
             SizedBox(height: AppSpacing.md),
             Text(
              '技能说明是公开规则；此人的下层牌、剩余次数等私密信息不会在这里显示。',
              style: TextStyle(fontSize: 12, color: context.palette.textTertiary),
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
        padding:  EdgeInsets.all(AppSpacing.md),
        decoration: BoxDecoration(
          color: danger ? context.palette.dangerSoft : context.palette.surfaceMuted,
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
                  color: danger ? context.palette.danger : context.palette.accent,
                ),
                 SizedBox(width: AppSpacing.xs),
                Text(
                  title,
                  style: TextStyle(
                    fontSize: 12,
                    fontWeight: FontWeight.w600,
                    color: danger ? context.palette.danger : context.palette.accent,
                  ),
                ),
              ],
            ),
             SizedBox(height: AppSpacing.xs),
            Text(
              body,
              style:  TextStyle(
                fontSize: 14,
                height: 1.6,
                color: context.palette.text,
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
    // 观战者已收拢进观战频道：观战者点头像不再提供私信入口。
    if (!ref.isHost && store.actor?.isSpectator != true)
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

  // 该参与者的账号 id：用于读取公开的成就摘要（总成就数 + 最稀有的 5 个）。
  final accountId = store.accountFor(ref.participantId);

  await showPredictiveSheet<void>(
    context: context,
    useSafeArea: true,
    isScrollControlled: true,
    builder: (sheetContext) => SafeArea(
      top: false,
      child: SingleChildScrollView(
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
                  RoleAvatar(
                    roleId: ref.roleId,
                    host: ref.isHost,
                    size: 44,
                    dead: ref.dead,
                  ),
                  const SizedBox(width: AppSpacing.md),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          ref.seatId != null
                              ? '${ref.seatId} 号 · ${ref.name}'
                              : ref.name,
                          style:  TextStyle(
                            fontSize: 17,
                            fontWeight: FontWeight.w600,
                            color: context.palette.text,
                          ),
                        ),
                        Text(
                          ref.muted
                              ? '已禁言'
                              : ref.isHost
                                  ? '主持人'
                                  : '选择要执行的操作',
                          style:  TextStyle(
                            fontSize: 12,
                            color: context.palette.textTertiary,
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
                      entry.danger ? context.palette.danger : context.palette.textSecondary,
                ),
                title: Text(
                  entry.label,
                  style: TextStyle(
                    fontSize: 15,
                    color: entry.danger ? context.palette.danger : context.palette.text,
                  ),
                ),
                onTap: () {
                  Navigator.pop(sheetContext);
                  entry.onTap();
                },
              ),
            // 成就摘要在菜单下方：总量与最稀有的几个都直接摊开，不用再点一次。
            // 主持人不是参与身份，但主持账号与它的玩家身份共用成就，所以一并显示。
            if (accountId != null) ...[
              Divider(height: AppSpacing.xl, color: context.palette.border),
              Padding(
                padding: const EdgeInsets.fromLTRB(
                  AppSpacing.xl,
                  0,
                  AppSpacing.xl,
                  AppSpacing.lg,
                ),
                child: AchievementSummaryBlock(store: store, accountId: accountId),
              ),
            ],
            const SizedBox(height: AppSpacing.lg),
          ],
        ),
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

/// 长按头像的快速标记：魔女 / 好人 / 疑似魔女 / 疑似好人 / 清除标记。
/// 标记只写进本机内存，服务端不知道，别的玩家也看不到。
Future<void> showMarkMenu(
  BuildContext context,
  GameStore store,
  ParticipantRef ref,
) async {
  if (ref.isHost || ref.seatId == null) {
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('只有入席玩家可以标记')),
    );
    return;
  }
  final choice = await showPredictiveSheet<_MarkChoice>(
    context: context,
    useSafeArea: true,
    isScrollControlled: true,
    builder: (sheetContext) => _MarkSheet(
      ref: ref,
      current: store.markFor(ref.participantId),
    ),
  );
  if (choice == null) return;
  store.setMark(ref.participantId, choice.mark);
  if (!context.mounted) return;
  final who = '${ref.seatId} 号${ref.name.isEmpty ? '' : ' ${ref.name}'}';
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(
      content: Text(
        choice.mark == null
            ? '已清除 $who 的标记'
            : '已标记 $who：${choice.mark!.label}（仅本机可见）',
      ),
    ),
  );
}

/// 面板选择结果：null 表示关掉面板没选，`_MarkChoice(null)` 表示清除标记。
class _MarkChoice {
  const _MarkChoice(this.mark);
  final PlayerMark? mark;
}

class _MarkSheet extends StatelessWidget {
  const _MarkSheet({required this.ref, required this.current});

  final ParticipantRef ref;
  final PlayerMark? current;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    return SafeArea(
      top: false,
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(
                AppSpacing.xl,
                0,
                AppSpacing.xl,
                AppSpacing.sm,
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
                          '${ref.seatId} 号 · ${ref.name}',
                          style: TextStyle(
                            fontSize: 17,
                            fontWeight: FontWeight.w600,
                            color: palette.text,
                          ),
                        ),
                        Text(
                          '快速标记 · 只保存在本机',
                          style: TextStyle(
                            fontSize: 12,
                            color: palette.textTertiary,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            for (final mark in PlayerMark.values)
              ListTile(
                leading: PlayerMarkDot(
                  color: mark.colorOf(palette),
                  size: 22,
                  icon: mark.icon,
                ),
                title: Text(
                  mark.label,
                  style: TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w600,
                    color: mark.colorOf(palette),
                  ),
                ),
                subtitle: Text(
                  mark.description,
                  style: TextStyle(fontSize: 12, color: palette.textTertiary),
                ),
                trailing: current == mark
                    ? Icon(Icons.check_rounded,
                        size: 20, color: mark.colorOf(palette))
                    : null,
                onTap: () => Navigator.pop(context, _MarkChoice(mark)),
              ),
            Divider(height: AppSpacing.lg, color: palette.border),
            ListTile(
              enabled: current != null,
              leading: PlayerMarkDot(
                color: clearedMarkColorOf(palette),
                size: 22,
                icon: Icons.layers_clear_outlined,
              ),
              title: Text(
                '清除标记',
                style: TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w600,
                  color: current == null
                      ? palette.textTertiary
                      : clearedMarkColorOf(palette),
                ),
              ),
              subtitle: Text(
                current == null ? '当前没有标记' : '恢复默认名字颜色',
                style: TextStyle(fontSize: 12, color: palette.textTertiary),
              ),
              onTap: current == null
                  ? null
                  : () => Navigator.pop(context, const _MarkChoice(null)),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(
                AppSpacing.xl,
                0,
                AppSpacing.xl,
                AppSpacing.lg,
              ),
              child: Text(
                '标记只是你的判断：不会发送给服务器，别人看不到，也不影响任何规则判定。',
                style: TextStyle(
                  fontSize: 12,
                  height: 1.5,
                  color: palette.textTertiary,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// 「如何标记他人」教程：固定在首个非平安夜结束后由外壳展示一次。
Future<void> showMarksTutorial(BuildContext context) =>
    showPredictiveSheet<void>(
      context: context,
      useSafeArea: true,
      isScrollControlled: true,
      builder: (sheetContext) => const _MarksTutorialSheet(),
    );

class _MarksTutorialSheet extends StatelessWidget {
  const _MarksTutorialSheet();

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    return SafeArea(
      top: false,
      child: SingleChildScrollView(
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
                Icon(Icons.touch_app_outlined, size: 20, color: palette.accent),
                const SizedBox(width: AppSpacing.sm),
                Text(
                  '如何标记他人',
                  style: TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.w600,
                    color: palette.text,
                  ),
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.sm),
            Text(
              '长按任意玩家的头像（牌桌上的席位，或聊天里发言者的头像），'
              '在面板里选一种标记。',
              style: TextStyle(
                fontSize: 14,
                height: 1.6,
                color: palette.text,
              ),
            ),
            const SizedBox(height: AppSpacing.md),
            for (final mark in PlayerMark.values)
              _MarkLegendRow(
                color: mark.colorOf(palette),
                icon: mark.icon,
                label: mark.label,
                detail: mark.description,
              ),
            _MarkLegendRow(
              color: clearedMarkColorOf(palette),
              icon: Icons.layers_clear_outlined,
              label: '清除标记',
              detail: '恢复默认文字颜色',
            ),
            const SizedBox(height: AppSpacing.md),
            Text(
              '标记之后，对局中这个玩家的名字就会显示成对应的颜色；'
              '再长按一次可以改标记或清除。',
              style: TextStyle(
                fontSize: 13,
                height: 1.6,
                color: palette.textSecondary,
              ),
            ),
            const SizedBox(height: AppSpacing.sm),
            Text(
              '标记只保存在这台设备的内存里：不会发给服务器，别人看不到，退出应用后清空。',
              style: TextStyle(
                fontSize: 12,
                height: 1.5,
                color: palette.textTertiary,
              ),
            ),
            const SizedBox(height: AppSpacing.lg),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                onPressed: () => Navigator.pop(context),
                child: const Text('知道了'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _MarkLegendRow extends StatelessWidget {
  const _MarkLegendRow({
    required this.color,
    required this.icon,
    required this.label,
    required this.detail,
  });

  final Color color;
  final IconData icon;
  final String label;
  final String detail;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 5),
        child: Row(
          children: [
            PlayerMarkDot(color: color, size: 20, icon: icon),
            const SizedBox(width: AppSpacing.md),
            Text(
              label,
              style: TextStyle(
                fontSize: 14,
                fontWeight: FontWeight.w600,
                color: color,
              ),
            ),
            const SizedBox(width: AppSpacing.sm),
            Expanded(
              child: Text(
                detail,
                style: TextStyle(
                  fontSize: 12,
                  color: context.palette.textTertiary,
                ),
              ),
            ),
          ],
        ),
      );
}

/// 技能播报卡片点开的「技能详细」：技能名、服务端下发的技能介绍，
/// 以及与该角色详情同源的公开技能说明。
///
/// 介绍与目标都来自服务端裁剪后的消息载荷：看不到的目标根本不会出现在载荷里，
/// 客户端只负责把拿到的部分展示出来，不做任何可见性判断。
Future<void> showSkillDetail(
  BuildContext context,
  GameStore store,
  Map<String, dynamic> payload,
) =>
    showPredictiveSheet<void>(
      context: context,
      useSafeArea: true,
      isScrollControlled: true,
      builder: (context) => _SkillDetailSheet(store: store, payload: payload),
    );

class _SkillDetailSheet extends StatelessWidget {
  const _SkillDetailSheet({required this.store, required this.payload});

  final GameStore store;
  final Map<String, dynamic> payload;

  @override
  Widget build(BuildContext context) {
    final roleId = payload['role_id']?.toString();
    final role = store.roleInfo(roleId);
    final visual = roleVisual(roleId);
    final skill = payload['ability_name']?.toString() ?? '';
    final intro = payload['intro']?.toString() ?? '';
    final seatId = payload['seat_id']?.toString() ?? '';
    final actorName = payload['actor_name']?.toString() ?? '';
    final target = payload['target'];
    final targetSeat = target is Map ? target['seat_id']?.toString() : null;
    final targetName = target is Map ? target['name']?.toString() ?? '' : '';
    final challengeable = payload['challengeable'] != false;
    return SafeArea(
      top: false,
      child: SingleChildScrollView(
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
                RoleAvatar(roleId: roleId, size: 52),
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '技能详情',
                        style: TextStyle(
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                          color: context.palette.accent,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        skill,
                        style: TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.w600,
                          color: context.palette.text,
                        ),
                      ),
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
            const SizedBox(height: AppSpacing.sm),
            Wrap(
              spacing: AppSpacing.sm,
              runSpacing: AppSpacing.sm,
              children: [
                if (visual != null)
                  Tag(
                    visual.name,
                    color: context.palette.textSecondary,
                    background: context.palette.surfaceMuted,
                  ),
                Tag(
                  challengeable ? '可质疑' : '不可质疑',
                  color: challengeable
                      ? context.palette.warning
                      : context.palette.textSecondary,
                  background: challengeable
                      ? context.palette.warningSoft
                      : context.palette.surfaceMuted,
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.lg),
            if (intro.isNotEmpty) _SkillBlock(title: '技能说明', body: intro),
            const SizedBox(height: AppSpacing.md),
            Text(
              '使用者：${seatId.isEmpty ? '—' : '$seatId号'}'
              '${actorName.isEmpty ? '' : ' $actorName'}'
              '${targetSeat == null ? '' : ' · 目标：$targetSeat号${targetName.isEmpty ? '' : ' $targetName'}'}',
              style: TextStyle(
                fontSize: 13,
                height: 1.5,
                color: context.palette.textSecondary,
              ),
            ),
            if (role != null) ...[
              const SizedBox(height: AppSpacing.md),
              _SkillBlock(title: '好人方技能', body: role.normal),
              if (role.witch.isNotEmpty) ...[
                const SizedBox(height: AppSpacing.md),
                _SkillBlock(title: '魔女化后', body: role.witch, danger: true),
              ],
            ],
            const SizedBox(height: AppSpacing.md),
            Text(
              '技能说明是公开规则；声明本身不代表身份——伪装声明的播报与真声明完全一致。'
              '剩余次数、下层牌与私密目标不会在这里显示。',
              style: TextStyle(fontSize: 12, color: context.palette.textTertiary),
            ),
          ],
        ),
      ),
    );
  }
}
