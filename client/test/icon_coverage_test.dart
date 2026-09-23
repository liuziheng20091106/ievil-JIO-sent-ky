import 'package:flutter_test/flutter_test.dart';
import 'package:seven_double_client/src/picks.dart';
import 'package:seven_double_client/src/role_visuals.dart';

/// 后端 actions.py 与 views.py 声明的全部行动 id。
/// 新增行动时必须同时补图标，否则这个检查会失败。
const backendActionIds = <String>[
  'balloon.agree',
  'balloon.choose',
  'balloon.decline',
  'balloon.propose',
  'channel.accept',
  'channel.create',
  'channel.end',
  'channel.reject',
  'day.challenge',
  'day.skill',
  'discussion.request_end',
  'evidence.submit',
  'execution.confirm',
  'execution.shoot',
  'hiro.exit',
  'honoka.disguise',
  'honoka.witness',
  'host.advance',
  'host.auto',
  'host.codex',
  'host.codex_order',
  'host.confirm_winner',
  'host.damage',
  'host.end',
  'host.information',
  'host.madness',
  'host.resolve',
  'host.rewind',
  'host.speech',
  'host.start',
  'host.state',
  'host.surrender',
  'host.warn',
  'host.water',
  'lobby.order',
  'lobby.ready',
  'meruru.revive',
  'night.clear',
  'night.confirm',
  'night.submit',
  'photo.permission',
  'player.profile',
  'player.surrender',
  'room.kick',
  'room.mute',
  'room.open_join',
  'room.replace',
  'speech.done',
  'speech.speak',
  'vote.cast',
  'vote.nominate',
  'vote.pass',
  'water.use',
];

void main() {
  test('每个后端行动都配了图标', () {
    final missing = backendActionIds
        .where((id) => !ActionIcons.covered.contains(id))
        .toList();
    expect(missing, isEmpty, reason: '以下行动缺少图标映射：${missing.join('、')}');
  });

  test('图标映射里没有多余或拼错的行动 id', () {
    final unknown = ActionIcons.covered
        .where((id) => !backendActionIds.contains(id))
        .toList();
    expect(unknown, isEmpty, reason: '以下图标映射不对应任何后端行动：${unknown.join('、')}');
  });

  test('自绘 SVG 与 Material 图标没有重复登记', () {
    final overlap =
        ActionIcons.svg.keys.where(ActionIcons.material.containsKey).toList();
    expect(overlap, isEmpty, reason: '同一行动登记了两种图标：${overlap.join('、')}');
  });

  test('角色视觉表与后端 catalog 的 id 一致', () {
    const backendRoleIds = <String>[
      'emma',
      'hiro',
      'hanna',
      'sherry',
      'meruru',
      'noah',
      'annan',
      'millia',
      'coco',
      'nanoka',
      'arisa',
      'marg',
      'leia',
      'honoka',
    ];
    expect(roleVisuals.map((role) => role.id).toSet(), backendRoleIds.toSet());
    // 只有穗乃香没有立绘。
    final withoutArt = roleVisuals
        .where((role) => !role.hasArt)
        .map((role) => role.id)
        .toList();
    expect(withoutArt, ['honoka']);
  });

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
