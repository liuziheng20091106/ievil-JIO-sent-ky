import 'dart:async';

import 'package:flutter/material.dart';

import 'api.dart';
import 'animation_player.dart';
import 'design.dart';
import 'resource_packs.dart';

Future<void> showResourcePackDialog(
  BuildContext context, {
  required GameApi api,
  ResourcePacks? resources,
  List<ResourcePackCheck>? initialChecks,
  bool beforeGame = false,
}) async {
  try {
    final cache = resources ?? await ResourcePacks.create(api);
    if (!context.mounted) return;
    await showDialog<void>(
      context: context,
      builder: (_) => ResourcePackDialog(
          resources: cache,
          initialChecks: initialChecks,
          beforeGame: beforeGame),
    );
  } catch (error) {
    if (context.mounted) {
      ScaffoldMessenger.maybeOf(context)?.showSnackBar(
        SnackBar(content: Text('无法打开资源包：$error')),
      );
    }
  }
}

class ResourcePackEntry extends StatefulWidget {
  const ResourcePackEntry(
      {super.key,
      required this.api,
      required this.gameId,
      required this.child,
      this.resources});
  final GameApi api;
  final String gameId;
  final Widget child;
  final ResourcePacks? resources;

  @override
  State<ResourcePackEntry> createState() => _ResourcePackEntryState();
}

class _ResourcePackEntryState extends State<ResourcePackEntry> {
  bool _ready = false;
  bool _checking = true;
  int _entry = 0;

  @override
  void initState() {
    super.initState();
    _scheduleCheck();
  }

  @override
  void didUpdateWidget(covariant ResourcePackEntry oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.api != widget.api || oldWidget.gameId != widget.gameId) {
      _ready = false;
      _checking = true;
      _scheduleCheck();
    }
  }

  void _scheduleCheck() {
    final entry = ++_entry;
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      if (!mounted || entry != _entry) return;
      final route = ModalRoute.of(context);
      try {
        final resources =
            widget.resources ?? await ResourcePacks.create(widget.api);
        final checks = await resources.checkAll();
        if (!mounted || entry != _entry) return;
        setState(() => _checking = false);
        if (checks.any((check) => check.needsDownload || check.error != null)) {
          while (mounted && entry == _entry && route?.isCurrent == false) {
            await Future<void>.delayed(const Duration(milliseconds: 200));
          }
          if (!mounted || entry != _entry) return;
          await showResourcePackDialog(context,
              api: resources.api,
              resources: resources,
              initialChecks: checks,
              beforeGame: true);
        }
      } catch (error) {
        if (mounted && entry == _entry) {
          ScaffoldMessenger.maybeOf(context)?.showSnackBar(
            SnackBar(content: Text('资源检查失败：$error')),
          );
        }
      } finally {
        if (mounted && entry == _entry) setState(() => _ready = true);
      }
    });
  }

  @override
  Widget build(BuildContext context) => _ready
      ? widget.child
      : Scaffold(
          appBar: AppBar(title: const Text('正在进入对局')),
          body: Center(
              child: _checking
                  ? const CircularProgressIndicator()
                  : const SizedBox.shrink()),
        );
}

class ResourcePackDialog extends StatefulWidget {
  const ResourcePackDialog(
      {super.key,
      required this.resources,
      this.initialChecks,
      this.beforeGame = false});
  final ResourcePacks resources;
  final List<ResourcePackCheck>? initialChecks;
  final bool beforeGame;

  @override
  State<ResourcePackDialog> createState() => _ResourcePackDialogState();
}

class _ResourcePackDialogState extends State<ResourcePackDialog> {
  final _checks = <String, ResourcePackCheck>{};
  final _selected = <String>{};
  final _failures = <String, String>{};
  final _progress = <String, ResourcePackProgress>{};
  bool _checking = false;
  bool _busy = false;
  bool _cancelled = false;
  bool _closed = false;
  String? _active;
  bool _previewing = false;

  @override
  void initState() {
    super.initState();
    final initial = widget.initialChecks;
    if (initial != null) {
      _apply(initial);
    } else {
      unawaited(_check());
    }
  }

  @override
  void dispose() {
    _closed = true;
    _cancelled = true;
    super.dispose();
  }

  void _apply(List<ResourcePackCheck> checks) {
    _checks.clear();
    _selected.clear();
    for (final check in checks) {
      _checks[check.pack] = check;
      if (check.needsDownload) _selected.add(check.pack);
    }
  }

  Future<void> _check() async {
    if (_checking || _busy) return;
    setState(() => _checking = true);
    final checks = await widget.resources.checkAll();
    if (!mounted) return;
    setState(() {
      _apply(checks);
      _failures.clear();
      _progress.clear();
      _checking = false;
    });
  }

  Future<void> _download(List<String> packs) async {
    if (_busy || _checking || packs.isEmpty) return;
    setState(() {
      _busy = true;
      _cancelled = false;
    });
    try {
      for (final pack in packs) {
        if (_cancelled || _closed) break;
        final manifest = _checks[pack]?.remote;
        if (manifest == null) continue;
        setState(() {
          _active = pack;
          _failures.remove(pack);
          _progress[pack] = ResourcePackProgress(0, manifest.totalSize, '');
        });
        try {
          await widget.resources.download(
            manifest,
            isCancelled: () => _cancelled || _closed,
            onProgress: (progress) {
              if (mounted) setState(() => _progress[pack] = progress);
            },
          );
          if (!mounted) return;
          setState(() {
            _checks[pack] = ResourcePackCheck(
                pack: pack, remote: manifest, local: manifest);
            _selected.remove(pack);
          });
        } catch (error) {
          if (!mounted) return;
          setState(() {
            _failures[pack] = _cancelled ? '已取消下载' : '下载失败：$error';
          });
        }
      }
    } finally {
      if (mounted) {
        setState(() {
          _active = null;
          _busy = false;
        });
      }
    }
  }

  Future<void> _previewAnimation() async {
    if (_busy || _checking || _previewing) return;
    setState(() => _previewing = true);
    try {
      final manifest = await widget.resources.localManifest('animation');
      final scripts = manifest?.files
              .where((file) => isAnimationScriptPath(file.path))
              .map((file) => file.path)
              .toList() ??
          <String>[];
      if (!mounted) return;
      final script = await showDialog<String>(
        context: context,
        builder: (context) => AlertDialog(
          title: Row(children: [
            const Expanded(child: Text('动画脚本')),
            IconButton(
              tooltip: '关闭选择',
              onPressed: () => Navigator.of(context).pop(),
              icon: const Icon(Icons.close),
            ),
          ]),
          content: scripts.isEmpty
              ? const Text('尚未下载动画脚本')
              : SizedBox(
                  width: 420,
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxHeight: 320),
                    child: ListView(
                      shrinkWrap: true,
                      children: [
                        for (final path in scripts)
                          ListTile(
                            title: Text(path),
                            trailing: const Icon(Icons.play_arrow),
                            onTap: () => Navigator.of(context).pop(path),
                          ),
                      ],
                    ),
                  ),
                ),
        ),
      );
      if (!mounted || script == null) return;
      await showAnimationPreviewDialog(context,
          resources: widget.resources, scriptPath: script);
    } catch (error) {
      if (mounted) {
        ScaffoldMessenger.maybeOf(context)?.showSnackBar(
          SnackBar(content: Text('无法预览动画：$error')),
        );
      }
    } finally {
      if (mounted) setState(() => _previewing = false);
    }
  }

  String _status(String pack) {
    if (_active == pack) {
      if (_cancelled) return '正在取消';
      return _progress[pack]?.verifying == true ? '正在校验' : '正在下载';
    }
    if (_failures.containsKey(pack)) return _failures[pack]!;
    final check = _checks[pack];
    if (_checking || check == null) return '正在检查';
    if (check.unpublished) {
      return check.local == null ? '未发布' : '未发布 · 保留本地缓存';
    }
    if (check.error != null) return check.error!;
    if (check.remote == null) return '检查失败';
    if (!check.needsDownload) return '已是最新';
    return check.local == null ? '尚未下载' : '有更新';
  }

  Widget _packRow(String pack) {
    final check = _checks[pack];
    final downloadable = check?.needsDownload == true;
    final progress = _progress[pack];
    final size = check?.remote?.totalSize ?? check?.local?.totalSize;
    final problem = _failures.containsKey(pack) || check?.error != null;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.md),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Checkbox(
                value: _selected.contains(pack),
                onChanged: !_busy && !_checking && downloadable
                    ? (value) => setState(() {
                          if (value == true) {
                            _selected.add(pack);
                          } else {
                            _selected.remove(pack);
                          }
                        })
                    : null,
              ),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.only(top: 6),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(pack == 'animation' ? '动画资源' : '表情资源',
                          style: const TextStyle(
                              fontSize: 15, fontWeight: FontWeight.w600)),
                      const SizedBox(height: AppSpacing.xs),
                      Text(_status(pack),
                          style: TextStyle(
                              fontSize: 13,
                              color: problem
                                  ? context.palette.danger
                                  : context.palette.textSecondary)),
                      if (size != null)
                        Text(_bytes(size),
                            style: TextStyle(
                                fontSize: 12,
                                color: context.palette.textTertiary)),
                    ],
                  ),
                ),
              ),
              if (pack == 'animation')
                IconButton(
                  tooltip: '预览动画',
                  onPressed: _busy || _checking || _previewing
                      ? null
                      : _previewAnimation,
                  icon: const Icon(Icons.play_arrow),
                ),
              if (_failures.containsKey(pack) && downloadable)
                IconButton(
                  tooltip: '重试',
                  onPressed:
                      _busy || _checking ? null : () => _download([pack]),
                  icon: const Icon(Icons.refresh),
                ),
            ],
          ),
          if (_active == pack && progress != null) ...[
            const SizedBox(height: AppSpacing.sm),
            LinearProgressIndicator(value: progress.fraction),
            const SizedBox(height: AppSpacing.xs),
            Text('${_bytes(progress.received)} / ${_bytes(progress.total)}',
                style: TextStyle(
                    fontSize: 12, color: context.palette.textSecondary)),
            if (progress.path.isNotEmpty)
              Text(progress.path,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(
                      fontSize: 12, color: context.palette.textTertiary)),
          ],
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: Row(
          children: [
            const Expanded(child: Text('资源包')),
            IconButton(
              tooltip: '重新检查',
              onPressed: _busy || _checking ? null : _check,
              icon: const Icon(Icons.refresh),
            ),
          ],
        ),
        content: SizedBox(
          width: 420,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                _packRow('animation'),
                const Divider(height: 1),
                _packRow('memes'),
              ],
            ),
          ),
        ),
        actions: [
          if (_busy)
            TextButton(
              onPressed:
                  _cancelled ? null : () => setState(() => _cancelled = true),
              child: const Text('取消下载'),
            ),
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: Text(widget.beforeGame
                ? (_busy ? '取消并进入对局' : '进入对局')
                : (_busy ? '关闭' : '暂不下载')),
          ),
          FilledButton.icon(
            onPressed: _busy || _checking || _selected.isEmpty
                ? null
                : () => _download(
                    resourcePackNames.where(_selected.contains).toList()),
            icon: const Icon(Icons.download_outlined, size: 18),
            label: const Text('下载所选'),
          ),
        ],
      );
}

String _bytes(int bytes) {
  if (bytes < 1024) return '$bytes B';
  if (bytes < 1024 * 1024) return '${(bytes / 1024).toStringAsFixed(1)} KB';
  if (bytes < 1024 * 1024 * 1024) {
    return '${(bytes / (1024 * 1024)).toStringAsFixed(1)} MB';
  }
  return '${(bytes / (1024 * 1024 * 1024)).toStringAsFixed(1)} GB';
}
