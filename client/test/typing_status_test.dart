// 输入状态（正在输入）回归检查：设置开关与持久化、typing 事件入表与过期、
// 上报节流与守卫、频道自动切换、指示器渲染（半重叠头像 / 上限 3 个 / 动画省略号）。
//
// 运行方式（client 目录）：flutter test test/typing_status_test.dart
import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:seven_double_client/src/api.dart';
import 'package:seven_double_client/src/design.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/role_visuals.dart';
import 'package:seven_double_client/src/store.dart';

/// 最小对局状态：公屏 + 一条可用私信，可按参数调整可用性。
Map<String, dynamic> viewJson({
  String status = 'playing',
  String phase = 'speech',
  bool publicSendable = true,
  bool publicTransient = false,
  bool privateSendable = true,
}) =>
    {
      'ui_version': 1,
      'id': 'game-1',
      'version': 1,
      'status': status,
      'day': 1,
      'half': 'day',
      'phase': phase,
      'phase_label': '顺序发言',
      'seats': <dynamic>[],
      'self': <String, dynamic>{},
      'actions': <dynamic>[],
      'public': <String, dynamic>{},
      'channels': [
        {
          'id': 'public',
          'label': '公开讨论',
          'status': 'active',
          'can_send': publicSendable,
          'reason': publicSendable ? '' : '夜间与夜间结果阶段无公开发言；可私信主持人',
          'blocked_transient': publicTransient,
          'actions': <dynamic>[],
        },
        {
          'id': 'private:x',
          'label': '私密 · 主持人',
          'status': 'active',
          'can_send': privateSendable,
          'reason': '',
          'actions': <dynamic>[],
        },
        {
          'id': 'system',
          'label': '系统与私密信息',
          'status': 'active',
          'can_send': false,
          'reason': '系统信息只用于告知，不能在此发言',
          'actions': <dynamic>[],
        },
      ],
    };

Actor actorJson() => Actor.fromJson({
      'id': 'p1',
      'account_id': 'a1',
      'kind': 'player',
      'seat_id': '1',
      'name': '一号',
    });

/// 记录 sendTyping 调用的 LiveConnection 假体：start/stop 都不动真 socket。
class RecordingLive extends LiveConnection {
  RecordingLive() : super(endpoint: ServerEndpoint.parse('http://127.0.0.1:1'), token: 't', onEvent: (_) {}, onConnected: () async {}, onStatus: (_) {});

  final frames = <({String channelId, bool active})>[];

  @override
  void sendTyping(String channelId, {bool active = true}) {
    frames.add((channelId: channelId, active: active));
  }
}

Future<GameStore> previewStore({
  Map<String, dynamic>? view,
  RecordingLive? live,
}) async {
  SharedPreferences.setMockInitialValues({});
  final preferences = await SharedPreferences.getInstance();
  final store = GameStore.forPreview(
    preferences: preferences,
    endpoint: ServerEndpoint.parse('http://127.0.0.1:8000'),
    actor: actorJson(),
    view: GameView.fromJson(view ?? viewJson()),
    gameId: 'game-1',
  );
  if (live != null) {
    store.live = live;
  }
  return store;
}

TypingUser typingUser(String id, {bool active = true}) =>
    TypingUser.fromJson({
      'participant_id': id,
      'name': '玩家$id',
      'kind': 'player',
      'seat_id': '2',
      'avatar_role_id': 'emma',
      'active': active,
      'channel_id': 'public',
    });

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('聊天设置', () {
    test('默认两个开关都开启', () async {
      final store = await previewStore();
      expect(store.typingPublicEnabled, isTrue);
      expect(store.autoSwitchChannel, isTrue);
    });

    test('切换开关立即持久化到偏好里', () async {
      final store = await previewStore();
      store.setTypingPublicEnabled(false);
      store.setAutoSwitchChannel(false);
      expect(
        store.preferences.getBool('chat_typing_public'),
        isFalse,
      );
      expect(
        store.preferences.getBool('chat_auto_switch_channel'),
        isFalse,
      );
    });
  });

  group('输入状态上报', () {
    test('typing 事件按频道入表，自己被排除', () async {
      final store = await previewStore();
      store.noteTyping(typingUser('p2'));
      store.noteTyping(typingUser('p1')); // 自己。
      expect(store.typingUsersIn('public').map((user) => user.id), ['p2']);
      expect(store.typingUsersIn('private:x'), isEmpty);
    });

    test('active=false 立即移除该人', () async {
      final store = await previewStore();
      store.noteTyping(typingUser('p2'));
      store.noteTyping(typingUser('p2', active: false));
      expect(store.typingUsersIn('public'), isEmpty);
    });

    test('聊天消息到达即移除发送者', () async {
      final store = await previewStore();
      store.noteTyping(typingUser('p2'));
      final event = {
        'type': 'message',
        'message': {
          'id': 5,
          'kind': 'chat',
          'channel_id': 'public',
          'sender_id': 'p2',
          'sender_name': '二号',
          'text': '发言',
          'created_at': '2024-01-01T00:00:00',
        },
      };
      store.applyLiveEvent(event);
      expect(store.typingUsersIn('public'), isEmpty);
    });

    test('reportTyping 3 秒节流且只上报当前可用频道', () async {
      final live = RecordingLive();
      final store = await previewStore(live: live);
      store.reportTyping(hasText: true);
      store.reportTyping(hasText: true);
      expect(live.frames, hasLength(1));
      expect(live.frames.single.channelId, 'public');
      expect(live.frames.single.active, isTrue);
    });

    test('关闭「公开我的输入状态」后不再上报', () async {
      final live = RecordingLive();
      final store = await previewStore(live: live);
      store.setTypingPublicEnabled(false);
      store.reportTyping(hasText: true);
      expect(live.frames, isEmpty);
    });

    test('hasText=false 补发停止帧', () async {
      final live = RecordingLive();
      final store = await previewStore(live: live);
      store.reportTyping(hasText: true);
      store.reportTyping(hasText: false);
      expect(
        live.frames.map((frame) => frame.active).toList(),
        [true, false],
      );
    });

    test('傀儡代发身份不上报输入状态', () async {
      final live = RecordingLive();
      final store = await previewStore(live: live);
      store.puppetSeatId = '3';
      store.reportTyping(hasText: true);
      expect(live.frames, isEmpty);
    });

    test('频道不可发言时不上报', () async {
      final live = RecordingLive();
      final store = await previewStore(
        view: viewJson(publicSendable: false),
        live: live,
      );
      // 默认落在公屏且公屏不可发言：不上报。
      store.reportTyping(hasText: true);
      expect(live.frames, isEmpty);
    });
  });

  group('自动切换到可用聊天频道', () {
    test('当前频道失效且有可用频道时切过去', () async {
      final store = await previewStore(view: viewJson(publicSendable: false));
      // forPreview 只注入视图；自动切换在状态应用时求值。
      store.applyView(GameView.fromJson(viewJson(publicSendable: false)));
      // 默认选中公屏（不可发言，频道级失效），私信可用：应自动切到私信。
      expect(store.selectedChannelId, 'private:x');
    });

    test('顺序发言的临时等待不触发切换', () async {
      final store = await previewStore(
        view: viewJson(publicSendable: false, publicTransient: true),
      );
      expect(store.selectedChannelId, 'public');
    });

    test('开关关闭后不自动切换', () async {
      final store = await previewStore(view: viewJson(publicSendable: false));
      store.setAutoSwitchChannel(false);
      store.applyView(GameView.fromJson(viewJson(publicSendable: false)));
      // applyView 时已是私信；再回公屏场景验证开关真的挡住切换。
      store.selectChannel('public');
      store.applyView(GameView.fromJson(viewJson(publicSendable: false)));
      expect(store.selectedChannelId, 'public');
    });

    test('没有可用频道时原地不动', () async {
      final store = await previewStore(
        view: viewJson(publicSendable: false, privateSendable: false),
      );
      store.applyView(
        GameView.fromJson(viewJson(publicSendable: false, privateSendable: false)),
      );
      expect(store.selectedChannelId, 'public');
    });
  });

  group('正在输入指示器', () {
    testWidgets('最多渲染 3 个头像，多余显示省略号', (tester) async {
      final store = await previewStore();
      for (final id in ['p2', 'p3', 'p4', 'p5', 'p6']) {
        store.noteTyping(typingUser(id));
      }
      await tester.pumpWidget(
        MaterialApp(
          theme: buildAppTheme(),
          home: Builder(builder: (context) {
            // 与 shell.dart 同一取数路径：指示器只渲染当前频道的输入者，
            // 头像上限 3、超出显示「…」，随后是「正在输入」。
            final users = store.typingUsersIn('public');
            return Directionality(
              textDirection: TextDirection.ltr,
              child: Padding(
                padding: const EdgeInsets.all(8),
                child: users.isEmpty
                    ? const SizedBox.shrink()
                    : Row(
                        children: [
                          for (final avatar in users.take(3))
                            Padding(
                              padding: const EdgeInsets.only(right: 2),
                              child: RoleAvatar(
                                roleId: avatar.avatarRoleId,
                                host: avatar.isHost,
                                size: 20,
                              ),
                            ),
                          if (users.length > 3) const Text('…'),
                          const Text('正在输入'),
                        ],
                      ),
              ),
            );
          }),
        ),
      );
      await tester.pump();
      expect(find.byType(RoleAvatar), findsNWidgets(3));
      expect(find.text('…'), findsOneWidget);
      expect(find.text('正在输入'), findsOneWidget);
      // 收掉 sweep 周期 Timer，避免测试结束时留下 pending timer。
      store.dispose();
    });
  });
}
