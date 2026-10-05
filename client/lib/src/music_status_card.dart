import 'dart:async';

import 'package:flutter/material.dart';

import 'design.dart';

class MusicStatusCard extends StatefulWidget {
  const MusicStatusCard(
      {super.key,
      required this.audio,
      required this.allowed,
      required this.elapsed});

  final Object? audio;
  final bool allowed;
  final Duration Function() elapsed;

  @override
  State<MusicStatusCard> createState() => _MusicStatusCardState();
}

class _MusicStatusCardState extends State<MusicStatusCard> {
  Timer? _timer;

  Iterable<Map> get _tracks {
    final audio = widget.audio;
    final tracks = audio is Map ? audio['tracks'] : null;
    return tracks is List ? tracks.whereType<Map>() : const [];
  }

  @override
  void initState() {
    super.initState();
    _updateTimer();
  }

  @override
  void didUpdateWidget(covariant MusicStatusCard oldWidget) {
    super.didUpdateWidget(oldWidget);
    _updateTimer();
  }

  void _updateTimer() {
    _timer?.cancel();
    if (_tracks.any((track) => track['playing'] == true)) {
      _timer = Timer.periodic(const Duration(seconds: 1), (_) {
        if (mounted) setState(() {});
      });
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  String _progress(Map track) {
    final position = track['position'];
    final rate = track['rate'];
    if (position is! num ||
        !position.isFinite ||
        rate is! num ||
        !rate.isFinite) {
      return '进度不可用';
    }
    final seconds = (position +
            (track['playing'] == true
                ? widget.elapsed().inMilliseconds / 1000 * rate
                : 0))
        .floor()
        .clamp(0, 2147483647);
    return '${seconds ~/ 60}:${(seconds % 60).toString().padLeft(2, '0')} · $rate×';
  }

  @override
  Widget build(BuildContext context) => Card(
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.md),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (!widget.allowed)
                Text('本机已关闭音频，其他参与者仍按各自设置播放。',
                    style: TextStyle(color: context.palette.textSecondary)),
              if (_tracks.isEmpty)
                const Text('当前没有音乐')
              else
                for (final track in _tracks)
                  ListTile(
                    dense: true,
                    contentPadding: EdgeInsets.zero,
                    leading: Icon(track['playing'] == true
                        ? Icons.music_note
                        : Icons.pause),
                    title: Text('${track['song'] ?? ''}'),
                    subtitle: Text(
                        '${track['playing'] == true ? '播放中' : '已暂停'} · ${_progress(track)}'),
                  ),
            ],
          ),
        ),
      );
}
