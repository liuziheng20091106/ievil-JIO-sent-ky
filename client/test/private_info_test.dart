import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:seven_double_client/src/models.dart';

import 'skill_broadcast_test.dart' show pumpShell, storeWith, viewJson;

void main() {
  testWidgets('主持人私密情报提示按原参与身份显示接收席位', (tester) async {
    final store = await storeWith([]);
    store.actor = Actor.fromJson({'id': 'host', 'kind': 'host', 'name': '主持人'});
    store.applyView(GameView.fromJson({
      ...viewJson(),
      'host': {
        'participants': [
          {'id': 'old-p2', 'seat_id': '2', 'active': false},
          {'id': 'replacement', 'seat_id': '2', 'active': true},
          {'id': 'p5', 'seat_id': '5', 'active': true},
        ],
      },
    }));
    GameMessage info(int id, List<String> audience) => GameMessage.fromJson({
          'id': id,
          'kind': 'information',
          'channel_id': 'information',
          'text': '私密情报',
          'audience': audience,
        });
    store.mergeMessagesForTest([
      info(1, ['old-p2'])
    ]);
    store.mergeMessagesForTest([
      info(2, ['old-p2', 'p5'])
    ]);
    await pumpShell(tester, store);
    expect(find.text('新的私密信息 · 发给2号、5号玩家'), findsOneWidget);
    expect(find.text('私密信息 · 发给2号玩家'), findsOneWidget);
    expect(find.text('私密信息 · 发给2号、5号玩家'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
