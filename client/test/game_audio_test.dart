import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:seven_double_client/src/game_audio.dart';
import 'package:seven_double_client/src/music_status_card.dart';

Map<String, Object> track(
        {double position = 12,
        double rate = 2,
        bool playing = true,
        int revision = 3,
        String id = 'a'}) =>
    {
      'id': id,
      'song': 'music/theme.mp3',
      'position': position,
      'rate': rate,
      'playing': playing,
      'revision': revision,
    };

void main() {
  testWidgets('重新打开音乐管理沿用接收快照的进度，暂停保持原位', (tester) async {
    var elapsed = const Duration(seconds: 60);
    final audio = {
      'tracks': [track(position: 120, rate: 1)]
    };
    Widget page(Object snapshot) => MaterialApp(
        home: Scaffold(
            body: MusicStatusCard(
                audio: snapshot, allowed: true, elapsed: () => elapsed)));
    await tester.pumpWidget(page(audio));
    expect(find.text('播放中 · 3:00 · 1.0×'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
    elapsed = const Duration(seconds: 70);
    await tester.pumpWidget(page(audio));
    expect(find.text('播放中 · 3:10 · 1.0×'), findsOneWidget);
    await tester.pumpWidget(page({
      'tracks': [track(position: 150, rate: 1, playing: false)]
    }));
    elapsed = const Duration(seconds: 100);
    await tester.pump(const Duration(seconds: 1));
    expect(find.text('已暂停 · 2:30 · 1.0×'), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  test('接收后单调时间补偿加载和静音间隔，暂停进度不前进', () {
    final playing = AudioTrackProjection.fromJson(track());
    expect(playing.positionAfter(const Duration(seconds: 5)),
        const Duration(seconds: 22));
    expect(playing.positionAfter(const Duration(seconds: -2)),
        const Duration(seconds: 12));
    final paused = AudioTrackProjection.fromJson(track(playing: false));
    expect(paused.positionAfter(const Duration(days: 1)),
        const Duration(seconds: 12));
    final limited =
        AudioTrackProjection.fromJson(track(position: 604799, rate: 4));
    expect(limited.positionAfter(const Duration(days: 365)),
        const Duration(seconds: 604800));
  });

  test('普通投影进度更新不被当作重播，控制修订和暂停必须同步', () {
    final original = AudioTrackProjection.fromJson(track());
    final progress = AudioTrackProjection.fromJson(track(position: 30));
    expect(original.sameControl(progress), isTrue);
    expect(
        original.sameControl(AudioTrackProjection.fromJson(track(revision: 4))),
        isFalse);
    expect(
        original
            .sameControl(AudioTrackProjection.fromJson(track(playing: false))),
        isFalse);
    expect(original.sameControl(AudioTrackProjection.fromJson(track(rate: .5))),
        isFalse);
  });

  test('拒绝非有限进度、过大进度、越界倍速和重复轨道ID', () {
    for (final position in [-1.0, 604800.1, double.infinity, double.nan]) {
      expect(() => AudioTrackProjection.fromJson(track(position: position)),
          throwsFormatException);
    }
    for (final rate in [.0, .24, 4.01, double.infinity, double.nan]) {
      expect(() => AudioTrackProjection.fromJson(track(rate: rate)),
          throwsFormatException);
    }
    expect(
        () => AudioSnapshot.fromJson({
              'server_time': double.nan,
              'tracks': [track()],
            }),
        throwsFormatException);
    expect(
        () => AudioSnapshot.fromJson({
              'server_time': 1,
              'tracks': [track(), track()],
            }),
        throwsFormatException);
    final snapshot = AudioSnapshot.fromJson({
      'server_time': 1,
      'tracks': [track(), track(id: 'b')],
    });
    expect(snapshot.tracks.length, 2);
  });
}
