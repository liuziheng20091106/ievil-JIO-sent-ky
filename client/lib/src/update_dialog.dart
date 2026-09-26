import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';

import 'announcement_pages.dart' show markdownStyleSheet;
import 'design.dart';
import 'platform_channel.dart';
import 'release.dart';
import 'store.dart';
import 'update_installer.dart';

/// 大厅里的更新入口：只要服务端说有新版本就一直存在。
///
/// 更新弹窗可以被用户关掉，但这个入口不会消失——它就是「完成更新前始终显示更新按钮」
/// 的落点，避免用户关掉弹窗后找不到再更新的地方。
class UpdateEntryCard extends StatelessWidget {
  const UpdateEntryCard({
    super.key,
    required this.store,
    required this.release,
  });

  final GameStore store;
  final ReleaseMonitor release;

  @override
  Widget build(BuildContext context) {
    final info = release.updateInfo;
    final latest = info?.latest ?? '';
    final mandatory = release.updateRequired;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.lg),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  mandatory
                      ? Icons.system_update_alt_rounded
                      : Icons.new_releases_outlined,
                  color: mandatory
                      ? context.palette.danger
                      : context.palette.accent,
                ),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: Text(
                    mandatory
                        ? '必须更新后才能加入对局'
                        : '发现新版本${latest.isEmpty ? '' : ' $latest'}',
                    style: TextStyle(
                      fontSize: 15,
                      fontWeight: FontWeight.w600,
                      color: context.palette.text,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.sm),
            Text(
              mandatory
                  ? '当前版本过旧，更新之前无法加入对局；其它功能仍可正常使用。'
                  : '应用内直接下载安装，不用再找主持人要安装包。',
              style: TextStyle(
                fontSize: 12,
                color: context.palette.textTertiary,
                height: 1.5,
              ),
            ),
            const SizedBox(height: AppSpacing.md),
            Row(
              children: [
                Expanded(
                  child: FilledButton.icon(
                    onPressed: () => showUpdateDialog(
                      context,
                      store: store,
                      release: release,
                    ),
                    icon: const Icon(Icons.download_rounded, size: 18),
                    label: const Text('立即更新'),
                  ),
                ),
                if (info?.hasGuide == true) ...[
                  const SizedBox(width: AppSpacing.md),
                  OutlinedButton(
                    onPressed: () => openUpdateGuide(context, info!),
                    child: const Text('打开网页'),
                  ),
                ],
              ],
            ),
          ],
        ),
      ),
    );
  }
}

/// 「必要时引导用户打开指定网页」：打不开就把链接复制到剪切板，让用户自己粘贴。
Future<void> openUpdateGuide(BuildContext context, ClientUpdateInfo info) async {
  final url = info.guideUrl.trim();
  if (url.isEmpty) return;
  final messenger = ScaffoldMessenger.maybeOf(context);
  final opened = await const ClientUpdateChannel().openUrl(url);
  if (opened) return;
  await Clipboard.setData(ClipboardData(text: url));
  messenger
    ?..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(content: Text('无法自动打开网页，链接已复制：$url')));
}

/// 更新弹窗：展示 Markdown 更新日志 + 「更新」（始终可见）+「打开网页」+「稍后」。
///
/// 强制更新（低于服务端 minimum）时不提供「稍后」，只能更新或退出客户端；
/// 其余情况用户可以关掉弹窗，大厅里的入口仍然在。
Future<void> showUpdateDialog(
  BuildContext context, {
  required GameStore store,
  required ReleaseMonitor release,
}) =>
    showDialog<void>(
      context: context,
      barrierDismissible: !release.updateRequired,
      builder: (context) => _UpdateDialog(store: store, release: release),
    );

class _UpdateDialog extends StatefulWidget {
  const _UpdateDialog({required this.store, required this.release});

  final GameStore store;
  final ReleaseMonitor release;

  @override
  State<_UpdateDialog> createState() => _UpdateDialogState();
}

class _UpdateDialogState extends State<_UpdateDialog> {
  UpdateProgress? _progress;
  bool _busy = false;
  bool _cancelled = false;
  String? _notice;

  ClientUpdateInfo? get _info => widget.release.updateInfo;
  bool get _mandatory => widget.release.updateRequired;

  @override
  Widget build(BuildContext context) {
    final info = _info;
    final latest = info?.latest ?? '';
    return AlertDialog(
      icon: Icon(
        _mandatory
            ? Icons.system_update_alt_rounded
            : Icons.new_releases_outlined,
        color: _mandatory ? context.palette.danger : context.palette.accent,
      ),
      title: Text(info?.title ?? '发现新版本'),
      content: SizedBox(
        width: 460,
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                latest.isEmpty
                    ? '当前版本 ${widget.release.currentVersion}'
                    : '当前版本 ${widget.release.currentVersion} → 最新 $latest',
                style: TextStyle(
                  fontSize: 13,
                  color: context.palette.textSecondary,
                ),
              ),
              if (_mandatory) ...[
                const SizedBox(height: AppSpacing.sm),
                Text(
                  '这个版本过旧，更新之前无法加入对局。',
                  style: TextStyle(fontSize: 13, color: context.palette.danger),
                ),
              ],
              if ((info?.notes ?? '').trim().isNotEmpty) ...[
                const SizedBox(height: AppSpacing.md),
                const Divider(height: 1),
                const SizedBox(height: AppSpacing.md),
                MarkdownBody(
                  data: info!.notes,
                  selectable: true,
                  styleSheet: markdownStyleSheet(context),
                ),
              ] else ...[
                const SizedBox(height: AppSpacing.md),
                Text(
                  '服务端没有提供更新日志，可以直接更新到最新版本。',
                  style: TextStyle(
                    fontSize: 13,
                    color: context.palette.textTertiary,
                  ),
                ),
              ],
              if (_progress != null) ...[
                const SizedBox(height: AppSpacing.lg),
                _progressArea(context, _progress!),
              ],
              if (_notice != null) ...[
                const SizedBox(height: AppSpacing.md),
                Text(
                  _notice!,
                  style: TextStyle(fontSize: 13, color: context.palette.danger),
                ),
              ],
            ],
          ),
        ),
      ),
      actions: [
        if (_progress?.stage == UpdateStage.downloading && _busy)
          TextButton(
            onPressed: () => setState(() => _cancelled = true),
            child: const Text('取消下载'),
          ),
        if (info?.hasGuide == true)
          TextButton(
            onPressed: () => openUpdateGuide(context, info!),
            child: const Text('打开网页'),
          ),
        if (!_mandatory)
          TextButton(
            // 关掉弹窗只是收起提示：大厅里的「立即更新」不会消失。
            onPressed: () => Navigator.of(context).maybePop(),
            child: const Text('稍后'),
          )
        else
          TextButton(
            // 强制更新也可以收起弹窗，但大厅的入口与横幅会一直提示；
            // 真正拦住的是服务端：过旧客户端加入对局会被拒。
            onPressed: () => Navigator.of(context).maybePop(),
            child: const Text('先不更新'),
          ),
        FilledButton.icon(
          // 「更新」在更新完成或用户主动关闭弹窗前始终可见，随时可以再点。
          onPressed: _busy ? null : _start,
          icon: const Icon(Icons.download_rounded, size: 18),
          label: Text(_busy ? '更新中…' : '更新'),
        ),
      ],
    );
  }

  Widget _progressArea(BuildContext context, UpdateProgress progress) {
    final fraction = progress.fraction;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (progress.stage == UpdateStage.downloading ||
            progress.stage == UpdateStage.installing ||
            progress.stage == UpdateStage.launching)
          LinearProgressIndicator(value: fraction),
        if (progress.message != null) ...[
          const SizedBox(height: AppSpacing.sm),
          Text(
            progress.message!,
            style: TextStyle(
              fontSize: 12,
              color: context.palette.textSecondary,
            ),
          ),
        ],
      ],
    );
  }

  Future<void> _start() async {
    final info = _info;
    if (info == null) {
      // 服务端只给了版本标签（旧式配置）：没有下载地址，只能提示去找安装包。
      setState(() => _notice = '服务端未下发安装包地址，请向主持人获取最新安装包。');
      return;
    }
    final api = widget.store.api;
    if (api == null) {
      setState(() => _notice = '尚未连接服务器');
      return;
    }
    setState(() {
      _busy = true;
      _cancelled = false;
      _notice = null;
      _progress = const UpdateProgress(UpdateStage.downloading);
    });
    final installer = await UpdateInstaller.create();
    final result = await installer.start(
      api: api,
      info: info,
      isCancelled: () => _cancelled,
      onProgress: (progress) {
        if (mounted) setState(() => _progress = progress);
      },
    );
    if (!mounted) return;
    setState(() {
      _busy = false;
      if (!result.ok && result.message != null) _notice = result.message;
      if (result.outcome == UpdateOutcome.permissionRequired) {
        _notice = result.message;
      }
    });
  }
}
