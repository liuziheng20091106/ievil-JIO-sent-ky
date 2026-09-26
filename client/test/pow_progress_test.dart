// 回归检查：登录挑战在算工作量证明时，登录页必须给出真实的计算进度动画。
//
// 关键边界：
// 1. 服务端没开 PoW（powSolving=false）时不能出现进度卡片，否则每次登录都闪一下；
// 2. 计算中按钮必须禁用，避免连点开出多个求解 isolate；
// 3. 算完拿到登录码后，进度卡片要让位给六位码 —— 六位码是玩家下一步唯一要做的事；
// 4. 进度里的尝试次数是真实计数（不是估算百分比）。
//
// 运行方式（client 目录）：flutter test test/pow_progress_test.dart

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:seven_double_client/main.dart';
import 'package:seven_double_client/src/design.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/pow_progress.dart';
import 'package:seven_double_client/src/store.dart';
import 'package:shared_preferences/shared_preferences.dart';

Future<GameStore> previewStore() async {
  SharedPreferences.setMockInitialValues({});
  final preferences = await SharedPreferences.getInstance();
  final store = GameStore.forPreview(
    preferences: preferences,
    endpoint: ServerEndpoint.parse('http://127.0.0.1:8000'),
    actor: Actor.fromJson({
      'id': 'p1',
      'account_id': 'a1',
      'kind': 'player',
      'game_id': null,
      'seat_id': null,
      'name': '阿雪',
      'qq_id': '10001',
      'avatar_url': null,
      'access_ids': <String>[],
    }),
    view: GameView.fromJson({'ui_version': 1}),
  );
  // 登录页的真实状态：还没有身份，也没有登录码。
  store.actor = null;
  store.challengeInfo = null;
  return store;
}

Future<void> pumpLogin(WidgetTester tester, GameStore store) async {
  await tester.pumpWidget(
    MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: buildAppTheme(),
      // 页面本身不自带监听：真实应用由 main.dart 的 AnimatedBuilder 包住，
      // 这里照做，store 变化才能驱动重建。
      home: AnimatedBuilder(
        animation: store,
        builder: (context, _) => LoginPage(store: store),
      ),
    ),
  );
  // 进度环是无限循环动画，不能用 pumpAndSettle（永远不 settle）。
  await tester.pump();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('计算中：显示进度卡片、真实尝试次数与耗时，按钮禁用', (tester) async {
    final store = await previewStore();
    store.powSolving = true;
    store.powDifficulty = 4;
    store.powAttempts = 12345;
    store.powStartedAt = DateTime.now().subtract(const Duration(seconds: 3));

    await pumpLogin(tester, store);

    expect(find.byType(PowProgressPanel), findsOneWidget);
    expect(find.text('工作量证明'), findsOneWidget);
    expect(find.textContaining('已尝试 12,345 次'), findsOneWidget);
    expect(find.textContaining('用时'), findsOneWidget);
    // 还没拿到登录码：标题说明正在验证，而不是继续提示去群里发。
    expect(find.text('正在进行安全验证'), findsOneWidget);

    final button = tester.widget<FilledButton>(find.byType(FilledButton));
    expect(button.onPressed, isNull, reason: '计算期间按钮必须禁用，避免连点开出多个求解 isolate');
    expect(find.text('正在验证，请稍候…'), findsOneWidget);

    // 未取到码就不该出现登录码卡片。
    expect(find.text('活动登录'), findsNothing);

    // 收尾：卸载无限动画，避免测试结束时报 ticker 未释放。
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('尝试次数增长时数字跟着变（不是假的固定文案）', (tester) async {
    final store = await previewStore();
    store.powSolving = true;
    store.powDifficulty = 4;
    store.powAttempts = 1000;
    store.powStartedAt = DateTime.now();

    await pumpLogin(tester, store);
    expect(find.textContaining('已尝试 1,000 次'), findsOneWidget);

    store.powAttempts = 250000;
    store.notifyListeners();
    await tester.pump();
    expect(find.textContaining('已尝试 250,000 次'), findsOneWidget);
    expect(find.textContaining('已尝试 1,000 次'), findsNothing);

    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('算完出码：进度卡片让位给六位登录码与复制按钮', (tester) async {
    final store = await previewStore();
    store.powSolving = true;
    store.powDifficulty = 4;
    store.powAttempts = 33792;
    store.powStartedAt = DateTime.now();
    await pumpLogin(tester, store);
    expect(find.byType(PowProgressPanel), findsOneWidget);

    // 求解成功：store 清掉进度、填上挑战码。
    store.powSolving = false;
    store.powAttempts = 0;
    store.powStartedAt = null;
    store.challengeInfo = {
      'id': 'challenge-1',
      'status': 'pending',
      'code': '654321',
      'expires_at': '2030-01-01T00:00:00+00:00',
    };
    store.notifyListeners();
    // AnimatedSwitcher 的切换动画要跑完才彻底移除旧卡片。
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 400));

    expect(find.byType(PowProgressPanel), findsNothing);
    expect(find.text('654321'), findsOneWidget);
    expect(find.text('一键复制「活动登录 654321」'), findsOneWidget);
    expect(find.text('请在指定 QQ 群发送'), findsOneWidget);

    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('等待跨分钟时耗时显示成「N 分 NN 秒」', (tester) async {
    final store = await previewStore();
    store.powSolving = true;
    store.powDifficulty = 6;
    store.powAttempts = 2600000;
    // 难度调高后等待可能超过一分钟：纯秒数会越来越难读。
    store.powStartedAt = DateTime.now().subtract(const Duration(seconds: 95));

    await pumpLogin(tester, store);
    expect(find.textContaining('已尝试 2,600,000 次'), findsOneWidget);
    expect(find.textContaining('1 分 '), findsOneWidget);

    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('未开启防护：不出现进度卡片，也不闪进度文案', (tester) async {
    final store = await previewStore();
    // powSolving 保持 false —— 服务端 required=false 或旧服务端就是这条路径。
    await pumpLogin(tester, store);

    expect(find.byType(PowProgressPanel), findsNothing);
    expect(find.text('正在进行安全验证'), findsNothing);
    expect(find.text('使用 QQ 群完成身份验证'), findsOneWidget);
    expect(find.text('获取登录码'), findsOneWidget);

    final button = tester.widget<FilledButton>(find.byType(FilledButton));
    expect(button.onPressed, isNotNull);

    await tester.pumpWidget(const SizedBox.shrink());
  });
}
