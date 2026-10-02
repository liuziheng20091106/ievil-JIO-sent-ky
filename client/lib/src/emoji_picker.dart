import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:path/path.dart' as p;
import 'package:shared_preferences/shared_preferences.dart';

import 'models.dart';
import 'design.dart';
import 'emoji.dart';
import 'resource_packs.dart';

/// 本机最近使用的 QQ 表情，显示时最多三行。
final recentEmojiIds = <String>[];
const int recentEmojiLimit = 96;
const String recentEmojiPreferenceKey = 'emoji_recent_ids';
SharedPreferences? _recentPreferences;

void loadRecentEmojiIds(SharedPreferences preferences) {
  _recentPreferences = preferences;
  final stored =
      preferences.getStringList(recentEmojiPreferenceKey) ?? const <String>[];
  recentEmojiIds
    ..clear()
    ..addAll(stored
        .where((id) => emojiFaceById(id) != null)
        .toSet()
        .take(recentEmojiLimit));
  if (stored.length != recentEmojiIds.length) {
    unawaited(preferences.setStringList(
        recentEmojiPreferenceKey, List<String>.of(recentEmojiIds)));
  }
}

void rememberRecentEmoji(String id) {
  if (emojiFaceById(id) == null) return;
  recentEmojiIds
    ..remove(id)
    ..insert(0, id);
  if (recentEmojiIds.length > recentEmojiLimit) {
    recentEmojiIds.removeRange(recentEmojiLimit, recentEmojiIds.length);
  }
  final preferences = _recentPreferences;
  if (preferences != null) {
    unawaited(preferences.setStringList(
        recentEmojiPreferenceKey, List<String>.of(recentEmojiIds)));
  }
}

/// 返回键先收输入区表情面板，不退出页面或丢弃行动表单。
class EmojiPanelScope extends StatelessWidget {
  const EmojiPanelScope(
      {super.key, required this.onClose, required this.child});
  final VoidCallback onClose;
  final Widget child;

  @override
  Widget build(BuildContext context) => PopScope(
        canPop: false,
        onPopInvokedWithResult: (didPop, _) {
          if (!didPop) onClose();
        },
        child: child,
      );
}

/// 不提供 onPickMeme 的纯文本表单只显示 QQ 表情。
class EmojiPicker extends StatefulWidget {
  const EmojiPicker({
    super.key,
    required this.onPick,
    this.resources,
    this.onPickMeme,
    this.height = 236,
  });

  final ValueChanged<EmojiFace> onPick;
  final ResourcePacks? resources;
  final double height;
  final Future<void> Function(String md5)? onPickMeme;
  @override
  State<EmojiPicker> createState() => _EmojiPickerState();
}

class _EmojiPickerState extends State<EmojiPicker> {
  static const _imageExtensions = {
    '.png',
    '.jpg',
    '.jpeg',
    '.gif',
    '.webp',
    '.bmp',
    '.avif'
  };
  static final _qqIds =
      emojiFaces.map((face) => face.id).toList(growable: false);
  final search = TextEditingController();
  final scroll = ScrollController();
  final memes = <String, File>{};
  final groups = <String, List<String>>{};
  String? group;
  String query = '';
  String? cacheError;
  bool searching = false;
  bool picking = false;
  bool loading = false;
  int _loadGeneration = 0;

  @override
  void initState() {
    super.initState();
    unawaited(loadMemes());
  }

  @override
  void didUpdateWidget(EmojiPicker oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.resources != widget.resources ||
        (oldWidget.onPickMeme == null) != (widget.onPickMeme == null)) {
      unawaited(loadMemes());
    }
  }

  Future<void> loadMemes() async {
    final generation = ++_loadGeneration;
    final cache = widget.resources;
    memes.clear();
    groups.clear();
    cacheError = null;
    loading = cache != null && widget.onPickMeme != null;
    if (mounted) setState(() {});
    if (loading) {
      try {
        // 一次打开只校验一次整包；点选时只重新验证选中的映射与文件。
        final manifest = await cache!.localManifest('memes');
        if (!mounted || generation != _loadGeneration) return;
        for (final entry in manifest?.files ?? <ResourcePackFile>[]) {
          if (!_imageExtensions
              .contains(p.posix.extension(entry.path).toLowerCase())) {
            continue;
          }
          final directory = p.posix.dirname(entry.path);
          memes[entry.path] = File(p.join(cache.directory.path, entry.md5));
          groups
              .putIfAbsent(directory == '.' ? 'memes' : directory, () => [])
              .add(entry.path);
        }
      } catch (_) {
        if (!mounted || generation != _loadGeneration) return;
        cacheError = '表情资源缓存不可用，请重新下载';
      }
    }
    if (!mounted || generation != _loadGeneration) return;
    setState(() {
      loading = false;
      if (!groups.containsKey(group)) group = null;
    });
  }

  @override
  void dispose() {
    search.dispose();
    scroll.dispose();
    super.dispose();
  }

  bool matches(String id, String keyword, String lower) {
    final face = emojiFaceById(id);
    if (face == null) return id.substring(5).toLowerCase().contains(lower);
    return face.name.contains(keyword) ||
        face.pinyin.any((word) => word.startsWith(lower));
  }

  Future<void> pick(String id) async {
    final face = emojiFaceById(id);
    if (face != null) {
      rememberRecentEmoji(id);
      setState(() {});
      widget.onPick(face);
      return;
    }
    final callback = widget.onPickMeme;
    final cache = widget.resources;
    if (picking || callback == null || cache == null) return;
    setState(() => picking = true);
    try {
      final path = await cache.filePath('memes', id.substring(5));
      if (!mounted) return;
      if (path == null) {
        setState(() {
          memes.remove(id.substring(5));
          for (final entries in groups.values) {
            entries.remove(id.substring(5));
          }
          groups.removeWhere((_, entries) => entries.isEmpty);
          if (!groups.containsKey(group)) group = null;
          cacheError = '这张表情已移除或损坏，请重新下载';
        });
        return;
      }
      await callback(p.basename(path));
    } catch (error) {
      if (mounted) {
        setState(() => cacheError =
            error is ApiException ? error.message : '无法读取这张表情，请重新下载');
      }
    } finally {
      if (mounted) setState(() => picking = false);
    }
  }

  void selectGroup(String? value) {
    setState(() {
      group = value;
      query = '';
      search.clear();
      searching = false;
    });
    FocusManager.instance.primaryFocus?.unfocus();
    if (scroll.hasClients) scroll.jumpTo(0);
  }

  Widget image(String id, {int decodeSize = 128}) {
    final face = emojiFaceById(id);
    if (face != null) {
      return Padding(
        padding: const EdgeInsets.all(7),
        child: Image.asset(face.asset,
            cacheWidth: 64,
            cacheHeight: 64,
            filterQuality: FilterQuality.medium),
      );
    }
    return Image(
        image: ResizeImage(FileImage(memes[id.substring(5)]!),
            width: decodeSize,
            height: decodeSize,
            policy: ResizeImagePolicy.fit),
        fit: BoxFit.contain,
        errorBuilder: (_, __, ___) => const Icon(Icons.broken_image_outlined));
  }

  Widget grid(List<String> ids, int columns, String section) => SliverGrid(
        gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: columns, mainAxisSpacing: 2, crossAxisSpacing: 2),
        delegate: SliverChildBuilderDelegate((context, index) {
          final id = ids[index];
          return Semantics(
            button: true,
            label: emojiFaceById(id)?.name ?? p.posix.basename(id.substring(5)),
            child: InkWell(
              key: ValueKey('$section:$id'),
              onTap: picking ? null : () => pick(id),
              borderRadius: BorderRadius.circular(AppRadius.field),
              child: image(id),
            ),
          );
        }, childCount: ids.length),
      );

  Widget heading(String label) => SliverToBoxAdapter(
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 8),
          child: Text(label,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(
                  fontSize: 12, color: context.palette.textSecondary)),
        ),
      );

  @override
  Widget build(BuildContext context) {
    final keyword = query.trim();
    final lower = keyword.toLowerCase();
    final list = keyword.isNotEmpty
        ? _qqIds
            .followedBy(widget.onPickMeme == null
                ? const Iterable<String>.empty()
                : memes.keys.map((path) => 'meme:$path'))
            .where((id) => matches(id, keyword, lower))
            .toList()
        : group == null
            ? _qqIds
            : [for (final path in groups[group] ?? <String>[]) 'meme:$path'];
    return Container(
      height: widget.height,
      decoration: BoxDecoration(
          color: context.palette.surfaceMuted,
          border: Border(top: BorderSide(color: context.palette.border))),
      child: Column(children: [
        SizedBox(
          height: 46,
          child: Row(children: [
            IconButton(
              tooltip: '搜索表情',
              onPressed: () => setState(() {
                searching = !searching;
                if (!searching) {
                  query = '';
                  search.clear();
                }
              }),
              icon: const Icon(Icons.search, size: 21),
            ),
            Expanded(
                child: ListView(
              scrollDirection: Axis.horizontal,
              children: [
                IconButton(
                  tooltip: 'QQ表情',
                  isSelected: group == null && query.isEmpty,
                  onPressed: () => selectGroup(null),
                  icon: const Icon(Icons.sentiment_satisfied_alt),
                ),
                for (final entry in groups.entries)
                  SizedBox(
                      width: 46,
                      child: IconButton(
                        tooltip: entry.key,
                        isSelected: group == entry.key && query.isEmpty,
                        onPressed: () => selectGroup(entry.key),
                        icon: SizedBox(
                            width: 32,
                            height: 32,
                            child: image('meme:${entry.value.first}',
                                decodeSize: 64)),
                      )),
              ],
            )),
          ]),
        ),
        if (searching)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8),
            child: SizedBox(
                height: 38,
                child: TextField(
                  controller: search,
                  autofocus: true,
                  textInputAction: TextInputAction.search,
                  style: const TextStyle(fontSize: 13),
                  decoration: const InputDecoration(
                      isDense: true,
                      hintText: '搜索表情名或拼音',
                      contentPadding: EdgeInsets.all(8)),
                  onChanged: (value) => setState(() => query = value),
                )),
          ),
        Expanded(child: LayoutBuilder(builder: (context, constraints) {
          final recentColumns =
              (constraints.maxWidth / 46).floor().clamp(1, 32);
          final columns = group == null && query.isEmpty
              ? recentColumns
              : (constraints.maxWidth / 90).floor().clamp(1, 32);
          final recent = recentEmojiIds
              .where((id) => emojiFaceById(id) != null)
              .take(recentColumns * 3)
              .toList();
          return CustomScrollView(controller: scroll, slivers: [
            SliverPadding(
                padding: const EdgeInsets.symmetric(horizontal: 8),
                sliver: SliverMainAxisGroup(slivers: [
                  heading('最近'),
                  if (recent.isNotEmpty) grid(recent, recentColumns, 'recent'),
                  if (widget.onPickMeme != null && groups.isEmpty)
                    heading(loading ? '正在读取表情资源' : cacheError ?? '尚未下载表情资源'),
                  if (cacheError != null && groups.isNotEmpty)
                    heading(cacheError!),
                  heading(query.trim().isNotEmpty ? '搜索结果' : group ?? 'QQ表情'),
                  if (list.isNotEmpty)
                    grid(list, columns, 'all')
                  else
                    heading('没有匹配的表情'),
                  const SliverToBoxAdapter(child: SizedBox(height: 8)),
                ])),
          ]);
        })),
      ]),
    );
  }
}
