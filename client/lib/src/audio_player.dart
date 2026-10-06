import 'dart:async';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/material.dart';

import 'resource_packs.dart';
import 'store.dart';

/// 根导航器和预览共用本机音频偏好。
class AudioPreferencesScope extends InheritedNotifier<GameStore> {
  const AudioPreferencesScope(
      {super.key, required GameStore store, required super.child})
      : super(notifier: store);

  static GameStore? maybeOf(BuildContext context) => context
      .dependOnInheritedWidgetOfExactType<AudioPreferencesScope>()
      ?.notifier;
}

/// 一路真实本地播放器；串行处理最新控制，不让过期的异步加载恢复声音。
class LocalAudioVoice {
  LocalAudioVoice(String path, {required this.onError}) {
    player.positionUpdater = null;
    _events = player.eventStream.listen((_) {}, onError: (Object error) {
      _fail(error);
    });
    _ready = _prepare(path);
  }

  final AudioPlayer player = AudioPlayer();
  final void Function(Object error) onError;
  late final StreamSubscription<dynamic> _events;
  late final Future<void> _ready;
  bool _disposed = false;
  bool _draining = false;
  Future<void>? _control;
  Future<void>? _closing;

  Future<void> get closed => _closing ?? Future.value();
  int _generation = 0;
  ({Duration Function() position, double rate, bool playing})? _pending;

  Future<void> _prepare(String path) async {
    try {
      // 不申请保活，也不让本应用不同 player 的焦点抢占打断彼此。
      await player.setAudioContext(AudioContext(
          android:
              const AudioContextAndroid(audioFocus: AndroidAudioFocus.none)));
      if (_disposed) return;
      await player.setReleaseMode(ReleaseMode.stop);
      if (_disposed) return;
      // Windows 补丁使 source method 只在原生工作函数返回后完成；
      // prepared/error 事件及其超时本身不能证明原生装载已经退出。
      await player.setSource(DeviceFileSource(path));
    } catch (error) {
      if (!_disposed) _fail(error);
    }
  }

  void update(
      {required Duration Function() position,
      double rate = 1,
      required bool playing}) {
    if (_disposed) return;
    ++_generation;
    _pending = (position: position, rate: rate, playing: playing);
    if (!playing && player.state == PlayerState.playing) {
      unawaited(player.pause().catchError((Object error) {
        if (!_disposed) _fail(error);
      }));
    }
    if (!_draining) _control = _drain();
  }

  Future<void> _drain() async {
    _draining = true;
    try {
      await _ready;
      while (!_disposed && _pending != null) {
        final request = _pending!;
        _pending = null;
        final generation = _generation;
        bool current() => !_disposed && generation == _generation;
        await player.setVolume(0);
        if (!current()) continue;
        await player.pause();
        if (!current()) continue;
        final duration = await player.getDuration();
        if (!current()) continue;
        final position = request.position();
        if (duration != null && position >= duration) continue;
        await player.seek(position);
        if (!current()) continue;
        if (request.playing) {
          await player.resume();
          if (!current()) continue;
          // Android MediaPlayer 的 setPlaybackParams 可启动播放；仅恢复时设倍速。
          await player.setPlaybackRate(request.rate);
          if (!current()) continue;
          await player.setVolume(1);
        }
      }
    } catch (error) {
      if (!_disposed) _fail(error);
    } finally {
      _draining = false;
    }
  }

  void _fail(Object error) {
    if (_disposed) return;
    onError(error);
    dispose();
  }

  void dispose() {
    if (_disposed) return;
    _disposed = true;
    ++_generation;
    _pending = null;
    // 立刻静音并暂停；prepare/控制队列退出后再销毁原生对象。
    _closing = _close();
  }

  Future<void> _close() async {
    try {
      await player.setVolume(0);
      await player.pause();
    } catch (error) {
      onError(error);
    }
    await _ready;
    await _control;
    await _events.cancel();
    try {
      await player.dispose();
    } catch (error) {
      onError(error);
    }
  }
}

/// 音效只跟随自己的动画控制器，和后台音乐使用不同 player。
class AnimationSound {
  AnimationSound(
      {required this.controller, required this.store, required this.onError}) {
    controller.addStatusListener(_statusChanged);
    _gameId = store?.gameId;
    _actorId = store?.actor?.id;
    store?.addListener(_preferencesChanged);
  }

  final AnimationController controller;
  final GameStore? store;
  final void Function(Object error) onError;
  LocalAudioVoice? _voice;
  ResourcePacks? _resources;
  String? _script;
  bool _disposed = false;
  bool _enabled = true;
  int _generation = 0;
  int? _loading;
  String? _gameId;
  String? _actorId;

  void _preferencesChanged() {
    if (_gameId != store?.gameId || _actorId != store?.actor?.id) {
      _gameId = store?.gameId;
      _actorId = store?.actor?.id;
      stop();
      _resources = null;
      _script = null;
      return;
    }
    if (_enabled != (store?.allowAudioEnabled ?? true)) sync();
  }

  Future<void> load(ResourcePacks resources, String script) async {
    _resources = resources;
    _script = script;
    final generation = ++_generation;
    _voice?.dispose();
    _voice = null;
    _enabled = store?.allowAudioEnabled ?? true;
    if (!_enabled || _disposed) return;
    _loading = generation;
    try {
      final path = await resources.animationSoundPath(script);
      if (_disposed || generation != _generation || !_enabled || path == null) {
        return;
      }
      _voice = LocalAudioVoice(path, onError: onError);
      sync();
    } catch (error) {
      if (!_disposed && generation == _generation) onError(error);
    } finally {
      if (_loading == generation) _loading = null;
    }
  }

  void _statusChanged(AnimationStatus status) {
    if (status == AnimationStatus.completed ||
        status == AnimationStatus.dismissed) {
      stop();
    } else {
      sync();
    }
  }

  void sync() {
    if (_disposed) return;
    final enabled = store?.allowAudioEnabled ?? true;
    if (!enabled) {
      _enabled = false;
      stop();
      return;
    }
    if (!_enabled) {
      _enabled = true;
      final resources = _resources;
      final script = _script;
      if (resources != null && script != null && controller.isAnimating) {
        unawaited(load(resources, script));
      }
      return;
    }
    if (_voice == null &&
        _loading == null &&
        controller.isAnimating &&
        _resources != null &&
        _script != null) {
      unawaited(load(_resources!, _script!));
      return;
    }
    _voice?.update(
        position: () => Duration(
            microseconds:
                ((controller.duration?.inMicroseconds ?? 0) * controller.value)
                    .round()),
        playing: controller.isAnimating && !controller.isCompleted);
  }

  void stop() {
    ++_generation;
    _loading = null;
    _voice?.dispose();
    _voice = null;
  }

  void dispose() {
    if (_disposed) return;
    _disposed = true;
    stop();
    controller.removeStatusListener(_statusChanged);
    store?.removeListener(_preferencesChanged);
  }
}
