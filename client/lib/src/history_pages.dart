import 'package:flutter/material.dart';

import 'design.dart';
import 'message_time.dart';
import 'models.dart';
import 'role_visuals.dart';
import 'store.dart';

/// 历史列表的数据来源；默认走 `store.api`，回归检查可以注入固定的历史数据
/// （widget 测试里所有真实 HTTP 都会被测试框架拦掉，页面本身不该为此加分支）。
typedef MatchHistoryLoader = Future<({List<MatchSummary> matches, bool hasMore})>
    Function({String? before, int limit});

/// 单局历史详情的数据来源；默认走 `store.api`。
typedef MatchDetailLoader = Future<MatchDetail> Function(String matchId);

/// 历史对局：已结束（或没结束就被清空）的对局留档。
///
/// 服务端把它存在独立库里（`data/history.sqlite3`），建新局与一键初始化都不会清掉。
/// 归档范围是**公开记录**：胜负与裁定、七个席位的两张角色牌、公屏与全场公告时间线；
/// 私信与只发给个人的情报不入库，页脚也把这件事写清楚。
class MatchHistoryPage extends StatefulWidget {
  const MatchHistoryPage({
    super.key,
    required this.store,
    @visibleForTesting this.loader,
  });

  final GameStore store;

  /// 仅回归检查使用：覆盖默认的数据来源。
  final MatchHistoryLoader? loader;

  @override
  State<MatchHistoryPage> createState() => _MatchHistoryPageState();
}

class _MatchHistoryPageState extends State<MatchHistoryPage> {
  List<MatchSummary> matches = const [];
  bool hasMore = false;
  bool loading = true;
  String? error;

  @override
  void initState() {
    super.initState();
    refresh();
  }

  Future<({List<MatchSummary> matches, bool hasMore})> _page({String? before}) {
    final loader = widget.loader;
    if (loader != null) return loader(before: before, limit: 20);
    return widget.store.api!.history(before: before, limit: 20);
  }

  Future<void> refresh() async {
    if (widget.loader == null && widget.store.api == null) {
      setState(() {
        loading = false;
        error = '尚未连接服务器';
      });
      return;
    }
    try {
      final page = await _page();
      if (!mounted) return;
      setState(() {
        matches = page.matches;
        hasMore = page.hasMore;
        error = null;
        loading = false;
      });
    } on ApiException catch (failure) {
      if (!mounted) return;
      setState(() {
        error = failure.message;
        loading = false;
      });
    }
  }

  Future<void> loadMore() async {
    if (matches.isEmpty || loading) return;
    if (widget.loader == null && widget.store.api == null) return;
    setState(() => loading = true);
    try {
      final page = await _page(before: matches.last.endedAt);
      if (!mounted) return;
      setState(() {
        matches = [...matches, ...page.matches];
        hasMore = page.hasMore;
        error = null;
        loading = false;
      });
    } on ApiException catch (failure) {
      if (!mounted) return;
      setState(() {
        error = failure.message;
        loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('历史对局')),
      body: RefreshIndicator(
        onRefresh: refresh,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(
            AppSpacing.lg,
            AppSpacing.sm,
            AppSpacing.lg,
            AppSpacing.xxl,
          ),
          children: [
            if (matches.isEmpty && !loading)
              EmptyState(
                icon: Icons.history_outlined,
                title: error ?? '还没有历史对局',
                detail: error == null
                    ? '一局结束（或没结束就被清空）后就会在这里留档，跨局保留。'
                    : '下拉可以重新加载。',
              ),
            for (final item in matches)
              Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.md),
                child: _MatchCard(
                  match: item,
                  onTap: () => Navigator.of(context).push(
                    MaterialPageRoute(
                      builder: (_) => MatchDetailPage(
                        store: widget.store,
                        matchId: item.id,
                      ),
                    ),
                  ),
                ),
              ),
            if (hasMore)
              Center(
                child: TextButton(
                  onPressed: loading ? null : loadMore,
                  child: const Text('加载更早的对局'),
                ),
              ),
            if (loading)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: AppSpacing.lg),
                child: Center(child: CircularProgressIndicator()),
              ),
          ],
        ),
      ),
    );
  }
}

/// 结算文案：终止对局不再显示成一个阵营获胜（与服务端下发的标题同源）。
String matchResultTitle(MatchSummary match) {
  if (match.source == 'aborted' && match.winner.isEmpty) return '本局已终止（未宣判）';
  return switch (match.winner) {
    'good' => '好人获胜',
    'witch' => '魔女获胜',
    'aborted' => '本局已终止',
    final other when other.isNotEmpty => other,
    _ => '本局已结束',
  };
}

class _MatchCard extends StatelessWidget {
  const _MatchCard({required this.match, required this.onTap});

  final MatchSummary match;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final names = [
      for (final player in match.players)
        if (player.kind == 'player') player.name,
    ];
    return Card(
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(AppRadius.card),
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      '第 ${match.day} 日 · ${matchResultTitle(match)}',
                      style: TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w600,
                        color: context.palette.text,
                      ),
                    ),
                  ),
                  const Icon(Icons.chevron_right, size: 20),
                ],
              ),
              const SizedBox(height: AppSpacing.xs),
              Text(
                '${match.hostName} · ${formatMessageTime(match.endedAt)}'
                '${match.source == 'aborted' ? ' · 对局未结束就被清空' : ''}',
                style: TextStyle(
                  fontSize: 12,
                  color: context.palette.textTertiary,
                ),
              ),
              if (match.reason.isNotEmpty) ...[
                const SizedBox(height: AppSpacing.sm),
                Text(
                  match.reason,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: 13,
                    height: 1.5,
                    color: context.palette.textSecondary,
                  ),
                ),
              ],
              if (names.isNotEmpty) ...[
                const SizedBox(height: AppSpacing.sm),
                Text(
                  names.join('、'),
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                    fontSize: 12,
                    color: context.palette.textTertiary,
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}

/// 单局详情：结算、七个席位的两张角色牌与公开时间线。
class MatchDetailPage extends StatefulWidget {
  const MatchDetailPage({
    super.key,
    required this.store,
    required this.matchId,
    @visibleForTesting this.loader,
  });

  final GameStore store;
  final String matchId;

  /// 仅回归检查使用：覆盖默认的数据来源。
  final MatchDetailLoader? loader;

  @override
  State<MatchDetailPage> createState() => _MatchDetailPageState();
}

class _MatchDetailPageState extends State<MatchDetailPage> {
  MatchDetail? detail;
  bool loading = true;
  String? error;

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    final loader = widget.loader;
    if (loader == null && widget.store.api == null) {
      setState(() {
        loading = false;
        error = '尚未连接服务器';
      });
      return;
    }
    try {
      final value =
          loader != null ? await loader(widget.matchId) : await widget.store.api!.match(widget.matchId);
      if (!mounted) return;
      setState(() {
        detail = value;
        error = null;
        loading = false;
      });
    } on ApiException catch (failure) {
      if (!mounted) return;
      setState(() {
        error = failure.message;
        loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final value = detail;
    return Scaffold(
      appBar: AppBar(title: const Text('对局记录')),
      body: RefreshIndicator(
        onRefresh: load,
        child: value == null
            ? ListView(
                padding: const EdgeInsets.all(AppSpacing.lg),
                children: [
                  if (loading)
                    const Padding(
                      padding: EdgeInsets.symmetric(vertical: AppSpacing.xxl),
                      child: Center(child: CircularProgressIndicator()),
                    )
                  else
                    EmptyState(
                      icon: Icons.history_toggle_off_outlined,
                      title: error ?? '读取不到这一局',
                      detail: '下拉可以重新加载。',
                    ),
                ],
              )
            : ListView(
                padding: const EdgeInsets.fromLTRB(
                  AppSpacing.lg,
                  AppSpacing.sm,
                  AppSpacing.lg,
                  AppSpacing.xxl,
                ),
                children: [
                  _ResultCard(match: value.match),
                  const SectionTitle(
                    '参与身份',
                    subtitle: '座位、昵称与最终的两张角色牌（上层在前）。',
                  ),
                  for (final player in value.match.players)
                    _PlayerCard(player: player),
                  const SectionTitle(
                    '公开时间线',
                    subtitle: '公屏发言与全场公告；私信与只发给个人的情报不入库。',
                  ),
                  if (value.events.isEmpty)
                    const EmptyState(
                      icon: Icons.timeline_outlined,
                      title: '没有可展示的公开记录',
                    )
                  else
                    for (final event in value.events) _EventRow(event: event),
                ],
              ),
      ),
    );
  }
}

class _ResultCard extends StatelessWidget {
  const _ResultCard({required this.match});

  final MatchSummary match;

  @override
  Widget build(BuildContext context) => Card(
        color: context.palette.hostSoft,
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(Icons.emoji_events_outlined, color: context.palette.host),
                  const SizedBox(width: AppSpacing.md),
                  Expanded(
                    child: Text(
                      matchResultTitle(match),
                      style: TextStyle(
                        fontSize: 17,
                        fontWeight: FontWeight.w600,
                        color: context.palette.text,
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: AppSpacing.sm),
              Text(
                '第 ${match.day} 日 · 主持人：${match.hostName} · '
                '${formatMessageTime(match.endedAt)}',
                style: TextStyle(fontSize: 12, color: context.palette.textTertiary),
              ),
              if (match.reason.isNotEmpty) ...[
                const SizedBox(height: AppSpacing.sm),
                Text(
                  match.reason,
                  style: TextStyle(
                    fontSize: 14,
                    height: 1.5,
                    color: context.palette.text,
                  ),
                ),
              ],
              if (match.source == 'aborted') ...[
                const SizedBox(height: AppSpacing.sm),
                Text(
                  '这一局没有宣判就被清空（一键初始化或开启下一局）。',
                  style: TextStyle(fontSize: 12, color: context.palette.textTertiary),
                ),
              ],
            ],
          ),
        ),
      );
}

class _PlayerCard extends StatelessWidget {
  const _PlayerCard({required this.player});

  final MatchPlayer player;

  @override
  Widget build(BuildContext context) {
    final dropped = !player.active || player.blocked;
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.sm),
      child: Card(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.md),
          child: Row(
            children: [
              Text(
                player.seatId == null ? '观战' : '${player.seatId} 号',
                style: TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w600,
                  color: dropped
                      ? context.palette.textTertiary
                      : context.palette.text,
                ),
              ),
              const SizedBox(width: AppSpacing.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Flexible(
                          child: Text(
                            player.name,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                              fontSize: 14,
                              color: dropped
                                  ? context.palette.textTertiary
                                  : context.palette.text,
                            ),
                          ),
                        ),
                        if (dropped) ...[
                          const SizedBox(width: AppSpacing.sm),
                          Tag(
                            player.blocked ? '已拉黑' : '已移出',
                            color: context.palette.textSecondary,
                            background: context.palette.surfaceMuted,
                          ),
                        ],
                      ],
                    ),
                    const SizedBox(height: AppSpacing.xs),
                    if (player.roleIds.isEmpty)
                      Text(
                        player.kind == 'spectator' ? '观战身份' : '未发牌',
                        style: TextStyle(
                          fontSize: 12,
                          color: context.palette.textTertiary,
                        ),
                      )
                    else
                      Wrap(
                        spacing: AppSpacing.md,
                        runSpacing: AppSpacing.xs,
                        children: [
                          for (final roleId in player.roleIds)
                            Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                RoleAvatar(roleId: roleId, size: 26),
                                const SizedBox(width: AppSpacing.xs),
                                Text(
                                  roleVisual(roleId)?.name ?? roleId,
                                  style: TextStyle(
                                    fontSize: 13,
                                    color: context.palette.textSecondary,
                                  ),
                                ),
                              ],
                            ),
                        ],
                      ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _EventRow extends StatelessWidget {
  const _EventRow({required this.event});

  final MatchEvent event;

  @override
  Widget build(BuildContext context) {
    final time = formatMessageTime(event.createdAt);
    if (event.kind != 'chat') {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: 3),
        child: Center(
          child: Container(
            constraints: const BoxConstraints(maxWidth: 460),
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 5),
            decoration: BoxDecoration(
              color: context.palette.surfaceMuted,
              borderRadius: BorderRadius.circular(AppRadius.chip),
            ),
            child: Text(
              event.text,
              textAlign: TextAlign.center,
              style: TextStyle(
                fontSize: 12.5,
                height: 1.3,
                color: context.palette.textSecondary,
              ),
            ),
          ),
        ),
      );
    }
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          RoleAvatar(roleId: event.avatarRoleId, size: 30),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Flexible(
                      child: Text(
                        event.senderName,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          fontSize: 12,
                          color: context.palette.textTertiary,
                        ),
                      ),
                    ),
                    if (time.isNotEmpty) ...[
                      const SizedBox(width: AppSpacing.sm),
                      Text(
                        time,
                        style: TextStyle(
                          fontSize: 11,
                          color: context.palette.textTertiary,
                        ),
                      ),
                    ],
                  ],
                ),
                const SizedBox(height: 2),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
                  decoration: BoxDecoration(
                    color: context.palette.surface,
                    borderRadius: BorderRadius.circular(AppRadius.card),
                    border: Border.all(color: context.palette.border),
                  ),
                  child: Text(
                    event.text,
                    style: TextStyle(
                      fontSize: 14,
                      height: 1.35,
                      color: context.palette.text,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
