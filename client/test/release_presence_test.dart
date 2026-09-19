// 版本标签比较（ReleaseMonitor 的发布检查）与断连提醒清理
// （同一参与者的旧「已掉线 / 重新连接」只留最新一条）的回归保护。
import 'package:flutter_test/flutter_test.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/release.dart';
import 'package:seven_double_client/src/store.dart';
import 'package:shared_preferences/shared_preferences.dart';

GameMessage presenceMessage(int id, String name, String suffix) =>
    GameMessage.fromJson({
      'id': id,
      'kind': 'presence',
      'text': '3号玩家【$name】$suffix',
      'channel_id': 'system',
      'created_at': '2026-09-19T10:00:00',
    });

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('版本标签比较', () {
    test('低于最低版本要求强制更新，低于最新只提示可更新', () {
      final monitor = ReleaseMonitor(currentVersion: '1.0.0');
      expect(compareVersionTags('1.0.0', '1.1.0')! < 0, isTrue);
      expect(compareVersionTags('1.0.0', '0.9.9')! > 0, isTrue);
      expect(compareVersionTags('1.0.0', '1.0.0'), 0);
      // 无标签或形状异常都视为「无法判断」，不触发任何提示。
      expect(compareVersionTags('1.0.0', null), isNull);
      expect(compareVersionTags('1.0.0', 'v1'), isNull);
      expect(monitor.updateRequired, isFalse);
      expect(monitor.updateAvailable, isFalse);
    });
  });

  group('断连提醒清理', () {
    test('同一玩家只保留最新一条在场提醒，其他玩家不受影响', () async {
      SharedPreferences.setMockInitialValues({});
      final preferences = await SharedPreferences.getInstance();
      final store = GameStore.forPreview(
        preferences: preferences,
        endpoint: ServerEndpoint.parse('http://127.0.0.1:8000'),
        actor: Actor.fromJson({
          'id': 'p1',
          'kind': 'player',
          'name': '我自己',
          'account_id': 'a1',
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
          'deadline': null,
          'ready_count': 0,
          'actions': <dynamic>[],
          'channels': <dynamic>[],
          'seats': <dynamic>[],
          'self': {
            'cards': <dynamic>[],
            'current_card_id': null,
            'warning_deadline': null,
          },
          'public': <String, dynamic>{},
        }),
      );
      store.mergeMessagesForTest([
        presenceMessage(1, '张三', '已掉线'),
        presenceMessage(2, '李四', '已掉线'),
        presenceMessage(3, '张三', '已连接 / 重新连接'),
        presenceMessage(4, '张三', '已掉线'),
      ]);
      final texts = store.messages.map((item) => item.text).toList();
      expect(texts, hasLength(2));
      expect(texts, contains('3号玩家【李四】已掉线'));
      expect(texts, contains('3号玩家【张三】已掉线'));
      expect(store.messages.map((item) => item.id), containsAll(<int>[2, 4]));
      expect(store.messages.any((item) => item.id == 1 || item.id == 3),
          isFalse);
    });

    test('主持人身份的在场提醒也按同一规则收敛', () {
      expect(GameStore.presenceKeyForTest(
          GameMessage.fromJson({
            'id': 1,
            'kind': 'presence',
            'text': '主持人已掉线',
          })), 'host');
      expect(
          GameStore.presenceKeyForTest(presenceMessage(2, '张三', '已掉线')),
          'named:张三');
    });
  });
}
