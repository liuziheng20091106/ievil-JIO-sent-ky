import 'package:flutter/material.dart';

import 'achievements.dart';
import 'api.dart';
import 'design.dart';
import 'models.dart';
import 'predictive_sheet.dart';
import 'store.dart';

/// 成就的两个页面：
/// - 玩家的「我的成就」：查看自己获得的成就并挑一个佩戴。
/// - 主持人的「成就管理」：自定义成就定义，按总玩家列表给谁授权、撤销授权。
///
/// 两个页面都只在大厅进入；对局内只显示别人佩戴的成就徽章（见 shell.dart）。

/// 玩家的「我的成就」。
class MyAchievementsPage extends StatefulWidget {
  const MyAchievementsPage({super.key, required this.store});

  final GameStore store;

  @override
  State<MyAchievementsPage> createState() => _MyAchievementsPageState();
}

class _MyAchievementsPageState extends State<MyAchievementsPage> {
  List<AchievementGrant> grants = const [];
  List<AchievementDef> catalog = const [];
  EquippedAchievement? equipped;
  String? error;
  bool loading = true;
  String? busyGrantId;

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    final api = widget.store.api;
    if (api == null) {
      setState(() {
        loading = false;
        error = '尚未连接服务器';
      });
      return;
    }
    setState(() => loading = true);
    try {
      final result = await api.myAchievements();
      // 成就一览要列出全部定义，所以顺带拉一次公开目录（任何登录身份可读）。
      final definitions = await api.achievementCatalog();
      if (!mounted) return;
      setState(() {
        grants = result.achievements;
        equipped = result.equipped;
        catalog = definitions;
        error = null;
        loading = false;
      });
    } on ApiException catch (failure) {
      if (!mounted) return;
      setState(() {
        error = failure.message;
        loading = false;
      });
    } on FormatException catch (failure) {
      if (!mounted) return;
      setState(() {
        error = failure.message;
        loading = false;
      });
    }
  }

  Future<void> equip(String? grantId) async {
    final api = widget.store.api;
    if (api == null) return;
    setState(() => busyGrantId = grantId ?? 'none');
    try {
      final value = await api.equipAchievement(grantId);
      if (!mounted) return;
      setState(() {
        equipped = value;
        busyGrantId = null;
      });
    } on ApiException catch (failure) {
      if (!mounted) return;
      setState(() => busyGrantId = null);
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(failure.message)));
    } on FormatException catch (failure) {
      if (!mounted) return;
      setState(() => busyGrantId = null);
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(failure.message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    final mine = equipped;
    // 一览里每行按成就定义找自己名下的授权：有就是已获得，可佩戴。
    final owned = {for (final grant in grants) grant.achievementId: grant};
    return Scaffold(
      appBar: AppBar(
        title: const Text('我的成就'),
        actions: [
          IconButton(
            tooltip: '刷新',
            onPressed: loading ? null : load,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: load,
        child: loading
            ? const Center(child: CircularProgressIndicator())
            : ListView(
                padding: const EdgeInsets.fromLTRB(
                  AppSpacing.lg,
                  AppSpacing.md,
                  AppSpacing.lg,
                  AppSpacing.xxl,
                ),
                children: [
                  Card(
                    color: mine == null
                        ? null
                        : AchievementRarity.of(mine.rarity)
                            .background
                            .withValues(alpha: .10),
                    child: Padding(
                      padding: const EdgeInsets.all(AppSpacing.lg),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            '佩戴中',
                            style: TextStyle(
                              fontSize: 12,
                              color: context.palette.textTertiary,
                            ),
                          ),
                          const SizedBox(height: AppSpacing.sm),
                          if (mine == null)
                            Text(
                              '还没有佩戴任何成就。获得成就后挑一个佩戴，对局内其他玩家就能在你的发言旁看到它。',
                              style: TextStyle(
                                fontSize: 13,
                                height: 1.5,
                                color: context.palette.textSecondary,
                              ),
                            )
                          else
                            Wrap(
                              spacing: AppSpacing.sm,
                              crossAxisAlignment: WrapCrossAlignment.center,
                              children: [
                                AchievementBadge(
                                  name: mine.name,
                                  rarity: mine.rarity,
                                ),
                                Text(
                                  '稀有度 ${mine.rarity}',
                                  style: TextStyle(
                                    fontSize: 12,
                                    color: context.palette.textTertiary,
                                  ),
                                ),
                                TextButton(
                                  onPressed: busyGrantId == null
                                      ? () => equip(null)
                                      : null,
                                  child: const Text('取消佩戴'),
                                ),
                              ],
                            ),
                        ],
                      ),
                    ),
                  ),
                  const SectionTitle(
                    '获得的成就',
                    subtitle: '成就由主持人授权；这里按稀有度从高到低排列。',
                  ),
                  if (error != null)
                    Padding(
                      padding:
                          const EdgeInsets.symmetric(vertical: AppSpacing.md),
                      child: Text(
                        error!,
                        style: TextStyle(
                            color: context.palette.danger, fontSize: 13),
                      ),
                    ),
                  if (grants.isEmpty && error == null)
                    const Padding(
                      padding: EdgeInsets.symmetric(vertical: AppSpacing.xl),
                      child: EmptyState(
                        icon: Icons.emoji_events_outlined,
                        title: '还没有获得成就',
                        detail: '主持人在「成就管理」里授权后，这里就会出现。',
                      ),
                    ),
                  for (final grant in grants)
                    _AchievementCard(
                      grant: grant,
                      equipped: grant.id == equipped?.id,
                      busy: busyGrantId != null,
                      onEquip: () => equip(grant.id),
                    ),
                  SectionTitle(
                    '成就一览',
                    subtitle: catalog.isEmpty
                        ? '主持人还没有创建成就定义。'
                        : '全部 ${catalog.length} 个成就；你已经获得 ${owned.length} 个，'
                            '淡色的是还没有获得的。',
                  ),
                  if (catalog.isEmpty && error == null)
                    const Padding(
                      padding: EdgeInsets.symmetric(vertical: AppSpacing.xl),
                      child: EmptyState(
                        icon: Icons.emoji_events_outlined,
                        title: '还没有成就定义',
                        detail: '主持人在「成就管理」里新建成就后，这里会列出全部成就。',
                      ),
                    ),
                  for (final definition in catalog)
                    _AchievementCatalogRow(
                      definition: definition,
                      grant: owned[definition.id],
                      equippedGrantId: equipped?.id,
                      busy: busyGrantId != null,
                      onEquip: () => equip(owned[definition.id]!.id),
                    ),
                ],
              ),
      ),
    );
  }
}

/// 玩家视角的一条成就。
class _AchievementCard extends StatelessWidget {
  const _AchievementCard({
    required this.grant,
    required this.equipped,
    required this.busy,
    required this.onEquip,
  });

  final AchievementGrant grant;
  final bool equipped;
  final bool busy;
  final VoidCallback onEquip;

  @override
  Widget build(BuildContext context) {
    final rarity = AchievementRarity.of(grant.rarity);
    return Card(
      color: rarity.background.withValues(alpha: equipped ? .16 : .07),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppRadius.card),
        side: BorderSide(
          color: equipped ? rarity.background : context.palette.border,
          width: equipped ? 1.4 : 1,
        ),
      ),
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.lg),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Flexible(
                  child: AchievementBadge(
                    name: grant.name,
                    rarity: grant.rarity,
                  ),
                ),
                const SizedBox(width: AppSpacing.sm),
                Text(
                  '稀有度 ${grant.rarity}',
                  style: TextStyle(
                      fontSize: 11, color: context.palette.textTertiary),
                ),
                const Spacer(),
                if (equipped)
                  Tag(
                    '已佩戴',
                    color: rarity.background,
                    background: rarity.background.withValues(alpha: .16),
                  )
                else
                  TextButton(
                    onPressed: busy ? null : onEquip,
                    child: const Text('佩戴'),
                  ),
              ],
            ),
            const SizedBox(height: AppSpacing.xs),
            Text(
              grant.detail,
              style: TextStyle(
                fontSize: 13,
                height: 1.5,
                color: context.palette.text,
              ),
            ),
            const SizedBox(height: AppSpacing.xs),
            Text(
              '获得于 ${achievementStamp(grant.grantedAt, withTime: true)}',
              style:
                  TextStyle(fontSize: 11, color: context.palette.textTertiary),
            ),
          ],
        ),
      ),
    );
  }
}

/// 「成就一览」里的一行：全部成就都列出来，没获得的用淡色徽章标出来。
class _AchievementCatalogRow extends StatelessWidget {
  const _AchievementCatalogRow({
    required this.definition,
    required this.grant,
    required this.equippedGrantId,
    required this.busy,
    required this.onEquip,
  });

  final AchievementDef definition;

  /// 自己名下的授权记录；为空表示还没获得这个成就。
  final AchievementGrant? grant;

  /// 当前佩戴的授权 id：只在 [grant] 存在且对得上时才算这一行佩戴中。
  final String? equippedGrantId;
  final bool busy;
  final VoidCallback onEquip;

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final rarity = AchievementRarity.of(definition.rarity);
    final owned = grant != null;
    final equipped = grant?.id == equippedGrantId && owned;
    return Card(
      color: owned
          ? rarity.background.withValues(alpha: equipped ? .16 : .07)
          : palette.surfaceMuted,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppRadius.card),
        side: BorderSide(
          color: equipped ? rarity.background : palette.border,
          width: equipped ? 1.4 : 1,
        ),
      ),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(
          AppSpacing.lg,
          AppSpacing.md,
          AppSpacing.md,
          AppSpacing.md,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Flexible(
                  child: Opacity(
                    // 未获得的成就不给彩色徽章，用淡色表示「还差这一个」。
                    opacity: owned ? 1 : .45,
                    child: AchievementBadge(
                      name: definition.name,
                      rarity: definition.rarity,
                    ),
                  ),
                ),
                const SizedBox(width: AppSpacing.sm),
                Text(
                  '稀有度 ${definition.rarity}',
                  style: TextStyle(fontSize: 11, color: palette.textTertiary),
                ),
                const Spacer(),
                if (equipped)
                  Tag(
                    '已佩戴',
                    color: rarity.background,
                    background: rarity.background.withValues(alpha: .16),
                  )
                else if (owned)
                  TextButton(
                    onPressed: busy ? null : onEquip,
                    child: const Text('佩戴'),
                  )
                else
                  Tag(
                    '未获得',
                    color: palette.textTertiary,
                    background: palette.surfaceStrong,
                  ),
              ],
            ),
            // 已获得的详情在上面那条里（带着获得时间），这里只补未获得的内容。
            if (!owned) ...[
              const SizedBox(height: AppSpacing.xs),
              Text(
                definition.detail,
                style: TextStyle(
                  fontSize: 12,
                  height: 1.4,
                  color: palette.textTertiary,
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// 主持人的「成就管理」：成就定义 + 玩家授权两页。
class AchievementAdminPage extends StatefulWidget {
  const AchievementAdminPage({super.key, required this.store});

  final GameStore store;

  @override
  State<AchievementAdminPage> createState() => _AchievementAdminPageState();
}

class _AchievementAdminPageState extends State<AchievementAdminPage>
    with SingleTickerProviderStateMixin {
  late final TabController tabs = TabController(length: 2, vsync: this);
  final definitionsKey = GlobalKey<_DefinitionsTabState>();
  final playersKey = GlobalKey<_PlayersTabState>();

  @override
  void initState() {
    super.initState();
    tabs.addListener(() {
      if (tabs.indexIsChanging) return;
      // 授权会改变「已授予人数」，切页时重新拉一次，两页始终一致。
      if (tabs.index == 0) definitionsKey.currentState?.load();
      if (tabs.index == 1) playersKey.currentState?.load();
    });
  }

  @override
  void dispose() {
    tabs.dispose();
    super.dispose();
  }

  void reloadCurrent() {
    if (tabs.index == 0) {
      definitionsKey.currentState?.load();
    } else {
      playersKey.currentState?.load();
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          title: const Text('成就管理'),
          actions: [
            IconButton(
              tooltip: '刷新',
              onPressed: reloadCurrent,
              icon: const Icon(Icons.refresh),
            ),
          ],
          bottom: TabBar(
            controller: tabs,
            indicatorColor: context.palette.accent,
            labelColor: context.palette.accent,
            unselectedLabelColor: context.palette.textTertiary,
            tabs: const [Tab(text: '成就定义'), Tab(text: '玩家授权')],
          ),
        ),
        body: TabBarView(
          controller: tabs,
          children: [
            _DefinitionsTab(key: definitionsKey, store: widget.store),
            _PlayersTab(key: playersKey, store: widget.store),
          ],
        ),
      );
}

/// 成就定义页：新建、编辑、删除。
class _DefinitionsTab extends StatefulWidget {
  const _DefinitionsTab({super.key, required this.store});

  final GameStore store;

  @override
  State<_DefinitionsTab> createState() => _DefinitionsTabState();
}

class _DefinitionsTabState extends State<_DefinitionsTab> {
  List<AchievementDef> definitions = const [];
  String? error;
  bool loading = true;

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    final api = widget.store.api;
    if (api == null) {
      setState(() {
        loading = false;
        error = '尚未连接服务器';
      });
      return;
    }
    try {
      final value = await api.achievementCatalog();
      if (!mounted) return;
      setState(() {
        definitions = value;
        error = null;
        loading = false;
      });
    } on ApiException catch (failure) {
      if (!mounted) return;
      setState(() {
        error = failure.message;
        loading = false;
      });
    } on FormatException catch (failure) {
      if (!mounted) return;
      setState(() {
        error = failure.message;
        loading = false;
      });
    }
  }

  Future<void> edit({AchievementDef? existing}) async {
    final api = widget.store.api;
    if (api == null) return;
    final saved = await showDialog<bool>(
      context: context,
      builder: (context) => _DefinitionDialog(api: api, existing: existing),
    );
    if (saved == true) await load();
  }

  Future<void> remove(AchievementDef definition) async {
    final api = widget.store.api;
    if (api == null) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        icon: Icon(Icons.delete_outline, color: context.palette.danger),
        title: Text('删除「${definition.name}」'),
        content: Text(
          definition.grantedCount == 0
              ? '这个成就还没有授权给任何人，删除后不可恢复。'
              : '已经有 ${definition.grantedCount} 名玩家获得这个成就，删除会一并撤销他们的记录（佩戴中的也会清空）。',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            style:
                FilledButton.styleFrom(backgroundColor: context.palette.danger),
            child: const Text('删除'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    try {
      await api.deleteAchievement(definition.id);
      if (!mounted) return;
      await load();
    } on ApiException catch (failure) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(failure.message)));
    } on FormatException catch (failure) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(failure.message)));
    }
  }

  @override
  Widget build(BuildContext context) {
    if (loading) return const Center(child: CircularProgressIndicator());
    return ListView(
      padding: const EdgeInsets.fromLTRB(
        AppSpacing.lg,
        AppSpacing.md,
        AppSpacing.lg,
        AppSpacing.xxl,
      ),
      children: [
        FilledButton.icon(
          onPressed: () => edit(),
          icon: const Icon(Icons.add, size: 18),
          label: const Text('新建成就'),
        ),
        const SectionTitle(
          '成就定义',
          subtitle: '名称与内容都可以自定义；稀有度 1-10，数字越大越稀有。',
        ),
        if (error != null)
          Text(
            error!,
            style: TextStyle(color: context.palette.danger, fontSize: 13),
          ),
        if (definitions.isEmpty && error == null)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: AppSpacing.xl),
            child: EmptyState(
              icon: Icons.emoji_events_outlined,
              title: '还没有成就定义',
              detail: '先新建一个成就，再到「玩家授权」里发给玩家。',
            ),
          ),
        for (final definition in definitions)
          Card(
            child: Padding(
              padding: const EdgeInsets.all(AppSpacing.lg),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Flexible(
                        child: AchievementBadge(
                          name: definition.name,
                          rarity: definition.rarity,
                        ),
                      ),
                      const SizedBox(width: AppSpacing.sm),
                      Text(
                        '稀有度 ${definition.rarity}',
                        style: TextStyle(
                            fontSize: 11, color: context.palette.textTertiary),
                      ),
                      const Spacer(),
                      IconButton(
                        tooltip: '编辑',
                        onPressed: () => edit(existing: definition),
                        icon: const Icon(Icons.edit_outlined, size: 20),
                      ),
                      IconButton(
                        tooltip: '删除',
                        onPressed: () => remove(definition),
                        icon: Icon(Icons.delete_outline,
                            size: 20, color: context.palette.danger),
                      ),
                    ],
                  ),
                  Text(
                    definition.detail,
                    style: TextStyle(
                      fontSize: 13,
                      height: 1.5,
                      color: context.palette.text,
                    ),
                  ),
                  const SizedBox(height: AppSpacing.xs),
                  Text(
                    '已授予 ${definition.grantedCount} 人',
                    style: TextStyle(
                        fontSize: 11, color: context.palette.textTertiary),
                  ),
                ],
              ),
            ),
          ),
      ],
    );
  }
}

/// 新建 / 编辑成就定义。
class _DefinitionDialog extends StatefulWidget {
  const _DefinitionDialog({required this.api, this.existing});

  final GameApi api;
  final AchievementDef? existing;

  @override
  State<_DefinitionDialog> createState() => _DefinitionDialogState();
}

class _DefinitionDialogState extends State<_DefinitionDialog> {
  late final TextEditingController name =
      TextEditingController(text: widget.existing?.name ?? '');
  late final TextEditingController detail =
      TextEditingController(text: widget.existing?.detail ?? '');
  late int rarity = widget.existing?.rarity ?? 1;
  String? error;
  bool saving = false;

  @override
  void dispose() {
    name.dispose();
    detail.dispose();
    super.dispose();
  }

  bool get valid =>
      name.text.trim().isNotEmpty && detail.text.trim().isNotEmpty;

  Future<void> save() async {
    if (!valid || saving) return;
    setState(() {
      saving = true;
      error = null;
    });
    try {
      final existing = widget.existing;
      if (existing == null) {
        await widget.api.createAchievement(
          name: name.text.trim(),
          detail: detail.text.trim(),
          rarity: rarity,
        );
      } else {
        await widget.api.updateAchievement(
          existing.id,
          name: name.text.trim(),
          detail: detail.text.trim(),
          rarity: rarity,
        );
      }
      if (mounted) Navigator.pop(context, true);
    } on ApiException catch (failure) {
      if (mounted) {
        setState(() {
          error = failure.message;
          saving = false;
        });
      }
    } on FormatException catch (failure) {
      if (mounted) {
        setState(() {
          error = failure.message;
          saving = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: Text(widget.existing == null ? '新建成就' : '编辑成就'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              TextField(
                controller: name,
                maxLength: 24,
                decoration: const InputDecoration(
                  labelText: '名称',
                  counterText: '',
                  hintText: '神秘黑幕女',
                ),
                onChanged: (_) => setState(() {}),
              ),
              const SizedBox(height: AppSpacing.md),
              TextField(
                controller: detail,
                maxLength: 200,
                minLines: 2,
                maxLines: 4,
                decoration: const InputDecoration(
                  labelText: '内容',
                  hintText: '在一局内控制傀儡未被识破',
                ),
                onChanged: (_) => setState(() {}),
              ),
              const SizedBox(height: AppSpacing.md),
              const SizedBox(
                width: double.infinity,
                child: Text('稀有度', style: TextStyle(fontSize: 13)),
              ),
              const SizedBox(height: AppSpacing.sm),
              AchievementRarityPicker(
                rarity: rarity,
                onChanged: (value) => setState(() => rarity = value),
              ),
              const SizedBox(height: AppSpacing.md),
              Row(
                children: [
                  Text(
                    '预览：',
                    style: TextStyle(
                        fontSize: 12, color: context.palette.textTertiary),
                  ),
                  const SizedBox(width: AppSpacing.sm),
                  AchievementBadge(
                    name: name.text.trim().isEmpty ? '成就名称' : name.text.trim(),
                    rarity: rarity,
                  ),
                ],
              ),
              if (error != null) ...[
                const SizedBox(height: AppSpacing.md),
                Text(
                  error!,
                  style: TextStyle(color: context.palette.danger, fontSize: 12),
                ),
              ],
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: saving ? null : () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: valid && !saving ? save : null,
            child: Text(saving ? '保存中…' : '保存'),
          ),
        ],
      );
}

/// 玩家授权页：总玩家列表（最近的参赛顺序在前）+ 每个玩家的成就管理。
class _PlayersTab extends StatefulWidget {
  const _PlayersTab({super.key, required this.store});

  final GameStore store;

  @override
  State<_PlayersTab> createState() => _PlayersTabState();
}

class _PlayersTabState extends State<_PlayersTab> {
  List<AchievementPlayer> players = const [];
  String? error;
  bool loading = true;

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    final api = widget.store.api;
    if (api == null) {
      setState(() {
        loading = false;
        error = '尚未连接服务器';
      });
      return;
    }
    try {
      final value = await api.achievementPlayers();
      if (!mounted) return;
      setState(() {
        players = value;
        error = null;
        loading = false;
      });
    } on ApiException catch (failure) {
      if (!mounted) return;
      setState(() {
        error = failure.message;
        loading = false;
      });
    } on FormatException catch (failure) {
      if (!mounted) return;
      setState(() {
        error = failure.message;
        loading = false;
      });
    }
  }

  Future<void> open(AchievementPlayer player) async {
    await showPredictiveSheet<void>(
      context: context,
      useSafeArea: true,
      isScrollControlled: true,
      builder: (context) => _PlayerSheet(
        store: widget.store,
        accountId: player.accountId,
        name: player.name,
        onChanged: load,
      ),
    );
    if (mounted) await load();
  }

  @override
  Widget build(BuildContext context) {
    if (loading) return const Center(child: CircularProgressIndicator());
    return RefreshIndicator(
      onRefresh: load,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(
          AppSpacing.lg,
          AppSpacing.md,
          AppSpacing.lg,
          AppSpacing.xxl,
        ),
        children: [
          const SectionTitle(
            '总玩家列表',
            subtitle: '按最近一次参赛排序；点一个玩家授权或撤销成就。',
          ),
          if (error != null)
            Text(
              error!,
              style: TextStyle(color: context.palette.danger, fontSize: 13),
            ),
          if (players.isEmpty && error == null)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: AppSpacing.xl),
              child: EmptyState(
                icon: Icons.group_outlined,
                title: '还没有玩家记录',
                detail: '玩家以玩家身份参局后，这里会按最近参赛顺序列出。',
              ),
            ),
          for (final player in players)
            Card(
              child: ListTile(
                contentPadding: const EdgeInsets.symmetric(
                  horizontal: AppSpacing.lg,
                  vertical: AppSpacing.xs,
                ),
                title: Row(
                  children: [
                    Flexible(
                      child: Text(
                        player.name,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w600,
                          color: context.palette.text,
                        ),
                      ),
                    ),
                    if (player.equipped != null) ...[
                      const SizedBox(width: AppSpacing.sm),
                      AchievementBadge(
                        name: player.equipped!.name,
                        rarity: player.equipped!.rarity,
                        dense: true,
                      ),
                    ],
                  ],
                ),
                subtitle: Padding(
                  padding: const EdgeInsets.only(top: AppSpacing.xs),
                  child: Text(
                    '成就 ${player.achievementCount} 个'
                    '${player.lastPlayedAt == null ? ' · 还没有参赛记录' : ' · 最近参赛 ${achievementStamp(player.lastPlayedAt!)}'}',
                    style: TextStyle(
                        fontSize: 12, color: context.palette.textTertiary),
                  ),
                ),
                trailing: const Icon(Icons.chevron_right),
                onTap: () => open(player),
              ),
            ),
        ],
      ),
    );
  }
}

/// 单个玩家的成就管理：授予、撤销。
class _PlayerSheet extends StatefulWidget {
  const _PlayerSheet({
    required this.store,
    required this.accountId,
    required this.name,
    this.onChanged,
  });

  final GameStore store;
  final String accountId;
  final String name;
  final VoidCallback? onChanged;

  @override
  State<_PlayerSheet> createState() => _PlayerSheetState();
}

class _PlayerSheetState extends State<_PlayerSheet> {
  List<AchievementDef> catalog = const [];
  List<AchievementGrant> grants = const [];
  String? error;
  bool loading = true;
  bool busy = false;

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    final api = widget.store.api;
    if (api == null) {
      setState(() {
        loading = false;
        error = '尚未连接服务器';
      });
      return;
    }
    try {
      final definitions = await api.achievementCatalog();
      final players = await api.achievementPlayers();
      if (!mounted) return;
      final player = players
          .where((item) => item.accountId == widget.accountId)
          .toList(growable: false);
      setState(() {
        catalog = definitions;
        grants = player.isEmpty ? const [] : player.first.achievements;
        error = null;
        loading = false;
      });
    } on ApiException catch (failure) {
      if (!mounted) return;
      setState(() {
        error = failure.message;
        loading = false;
      });
    } on FormatException catch (failure) {
      if (!mounted) return;
      setState(() {
        error = failure.message;
        loading = false;
      });
    }
  }

  void report(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> grant(AchievementDef definition) async {
    final api = widget.store.api;
    if (api == null || busy) return;
    setState(() => busy = true);
    try {
      await api.grantAchievement(widget.accountId, definition.id);
      widget.onChanged?.call();
      await load();
      report('已授权「${definition.name}」');
    } on ApiException catch (failure) {
      report(failure.message);
    } on FormatException catch (failure) {
      report(failure.message);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> revoke(AchievementGrant grant) async {
    final api = widget.store.api;
    if (api == null || busy) return;
    setState(() => busy = true);
    try {
      await api.revokeAchievement(grant.id);
      widget.onChanged?.call();
      await load();
      report('已撤销「${grant.name}」');
    } on ApiException catch (failure) {
      report(failure.message);
    } on FormatException catch (failure) {
      report(failure.message);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> pickAndGrant() async {
    final owned = grants.map((grant) => grant.achievementId).toSet();
    final picked = await showPredictiveSheet<AchievementDef>(
      context: context,
      useSafeArea: true,
      isScrollControlled: true,
      builder: (context) => _DefinitionPicker(
        definitions: catalog,
        owned: owned,
      ),
    );
    if (picked != null) await grant(picked);
  }

  @override
  Widget build(BuildContext context) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: .7,
        maxChildSize: .95,
        minChildSize: .4,
        builder: (context, scroll) => Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(
                AppSpacing.xl,
                AppSpacing.lg,
                AppSpacing.md,
                AppSpacing.sm,
              ),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      '${widget.name} 的成就',
                      style: TextStyle(
                        fontSize: 17,
                        fontWeight: FontWeight.w600,
                        color: context.palette.text,
                      ),
                    ),
                  ),
                  IconButton(
                    tooltip: '关闭',
                    onPressed: () => Navigator.pop(context),
                    icon: const Icon(Icons.close, size: 20),
                  ),
                ],
              ),
            ),
            if (loading)
              const Padding(
                padding: EdgeInsets.all(AppSpacing.xl),
                child: CircularProgressIndicator(),
              )
            else
              Expanded(
                child: ListView(
                  controller: scroll,
                  padding: const EdgeInsets.fromLTRB(
                    AppSpacing.lg,
                    0,
                    AppSpacing.lg,
                    AppSpacing.xl,
                  ),
                  children: [
                    if (error != null)
                      Text(
                        error!,
                        style: TextStyle(
                            color: context.palette.danger, fontSize: 13),
                      ),
                    FilledButton.icon(
                      onPressed: busy || catalog.isEmpty ? null : pickAndGrant,
                      icon: const Icon(Icons.add, size: 18),
                      label: const Text('授予成就'),
                    ),
                    const SectionTitle(
                      '已获得',
                      subtitle: '撤销后该玩家不再拥有这个成就，佩戴中的会一并清空。',
                    ),
                    if (grants.isEmpty)
                      Text(
                        '还没有获得任何成就。',
                        style: TextStyle(
                            fontSize: 13, color: context.palette.textTertiary),
                      ),
                    for (final grant in grants)
                      Card(
                        child: Padding(
                          padding: const EdgeInsets.fromLTRB(
                            AppSpacing.lg,
                            AppSpacing.md,
                            AppSpacing.sm,
                            AppSpacing.md,
                          ),
                          child: Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Expanded(
                                child: Column(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Wrap(
                                      spacing: AppSpacing.sm,
                                      crossAxisAlignment:
                                          WrapCrossAlignment.center,
                                      children: [
                                        AchievementBadge(
                                          name: grant.name,
                                          rarity: grant.rarity,
                                        ),
                                        Text(
                                          '稀有度 ${grant.rarity}',
                                          style: TextStyle(
                                            fontSize: 11,
                                            color: context.palette.textTertiary,
                                          ),
                                        ),
                                      ],
                                    ),
                                    const SizedBox(height: AppSpacing.xs),
                                    Text(
                                      grant.detail,
                                      style: TextStyle(
                                        fontSize: 12,
                                        height: 1.4,
                                        color: context.palette.textSecondary,
                                      ),
                                    ),
                                    const SizedBox(height: 2),
                                    Text(
                                      '获得于 ${achievementStamp(grant.grantedAt, withTime: true)}',
                                      style: TextStyle(
                                        fontSize: 11,
                                        color: context.palette.textTertiary,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                              IconButton(
                                tooltip: '撤销',
                                onPressed: busy ? null : () => revoke(grant),
                                icon: Icon(
                                  Icons.remove_circle_outline,
                                  size: 20,
                                  color: context.palette.danger,
                                ),
                              ),
                            ],
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

/// 授予成就时的定义选择：已获得的置灰，避免重复授权。
class _DefinitionPicker extends StatelessWidget {
  const _DefinitionPicker({required this.definitions, required this.owned});

  final List<AchievementDef> definitions;
  final Set<String> owned;

  @override
  Widget build(BuildContext context) => SafeArea(
        top: false,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(
                AppSpacing.xl,
                AppSpacing.lg,
                AppSpacing.xl,
                AppSpacing.sm,
              ),
              child: Text(
                '授予哪个成就',
                style: TextStyle(
                  fontSize: 17,
                  fontWeight: FontWeight.w600,
                  color: context.palette.text,
                ),
              ),
            ),
            if (definitions.isEmpty)
              const Padding(
                padding: EdgeInsets.all(AppSpacing.lg),
                child: Text('还没有成就定义，先在「成就定义」里新建。'),
              )
            else
              ConstrainedBox(
                constraints: const BoxConstraints(maxHeight: 380),
                child: ListView(
                  shrinkWrap: true,
                  padding: const EdgeInsets.only(bottom: AppSpacing.lg),
                  children: [
                    for (final definition in definitions)
                      ListTile(
                        enabled: !owned.contains(definition.id),
                        title: AchievementBadge(
                          name: definition.name,
                          rarity: definition.rarity,
                        ),
                        subtitle: Padding(
                          padding: const EdgeInsets.only(top: 4),
                          child: Text(
                            owned.contains(definition.id)
                                ? '已获得 · ${definition.detail}'
                                : definition.detail,
                            style: TextStyle(
                                fontSize: 12,
                                color: context.palette.textTertiary),
                          ),
                        ),
                        onTap: () => Navigator.pop(context, definition),
                      ),
                  ],
                ),
              ),
          ],
        ),
      );
}
