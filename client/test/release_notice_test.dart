// 回归检查：版本提示与保活（电池优化）提示的显示边界。
//
// 1. 更新提示出现在「已连上服务器、还没进对局」的所有页面（协议门、登录页、大厅）：
//    版本过旧时用户在登录页第一眼就该看到，而不是等登录进大厅才知道；对局中不显示，
//    那里的横幅会挤占消息与输入区，也不该在牌局中间打断玩家。
// 2. 保活（忽略电池优化）提示只在大厅出现：它针对对局中的后台断连。
// 3. 「知道了 / 忽略」必须真的关得掉：横幅是 AppGate 自己渲染的 Column，不在
//    ScaffoldMessenger 的队列里，早先调用 hideCurrentMaterialBanner 完全没有效果。
// 4. 关闭结果写进 shared_preferences：重启后不重复弹同一条，只有服务端下发更新的
//    latest 标签才重新提示。
//
// 运行方式（client 目录）：flutter test test/release_notice_test.dart

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:seven_double_client/main.dart';
import 'package:seven_double_client/src/design.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/release.dart';
import 'package:seven_double_client/src/store.dart';

const updateNoticeText = '有新版本可用，可直接在应用内更新。';
const mandatoryUpdateText = '当前版本过旧，更新之前无法加入对局；其它功能仍可正常使用。';
const batteryNoticeText = '为避免后台断连，建议允许应用忽略电池优化。';

Map<String, dynamic> viewJson() => {
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
    };

/// [gameId] 为空表示停在大厅；[restoring] 为真时页面停在启动占位页，
/// 用来单独验证横幅本身，不牵扯大厅的轮询与网络请求。
Future<GameStore> previewStore({
  String? gameId,
  bool restoring = false,
  SharedPreferences? preferences,
}) async {
  final store = GameStore.forPreview(
    preferences: preferences ?? await mockPreferences(),
    endpoint: ServerEndpoint.parse('http://127.0.0.1:8000'),
    actor: Actor.fromJson({
      'id': 'p1',
      'account_id': 'a1',
      'kind': 'player',
      'seat_id': '1',
      'name': '阿雪',
    }),
    view: GameView.fromJson(viewJson()),
    gameId: gameId,
  );
  store.restoring = restoring;
  return store;
}

Future<SharedPreferences> mockPreferences() async {
  SharedPreferences.setMockInitialValues({});
  return SharedPreferences.getInstance();
}

/// 登录页：actor 为空，且把协议门放行（forPreview 起过协议刷新，抓取期间会
/// [GameStore.agreementPending] 为真，页面就停在协议门而不是登录页）。
Future<GameStore> previewLoginStore({SharedPreferences? preferences}) async {
  final store = await previewStore(preferences: preferences);
  store.actor = null;
  store.agreementLoading = false;
  return store;
}

Future<void> pumpGate(
  WidgetTester tester, {
  required GameStore store,
  required ReleaseMonitor release,
}) async {
  await tester.pumpWidget(
    MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: buildAppTheme(),
      home: AppGate(store: store, release: release),
    ),
  );
  await tester.pump();
}

/// 关闭提示要等偏好写入完成；重启占位页的转圈动画永不静止，不能用 pumpAndSettle。
Future<void> settleNotice(WidgetTester tester) async {
  await tester.pump();
  await tester.pump(const Duration(milliseconds: 20));
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('更新提示覆盖大厅与登录页，保活提示只在大厅', () {
    test('登录页与大厅都要提示更新，对局中不提示', () async {
      final lobby = await previewStore();
      expect(AppGate.showsUpdateNotices(lobby), isTrue);

      final inGame = await previewStore(gameId: 'game-1');
      expect(AppGate.showsUpdateNotices(inGame), isFalse, reason: '对局中的横幅会挤占消息与输入区');

      final beforeLogin = await previewStore();
      beforeLogin.actor = null;
      expect(AppGate.showsUpdateNotices(beforeLogin), isTrue, reason: '登录页也要提示更新');
    });

    test('保活提示只在大厅：登录页与对局中都不出现', () async {
      expect(AppGate.showsBatteryNotice(await previewStore()), isTrue);
      expect(
        AppGate.showsBatteryNotice(await previewStore(gameId: 'game-1')),
        isFalse,
      );

      final beforeLogin = await previewStore();
      beforeLogin.actor = null;
      expect(AppGate.showsBatteryNotice(beforeLogin), isFalse);
    });

    testWidgets('大厅页面上真的渲染出横幅', (tester) async {
      final preferences = await mockPreferences();
      final store = await previewStore(preferences: preferences);
      final release = ReleaseMonitor(preferences: preferences)
        ..applyVersionTags(latest: '9.9.9', minimum: '1.0.0');

      await pumpGate(tester, store: store, release: release);
      expect(find.byType(LobbyPage), findsOneWidget);
      expect(find.text(updateNoticeText), findsOneWidget);

      // 大厅的定时刷新随页面销毁一起停掉。
      await tester.pumpWidget(const SizedBox());
    });

    testWidgets('登录页上也有更新横幅与「立即更新」，但不带保活横幅', (tester) async {
      final preferences = await mockPreferences();
      final store = await previewLoginStore(preferences: preferences);
      final release = ReleaseMonitor(preferences: preferences)
        ..applyVersionTags(latest: '9.9.9', minimum: '1.0.0');
      // 保活提示本身处于「可见」状态，用来证明确实是页面边界把它挡在登录页之外。
      release.batteryOptimizationIgnored = false;

      await pumpGate(tester, store: store, release: release);
      expect(find.byType(LoginPage), findsOneWidget);
      expect(find.text(updateNoticeText), findsOneWidget);
      expect(find.text('立即更新'), findsOneWidget);
      expect(find.text(batteryNoticeText), findsNothing);
    });

    testWidgets('强制更新时登录页给出「必须更新后才能加入对局」的横幅', (tester) async {
      final preferences = await mockPreferences();
      final store = await previewLoginStore(preferences: preferences);
      final release = ReleaseMonitor(preferences: preferences)
        ..applyVersionTags(latest: '9.9.9', minimum: '9.9.9');

      await pumpGate(tester, store: store, release: release);
      expect(find.byType(LoginPage), findsOneWidget);
      expect(find.text(mandatoryUpdateText), findsOneWidget);
      expect(find.text('立即更新'), findsOneWidget);
    });
  });

  group('版本提示可关闭', () {
    testWidgets('点「知道了」横幅消失，重启后不再提示同一条', (tester) async {
      final preferences = await mockPreferences();
      final store =
          await previewStore(restoring: true, preferences: preferences);
      final release = ReleaseMonitor(preferences: preferences)
        ..applyVersionTags(latest: '9.9.9', minimum: '1.0.0');

      await pumpGate(tester, store: store, release: release);
      expect(find.text(updateNoticeText), findsOneWidget);

      await tester.tap(find.text('知道了'));
      await settleNotice(tester);
      expect(find.text(updateNoticeText), findsNothing);
      expect(preferences.getString(updateNoticeDismissedKey), '9.9.9');

      // 重启：新监控读同一份偏好，同一条提示不再出现。
      final restarted = ReleaseMonitor(preferences: preferences)
        ..applyVersionTags(latest: '9.9.9', minimum: '1.0.0');
      expect(restarted.updateNoticeVisible, isFalse);
      // 服务端下发更新的版本时重新提示。
      restarted.applyVersionTags(latest: '9.9.10', minimum: '1.0.0');
      expect(restarted.updateNoticeVisible, isTrue);
    });

    test('低于 minimum 的强制更新横幅不提供关闭', () async {
      final preferences = await mockPreferences();
      final release =
          ReleaseMonitor(currentVersion: '1.0.5', preferences: preferences)
            ..applyVersionTags(latest: '9.9.9', minimum: '9.9.9');
      expect(release.updateRequired, isTrue);
      expect(release.updateNoticeVisible, isFalse);
    });
  });

  group('电池优化提示可忽略', () {
    testWidgets('点「忽略」后横幅消失并记住', (tester) async {
      final preferences = await mockPreferences();
      final store =
          await previewStore(restoring: true, preferences: preferences);
      final release = ReleaseMonitor(preferences: preferences);
      release.batteryOptimizationIgnored = false;

      await pumpGate(tester, store: store, release: release);
      expect(find.text(batteryNoticeText), findsOneWidget);

      await tester.tap(find.text('忽略'));
      await settleNotice(tester);
      expect(find.text(batteryNoticeText), findsNothing);
      expect(preferences.getBool(batteryNoticeDismissedKey), isTrue);

      // 重启后仍然不提示；系统里重新授权也会让它消失。
      final restarted = ReleaseMonitor(preferences: preferences);
      restarted.batteryOptimizationIgnored = false;
      expect(restarted.batteryNoticeVisible, isFalse);
      restarted.batteryOptimizationIgnored = true;
      expect(restarted.batteryNoticeVisible, isFalse);
    });

    test('未关闭且未授权时保持可见', () async {
      final preferences = await mockPreferences();
      final release = ReleaseMonitor(preferences: preferences);
      release.batteryOptimizationIgnored = false;
      expect(release.batteryNoticeVisible, isTrue);
    });
  });
}
