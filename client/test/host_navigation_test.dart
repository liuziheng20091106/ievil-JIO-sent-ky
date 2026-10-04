import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:seven_double_client/main.dart';
import 'package:seven_double_client/src/api.dart';
import 'package:seven_double_client/src/design.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/shell.dart';
import 'package:seven_double_client/src/store.dart';

import 'resource_packs_test.dart' show gamePayload;

final host = Actor.fromJson({
  'id': 'host',
  'account_id': 'host-account',
  'kind': 'host',
  'name': '主持人',
  'host_level': 2,
});

class NavigationApi extends GameApi {
  NavigationApi() : super(ServerEndpoint.parse('http://127.0.0.1:19286'));
  Completer<GameView>? pendingState;

  // These checks isolate navigation from the live transport.
  @override
  String? get token => null;
  @override
  set token(String? value) {}

  Map<String, dynamic> get game => {
        'id': 'game-1',
        'status': 'playing',
        'phase': 'speech',
        'join_open': false,
        'player_seats_available': 0,
        'can_join_player': false,
        'can_join_spectator': false,
      };

  @override
  Future<Map<String, dynamic>> me() async =>
      {'actor': host.raw, 'game_id': 'game-1'};

  @override
  Future<Map<String, dynamic>> lobby() async =>
      {'game': game, 'participation': host.raw};

  @override
  Future<Map<String, dynamic>> catalog() async => {};

  @override
  Future<Map<String, dynamic>> online({String? gameId}) async => {};

  @override
  Future<Map<String, dynamic>> references(String gameId) async =>
      {'events': [], 'roles': [], 'skills': []};

  @override
  Future<GameView> state(String gameId) async =>
      pendingState == null ? hostView() : await pendingState!.future;

  @override
  Future<({List<GameMessage> messages, bool hasMore})> messages(
    String gameId, {
    String scope = 'all',
    int? before,
    int? after,
    String? channelId,
    String? asSeat,
  }) async =>
      (messages: <GameMessage>[], hasMore: false);
}

GameView hostView() => GameView.fromJson({
      ...gamePayload('game-1'),
      'status': 'playing',
      'phase': 'speech',
      'phase_label': '顺序发言',
      'host_entry_required': true,
    });

Future<GameStore> navigationStore(NavigationApi api) async {
  SharedPreferences.setMockInitialValues({});
  FlutterSecureStorage.setMockInitialValues({'login_token': 'host-session'});
  final store = GameStore.forPreview(
    preferences: await SharedPreferences.getInstance(),
    endpoint: api.endpoint,
    actor: host,
    gameId: 'game-1',
    view: hostView(),
    lobbyGame: LobbyGame.fromJson(api.game),
  );
  store.api?.close();
  store.api = api;
  store.agreementLoading = false;
  return store;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('进行中的主持人可返回大厅，轮询不会拉回，主持入口仍需管理确认',
      (tester) async {
    await tester.binding.setSurfaceSize(const Size(1280, 900));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final api = NavigationApi();
    final store = await navigationStore(api);
    addTearDown(store.dispose);
    await tester.pumpWidget(MaterialApp(
      theme: buildAppTheme(),
      home: AnimatedBuilder(
        animation: store,
        builder: (context, _) => store.gameId == null
            ? LobbyPage(store: store)
            : GameShell(store: store),
      ),
    ));
    await tester.pumpAndSettle();
    expect(find.byType(HostEntryGate), findsOneWidget);
    expect(find.byType(HostManagementPage), findsNothing);
    store.writeBusy = true;
    await tester.pump();
    await tester.tap(find.widgetWithText(TextButton, '返回大厅'));
    await tester.pumpAndSettle();
    expect(find.byType(LobbyPage), findsOneWidget);
    expect(store.actor?.isHost, isTrue);
    expect(store.view, isNull);
    await store.refreshLobby();
    await tester.pump(const Duration(seconds: 6));
    await tester.pumpAndSettle();
    expect(store.gameId, isNull);
    expect(find.byType(LobbyPage), findsOneWidget);
    expect(find.text('加入游戏'), findsNothing);
    expect(find.text('观战'), findsNothing);
    store.writeBusy = false;
    await tester.pumpWidget(const SizedBox.shrink());
    await tester.pumpWidget(MaterialApp(
      theme: buildAppTheme(),
      home: AnimatedBuilder(
        animation: store,
        builder: (context, _) => store.gameId == null
            ? LobbyPage(store: store)
            : GameShell(store: store),
      ),
    ));
    await tester.pumpAndSettle();
    await tester.tap(find.text('进入主持人视角'));
    await tester.pumpAndSettle();
    expect(store.gameId, 'game-1');
    expect(store.preferences.getString('cached_game_id'), 'game-1');
    expect(find.byType(HostEntryGate), findsOneWidget);
    expect(find.byType(HostManagementPage), findsNothing);
    await tester.tap(find.widgetWithText(OutlinedButton, '返回大厅'));
    await tester.pumpAndSettle();
    expect(find.byType(LobbyPage), findsOneWidget);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  testWidgets('窄屏键盘打开时主持人仍可返回大厅', (tester) async {
    final api = NavigationApi();
    final store = await navigationStore(api);
    addTearDown(store.dispose);
    tester.view.viewInsets = const FakeViewPadding(bottom: 300);
    addTearDown(tester.view.resetViewInsets);
    await tester.pumpWidget(MaterialApp(
      theme: buildAppTheme(),
      home: GameShell(store: store),
    ));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(TextButton, '返回大厅'));
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 300));
    expect(store.gameId, isNull);
    expect(store.actor?.isHost, isTrue);
    await tester.pumpWidget(const SizedBox.shrink());
  });

  test('加载期间返回大厅，晚到的状态不能恢复对局或实时连接', () async {
    final api = NavigationApi()..pendingState = Completer<GameView>();
    final store = await navigationStore(api);
    addTearDown(store.dispose);
    final entering = store.enterGame('game-1');
    await Future<void>.delayed(Duration.zero);
    await store.returnToLobby();
    api.pendingState!.complete(hostView());
    await entering;
    await store.refreshLobby();
    expect(store.gameId, isNull);
    expect(store.view, isNull);
    expect(store.live, isNull);
    expect(store.actor?.isHost, isTrue);
    expect(store.preferences.getString('cached_game_id'), isNull);
  });
}
