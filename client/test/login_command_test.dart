// 回归检查：登录页的「一键复制」必须把网关认得的那一整句放进剪切板。
//
// 网关只接受 ^\s*活动登录\s+(\d{6})\s*$（gateway/gateway.py 的 LOGIN_PATTERN），
// 所以复制内容必须自带「活动登录 」前缀；只复制六位码会登录失败。
//
// 运行方式（client 目录）：flutter test test/login_command_test.dart

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:seven_double_client/main.dart';
import 'package:seven_double_client/src/design.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/store.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// 与 gateway/gateway.py 的 LOGIN_PATTERN 一致。
final loginPattern = RegExp(r'^\s*活动登录\s+(\d{6})\s*$');

Future<GameStore> loginStore({String code = '123456'}) async {
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
  // 登录页的真实状态：还没有身份，只有一个等待群内验证的挑战码。
  store.actor = null;
  store.challengeInfo = {
    'id': 'challenge-1',
    'status': 'pending',
    'code': code,
    'expires_at': '2030-01-01T00:00:00+00:00',
  };
  return store;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('复制内容就是网关认得的整句登录请求', () {
    expect(loginCommandText('123456'), '活动登录 123456');
    expect(loginPattern.hasMatch(loginCommandText('123456')), isTrue);
    // 只复制六位码网关不认，前缀必须由复制内容自带。
    expect(loginPattern.hasMatch('123456'), isFalse);
  });

  testWidgets('点「一键复制」把整句登录请求写进剪切板', (tester) async {
    final copied = <String?>[];
    final messenger = tester.binding.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(SystemChannels.platform, (call) async {
      if (call.method == 'Clipboard.setData') {
        copied.add((call.arguments as Map)['text'] as String?);
      }
      return null;
    });
    addTearDown(
      () => messenger.setMockMethodCallHandler(SystemChannels.platform, null),
    );

    final store = await loginStore();
    await tester.pumpWidget(
      MaterialApp(
        debugShowCheckedModeBanner: false,
        theme: buildAppTheme(),
        home: LoginPage(store: store),
      ),
    );
    await tester.pumpAndSettle();

    // 按钮本身写清会复制哪一句，玩家不用猜。
    const label = '一键复制「活动登录 123456」';
    expect(find.text(label), findsOneWidget);

    await tester.tap(find.text(label));
    await tester.pumpAndSettle();

    expect(copied, ['活动登录 123456']);
    expect(loginPattern.hasMatch(copied.single!), isTrue);
    expect(find.textContaining('已复制'), findsOneWidget);
  });
}
