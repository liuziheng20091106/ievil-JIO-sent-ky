// 主持人分级与公告的客户端边界：
// 1. 等级解析与入口门控（3 级才有成就管理、4 级才有授权、5 级才有公告）。
// 2. 主持授权接口的路径与请求体。
// 3. 公告：大厅轮询带回来的列表 + 本地按 sha256 记已读，内容一改重新算未读。
// 4. markdown 正文真的被解析渲染，而不是把原始标记当纯文本显示。
//
// 服务端的等级判定与权限矩阵由 checks/test_hosts.py 守着。
//
// 运行方式（client 目录）：flutter test test/host_announcement_test.dart

import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:seven_double_client/src/announcement_pages.dart';
import 'package:seven_double_client/src/api.dart';
import 'package:seven_double_client/src/design.dart';
import 'package:seven_double_client/src/host_pages.dart';
import 'package:seven_double_client/src/models.dart';
import 'package:seven_double_client/src/store.dart';

Map<String, dynamic> announcementJson(
  String id,
  String title, {
  String body = '正文',
  String hash = 'hash-1',
}) =>
    {
      'id': id,
      'title': title,
      'body': body,
      'author_name': '管理员',
      'created_at': '2026-09-24T10:00:00',
      'updated_at': '2026-09-24T10:00:00',
      'hash': hash,
    };

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
      'seat_id': '1',
      'name': '阿雪',
    }),
    view: GameView.fromJson({
      'ui_version': 1,
      'id': 'game-1',
      'version': 1,
      'status': 'playing',
      'day': 1,
      'half': 'day',
      'phase': 'speech',
      'phase_label': '顺序发言',
      'actions': <dynamic>[],
      'channels': <dynamic>[],
      'seats': <dynamic>[],
      'self': <String, dynamic>{},
      'public': <String, dynamic>{},
    }),
  );
  store.gameId = null;
  return store;
}

/// 找出渲染出来的富文本里是否含有某段文字：markdown 渲染后是 RichText 里的 span，
/// 用 find.text 匹配不到。
Finder richTextContaining(String needle) => find.byWidgetPredicate(
      (widget) =>
          widget is RichText && widget.text.toPlainText().contains(needle),
    );

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('主持等级', () {
    test('等级决定客户端显示哪些入口，玩家没有等级', () {
      Actor host(int level) => Actor.fromJson({
            'id': 'host',
            'account_id': 'a1',
            'kind': 'host',
            'name': '主持人',
            'host_level': level,
          });

      expect(host(2).canManageAchievements, isFalse);
      expect(host(3).canManageAchievements, isTrue);
      expect(host(3).canManageHosts, isFalse);
      expect(host(4).canManageHosts, isTrue);
      expect(host(4).isAdmin, isFalse);
      expect(host(5).isAdmin, isTrue);
      expect(host(5).canManageHosts, isTrue);

      final player = Actor.fromJson({
        'id': 'p1',
        'account_id': 'a1',
        'kind': 'player',
        'name': '阿雪',
      });
      expect(player.hostLevel, 0);
      expect(player.isHost, isFalse);
      expect(player.canManageAchievements, isFalse);

      for (var level = 1; level <= 5; level++) {
        expect(hostLevelName(level), contains('$level 级'));
        expect(hostLevelDuty(level), isNotEmpty);
      }
      expect(hostLevelName(0), '未授权');
    });
  });

  group('公告与授权接口', () {
    late HttpServer server;
    late ServerEndpoint endpoint;
    final calls = <String>[];
    final bodies = <String>[];
    HttpOverrides? savedOverrides;
    String announcementBody = '正文';
    String announcementHash = 'hash-1';

    setUp(() async {
      calls.clear();
      bodies.clear();
      announcementBody = '正文';
      announcementHash = 'hash-1';
      // flutter_test 默认把 HttpClient 换成「一律 400」的桩；这一组用真实回环服务器。
      savedOverrides = HttpOverrides.current;
      HttpOverrides.global = null;
      server = await HttpServer.bind(InternetAddress.loopbackIPv4, 0);
      server.listen((request) async {
        final path = request.uri.path;
        calls.add('${request.method} $path');
        final raw = request.method == 'POST'
            ? await utf8.decoder.bind(request).join()
            : '';
        if (raw.isNotEmpty) bodies.add(raw);
        Object payload;
        if (path == '/api/announcements') {
          payload = request.method == 'GET'
              ? {
                  'announcements': [
                    announcementJson('note-1', '维护公告',
                        body: announcementBody, hash: announcementHash),
                  ],
                  'announcements_version': announcementHash,
                }
              : announcementJson('note-1', '维护公告', body: '# 正文');
        } else if (path.startsWith('/api/announcements/')) {
          payload = request.method == 'DELETE'
              ? {'ok': true}
              : announcementJson('note-1', '维护公告', body: '改过的正文');
        } else if (path == '/api/hosts') {
          payload = {
            'hosts': [
              {
                'account_id': 'a1',
                'name': '主持10001',
                'qq_id': '10001',
                'avatar_url': '',
                'level': 5,
                'consumed': false,
                'builtin': true,
                'granted_at': null,
                'granted_by': null,
              },
              {
                'account_id': 'a2',
                'name': '主持10003',
                'qq_id': '10003',
                'avatar_url': '',
                'level': 1,
                'consumed': true,
                'builtin': false,
                'granted_at': '2026-09-24T10:00:00',
                'granted_by': 'a1',
              },
            ],
            'min_level': 1,
            'max_level': 5,
            'grantable': 3,
          };
        } else if (path == '/api/hosts/accounts') {
          payload = {
            'accounts': [
              {
                'account_id': 'a3',
                'name': '主持10004',
                'qq_id': '10004',
                'avatar_url': '',
                'level': 0,
                'consumed': false,
                'builtin': false,
                'granted_at': null,
                'granted_by': null,
              },
            ],
          };
        } else if (path.startsWith('/api/hosts/')) {
          payload = request.method == 'DELETE'
              ? {'ok': true}
              : {
                  'account_id': 'a3',
                  'name': '主持10004',
                  'qq_id': '10004',
                  'avatar_url': '',
                  'level': 2,
                  'consumed': false,
                  'builtin': false,
                  'granted_at': '2026-09-24T10:00:00',
                  'granted_by': 'a1',
                };
        } else if (path.startsWith('/api/native/auth/host/challenges')) {
          payload = path.endsWith('/challenges')
              ? {
                  'id': 'challenge-1',
                  'code': '135790',
                  'status': 'pending',
                  'expires_at': '2026-09-24T10:05:00',
                }
              : {
                  'status': 'completed',
                  'session_token': 'token-host',
                  'session': {
                    'actor': {
                      'id': 'host',
                      'account_id': 'a1',
                      'kind': 'host',
                      'name': '主持人',
                      'host_level': 3,
                    },
                    'game_id': null,
                  },
                };
        } else if (path == '/api/lobby') {
          payload = {
            'game': null,
            'participation': null,
            'invites': <dynamic>[],
            'announcements': [
              announcementJson('note-1', '维护公告',
                  body: announcementBody, hash: announcementHash),
            ],
            'announcements_version': announcementHash,
          };
        } else if (path == '/api/catalog') {
          payload = {'roles': <dynamic>[], 'default_codex': <dynamic>[]};
        } else {
          payload = <String, dynamic>{};
        }
        request.response.statusCode = 200;
        request.response.headers.contentType = ContentType.json;
        request.response.write(jsonEncode(payload));
        await request.response.close();
      });
      endpoint = ServerEndpoint.parse('http://127.0.0.1:${server.port}');
    });

    tearDown(() async {
      await server.close(force: true);
      HttpOverrides.global = savedOverrides;
    });

    test('公告接口的路径与方法', () async {
      final api = GameApi(endpoint, token: 'token-abc');
      final listed = await api.announcements();
      expect(listed.announcements.single.title, '维护公告');
      expect(listed.version, 'hash-1');

      await api.createAnnouncement(title: '维护公告', body: '# 正文');
      await api.updateAnnouncement('note-1', title: '维护公告', body: '改过的正文');
      await api.deleteAnnouncement('note-1');

      expect(calls, contains('GET /api/announcements'));
      expect(calls, contains('POST /api/announcements'));
      expect(calls, contains('POST /api/announcements/note-1'));
      expect(calls, contains('DELETE /api/announcements/note-1'));
      expect(bodies.first, '{"title":"维护公告","body":"# 正文"}');
    });

    test('主持授权接口的路径与请求体', () async {
      final api = GameApi(endpoint, token: 'token-abc');
      final listed = await api.hosts();
      expect(listed.grantable, 3);
      expect(listed.hosts.first.name, '主持10001');
      expect(listed.hosts.first.builtin, isTrue);
      expect(listed.hosts.last.consumed, isTrue);
      expect(listed.hosts.last.effectiveLevel, 0);

      final found = await api.hostAccounts('10004');
      expect(found.single.qqId, '10004');
      expect(found.single.level, 0);

      final granted = await api.authorizeHost('a3', 2);
      expect(granted.level, 2);
      expect(granted.builtin, isFalse);
      await api.revokeHost('a3');

      expect(calls, contains('GET /api/hosts'));
      expect(calls, contains('GET /api/hosts/accounts'));
      expect(calls, contains('POST /api/hosts/a3'));
      expect(calls, contains('DELETE /api/hosts/a3'));
      expect(bodies.last, '{"level":2}');
    });

    test('主持人登录走主持人挑战端点', () async {
      final api = GameApi(endpoint, token: 'token-abc');
      final created = await api.createHostChallenge();
      expect(created['code'], '135790');
      final completed = await api.hostChallenge('challenge-1');
      expect(completed['status'], 'completed');
      expect(
        Actor.fromJson(completed['session']['actor']).hostLevel,
        3,
      );
      expect(
        calls,
        containsAll(<String>[
          'POST /api/native/auth/host/challenges',
          'GET /api/native/auth/host/challenges/challenge-1',
        ]),
      );
    });

    test('大厅轮询带回公告，本地按 sha256 记已读', () async {
      final store = await previewStore();
      store.api = GameApi(endpoint, token: 'token-abc');
      await store.refreshLobby();
      expect(store.announcements.single.title, '维护公告');
      expect(store.announcementsVersion, 'hash-1');
      expect(store.unreadAnnouncements, hasLength(1));

      await store.markAnnouncementRead(store.announcements.single);
      expect(store.unreadAnnouncements, isEmpty);
      // 已读状态存的是内容哈希，不存正文。
      final saved =
          store.preferences.getStringList('announcement_read_hashes') ?? const [];
      expect(saved, ['hash-1']);

      // 公告被改过：哈希变了，重新算未读。
      announcementBody = '改过的正文';
      announcementHash = 'hash-2';
      await store.refreshLobby();
      expect(store.announcements.single.hash, 'hash-2');
      expect(store.unreadAnnouncements, hasLength(1));

      await store.markAllAnnouncementsRead();
      expect(store.unreadAnnouncements, isEmpty);
      expect(
        store.preferences.getStringList('announcement_read_hashes'),
        containsAll(<String>['hash-1', 'hash-2']),
      );
    });
  });

  group('公告 markdown 渲染', () {
    testWidgets('标题、列表与粗体被解析，而不是显示原文标记', (tester) async {
      const markdown = '# 大标题\n\n正文里有**加粗**。\n\n- 第一条\n- 第二条\n';
      await tester.pumpWidget(MaterialApp(
        theme: buildAppTheme(),
        home: Scaffold(
          body: Builder(
            builder: (context) => MarkdownBody(
              data: markdown,
              styleSheet: markdownStyleSheet(context),
            ),
          ),
        ),
      ));
      expect(find.byType(MarkdownBody), findsOneWidget);
      expect(richTextContaining('大标题'), findsWidgets);
      expect(richTextContaining('正文里有'), findsWidgets);
      expect(richTextContaining('第一条'), findsWidgets);
      expect(richTextContaining('第二条'), findsWidgets);
      // 原始标记不该出现在渲染结果里。
      expect(richTextContaining('# 大标题'), findsNothing);
      expect(richTextContaining('**加粗**'), findsNothing);
      expect(richTextContaining('- 第一条'), findsNothing);
    });

    testWidgets('公告页渲染标题、署名与 markdown 正文', (tester) async {
      final store = await previewStore();
      await tester.pumpWidget(MaterialApp(
        theme: buildAppTheme(),
        home: AnnouncementPage(
          store: store,
          announcement: Announcement.fromJson(
            announcementJson('note-1', '维护公告', body: '## 小标题\n\n正文'),
          ),
        ),
      ));
      await tester.pump();
      expect(find.text('维护公告'), findsOneWidget);
      expect(find.textContaining('管理员'), findsOneWidget);
      expect(find.byType(MarkdownBody), findsOneWidget);
    });
  });
}
