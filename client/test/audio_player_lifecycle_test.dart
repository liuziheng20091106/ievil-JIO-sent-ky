import 'dart:async';
import 'dart:ui' as ui;

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:seven_double_client/src/audio_player.dart';

/// A controlled platform boundary: preparation can be announced before the
/// source method actually returns, as the Windows native worker does.
class LoadingPlatform {
  final sourceStarted = Completer<void>();
  final sourceReturned = Completer<void>();
  final calls = <String>[];
  String? playerId;
  double volume = 1;
  bool paused = false;
  bool disposed = false;

  final messenger =
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;

  void install() {
    messenger.setMockMethodCallHandler(
        const MethodChannel('xyz.luan/audioplayers.global'), (_) async => null);
    messenger.setMockMethodCallHandler(
        const MethodChannel('xyz.luan/audioplayers.global/events'),
        (_) async => null);
    messenger.setMockMethodCallHandler(
        const MethodChannel('xyz.luan/audioplayers'), _handle);
  }

  Future<Object?> _handle(MethodCall call) async {
    calls.add(call.method);
    final args = call.arguments as Map;
    playerId = args['playerId'] as String;
    switch (call.method) {
      case 'create':
        messenger.setMockMethodCallHandler(
            MethodChannel('xyz.luan/audioplayers/events/$playerId'),
            (_) async => null);
        return null;
      case 'setSourceUrl':
        sourceStarted.complete();
        await sourceReturned.future;
        return null;
      case 'setVolume':
        volume = (args['volume'] as num).toDouble();
        return null;
      case 'pause':
        paused = true;
        return null;
      case 'resume':
        paused = false;
        return null;
      case 'getDuration':
        return 30000;
      case 'getCurrentPosition':
        return 0;
      case 'dispose':
        disposed = true;
        return null;
      default:
        return null;
    }
  }

  Future<void> prepared() async {
    final delivered = Completer<void>();
    ui.channelBuffers.push(
        'xyz.luan/audioplayers/events/$playerId',
        const StandardMethodCodec().encodeSuccessEnvelope({
          'event': 'audio.onPrepared', 'value': true,
        }), (_) => delivered.complete());
    await delivered.future;
  }

  void uninstall() {
    for (final channel in [
      'xyz.luan/audioplayers.global',
      'xyz.luan/audioplayers.global/events',
      'xyz.luan/audioplayers',
      'xyz.luan/audioplayers/events/$playerId',
    ]) {
      messenger.setMockMethodCallHandler(MethodChannel(channel), null);
    }
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('取消装载立刻静音，但 prepared 不能提前触发销毁或恢复播放', () async {
    final platform = LoadingPlatform()..install();
    final errors = <Object>[];
    final voice = LocalAudioVoice('verified-cache-file', onError: errors.add);
    voice.update(position: () => const Duration(seconds: 2), playing: true);
    await platform.sourceStarted.future;
    await platform.prepared();
    voice.dispose();
    // Expose the async mute/pause calls while the source setup remains pending.
    await Future<void>.delayed(Duration.zero);
    expect(platform.volume, 0);
    expect(platform.paused, isTrue);
    expect(platform.disposed, isFalse);
    expect(platform.calls, isNot(contains('resume')));
    expect(platform.calls, isNot(contains('release')));
    voice.update(position: () => Duration.zero, playing: true);
    platform.sourceReturned.complete();
    await voice.closed;
    expect(platform.disposed, isTrue);
    expect(voice.player.state, PlayerState.disposed);
    expect(platform.calls, isNot(contains('resume')));
    expect(errors, isEmpty);
    platform.uninstall();
  });
}
