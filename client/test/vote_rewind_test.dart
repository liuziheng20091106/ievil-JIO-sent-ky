import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:seven_double_client/src/action_sheet.dart';
import 'package:seven_double_client/src/api.dart';
import 'package:seven_double_client/src/design.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/store.dart';
import 'package:shared_preferences/shared_preferences.dart';

ActionDescriptor ballot(List<String> candidates) => ActionDescriptor.fromJson({
      'id': 'vote.cast',
      'ui_version': 1,
      'short_label': 'Vote',
      'label': 'Vote',
      'payload': <String, dynamic>{},
      'fields': [
        for (final name in candidates)
          {
            'name': name,
            'label': name,
            'type': 'select',
            'required': true,
            'seat_id': {'meruru': '6', 'honoka': '2', 'coco': '1', 'hanna': '4'}[name],
            'options': [
              {'value': 'yes', 'label': 'Agree'},
              {'value': 'no', 'label': 'Disagree'},
              {'value': 'abstain', 'label': 'Abstain'},
            ],
          },
      ],
    });

Map<String, dynamic> votingView(ActionDescriptor action) => {
      'ui_version': 1,
      'id': 'rewind-game',
      'version': 12,
      'status': 'playing',
      'day': 1,
      'half': 'day',
      'phase': 'voting',
      'actions': [action.raw],
      'self': {'seat_id': '4'},
    };

Future<GameStore> votingStore(ActionDescriptor action, ServerEndpoint endpoint) async {
  SharedPreferences.setMockInitialValues({});
  return GameStore.forPreview(
    preferences: await SharedPreferences.getInstance(),
    endpoint: endpoint,
    actor: Actor.fromJson({
      'id': 'p4',
      'account_id': 'a4',
      'kind': 'player',
      'game_id': 'rewind-game',
      'seat_id': '4',
      'name': 'Player',
      'access_ids': ['p4'],
    }),
    view: GameView.fromJson(votingView(action)),
    gameId: 'rewind-game',
  );
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('rewound ballot drops removed candidates but preserves remaining choices',
      (tester) async {
    final old = ballot(['meruru', 'honoka', 'coco', 'hanna']);
    final current = ballot(['meruru', 'honoka', 'hanna']);
    final store = await votingStore(old, ServerEndpoint.parse('http://127.0.0.1:1'));
    addTearDown(() => store.api?.close());
    await store.saveDraft(old, {'meruru': 'no', 'honoka': 'yes', 'coco': 'no', 'hanna': 'no'});
    store.view = GameView.fromJson(votingView(current));

    await tester.pumpWidget(MaterialApp(
      theme: buildAppTheme(),
      home: Scaffold(body: ActionFormSheet(store: store, action: current)),
    ));
    await tester.pump();
    expect(find.byIcon(Icons.check_circle), findsNWidgets(3));

    await tester.tap(find.text('Abstain').last);
    await tester.pump();
    expect(store.draftFor(current), {'meruru': 'no', 'honoka': 'yes', 'hanna': 'abstain'});
  });

  test('an open obsolete ballot is rejected without writing votes or losing its draft', () async {
    final old = ballot(['meruru', 'honoka', 'coco', 'hanna']);
    final current = ballot(['meruru', 'honoka', 'hanna']);
    final server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
    var writes = 0;
    final subscription = server.listen((request) async {
      await request.drain<void>();
      request.response.headers.contentType = ContentType.json;
      if (request.method == 'POST') {
        writes++;
        request.response.statusCode = 422;
        request.response.write(jsonEncode({'detail': 'Unexpected obsolete ballot'}));
      } else if (request.uri.path.endsWith('/messages')) {
        request.response.write(jsonEncode({'messages': [], 'has_more': false}));
      } else {
        request.response.write(jsonEncode(votingView(current)));
      }
      await request.response.close();
    });
    addTearDown(() async {
      await subscription.cancel();
      await server.close(force: true);
    });
    final store = await votingStore(old,
        ServerEndpoint.parse('http://127.0.0.1:${server.port}'));
    addTearDown(() => store.api?.close());
    final choices = {'meruru': 'no', 'honoka': 'yes', 'coco': 'no', 'hanna': 'no'};
    await store.saveDraft(old, choices);
    store.view = GameView.fromJson(votingView(current));

    await expectLater(store.execute(old, choices),
        throwsA(isA<ApiException>().having((error) => error.isConflict, 'conflict', isTrue)));
    expect(writes, 0);
    expect(store.draftFor(old), choices);
    expect(store.writeBusy, isFalse);
  });
}
