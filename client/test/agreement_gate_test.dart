// 首次连接服务器时的用户协议门回归检查：
// 展示服务端下发的 Markdown 协议、由用户决定「同意并继续」或「取消连接」，
// 同意记录按「服务地址 + 协议内容哈希」保存，协议改过要重新同意。
//
// 运行方式（client 目录）：flutter test test/agreement_gate_test.dart

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:seven_double_client/main.dart';
import 'package:seven_double_client/src/agreement_gate.dart';
import 'package:seven_double_client/src/design.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/store.dart';
import 'package:shared_preferences/shared_preferences.dart';

const agreementText = '# 用户协议\n\n1. 友善发言\n2. 不泄露他人身份';

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

/// 协议门只拦「登录前」的用户，所以这里造一个还没登录的 store。
Future<GameStore> agreementStore({
  required Agreement agreement,
  String endpoint = 'http://127.0.0.1:8000',
  String? acceptedHash,
}) async {
  SharedPreferences.setMockInitialValues({});
  final preferences = await SharedPreferences.getInstance();
  final parsed = ServerEndpoint.parse(endpoint);
  final store = GameStore.forPreview(
    preferences: preferences,
    endpoint: parsed,
    actor: Actor.fromJson({
      'id': 'p1',
      'account_id': 'a1',
      'kind': 'player',
      'seat_id': '1',
      'name': '阿雪',
    }),
    view: GameView.fromJson(viewJson()),
  );
  store.actor = null;
  store.agreementLoading = false;
  store.agreement = agreement;
  if (acceptedHash != null) {
    await preferences.setString('agreement_accepted:$parsed', acceptedHash);
  }
  return store;
}

Future<void> pumpGate(WidgetTester tester, GameStore store) async {
  await tester.pumpWidget(
    MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: buildAppTheme(),
      // 与 main.dart 一致：store 变化驱动 AppGate 在协议门 / 登录页 / 地址页之间切换。
      home: AnimatedBuilder(
        animation: store,
        builder: (context, _) => AppGate(store: store),
      ),
    ),
  );
  await tester.pump();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('首次连接展示 Markdown 协议，由用户决定是否继续', (tester) async {
    final store = await agreementStore(
      agreement: const Agreement(text: agreementText, hash: 'hash-v1'),
    );
    expect(store.agreementPending, isTrue);

    await pumpGate(tester, store);
    expect(find.byType(AgreementGate), findsOneWidget);
    // 正文按 Markdown 渲染：标题与列表项都在（正文里的「用户协议」标题也算一处）。
    expect(find.text('用户协议'), findsWidgets);
    expect(find.text('同意并继续'), findsOneWidget);
    expect(find.text('取消连接'), findsOneWidget);
    expect(find.textContaining('友善发言'), findsOneWidget);
  });

  testWidgets('同意并继续后进入登录页并记住这一版协议', (tester) async {
    final store = await agreementStore(
      agreement: const Agreement(text: agreementText, hash: 'hash-v1'),
    );
    await pumpGate(tester, store);

    await tester.tap(find.text('同意并继续'));
    await tester.pump();

    expect(store.agreementPending, isFalse);
    expect(
      store.preferences.getString('agreement_accepted:${store.endpoint}'),
      'hash-v1',
    );
    expect(find.byType(AgreementGate), findsNothing);
    expect(find.byType(LoginPage), findsOneWidget);
  });

  testWidgets('取消连接清掉服务地址并回到地址输入页，不写同意记录', (tester) async {
    final store = await agreementStore(
      agreement: const Agreement(text: agreementText, hash: 'hash-v1'),
    );
    await pumpGate(tester, store);

    await tester.tap(find.text('取消连接'));
    await tester.pump();

    expect(store.endpoint, isNull);
    expect(store.preferences.getString('server_endpoint'), isNull);
    expect(find.byType(EndpointPage), findsOneWidget);
    expect(
      store.preferences.getString('agreement_accepted:http://127.0.0.1:8000'),
      isNull,
    );
  });

  testWidgets('协议内容改过（哈希变了）要重新同意', (tester) async {
    final store = await agreementStore(
      agreement: const Agreement(text: agreementText, hash: 'hash-v2'),
      acceptedHash: 'hash-v1',
    );
    expect(store.agreementPending, isTrue);
    await pumpGate(tester, store);
    expect(find.byType(AgreementGate), findsOneWidget);
  });

  testWidgets('同一版协议同意过就不再拦', (tester) async {
    final store = await agreementStore(
      agreement: const Agreement(text: agreementText, hash: 'hash-v1'),
      acceptedHash: 'hash-v1',
    );
    expect(store.agreementPending, isFalse);
    await pumpGate(tester, store);
    expect(find.byType(AgreementGate), findsNothing);
    expect(find.byType(LoginPage), findsOneWidget);
  });

  testWidgets('服务端没配协议时直接进入登录页', (tester) async {
    final store = await agreementStore(agreement: const Agreement());
    expect(store.agreementPending, isFalse);
    await pumpGate(tester, store);
    expect(find.byType(AgreementGate), findsNothing);
    expect(find.byType(LoginPage), findsOneWidget);
  });

  test('协议同意的记忆按服务地址隔离', () async {
    final first = await agreementStore(
      agreement: const Agreement(text: agreementText, hash: 'hash-v1'),
      endpoint: 'http://127.0.0.1:8000',
      acceptedHash: 'hash-v1',
    );
    expect(first.agreementPending, isFalse);
    // 换一个服务地址：同一个协议也要重新同意一次。
    first.endpoint = ServerEndpoint.parse('http://127.0.0.1:9000');
    expect(first.agreementPending, isTrue);
  });
}
