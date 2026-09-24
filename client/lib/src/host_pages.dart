import 'package:flutter/material.dart';

import 'api.dart';
import 'design.dart';
import 'models.dart';
import 'predictive_sheet.dart';
import 'store.dart';

/// 主持等级与授权管理。
///
/// 等级由服务端判定（授权与 QQ 账号绑定），客户端只负责显示与发起请求：
/// 1 级只主持 1 局；2 级有永久组织权；3 级加 1-3 级成就；4 级加 1-4 级成就并能
/// 授权 1-3 级主持；5 级是系统管理员，能发布公告、分发全等级成就、授权 1-5 级。

String hostLevelName(int level) => switch (level) {
      1 => '1 级主持 · 单局',
      2 => '2 级主持 · 组织权',
      3 => '3 级主持 · 成就 1-3',
      4 => '4 级主持 · 成就 1-4 + 授权',
      5 => '5 级主持 · 系统管理员',
      _ => '未授权',
    };

String hostLevelDuty(int level) => switch (level) {
      1 => '可以主持 1 局，那一局结束后授权自动失效。',
      2 => '永久对局组织权。',
      3 => '组织权，另外可以分发稀有度 1-3 的成就。',
      4 => '在上面基础上可以分发 4 级成就，并授权他人成为 1-3 级主持。',
      5 => '最高级别：发布公告、全等级成就，授权或取消 1-5 级主持。',
      _ => '没有主持授权。',
    };

Color hostLevelColor(BuildContext context, int level) => switch (level) {
      5 => context.palette.host,
      4 => context.palette.accent,
      3 => context.palette.info,
      2 => context.palette.success,
      1 => context.palette.warning,
      _ => context.palette.textTertiary,
    };

/// 主持授权管理：4 级看得到，能授到几级由服务端给的 grantable 决定。
class HostAuthorizationPage extends StatefulWidget {
  const HostAuthorizationPage({super.key, required this.store});

  final GameStore store;

  @override
  State<HostAuthorizationPage> createState() => _HostAuthorizationPageState();
}

class _HostAuthorizationPageState extends State<HostAuthorizationPage> {
  List<HostAccount> hosts = const [];
  int grantable = 0;
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
      final result = await api.hosts();
      if (!mounted) return;
      setState(() {
        hosts = result.hosts;
        grantable = result.grantable;
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

  Future<void> pickAccount() async {
    final api = widget.store.api;
    if (api == null || busy || grantable < 1) return;
    final account = await showPredictiveSheet<HostAccount>(
      context: context,
      useSafeArea: true,
      isScrollControlled: true,
      builder: (context) => _AccountPicker(api: api),
    );
    if (account == null || !mounted) return;
    final level = await showDialog<int>(
      context: context,
      builder: (context) => _LevelPicker(account: account, grantable: grantable),
    );
    if (level == null || !mounted) return;
    setState(() => busy = true);
    try {
      await api.authorizeHost(account.accountId, level);
      report('已把「${account.name}」设为 ${hostLevelName(level)}');
      await load();
    } on ApiException catch (failure) {
      report(failure.message);
    } on FormatException catch (failure) {
      report(failure.message);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> revoke(HostAccount account) async {
    final api = widget.store.api;
    if (api == null || busy) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('取消「${account.name}」的主持授权'),
        content: const Text('取消后该账号的登录令牌立即失效，需要重新授权才能再进入主持人端。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('返回'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            style:
                FilledButton.styleFrom(backgroundColor: context.palette.danger),
            child: const Text('取消授权'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() => busy = true);
    try {
      await api.revokeHost(account.accountId);
      report('已取消「${account.name}」的主持授权');
      await load();
    } on ApiException catch (failure) {
      report(failure.message);
    } on FormatException catch (failure) {
      report(failure.message);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  bool canRevoke(HostAccount account) =>
      !account.builtin && account.level >= 1 && account.level <= grantable;

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          title: const Text('主持授权'),
          actions: [
            IconButton(
              tooltip: '刷新',
              onPressed: loading ? null : load,
              icon: const Icon(Icons.refresh),
            ),
          ],
        ),
        floatingActionButton: grantable < 1
            ? null
            : FloatingActionButton.extended(
                onPressed: busy ? null : pickAccount,
                icon: const Icon(Icons.person_add_alt),
                label: Text('授权新主持（1-$grantable 级）'),
              ),
        body: loading
            ? const Center(child: CircularProgressIndicator())
            : RefreshIndicator(
                onRefresh: load,
                child: ListView(
                  padding: const EdgeInsets.fromLTRB(
                    AppSpacing.lg,
                    AppSpacing.md,
                    AppSpacing.lg,
                    AppSpacing.xxl * 2,
                  ),
                  children: [
                    SectionTitle(
                      '主持名单',
                      subtitle: '你是 ${hostLevelName(widget.store.actor?.hostLevel ?? 0)}，'
                          '最多可以授权到 $grantable 级。',
                    ),
                    if (error != null)
                      Text(
                        error!,
                        style: TextStyle(
                            color: context.palette.danger, fontSize: 13),
                      ),
                    for (final account in hosts)
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
                                    Row(
                                      children: [
                                        Flexible(
                                          child: Text(
                                            account.name,
                                            overflow: TextOverflow.ellipsis,
                                            style: TextStyle(
                                              fontSize: 15,
                                              fontWeight: FontWeight.w600,
                                              color: context.palette.text,
                                            ),
                                          ),
                                        ),
                                        const SizedBox(width: AppSpacing.sm),
                                        Tag(
                                          'Lv.${account.level}',
                                          color: hostLevelColor(
                                              context, account.level),
                                          background: hostLevelColor(
                                                  context, account.level)
                                              .withValues(alpha: .16),
                                        ),
                                        if (account.builtin) ...[
                                          const SizedBox(width: AppSpacing.xs),
                                          Tag(
                                            '内置管理员',
                                            color: context.palette.host,
                                            background: context.palette.hostSoft,
                                          ),
                                        ],
                                        if (account.consumed) ...[
                                          const SizedBox(width: AppSpacing.xs),
                                          Tag(
                                            '已用完 1 局',
                                            color: context.palette.warning,
                                            background:
                                                context.palette.warningSoft,
                                          ),
                                        ],
                                      ],
                                    ),
                                    const SizedBox(height: 2),
                                    Text(
                                      'QQ ${account.qqId}',
                                      style: TextStyle(
                                        fontSize: 12,
                                        color: context.palette.textTertiary,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                              IconButton(
                                tooltip: account.builtin
                                    ? '内置管理员的等级来自服务端配置'
                                    : canRevoke(account)
                                        ? '取消授权'
                                        : '超出你能管理的等级',
                                onPressed: canRevoke(account) && !busy
                                    ? () => revoke(account)
                                    : null,
                                icon: Icon(
                                  Icons.person_remove_outlined,
                                  size: 20,
                                  color: canRevoke(account)
                                      ? context.palette.danger
                                      : context.palette.textTertiary,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                  ],
                ),
              ),
      );
}

/// 挑一个账号来授权：按昵称或 QQ 号搜索。
class _AccountPicker extends StatefulWidget {
  const _AccountPicker({required this.api});

  final GameApi api;

  @override
  State<_AccountPicker> createState() => _AccountPickerState();
}

class _AccountPickerState extends State<_AccountPicker> {
  final query = TextEditingController();
  List<HostAccount> accounts = const [];
  String? error;
  bool loading = true;

  @override
  void initState() {
    super.initState();
    search('');
  }

  @override
  void dispose() {
    query.dispose();
    super.dispose();
  }

  Future<void> search(String value) async {
    setState(() => loading = true);
    try {
      final rows = await widget.api.hostAccounts(value);
      if (!mounted) return;
      setState(() {
        accounts = rows;
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

  @override
  Widget build(BuildContext context) => DraggableScrollableSheet(
        expand: false,
        initialChildSize: .75,
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
                      '选择账号',
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
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: AppSpacing.lg),
              child: TextField(
                controller: query,
                decoration: const InputDecoration(
                  hintText: '按昵称或 QQ 号搜索',
                  prefixIcon: Icon(Icons.search, size: 20),
                  isDense: true,
                ),
                onSubmitted: search,
                onChanged: (value) {
                  if (value.trim().isEmpty) search('');
                },
              ),
            ),
            const SizedBox(height: AppSpacing.sm),
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
                    if (accounts.isEmpty && error == null)
                      Text(
                        '没有匹配的账号。对方需要先在 QQ 群里登录过一次。',
                        style: TextStyle(
                            fontSize: 13, color: context.palette.textTertiary),
                      ),
                    for (final account in accounts)
                      ListTile(
                        title: Text(account.name),
                        subtitle: Text('QQ ${account.qqId} · '
                            '${account.builtin ? '内置管理员' : hostLevelName(account.level)}'),
                        trailing: account.builtin
                            ? Tag(
                                'Lv.5',
                                color: context.palette.host,
                                background: context.palette.hostSoft,
                              )
                            : null,
                        onTap: account.builtin
                            ? null
                            : () => Navigator.pop(context, account),
                      ),
                  ],
                ),
              ),
          ],
        ),
      );
}

/// 选等级：只能选到授权人自己可授权的上限。
class _LevelPicker extends StatelessWidget {
  const _LevelPicker({required this.account, required this.grantable});

  final HostAccount account;
  final int grantable;

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: Text('把「${account.name}」设为几级？'),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              for (var level = 1; level <= grantable; level++)
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: Tag(
                    'Lv.$level',
                    color: hostLevelColor(context, level),
                    background: hostLevelColor(context, level)
                        .withValues(alpha: .16),
                  ),
                  title: Text(hostLevelName(level)),
                  subtitle: Text(
                    hostLevelDuty(level),
                    style: TextStyle(
                        fontSize: 12, color: context.palette.textTertiary),
                  ),
                  onTap: () => Navigator.pop(context, level),
                ),
            ],
          ),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('取消'),
          ),
        ],
      );
}
