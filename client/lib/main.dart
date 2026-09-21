import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'src/app_icons.dart';
import 'src/design.dart';
import 'src/models.dart';
import 'src/picks.dart';
import 'src/release.dart';
import 'src/role_visuals.dart';
import 'src/shell.dart';
import 'src/store.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final store = await GameStore.create();
  final release = ReleaseMonitor();
  // 版本标签与保活白名单是只读探测，失败不阻塞启动；每个服务地址只查一次。
  Object? checked;
  store.addListener(() {
    final endpoint = store.endpoint;
    if (endpoint != null && !identical(endpoint, checked)) {
      checked = endpoint;
      release.check(endpoint);
    }
  });
  runApp(SevenDoubleApp(store: store, release: release));
}

class SevenDoubleApp extends StatelessWidget {
  const SevenDoubleApp({super.key, required this.store, required this.release});

  final GameStore store;
  final ReleaseMonitor release;

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: kAppTitle,
        debugShowCheckedModeBanner: false,
        theme: buildAppTheme(),
        darkTheme: buildAppTheme(Brightness.dark),
        themeMode: ThemeMode.system,
        home: AnimatedBuilder(
          animation: store,
          builder: (context, _) => AppGate(store: store, release: release),
        ),
      );
}

class AppGate extends StatelessWidget {
  const AppGate({super.key, required this.store, this.release});

  final GameStore store;
  // 测试与预览不传：没有发布监控时直接渲染页面本身。
  final ReleaseMonitor? release;

  @override
  Widget build(BuildContext context) {
    final page = _page(context);
    final release = this.release;
    if (release == null) return page;
    return AnimatedBuilder(
      animation: release,
      builder: (context, _) {
        final banners = <Widget>[
          if (release.updateRequired)
            MaterialBanner(
              backgroundColor: context.palette.danger,
              content: Text(
                '当前版本过旧，必须更新后才能继续使用，请向主持人获取最新安装包。',
                style: TextStyle(color: context.palette.onAccent),
              ),
              actions: const [SizedBox.shrink()],
            )
          else if (release.updateAvailable)
            MaterialBanner(
              content: const Text('有新版本可用，建议向主持人获取最新安装包。'),
              actions: [
                TextButton(
                  onPressed: ScaffoldMessenger.of(context).hideCurrentMaterialBanner,
                  child: const Text('知道了'),
                ),
              ],
            ),
          if (!release.batteryOptimizationIgnored)
            MaterialBanner(
              content: const Text('为避免后台断连，建议允许应用忽略电池优化。'),
              actions: [
                TextButton(
                  onPressed: release.requestBatteryWhitelist,
                  child: const Text('去设置'),
                ),
                TextButton(
                  onPressed: ScaffoldMessenger.of(context).hideCurrentMaterialBanner,
                  child: const Text('忽略'),
                ),
              ],
            ),
        ];
        if (banners.isEmpty) return page;
        return Column(
          children: [
            SafeArea(bottom: false, child: Column(children: banners)),
            Expanded(child: page),
          ],
        );
      },
    );
  }

  Widget _page(BuildContext context) {
    if (store.restoring) {
      return const Scaffold(
        body: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              AppLogo(size: 72, rounded: true),
              SizedBox(height: AppSpacing.lg),
              SizedBox(
                width: 22,
                height: 22,
                child: CircularProgressIndicator(strokeWidth: 2.4),
              ),
            ],
          ),
        ),
      );
    }
    if (store.endpoint == null) {
      return EndpointPage(store: store);
    }
    if (store.actor == null) {
      return LoginPage(store: store);
    }
    if (store.gameId == null) {
      return LobbyPage(store: store);
    }
    if (store.view == null) {
      return Scaffold(
        appBar: AppBar(title:  Text('正在进入对局')),
        body: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (store.error == null)  CircularProgressIndicator(),
              if (store.error != null) ...[
                 Icon(
                  Icons.cloud_off_outlined,
                  size: 40,
                  color: context.palette.textTertiary,
                ),
                const SizedBox(height: AppSpacing.md),
                Text(store.error!, textAlign: TextAlign.center),
                const SizedBox(height: AppSpacing.lg),
                FilledButton(
                  onPressed: () => store.enterGame(store.gameId!),
                  child: const Text('重新连接'),
                ),
                TextButton(onPressed: store.logout, child: const Text('退出登录')),
              ],
            ],
          ),
        ),
      );
    }
    return GameShell(store: store);
  }
}

/// 服务器地址：浅色极简，居中单列。
class EndpointPage extends StatefulWidget {
  const EndpointPage({super.key, required this.store});
  final GameStore store;

  @override
  State<EndpointPage> createState() => _EndpointPageState();
}

class _EndpointPageState extends State<EndpointPage> {
  final controller = TextEditingController();
  String? error;

  @override
  void dispose() {
    controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        body: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(AppSpacing.xl),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 460),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                     Center(child: AppLogo(size: 88, rounded: true)),
                     SizedBox(height: AppSpacing.xl),
                     Text(
                      kAppTitle,
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        fontSize: 28,
                        fontWeight: FontWeight.w700,
                        color: context.palette.text,
                      ),
                    ),
                     SizedBox(height: AppSpacing.sm),
                     Text(
                      '七人双角色 · 由真人主持人主持的魔女审判',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                          fontSize: 14, color: context.palette.textTertiary),
                    ),
                    const SizedBox(height: AppSpacing.xxl),
                    const SectionTitle(
                      '连接服务器',
                      subtitle: '局域网可用 HTTP；公网地址必须使用 HTTPS。',
                    ),
                    TextField(
                      controller: controller,
                      keyboardType: TextInputType.url,
                      autocorrect: false,
                      decoration: InputDecoration(
                        labelText: '服务根地址',
                        hintText: 'https://game.example.com',
                        errorText: error,
                        prefixIcon: const Icon(Icons.dns_outlined, size: 20),
                      ),
                      onSubmitted: (_) => submit(),
                    ),
                    const SizedBox(height: AppSpacing.lg),
                    FilledButton.icon(
                      onPressed: submit,
                      icon: const Icon(Icons.arrow_forward_rounded, size: 18),
                      label: const Text('继续'),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      );

  Future<void> submit() async {
    try {
      await widget.store.setEndpoint(controller.text);
      if (mounted && Navigator.of(context).canPop()) {
        Navigator.pop(context);
      }
    } catch (failure) {
      if (mounted) {
        setState(
          () => error = failure.toString().replaceFirst(
                'FormatException: ',
                '',
              ),
        );
      }
    }
  }
}

/// QQ 登录请求的完整文字。网关只认整句「活动登录 123456」
/// （gateway/gateway.py 的 LOGIN_PATTERN），少一个空格或不带前缀都不算登录。
String loginCommandText(String code) => '活动登录 $code';

/// 登录：QQ 群验证码 / 主持人密码。
class LoginPage extends StatefulWidget {
  const LoginPage({super.key, required this.store});
  final GameStore store;

  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage>
    with SingleTickerProviderStateMixin {
  late final TabController tabs = TabController(length: 2, vsync: this);
  final password = TextEditingController();
  bool hostBusy = false;

  @override
  void dispose() {
    tabs.dispose();
    password.dispose();
    super.dispose();
  }

  /// 一键把整句登录请求放进剪切板：玩家不必自己补「活动登录」前缀，
  /// 也不用手抄六位码，去 QQ 群直接粘贴发送即可。
  Future<void> copyLoginCommand() async {
    final code = '${widget.store.challengeInfo?['code'] ?? ''}';
    if (code.isEmpty) return;
    await Clipboard.setData(ClipboardData(text: loginCommandText(code)));
    if (!mounted) return;
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(
        SnackBar(
          content: Text('已复制「${loginCommandText(code)}」，去指定 QQ 群粘贴发送'),
        ),
      );
  }

  @override
  Widget build(BuildContext context) {
    final challenge = widget.store.challengeInfo;
    final code = '${challenge?['code'] ?? ''}';
    return Scaffold(
      appBar: AppBar(
        title: const Text(kAppTitle),
        actions: [
          IconButton(
            tooltip: '更换服务器',
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(
                builder: (_) => EndpointPage(store: widget.store),
              ),
            ),
            icon:  Icon(Icons.dns_outlined),
          ),
        ],
        bottom: TabBar(
          controller: tabs,
          indicatorColor: context.palette.accent,
          labelColor: context.palette.accent,
          unselectedLabelColor: context.palette.textTertiary,
          tabs: const [Tab(text: '玩家 / 观战'), Tab(text: '主持人')],
        ),
      ),
      body: TabBarView(
        controller: tabs,
        children: [
          Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(AppSpacing.xl),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 460),
                child: Column(
                  children: [
                     AppLogo(size: 88, rounded: true),
                     SizedBox(height: AppSpacing.xl),
                    Text(
                      challenge == null ? '使用 QQ 群完成身份验证' : '请在指定 QQ 群发送',
                      style:  TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.w600,
                        color: context.palette.text,
                      ),
                    ),
                     SizedBox(height: AppSpacing.md),
                    if (challenge != null) ...[
                      Container(
                        padding:  EdgeInsets.symmetric(
                          horizontal: 20,
                          vertical: 16,
                        ),
                        decoration: BoxDecoration(
                          color: context.palette.accentSoft,
                          borderRadius: BorderRadius.circular(AppRadius.card),
                        ),
                        child: Column(
                          children: [
                             Text(
                              '活动登录',
                              style: TextStyle(
                                fontSize: 13,
                                color: context.palette.textSecondary,
                              ),
                            ),
                             SizedBox(height: AppSpacing.xs),
                            SelectableText(
                              code,
                              style:  TextStyle(
                                fontSize: 34,
                                fontWeight: FontWeight.w700,
                                letterSpacing: 6,
                                color: context.palette.accent,
                              ),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(height: AppSpacing.md),
                      OutlinedButton.icon(
                        onPressed: copyLoginCommand,
                        icon: const Icon(Icons.content_copy_rounded, size: 18),
                        label: Text('一键复制「${loginCommandText(code)}」'),
                      ),
                    ],
                    const SizedBox(height: AppSpacing.xl),
                    FilledButton.icon(
                      onPressed: challenge == null
                          ? () async {
                              try {
                                await widget.store.startPlayerLogin();
                              } catch (_) {
                                // 具体原因由 store.error 呈现。
                              }
                            }
                          : null,
                      icon: Icon(
                        challenge == null
                            ? Icons.verified_user_outlined
                            : Icons.hourglass_top_rounded,
                        size: 18,
                      ),
                      label: Text(
                        challenge == null ? '获取登录码' : '等待群内验证…',
                      ),
                    ),
                    if (widget.store.error != null) ...[
                       SizedBox(height: AppSpacing.md),
                      Text(
                        widget.store.error!,
                        textAlign: TextAlign.center,
                        style:  TextStyle(
                          color: context.palette.danger,
                          fontSize: 13,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ),
          Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(AppSpacing.xl),
              child: ConstrainedBox(
                constraints:  BoxConstraints(maxWidth: 420),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Container(
                      padding:  EdgeInsets.all(AppSpacing.lg),
                      decoration: BoxDecoration(
                        color: context.palette.hostSoft,
                        borderRadius: BorderRadius.circular(AppRadius.card),
                      ),
                      child:  Row(
                        children: [
                          Icon(
                            Icons.workspace_premium_outlined,
                            color: context.palette.host,
                          ),
                          SizedBox(width: AppSpacing.md),
                          Expanded(
                            child: Text(
                              '主持人可以查看本局全部角色与私密信息，请勿共享登录会话。',
                              style: TextStyle(
                                fontSize: 13,
                                color: context.palette.textSecondary,
                                height: 1.5,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: AppSpacing.lg),
                    TextField(
                      controller: password,
                      obscureText: true,
                      decoration: const InputDecoration(
                        labelText: '主持人密码',
                        prefixIcon: Icon(Icons.lock_outline, size: 20),
                      ),
                      onSubmitted: (_) => loginHost(),
                    ),
                    const SizedBox(height: AppSpacing.lg),
                    FilledButton(
                      onPressed: hostBusy ? null : loginHost,
                      child: Text(hostBusy ? '登录中…' : '进入主持人工作台'),
                    ),
                    if (widget.store.error != null) ...[
                       SizedBox(height: AppSpacing.md),
                      Text(
                        widget.store.error!,
                        style:  TextStyle(
                          color: context.palette.danger,
                          fontSize: 13,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Future<void> loginHost() async {
    if (password.text.isEmpty) {
      return;
    }
    setState(() => hostBusy = true);
    try {
      await widget.store.hostLogin(password.text);
    } catch (_) {
      // 服务端原因由 store.error 暴露，密码输入保留。
    } finally {
      if (mounted) {
        setState(() => hostBusy = false);
      }
    }
  }
}

/// 大厅：等待开放、加入或观战；主持人可先确认魔典再建局。
class LobbyPage extends StatefulWidget {
  const LobbyPage({super.key, required this.store});
  final GameStore store;

  @override
  State<LobbyPage> createState() => _LobbyPageState();
}

class _LobbyPageState extends State<LobbyPage> {
  List<String>? codex;
  Timer? _ticker;
  bool _ticking = false;

  @override
  void initState() {
    super.initState();
    // 大厅没有 WebSocket：定时刷新既是自己的在线心跳，也用来收邀请。
    _ticker = Timer.periodic(const Duration(seconds: 5), (_) => _tick());
    _tick();
  }

  @override
  void dispose() {
    _ticker?.cancel();
    super.dispose();
  }

  Future<void> _tick() async {
    final store = widget.store;
    // 单次请求最长 25 秒：慢响应时跳过这一拍，避免轮询叠加。
    if (!mounted || _ticking || store.writeBusy) return;
    _ticking = true;
    try {
      await store.refreshLobby();
      if (mounted) await store.loadOnline();
    } finally {
      _ticking = false;
    }
  }

  List<OnlineAccount> _others(GameStore store) => store.online
      .where((account) => account.id != store.actor?.accountId)
      .toList(growable: false);

  Future<void> _accept(LobbyInvite invite) async {
    try {
      await widget.store.acceptInvite(invite.id);
    } on ApiException catch (failure) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(failure.message)));
      }
    } on FormatException catch (failure) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(failure.message)));
      }
    }
  }

  Future<void> _reject(LobbyInvite invite) async {
    try {
      await widget.store.rejectInvite(invite.id);
    } on ApiException catch (failure) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(failure.message)));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final store = widget.store;
    final game = store.lobbyGame;
    return Scaffold(
      appBar: AppBar(
        title: const Text('大厅'),
        actions: [
          IconButton(
            onPressed: store.logout,
            tooltip: '退出登录',
            icon: const Icon(Icons.logout),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: store.refreshLobby,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(
            AppSpacing.lg,
            AppSpacing.sm,
            AppSpacing.lg,
            AppSpacing.xxl,
          ),
          children: [
            Row(
              children: [
                // 主持人就是月代雪，直接用应用标志那张立绘。
                store.actor!.isHost
                    ? const AppLogo(size: 48)
                    : const RoleAvatar(roleId: null, size: 48),
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        store.actor!.name,
                        style:  TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.w600,
                          color: context.palette.text,
                        ),
                      ),
                      Text(
                        store.actor!.isHost ? '主持人' : '已通过 QQ 登录',
                        style:  TextStyle(
                          fontSize: 13,
                          color: context.palette.textTertiary,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
            if (store.invites.isNotEmpty) ...[
              const SectionTitle(
                '收到的邀请',
                subtitle: '接受后按服务器规则占席；主持人开放加入后才能入席。',
              ),
              for (final invite in store.invites)
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(AppSpacing.lg),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '${invite.fromName} 邀请你加入当前对局',
                          style:  TextStyle(
                            fontSize: 15,
                            fontWeight: FontWeight.w600,
                            color: context.palette.text,
                          ),
                        ),
                         SizedBox(height: AppSpacing.sm),
                        Text(
                          '空席 ${invite.game?.seatsAvailable ?? 0} / 7'
                          '${invite.game?.joinOpen == true ? '' : ' · 等待主持人开放加入'}',
                          style:  TextStyle(
                              fontSize: 13, color: context.palette.textTertiary),
                        ),
                        const SizedBox(height: AppSpacing.md),
                        Row(
                          children: [
                            Expanded(
                              child: FilledButton(
                                onPressed: store.writeBusy ||
                                        invite.game?.canJoinPlayer != true
                                    ? null
                                    : () => _accept(invite),
                                child: const Text('接受邀请'),
                              ),
                            ),
                            const SizedBox(width: AppSpacing.md),
                            Expanded(
                              child: OutlinedButton(
                                onPressed: store.writeBusy
                                    ? null
                                    : () => _reject(invite),
                                child: const Text('拒绝'),
                              ),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ),
            ],
            if (game == null)
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(AppSpacing.lg),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const EmptyState(
                        icon: Icons.meeting_room_outlined,
                        title: '当前没有开放的对局',
                        detail: '主持人宣布对局可用后，这里会出现加入与观战入口。',
                      ),
                      if (store.actor!.isHost) ...[
                        const SizedBox(height: AppSpacing.lg),
                        FilledButton.icon(
                          onPressed:
                              store.writeBusy ? null : pickCodexThenCreate,
                          icon: const Icon(
                            Icons.auto_stories_outlined,
                            size: 18,
                          ),
                          label: const Text('创建对局'),
                        ),
                      ],
                    ],
                  ),
                ),
              )
            else
              Card(
                child: Padding(
                  padding:  EdgeInsets.all(AppSpacing.lg),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                           Icon(
                            Icons.casino_outlined,
                            color: context.palette.accent,
                          ),
                           SizedBox(width: AppSpacing.sm),
                           Text(
                            '当前对局',
                            style: TextStyle(
                              fontSize: 17,
                              fontWeight: FontWeight.w600,
                              color: context.palette.text,
                            ),
                          ),
                           Spacer(),
                          Tag(
                            game.joinOpen ? '已开放加入' : '未开放',
                            color: game.joinOpen
                                ? context.palette.success
                                : context.palette.textSecondary,
                            background: game.joinOpen
                                ? context.palette.successSoft
                                : context.palette.surfaceMuted,
                          ),
                        ],
                      ),
                       SizedBox(height: AppSpacing.md),
                      Row(
                        children: [
                           Icon(
                            Icons.event_seat_outlined,
                            size: 16,
                            color: context.palette.textTertiary,
                          ),
                           SizedBox(width: AppSpacing.xs),
                          Text(
                            '空席 ${game.seatsAvailable} / 7',
                            style:  TextStyle(
                              fontSize: 13,
                              color: context.palette.textSecondary,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: AppSpacing.lg),
                      Row(
                        children: [
                          Expanded(
                            child: FilledButton.icon(
                              onPressed: game.canJoinPlayer && !store.writeBusy
                                  ? () => store.participate('player')
                                  : null,
                              icon: const Icon(Icons.login_rounded, size: 18),
                              label: const Text('加入游戏'),
                            ),
                          ),
                          const SizedBox(width: AppSpacing.md),
                          Expanded(
                            child: OutlinedButton.icon(
                              onPressed:
                                  game.canJoinSpectator && !store.writeBusy
                                      ? () => store.participate('spectator')
                                      : null,
                              icon: const Icon(
                                Icons.visibility_outlined,
                                size: 18,
                              ),
                              label: const Text('观战'),
                            ),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
            const SectionTitle('在线玩家', subtitle: '最近一分钟内有活动的已登录账号。'),
            Card(
              child: Padding(
                padding: const EdgeInsets.all(AppSpacing.md),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    if (_others(store).isEmpty)
                       Padding(
                        padding: EdgeInsets.all(AppSpacing.sm),
                        child: Text(
                          '当前没有其他人在线。',
                          style: TextStyle(
                              fontSize: 13, color: context.palette.textTertiary),
                        ),
                      ),
                    for (final account in _others(store))
                      ListTile(
                        leading: const RoleAvatar(roleId: null, size: 40),
                        title: Text(account.name),
                        trailing:  Tag('在线', icon: Icons.wifi_tethering),
                      ),
                  ],
                ),
              ),
            ),
            if (store.error != null) ...[
               SizedBox(height: AppSpacing.md),
              Text(
                store.error!,
                style:  TextStyle(color: context.palette.danger, fontSize: 13),
              ),
            ],
          ],
        ),
      ),
    );
  }

  /// 建局前必须确认 11 名魔典角色。
  Future<void> pickCodexThenCreate() async {
    final store = widget.store;
    final initial = codex ?? await _defaultCodex(store);
    if (!mounted) {
      return;
    }
    final chosen = await showCodexPicker(
      context,
      initial: initial,
      requiredCount: 11,
    );
    if (chosen == null || !mounted) {
      return;
    }
    setState(() => codex = chosen);
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        icon:  Icon(
          Icons.auto_stories_outlined,
          color: context.palette.accent,
        ),
        title: const Text('确认魔典并建局'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('本局魔典（${chosen.length} 名）：'),
             SizedBox(height: AppSpacing.sm),
            Wrap(
              spacing: AppSpacing.sm,
              runSpacing: AppSpacing.sm,
              children: [
                for (final id in chosen)
                  Tag(
                    roleVisual(id)?.name ?? id,
                    color: context.palette.textSecondary,
                    background: context.palette.surfaceMuted,
                  ),
              ],
            ),
             SizedBox(height: AppSpacing.md),
             Text(
              '建立七席空局。建局后请点击「开放加入」，玩家才能主动入席。',
              style: TextStyle(fontSize: 13, color: context.palette.textTertiary),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('返回修改'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('确认建局'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) {
      return;
    }
    try {
      await store.createGame(chosen);
    } catch (_) {
      // 失败原因由 store.error 呈现。
    }
  }

  Future<List<String>> _defaultCodex(GameStore store) async {
    try {
      final catalog = await store.api!.catalog();
      final value = catalog['default_codex'];
      if (value is List) {
        return value.map((item) => item.toString()).toList();
      }
    } catch (_) {
      // 取不到默认名单时留空，由主持人自行选择 11 名。
    }
    return const [];
  }
}
