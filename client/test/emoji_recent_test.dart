// 表情「最近」分组回归检查：使用记录落盘（跨重启恢复、认不出的 id 丢掉、
// 上限 16 条）、聊天设置「默认打开最近分组」的默认值与持久化，
// 以及面板据此选的初始分组。
//
// 运行方式（client 目录）：flutter test test/emoji_recent_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:seven_double_client/src/emoji.dart';
import 'package:seven_double_client/src/emoji_picker.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/shell.dart';
import 'package:seven_double_client/src/store.dart';

import 'golden_harness.dart';

/// 面板初始分组：选中的分组按钮就是当前分组。
String selectedGroup(WidgetTester tester) {
  final chip = tester
      .widgetList<FilterChip>(find.byType(FilterChip))
      .firstWhere((chip) => chip.selected);
  return (chip.label as Text).data!;
}

Future<void> pumpPanel(WidgetTester tester, {required bool recentFirst}) =>
    tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: EmojiPicker(
            onPick: (_) {},
            recentFirst: recentFirst,
            height: 300,
          ),
        ),
      ),
    );

Future<GameStore> previewStore([Map<String, Object> values = const {}]) async {
  SharedPreferences.setMockInitialValues(values);
  final preferences = await SharedPreferences.getInstance();
  final store = GameStore.forPreview(
    preferences: preferences,
    endpoint: ServerEndpoint.parse('http://127.0.0.1:8000'),
    actor: Actor.fromJson({
      'id': 'p1',
      'account_id': 'a1',
      'kind': 'player',
      'seat_id': '1',
      'name': '一号',
    }),
    view: GameView.fromJson({
      'ui_version': 1,
      'id': 'game-1',
      'version': 1,
      'status': 'playing',
      'day': 1,
      'half': 'day',
      'phase': 'speech',
      'phase_label': '顺序发言',
      'seats': <dynamic>[],
      'self': <String, dynamic>{},
      'actions': <dynamic>[],
      'public': <String, dynamic>{},
      'channels': [
        {
          'id': 'public',
          'label': '公开讨论',
          'status': 'active',
          'can_send': true,
          'reason': '',
          'actions': <dynamic>[],
        },
      ],
    }),
    gameId: 'game-1',
  );
  // 预览用不上服务端：留着会让聊天区真的去连一次网络。
  store.api = null;
  return store;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  // 真实外壳里的分组按钮要按字形宽度排版，先把内置字体装上。
  setUpAll(loadBundledFonts);
  setUp(recentEmojiIds.clear);

  group('使用记录落盘', () {
    test('用过的表情记下来，重新读偏好就能恢复（重启后还在）', () async {
      SharedPreferences.setMockInitialValues({});
      final preferences = await SharedPreferences.getInstance();
      loadRecentEmojiIds(preferences);
      expect(recentEmojiIds, isEmpty);

      // 最近一次在最前，重复使用只置顶不重复。
      rememberRecentEmoji('14');
      rememberRecentEmoji('1');
      rememberRecentEmoji('14');
      expect(recentEmojiIds, ['14', '1']);
      await pumpEventQueue();
      expect(preferences.getStringList('emoji_recent_ids'), ['14', '1']);

      // 模拟重启：内存清空后重新读一次落盘的内容。
      recentEmojiIds.clear();
      loadRecentEmojiIds(preferences);
      expect(recentEmojiIds, ['14', '1']);
    });

    test('超过 16 条只留最近的 16 条', () async {
      SharedPreferences.setMockInitialValues({});
      final preferences = await SharedPreferences.getInstance();
      loadRecentEmojiIds(preferences);

      for (final face in emojiFaces.take(20)) {
        rememberRecentEmoji(face.id);
      }
      expect(recentEmojiIds.length, recentEmojiLimit);
      // 后 16 个：最后用过的排最前。
      expect(recentEmojiIds.first, emojiFaces[19].id);
      expect(recentEmojiIds.last, emojiFaces[4].id);
      await pumpEventQueue();
      expect(preferences.getStringList('emoji_recent_ids')!.length, 16);
    });

    test('表情总表里认不出的旧 id 直接丢掉', () async {
      SharedPreferences.setMockInitialValues({
        'emoji_recent_ids': ['14', 'no-such-face', '1'],
      });
      final preferences = await SharedPreferences.getInstance();
      loadRecentEmojiIds(preferences);
      expect(recentEmojiIds, ['14', '1']);
    });
  });

  group('默认打开最近分组', () {
    test('默认开启，切换立即持久化', () async {
      final store = await previewStore();
      expect(store.emojiRecentFirst, isTrue);
      store.setEmojiRecentFirst(false);
      expect(store.preferences.getBool('chat_emoji_recent_first'), isFalse);
      store.setEmojiRecentFirst(true);
      expect(store.preferences.getBool('chat_emoji_recent_first'), isTrue);
    });

    test('已存的偏好优先于默认值', () async {
      expect((await previewStore({'chat_emoji_recent_first': false}))
          .emojiRecentFirst, isFalse);
      expect((await previewStore({'chat_emoji_recent_first': true}))
          .emojiRecentFirst, isTrue);
    });

    testWidgets('开启且有记录时先显示「最近」', (tester) async {
      recentEmojiIds.addAll(['14', '1']);
      await pumpPanel(tester, recentFirst: true);
      await tester.pump();
      expect(selectedGroup(tester), '最近');
      final cells = find.descendant(
        of: find.byType(GridView),
        matching: find.byType(InkWell),
      );
      expect(cells, findsNWidgets(2), reason: '最近分组里就是用过的那两张');
    });

    testWidgets('关闭时仍从经典开始，最近分组只是排在后面', (tester) async {
      recentEmojiIds.addAll(['14', '1']);
      await pumpPanel(tester, recentFirst: false);
      await tester.pump();
      expect(selectedGroup(tester), '经典');
      expect(find.widgetWithText(FilterChip, '最近'), findsOneWidget);
    });

    testWidgets('开启但没有记录时退回经典，不显示空的最近分组', (tester) async {
      await pumpPanel(tester, recentFirst: true);
      await tester.pump();
      expect(selectedGroup(tester), '经典');
      expect(find.widgetWithText(FilterChip, '最近'), findsNothing);
    });
  });

  // 真实外壳里的接线：聊天输入区的表情面板读的就是 store 里那份本机设置。
  group('聊天输入区的表情面板', () {
    testWidgets('按设置决定打开时的分组', (tester) async {
      recentEmojiIds.addAll(['14', '1']);
      final store = await previewStore();
      await pumpPhone(tester, GameShell(store: store));

      Future<void> togglePanel() async {
        await tester.tap(find.byIcon(Icons.emoji_emotions_outlined));
        await tester.pump(const Duration(milliseconds: 300));
      }

      await togglePanel();
      expect(selectedGroup(tester), '最近', reason: '默认开启：先给最近用过的');

      // 关掉设置后重新打开：从经典开始。
      await togglePanel();
      expect(find.byType(EmojiPicker), findsNothing);
      store.setEmojiRecentFirst(false);
      await tester.pump();
      await togglePanel();
      expect(selectedGroup(tester), '经典');
    });
  });
}
