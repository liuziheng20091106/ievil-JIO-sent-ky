// 服务地址默认值回归检查：默认预填官方地址，但玩家可以随意修改
// （既不阻止修改，也不自动连接）。
//
// 运行方式（client 目录）：flutter test test/endpoint_default_test.dart

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:seven_double_client/main.dart';
import 'package:seven_double_client/src/client_version.dart';
import 'package:seven_double_client/src/design.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/store.dart';
import 'package:shared_preferences/shared_preferences.dart';

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

Future<GameStore> storeWithoutEndpoint() async {
  SharedPreferences.setMockInitialValues({});
  final preferences = await SharedPreferences.getInstance();
  final store = GameStore.forPreview(
    preferences: preferences,
    endpoint: ServerEndpoint.parse('http://127.0.0.1:8000'),
    actor: Actor.fromJson({
      'id': 'p1',
      'account_id': 'a1',
      'kind': 'player',
      'seat_id': '1',
      'name': '阿雪',
    }),
    view: GameView.fromJson(viewJson()),
  );
  store.endpoint = null;
  store.api = null;
  store.actor = null;
  store.agreementLoading = false;
  return store;
}

Future<void> pumpEndpoint(WidgetTester tester, GameStore store) async {
  await tester.pumpWidget(
    MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: buildAppTheme(),
      home: EndpointPage(store: store),
    ),
  );
  await tester.pump();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('默认地址指向官方服务端', () {
    expect(kDefaultServerEndpoint, 'https://super.tkcloud.online:447');
    // 默认值必须是能通过地址校验的合法地址。
    expect(ServerEndpoint.parse(kDefaultServerEndpoint).toString(),
        kDefaultServerEndpoint);
  });

  testWidgets('首次进入时预填默认地址', (tester) async {
    final store = await storeWithoutEndpoint();
    await pumpEndpoint(tester, store);

    final field = tester.widget<TextField>(find.byType(TextField));
    expect(field.controller!.text, kDefaultServerEndpoint);
  });

  testWidgets('玩家可以改成自己的地址，不被默认值挡住', (tester) async {
    final store = await storeWithoutEndpoint();
    await pumpEndpoint(tester, store);

    await tester.enterText(find.byType(TextField), 'http://192.168.0.5:8000');
    await tester.pump();
    final field = tester.widget<TextField>(find.byType(TextField));
    expect(field.controller!.text, 'http://192.168.0.5:8000');
  });

  testWidgets('已经设过地址时预填已保存的地址', (tester) async {
    final store = await storeWithoutEndpoint();
    store.endpoint = ServerEndpoint.parse('http://10.0.0.9:8000');
    await pumpEndpoint(tester, store);

    final field = tester.widget<TextField>(find.byType(TextField));
    expect(field.controller!.text, 'http://10.0.0.9:8000');
  });
}
