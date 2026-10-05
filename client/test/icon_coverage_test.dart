import 'package:flutter_test/flutter_test.dart';
import 'package:seven_double_client/src/picks.dart';

void main() {
  test('行动选项能通过 participant_id 关联到席位与角色', () {
    final seats = <Map<String, dynamic>>[
      {
        'id': '1',
        'name': '阿雪',
        'participant_id': 'p1',
        'occupied': true,
        'alive': true,
        'cards': [
          {'id': 'c1', 'role_id': 'emma'},
          {'id': 'c2', 'role_id': 'coco'},
        ],
      },
      {
        'id': '5',
        'name': '庭雨',
        'participant_id': 'p5',
        'occupied': true,
        'alive': false,
        'cards': [
          {'id': 'c9', 'role_id': 'millia'},
        ],
      },
      {
        'id': '4',
        'name': '',
        'participant_id': null,
        'occupied': false,
        'alive': true
      },
    ];
    final players = playersFromOptions(
      [
        {'value': 'p1', 'label': '阿雪（1号）'},
        {'value': 'p5', 'label': '庭雨（5号）'},
        {'value': 's1', 'label': '旁观（观战）'},
      ],
      seats: seats,
    );
    expect(players[0].seatId, '1');
    expect(players[0].roleId, 'emma');
    expect(players[0].dead, isFalse);
    expect(players[1].seatId, '5');
    expect(players[1].roleId, 'millia');
    expect(players[1].dead, isTrue);
    // 观战者不在席位里，保持空角色而不是错配到别的席位。
    expect(players[2].seatId, isNull);
    expect(players[2].roleId, isNull);
  });
}
