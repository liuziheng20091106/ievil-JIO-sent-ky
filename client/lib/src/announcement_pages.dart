import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';

import 'achievements.dart' show achievementStamp;
import 'api.dart';
import 'design.dart';
import 'models.dart';
import 'store.dart';

/// 公告：大厅卡片、列表、正文与管理员发布。
///
/// 正文是 markdown，统一用 MarkdownBody 渲染；已读状态按每条公告的 sha256 记在本机，
/// 公告内容被改过（哈希变了）就重新算未读。大厅轮询带着公告与版本号，见 store。

/// 大厅里的公告卡片：最新的几条 + 未读数 + 查看全部。
class AnnouncementSection extends StatelessWidget {
  const AnnouncementSection({super.key, required this.store});

  final GameStore store;

  @override
  Widget build(BuildContext context) {
    if (store.announcements.isEmpty) return const SizedBox.shrink();
    final unread = store.unreadAnnouncements.length;
    final latest = store.announcements.take(3).toList(growable: false);
    return Card(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(
          AppSpacing.lg,
          AppSpacing.md,
          AppSpacing.lg,
          AppSpacing.md,
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.campaign_outlined,
                    size: 18, color: context.palette.accent),
                const SizedBox(width: AppSpacing.sm),
                Text(
                  '公告',
                  style: TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w600,
                    color: context.palette.text,
                  ),
                ),
                if (unread > 0) ...[
                  const SizedBox(width: AppSpacing.sm),
                  Tag(
                    '$unread 条未读',
                    color: context.palette.danger,
                    background: context.palette.dangerSoft,
                  ),
                ],
                const Spacer(),
                TextButton(
                  onPressed: () => openAnnouncements(context, store),
                  child: Text('查看全部 ${store.announcements.length} 条'),
                ),
              ],
            ),
            for (final item in latest)
              _AnnouncementTile(
                store: store,
                announcement: item,
                dense: true,
              ),
          ],
        ),
      ),
    );
  }
}

/// 公告列表：全部公告 + 一键全部已读。
Future<void> openAnnouncements(BuildContext context, GameStore store) =>
    Navigator.of(context).push(
      MaterialPageRoute(builder: (_) => AnnouncementsPage(store: store)),
    );

class AnnouncementsPage extends StatefulWidget {
  const AnnouncementsPage({super.key, required this.store});

  final GameStore store;

  @override
  State<AnnouncementsPage> createState() => _AnnouncementsPageState();
}

class _AnnouncementsPageState extends State<AnnouncementsPage> {
  @override
  void initState() {
    super.initState();
    // 进来先拉一次：立刻看到刚发布的公告，不必等大厅那 5 秒轮询。
    widget.store.loadAnnouncements();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          title: const Text('公告'),
          actions: [
            TextButton(
              onPressed: widget.store.announcements.isEmpty
                  ? null
                  : widget.store.markAllAnnouncementsRead,
              child: const Text('全部已读'),
            ),
          ],
        ),
        body: RefreshIndicator(
          onRefresh: widget.store.loadAnnouncements,
          child: ListView(
            padding: const EdgeInsets.fromLTRB(
              AppSpacing.lg,
              AppSpacing.md,
              AppSpacing.lg,
              AppSpacing.xxl,
            ),
            children: [
              if (widget.store.announcements.isEmpty)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: AppSpacing.xl),
                  child: EmptyState(
                    icon: Icons.campaign_outlined,
                    title: '暂时没有公告',
                    detail: '管理员发布公告后，这里和大厅都会显示。',
                  ),
                ),
              for (final item in widget.store.announcements)
                _AnnouncementTile(store: widget.store, announcement: item),
            ],
          ),
        ),
      );
}

/// 一条公告：未读点 + 标题 + 时间。
class _AnnouncementTile extends StatelessWidget {
  const _AnnouncementTile({
    required this.store,
    required this.announcement,
    this.dense = false,
  });

  final GameStore store;
  final Announcement announcement;
  final bool dense;

  @override
  Widget build(BuildContext context) {
    final unread = !store.readAnnouncementHashes.contains(announcement.hash);
    final edited = announcement.updatedAt.isNotEmpty &&
        announcement.updatedAt != announcement.createdAt;
    return ListTile(
      contentPadding: EdgeInsets.symmetric(
        horizontal: dense ? 0 : AppSpacing.sm,
        vertical: 0,
      ),
      leading: Container(
        width: 8,
        height: 8,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: unread ? context.palette.danger : Colors.transparent,
        ),
      ),
      title: Text(
        announcement.title,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: TextStyle(
          fontSize: dense ? 14 : 15,
          fontWeight: unread ? FontWeight.w700 : FontWeight.w500,
          color: context.palette.text,
        ),
      ),
      subtitle: Text(
        '${announcement.authorName} · '
        '${achievementStamp(announcement.createdAt, withTime: true)}'
        '${edited ? '（已修改）' : ''}',
        style: TextStyle(fontSize: 11, color: context.palette.textTertiary),
      ),
      trailing: const Icon(Icons.chevron_right, size: 18),
      onTap: () => Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => AnnouncementPage(
            store: store,
            announcement: announcement,
          ),
        ),
      ),
    );
  }
}

/// 公告正文：markdown 渲染，打开即记为已读。
class AnnouncementPage extends StatefulWidget {
  const AnnouncementPage({
    super.key,
    required this.store,
    required this.announcement,
  });

  final GameStore store;
  final Announcement announcement;

  @override
  State<AnnouncementPage> createState() => _AnnouncementPageState();
}

class _AnnouncementPageState extends State<AnnouncementPage> {
  @override
  void initState() {
    super.initState();
    // 打开就算已读：哈希写进本地偏好，公告改过内容会重新变成未读。
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) widget.store.markAnnouncementRead(widget.announcement);
    });
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(title: const Text('公告')),
        body: ListView(
          padding: const EdgeInsets.fromLTRB(
            AppSpacing.lg,
            AppSpacing.lg,
            AppSpacing.lg,
            AppSpacing.xxl,
          ),
          children: [
            Text(
              widget.announcement.title,
              style: TextStyle(
                fontSize: 20,
                fontWeight: FontWeight.w700,
                color: context.palette.text,
              ),
            ),
            const SizedBox(height: AppSpacing.xs),
            Text(
              '${widget.announcement.authorName} · '
              '${achievementStamp(widget.announcement.createdAt, withTime: true)}',
              style: TextStyle(
                  fontSize: 12, color: context.palette.textTertiary),
            ),
            const SizedBox(height: AppSpacing.md),
            const Divider(height: 1),
            const SizedBox(height: AppSpacing.md),
            MarkdownBody(
              data: widget.announcement.body,
              selectable: true,
              styleSheet: markdownStyleSheet(context),
            ),
          ],
        ),
      );
}

/// 公告的 markdown 样式：跟随应用主题的语义色板。
MarkdownStyleSheet markdownStyleSheet(BuildContext context) {
  final palette = context.palette;
  return MarkdownStyleSheet(
    p: TextStyle(fontSize: 14, height: 1.7, color: palette.text),
    h1: TextStyle(
        fontSize: 20, fontWeight: FontWeight.w700, color: palette.text),
    h2: TextStyle(
        fontSize: 18, fontWeight: FontWeight.w700, color: palette.text),
    h3: TextStyle(
        fontSize: 16, fontWeight: FontWeight.w600, color: palette.text),
    h4: TextStyle(
        fontSize: 15, fontWeight: FontWeight.w600, color: palette.text),
    h5: TextStyle(
        fontSize: 14, fontWeight: FontWeight.w600, color: palette.textSecondary),
    h6: TextStyle(
        fontSize: 14, fontWeight: FontWeight.w600, color: palette.textTertiary),
    strong: TextStyle(fontWeight: FontWeight.w700, color: palette.text),
    em: TextStyle(fontStyle: FontStyle.italic, color: palette.text),
    a: TextStyle(color: palette.accent, decoration: TextDecoration.underline),
    code: TextStyle(
      fontSize: 13,
      fontFamily: 'monospace',
      color: palette.text,
      backgroundColor: palette.surfaceMuted,
    ),
    codeblockDecoration: BoxDecoration(
      color: palette.surfaceMuted,
      borderRadius: BorderRadius.circular(AppRadius.field),
    ),
    codeblockPadding: const EdgeInsets.all(AppSpacing.md),
    blockquote: TextStyle(fontSize: 14, height: 1.6, color: palette.textSecondary),
    blockquotePadding: const EdgeInsets.all(AppSpacing.md),
    blockquoteDecoration: BoxDecoration(
      color: palette.surfaceMuted,
      border: Border(left: BorderSide(color: palette.accent, width: 3)),
    ),
    listBullet: TextStyle(fontSize: 14, color: palette.textSecondary),
    horizontalRuleDecoration: BoxDecoration(
      border: Border(top: BorderSide(color: palette.border)),
    ),
    tableHead: TextStyle(
        fontSize: 13, fontWeight: FontWeight.w700, color: palette.text),
    tableBody: TextStyle(fontSize: 13, color: palette.text),
    tableBorder: TableBorder.all(color: palette.border, width: 1),
    tableCellsPadding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.sm, vertical: 6),
  );
}

/// 公告管理（5 级/系统管理员）：发布、编辑、删除。
class AnnouncementAdminPage extends StatefulWidget {
  const AnnouncementAdminPage({super.key, required this.store});

  final GameStore store;

  @override
  State<AnnouncementAdminPage> createState() => _AnnouncementAdminPageState();
}

class _AnnouncementAdminPageState extends State<AnnouncementAdminPage> {
  String? error;
  bool loading = true;
  bool busy = false;

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    setState(() => loading = true);
    await widget.store.loadAnnouncements();
    if (!mounted) return;
    setState(() {
      loading = false;
      error = widget.store.api == null ? '尚未连接服务器' : null;
    });
  }

  void report(String message) {
    if (!mounted) return;
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> edit({Announcement? existing}) async {
    final api = widget.store.api;
    if (api == null || busy) return;
    final saved = await showDialog<bool>(
      context: context,
      builder: (context) => _AnnouncementDialog(api: api, existing: existing),
    );
    if (saved == true) await load();
  }

  Future<void> remove(Announcement item) async {
    final api = widget.store.api;
    if (api == null || busy) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('删除公告「${item.title}」'),
        content: const Text('删除后所有端都不再显示这条公告，且不可恢复。'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('返回'),
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
    setState(() => busy = true);
    try {
      await api.deleteAnnouncement(item.id);
      await load();
    } on ApiException catch (failure) {
      report(failure.message);
    } on FormatException catch (failure) {
      report(failure.message);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          title: const Text('公告管理'),
          actions: [
            IconButton(
              tooltip: '刷新',
              onPressed: loading ? null : load,
              icon: const Icon(Icons.refresh),
            ),
          ],
        ),
        floatingActionButton: FloatingActionButton.extended(
          onPressed: busy ? null : () => edit(),
          icon: const Icon(Icons.add),
          label: const Text('发布公告'),
        ),
        body: loading
            ? const Center(child: CircularProgressIndicator())
            : ListView(
                padding: const EdgeInsets.fromLTRB(
                  AppSpacing.lg,
                  AppSpacing.md,
                  AppSpacing.lg,
                  AppSpacing.xxl * 2,
                ),
                children: [
                  const SectionTitle(
                    '已发布的公告',
                    subtitle: '正文用 markdown 写；发布后大厅轮询会带着它推给所有端。',
                  ),
                  if (error != null)
                    Text(
                      error!,
                      style: TextStyle(
                          color: context.palette.danger, fontSize: 13),
                    ),
                  if (widget.store.announcements.isEmpty && error == null)
                    const Padding(
                      padding: EdgeInsets.symmetric(vertical: AppSpacing.xl),
                      child: EmptyState(
                        icon: Icons.campaign_outlined,
                        title: '还没有公告',
                        detail: '点右下角发布第一条公告。',
                      ),
                    ),
                  for (final item in widget.store.announcements)
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
                                  Text(
                                    item.title,
                                    style: TextStyle(
                                      fontSize: 15,
                                      fontWeight: FontWeight.w600,
                                      color: context.palette.text,
                                    ),
                                  ),
                                  const SizedBox(height: 2),
                                  Text(
                                    '${item.authorName} · '
                                    '${achievementStamp(item.createdAt, withTime: true)}',
                                    style: TextStyle(
                                      fontSize: 11,
                                      color: context.palette.textTertiary,
                                    ),
                                  ),
                                  const SizedBox(height: AppSpacing.xs),
                                  Text(
                                    item.body,
                                    maxLines: 3,
                                    overflow: TextOverflow.ellipsis,
                                    style: TextStyle(
                                      fontSize: 12,
                                      height: 1.4,
                                      color: context.palette.textSecondary,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                            IconButton(
                              tooltip: '编辑',
                              onPressed: busy ? null : () => edit(existing: item),
                              icon: const Icon(Icons.edit_outlined, size: 20),
                            ),
                            IconButton(
                              tooltip: '删除',
                              onPressed: busy ? null : () => remove(item),
                              icon: Icon(Icons.delete_outline,
                                  size: 20, color: context.palette.danger),
                            ),
                          ],
                        ),
                      ),
                    ),
                ],
              ),
      );
}

/// 发布 / 编辑公告：标题 + markdown 正文，带实时预览。
class _AnnouncementDialog extends StatefulWidget {
  const _AnnouncementDialog({required this.api, this.existing});

  final GameApi api;
  final Announcement? existing;

  @override
  State<_AnnouncementDialog> createState() => _AnnouncementDialogState();
}

class _AnnouncementDialogState extends State<_AnnouncementDialog> {
  late final TextEditingController title =
      TextEditingController(text: widget.existing?.title ?? '');
  late final TextEditingController body =
      TextEditingController(text: widget.existing?.body ?? '');
  String? error;
  bool saving = false;

  @override
  void dispose() {
    title.dispose();
    body.dispose();
    super.dispose();
  }

  bool get valid => title.text.trim().isNotEmpty && body.text.trim().isNotEmpty;

  Future<void> save() async {
    if (!valid || saving) return;
    setState(() {
      saving = true;
      error = null;
    });
    try {
      final existing = widget.existing;
      if (existing == null) {
        await widget.api.createAnnouncement(
          title: title.text.trim(),
          body: body.text,
        );
      } else {
        await widget.api.updateAnnouncement(
          existing.id,
          title: title.text.trim(),
          body: body.text,
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
        title: Text(widget.existing == null ? '发布公告' : '编辑公告'),
        content: SizedBox(
          width: 520,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                TextField(
                  controller: title,
                  maxLength: 60,
                  decoration: const InputDecoration(
                    labelText: '标题',
                    counterText: '',
                  ),
                  onChanged: (_) => setState(() {}),
                ),
                const SizedBox(height: AppSpacing.md),
                TextField(
                  controller: body,
                  maxLength: 4000,
                  minLines: 6,
                  maxLines: 12,
                  decoration: const InputDecoration(
                    labelText: '正文（markdown）',
                    hintText: '# 标题\n\n- 列表项\n- **加粗** 与 `代码`',
                    alignLabelWithHint: true,
                  ),
                  onChanged: (_) => setState(() {}),
                ),
                const SizedBox(height: AppSpacing.md),
                Text(
                  '预览',
                  style: TextStyle(
                      fontSize: 12, color: context.palette.textTertiary),
                ),
                const SizedBox(height: AppSpacing.xs),
                Container(
                  width: double.infinity,
                  constraints: const BoxConstraints(maxHeight: 220),
                  padding: const EdgeInsets.all(AppSpacing.md),
                  decoration: BoxDecoration(
                    color: context.palette.surfaceMuted,
                    borderRadius: BorderRadius.circular(AppRadius.field),
                  ),
                  child: SingleChildScrollView(
                    child: MarkdownBody(
                      data: body.text.trim().isEmpty
                          ? '（正文为空）'
                          : body.text,
                      styleSheet: markdownStyleSheet(context),
                    ),
                  ),
                ),
                if (error != null) ...[
                  const SizedBox(height: AppSpacing.md),
                  Text(
                    error!,
                    style:
                        TextStyle(color: context.palette.danger, fontSize: 12),
                  ),
                ],
              ],
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: saving ? null : () => Navigator.pop(context, false),
            child: const Text('取消'),
          ),
          FilledButton(
            onPressed: valid && !saving ? save : null,
            child: Text(saving ? '发布中…' : '发布'),
          ),
        ],
      );
}
