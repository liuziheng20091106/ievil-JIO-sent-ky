import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:seven_double_client/src/emoji.dart';
import 'package:seven_double_client/src/emoji_picker.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(recentEmojiIds.clear);

  test('最近只恢复 QQ，清除旧下载表情记录且不再保存下载表情', () async {
    SharedPreferences.setMockInitialValues({
      recentEmojiPreferenceKey: ['14', 'meme:Pack/old.png', '1'],
    });
    final preferences = await SharedPreferences.getInstance();
    loadRecentEmojiIds(preferences);
    await pumpEventQueue();
    expect(preferences.getStringList(recentEmojiPreferenceKey), ['14', '1']);
    rememberRecentEmoji('14');
    rememberRecentEmoji('1');
    rememberRecentEmoji('meme:MahouSyouzyo/1.png');
    rememberRecentEmoji('14');
    await pumpEventQueue();
    recentEmojiIds.clear();
    loadRecentEmojiIds(preferences);
    expect(recentEmojiIds, ['14', '1']);
  });

  test('持久化只保留最近上限，丢弃未知 QQ id 和重复记录', () async {
    SharedPreferences.setMockInitialValues({
      recentEmojiPreferenceKey: ['14', 'unknown', '14', '1'],
    });
    final preferences = await SharedPreferences.getInstance();
    loadRecentEmojiIds(preferences);
    expect(recentEmojiIds, ['14', '1']);
    for (final face in emojiFaces.take(recentEmojiLimit + 4)) {
      rememberRecentEmoji(face.id);
    }
    await pumpEventQueue();
    recentEmojiIds.clear();
    loadRecentEmojiIds(preferences);
    expect(recentEmojiIds.length, recentEmojiLimit);
    expect(recentEmojiIds.first, emojiFaces[recentEmojiLimit + 3].id);
    expect(recentEmojiIds.last, emojiFaces[4].id);
  });

  testWidgets('最近最多三行，上方最近不替代下方完整 QQ 列表', (tester) async {
    recentEmojiIds.addAll(emojiFaces.take(24).map((face) => face.id));
    await tester.pumpWidget(MaterialApp(
        home: Scaffold(
            body: Align(
      alignment: Alignment.topLeft,
      child: SizedBox(
          width: 320,
          child: EmojiPicker(
            height: 600,
            onPick: (_) {},
          )),
    ))));
    await tester.pump();
    final recentCells = find.byWidgetPredicate((widget) =>
        widget is InkWell &&
        widget.key is ValueKey<String> &&
        (widget.key as ValueKey<String>).value.startsWith('recent:'));
    final rowOffsets = recentCells
        .evaluate()
        .map((cell) => tester.getTopLeft(find.byKey(cell.widget.key!)).dy)
        .toSet();
    expect(rowOffsets.length, 3);
    expect(tester.getSize(recentCells.first),
        tester.getSize(find.byKey(ValueKey('all:${emojiFaces.first.id}'))));
    final rows = tester.getTopLeft(recentCells.last).dy -
        tester.getTopLeft(recentCells.first).dy;
    expect(
        rows, closeTo(tester.getSize(recentCells.first).height * 2 + 4, 0.1));
    expect(
        tester
            .getTopLeft(find.byKey(ValueKey('all:${emojiFaces.first.id}')))
            .dy,
        greaterThan(tester.getBottomLeft(recentCells.last).dy));
    expect(find.byKey(ValueKey('recent:${emojiFaces[23].id}')), findsNothing);
  });
}
