import 'dart:async';
import 'dart:math' as math;

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/material.dart';

import 'audio_player.dart';
import 'resource_packs.dart';
import 'store.dart';

double _finiteNumber(Object? value, String label) {
  if (value is! num || !value.isFinite) {
    throw FormatException('音频$label不合法');
  }
  return value.toDouble();
}

const maxAudioPosition = 604800.0;

class AudioTrackProjection {
  AudioTrackProjection.fromJson(Object? value) {
    if (value is! Map ||
        value['id'] is! String ||
        (value['id'] as String).isEmpty ||
        value['song'] is! String ||
        (value['song'] as String).isEmpty ||
        value['playing'] is! bool ||
        value['revision'] is! int ||
        (value['revision'] as int) < 0) {
      throw const FormatException('音频轨道数据不合法');
    }
    id = value['id'] as String;
    song = value['song'] as String;
    playing = value['playing'] as bool;
    revision = value['revision'] as int;
    position = _finiteNumber(value['position'], '进度');
    rate = _finiteNumber(value['rate'], '倍速');
    if (position < 0 || position > maxAudioPosition || rate < .25 || rate > 4) {
      throw const FormatException('音频进度或倍速不合法');
    }
  }

  late final String id;
  late final String song;
  late final double position;
  late final double rate;
  late final bool playing;
  late final int revision;

  bool sameControl(AudioTrackProjection other) =>
      id == other.id &&
      song == other.song &&
      revision == other.revision &&
      playing == other.playing &&
      rate == other.rate;

  Duration positionAfter(Duration elapsed) {
    final seconds = math.min(
        maxAudioPosition,
        position +
            (playing
                ? math.max(0, elapsed.inMicroseconds) /
                    Duration.microsecondsPerSecond *
                    rate
                : 0));
    return Duration(
        microseconds: (seconds * Duration.microsecondsPerSecond).round());
  }
}

class AudioSnapshot {
  AudioSnapshot.fromJson(Object? raw) {
    if (raw is! Map || raw['tracks'] is! List) {
      throw const FormatException('音频同步数据不合法');
    }
    serverTime = _finiteNumber(raw['server_time'], '同步时间');
    if (serverTime < 0) throw const FormatException('音频同步时间不合法');
    final ids = <String>{};
    tracks = [
      for (final value in raw['tracks'] as List)
        AudioTrackProjection.fromJson(value)
    ];
    for (final track in tracks) {
      if (!ids.add(track.id)) throw const FormatException('音频轨道标识重复');
    }
  }

  late final double serverTime;
  late final List<AudioTrackProjection> tracks;
}

/// 根级订阅；每条后台轨道拥有自己的原生播放器。
class GameAudioController extends ChangeNotifier {
  GameAudioController({required this.store, this.resources}) {
    store.addListener(_changed);
    ResourcePacks.audioChanges.addListener(_audioInstalled);
    _changed();
  }

  final GameStore store;
  final ResourcePacks? resources;
  final _tracks = <String, _MusicTrack>{};
  final _failures = <String, String>{};
  Object? _lastRaw;
  Object? _sessionApi;
  String? _gameId;
  Future<ResourcePacks>? _cache;
  bool _disposed = false;
  final _clock = Stopwatch()..start();
  AudioSnapshot? _snapshot;
  Duration _receivedAt = Duration.zero;

  String? get error => _failures.isEmpty ? null : _failures.values.join('\n');

  /// 原生状态可用于真实声音烟测，不提供模拟播放状态。
  Map<String, AudioPlayer> get players => Map.unmodifiable({
        for (final entry in _tracks.entries)
          if (entry.value.voice != null) entry.key: entry.value.voice!.player,
      });

  void _report(String id, String message) {
    if (_disposed || _failures[id] == message) return;
    _failures[id] = message;
    notifyListeners();
  }

  void _audioInstalled() {
    if (store.allowAudioEnabled && store.gameId != null) retry();
  }

  void _changed() {
    if (_disposed) return;
    if (_gameId != store.gameId || !identical(_sessionApi, store.api)) {
      _stopAll();
      _gameId = store.gameId;
      _sessionApi = store.api;
      _cache = null;
      _lastRaw = null;
      _snapshot = null;
      _failures.clear();
      notifyListeners();
    }
    if (store.gameId == null || store.actor == null || store.view == null) {
      _stopAll();
      _lastRaw = null;
      _snapshot = null;
      if (_failures.isNotEmpty) {
        _failures.clear();
        notifyListeners();
      }
      return;
    }
    final raw = store.view!.raw['audio'];
    if (raw == null) {
      _stopAll();
      _lastRaw = null;
      _snapshot = null;
      if (_failures.isNotEmpty) {
        _failures.clear();
        notifyListeners();
      }
      return;
    }
    // 静音期间也接收新进度；普通本机设置/聊天通知不会重置接收时刻。
    if (!identical(raw, _lastRaw)) {
      _lastRaw = raw;
      try {
        _snapshot = AudioSnapshot.fromJson(raw);
        _receivedAt = _clock.elapsed;
        if (_failures.remove('projection') != null) notifyListeners();
      } catch (error) {
        _snapshot = null;
        _stopAll();
        _report('projection', '音频同步失败：$error');
      }
    }
    if (!store.allowAudioEnabled) {
      _stopAll();
      if (_failures.isNotEmpty) {
        _failures.clear();
        notifyListeners();
      }
      return;
    }
    final snapshot = _snapshot;
    if (snapshot == null) return;
    final ids = snapshot.tracks.map((track) => track.id).toSet();
    for (final id in _tracks.keys.toList()) {
      if (!ids.contains(id)) {
        _tracks.remove(id)!.dispose();
        if (_failures.remove(id) != null) notifyListeners();
      }
    }
    for (final projection in snapshot.tracks) {
      final existing = _tracks[projection.id];
      if (existing != null && existing.projection.song == projection.song) {
        final changed = !existing.projection.sameControl(projection);
        existing.projection = projection;
        existing.receivedAt = _receivedAt;
        if (changed) existing.sync();
        continue;
      }
      existing?.dispose();
      if (_failures.remove(projection.id) != null) notifyListeners();
      final track = _MusicTrack(projection, _receivedAt,
          elapsed: () => _clock.elapsed,
          onError: (error) =>
              _report(projection.id, '音频「${projection.song}」无法播放：$error'));
      _tracks[projection.id] = track;
      final api = store.api;
      if (resources == null && api == null) {
        _report(projection.id, '音频资源不可用：尚未连接服务器');
        continue;
      }
      _cache ??= resources != null
          ? Future.value(resources!)
          : ResourcePacks.create(api!);
      unawaited(track.load(_cache!));
    }
  }

  void retry() {
    if (_disposed) return;
    _stopAll();
    if (_snapshot == null) _lastRaw = null;
    _cache = null;
    _failures.clear();
    notifyListeners();
    _changed();
  }

  void _stopAll() {
    for (final track in _tracks.values) {
      track.dispose();
    }
    _tracks.clear();
  }

  @override
  void dispose() {
    _disposed = true;
    store.removeListener(_changed);
    ResourcePacks.audioChanges.removeListener(_audioInstalled);
    _stopAll();
    _clock.stop();
    super.dispose();
  }
}

class _MusicTrack {
  _MusicTrack(this.projection, this.receivedAt,
      {required this.elapsed, required this.onError});
  AudioTrackProjection projection;
  Duration receivedAt;
  final Duration Function() elapsed;
  final void Function(Object) onError;
  LocalAudioVoice? voice;
  bool _disposed = false;

  Future<void> load(Future<ResourcePacks> cache) async {
    try {
      final resources = await cache;
      if (_disposed) return;
      final path = await resources.filePath('audio', projection.song);
      if (_disposed) return;
      if (path == null) {
        throw StateError('音频包未下载、文件缺失或校验失败；请在资源包中下载音频后重试');
      }
      voice = LocalAudioVoice(path, onError: (error) {
        if (!_disposed) onError(error);
      });
      sync();
    } catch (error) {
      if (!_disposed) onError(error);
    }
  }

  void sync() => voice?.update(
      position: () => projection.positionAfter(elapsed() - receivedAt),
      rate: projection.rate,
      playing: projection.playing);

  void dispose() {
    _disposed = true;
    voice?.dispose();
  }
}

class GameAudioPlayback extends StatefulWidget {
  const GameAudioPlayback({super.key, required this.store, this.resources});
  final GameStore store;
  final ResourcePacks? resources;

  @override
  State<GameAudioPlayback> createState() => _GameAudioPlaybackState();
}

class _GameAudioPlaybackState extends State<GameAudioPlayback> {
  late GameAudioController _audio;
  String? _dismissed;

  @override
  void initState() {
    super.initState();
    _audio =
        GameAudioController(store: widget.store, resources: widget.resources);
  }

  @override
  void didUpdateWidget(covariant GameAudioPlayback oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.store != widget.store ||
        oldWidget.resources != widget.resources) {
      _audio.dispose();
      _audio =
          GameAudioController(store: widget.store, resources: widget.resources);
      _dismissed = null;
    }
  }

  @override
  void dispose() {
    _audio.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: _audio,
        builder: (context, _) {
          final error = _audio.error;
          if (error == null || error == _dismissed) {
            return const SizedBox.shrink();
          }
          return Positioned(
              top: 0,
              left: 0,
              right: 0,
              child: SafeArea(
                  child: Card(
                      child: Padding(
                padding: const EdgeInsets.only(left: 12),
                child: Row(children: [
                  Expanded(
                      child: Text(error,
                          maxLines: 4, overflow: TextOverflow.ellipsis)),
                  IconButton(
                      tooltip: '重试音频',
                      icon: const Icon(Icons.refresh),
                      onPressed: () {
                        _dismissed = null;
                        _audio.retry();
                      }),
                  IconButton(
                      tooltip: '关闭提示',
                      icon: const Icon(Icons.close),
                      onPressed: () => setState(() => _dismissed = error)),
                ]),
              ))));
        },
      );
}
