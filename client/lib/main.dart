import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'src/agreement_gate.dart';
import 'src/app_icons.dart';
import 'src/achievement_pages.dart';
import 'src/announcement_pages.dart';
import 'src/client_version.dart';
import 'src/design.dart';
import 'src/history_pages.dart';
import 'src/host_pages.dart';
import 'src/models.dart';
import 'src/picks.dart';
import 'src/predictive_sheet.dart';
import 'src/release.dart';
import 'src/role_visuals.dart';
import 'src/shell.dart';
import 'src/store.dart';
import 'src/update_dialog.dart';
import 'src/update_installer.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // 行动弹窗的预测性返回：注册返回手势观察者（Android 14+ 由系统送到这里）。
  PredictiveSheetBack.instance.start();
  final store = await GameStore.create();
  // 「知道了 / 忽略」的记忆写在偏好里，重启后不重复弹同一条提示。
  final release = ReleaseMonitor(preferences: store.preferences);
  // 上一次应用内更新留下的安装包在这里清理（安卓：安装完成或失败后的残留）。
  unawaited(UpdateInstaller.create()
      .then((installer) => installer.cleanupStale(kClientVersion))
      .catchError((Object _) {}));
  // 版本标签与保活白名单是只读探测，失败不阻塞启动；每个服务地址只查一次。
  Object? checked;
  var seenUpdateFlag = store.updateFlag;
  store.addListener(() {
    final endpoint = store.endpoint;
    if (endpoint != null && !identical(endpoint, checked)) {
      checked = endpoint;
      release.check(endpoint);
    }
    // /api/online 回报「有更新」时再请求一次 /api/health 取版本字段与更新详情；
    // 同一服务地址与同一标签 10 分钟内只查一次（见 ReleaseMonitor.checkFromOnline）。
    if (store.updateFlag != seenUpdateFlag) {
      seenUpdateFlag = store.updateFlag;
      if (endpoint != null) release.checkFromOnline(endpoint);
    }
  });
  runApp(SevenDoubleApp(store: store, release: release));
}

class SevenDoubleApp extends StatelessWidget {
  const SevenDoubleApp({super.key, required this.store, required this.release});

  final GameStore store;
  final ReleaseMonitor release;

  @override
  Widget build(BuildContext context) => SheetVsyncHost(
        // SheetVsyncHost 给行动弹窗的控制器提供 vsync；面板控制器必须在路由建立前
        // 创建，所以 vsync 只能从树里的 State 拿（见 src/predictive_sheet.dart）。
        child: MaterialApp(
          title: kAppTitle,
          debugShowCheckedModeBanner: false,
          theme: buildAppTheme(),
          darkTheme: buildAppTheme(Brightness.dark),
          themeMode: ThemeMode.system,
          navigatorObservers: [PredictiveSheetBack.instance.routeObserver],
          home: AnimatedBuilder(
            animation: store,
            builder: (context, _) => AppGate(store: store, release: release),
          ),
        ),
      );
}

class AppGate extends StatelessWidget {
  const AppGate({super.key, required this.store, this.release});

  final GameStore store;
  // 测试与预览不传：没有发布监控时直接渲染页面本身。
  final ReleaseMonitor? release;

  /// 版本与保活提示只在大厅出现：这两种横幅都挂在标题栏之上，对局中会挤占消息
  /// 与输入区（软键盘打开时尤其明显），也不该在牌局中间打断玩家。
  static bool showsNotices(GameStore store) =>
      store.actor != null && store.gameId == null;

  @override
  Widget build(BuildContext context) {
    final page = _page(context);
    final release = this.release;
    if (release == null || !showsNotices(store)) return page;
    return AnimatedBuilder(
      animation: release,
      builder: (context, _) {
        final banners = <Widget>[
          if (release.updateRequired)
            MaterialBanner(
              backgroundColor: context.palette.danger,
              content: Text(
                '当前版本过旧，更新之前无法加入对局；其它功能仍可正常使用。',
                style: TextStyle(color: context.palette.onAccent),
              ),
              actions: [
                TextButton(
                  onPressed: () => showUpdateDialog(
                    context,
                    store: store,
                    release: release,
                  ),
                  child: Text(
                    '立即更新',
                    style: TextStyle(color: context.palette.onAccent),
                  ),
                ),
              ],
            )
          else if (release.updateNoticeVisible)
            MaterialBanner(
              content: const Text('有新版本可用，可直接在应用内更新。'),
              actions: [
                TextButton(
                  onPressed: () => showUpdateDialog(
                    context,
                    store: store,
                    release: release,
                  ),
                  child: const Text('立即更新'),
                ),
                TextButton(
                  // 横幅是页面自己渲染的，不在 ScaffoldMessenger 的队列里，
                  // 必须真的把「已关闭」记下来才会消失；大厅里的更新入口不受影响。
                  onPressed: release.dismissUpdateNotice,
                  child: const Text('知道了'),
                ),
              ],
            ),
          if (release.batteryNoticeVisible)
            MaterialBanner(
              content: const Text('为避免后台断连，建议允许应用忽略电池优化。'),
              actions: [
                TextButton(
                  onPressed: release.requestBatteryWhitelist,
                  child: const Text('去设置'),
                ),
                TextButton(
                  onPressed: release.dismissBatteryNotice,
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
    // 首次连接服务器：协议还没同意之前先过协议门（同意并继续 / 取消连接）。
    if (store.agreementPending) {
      return AgreementGate(store: store);
    }
    if (store.actor == null) {
      return LoginPage(store: store);
    }
    if (store.gameId == null) {
      return LobbyPage(store: store, release: release);
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
  /// 默认预填官方服务地址；玩家可以随意改成别的地址（既不阻止修改，也不自动连接）。
  late final controller = TextEditingController(
    text: widget.store.endpoint?.toString() ?? kDefaultServerEndpoint,
  );
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
                      subtitle: '已默认填好官方地址；局域网可用 HTTP，公网地址必须使用 HTTPS，地址可以自行修改。',
                    ),
                    TextField(
                      controller: controller,
                      keyboardType: TextInputType.url,
                      autocorrect: false,
                      decoration: InputDecoration(
                        labelText: '服务根地址',
                        hintText: kDefaultServerEndpoint,
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

/// 登录：玩家与主持人都是 QQ 群验证码；主持授权与账号绑定，没有密码入口。
class LoginPage extends StatefulWidget {
  const LoginPage({super.key, required this.store});
  final GameStore store;

  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage>
    with SingleTickerProviderStateMixin {
  late final TabController tabs = TabController(length: 2, vsync: this);

  @override
  void dispose() {
    tabs.dispose();
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
                              '主持授权与 QQ 账号绑定：管理员授权后，用同一个群登录码进入主持人端。'
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
                    const SizedBox(height: AppSpacing.xl),
                    Center(child: AppLogo(size: 88, rounded: true)),
                    const SizedBox(height: AppSpacing.lg),
                    Text(
                      challenge == null ? '用 QQ 群完成主持人验证' : '请在指定 QQ 群发送',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.w600,
                        color: context.palette.text,
                      ),
                    ),
                    if (challenge != null) ...[
                       SizedBox(height: AppSpacing.md),
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
                     SizedBox(height: AppSpacing.xl),
                    FilledButton.icon(
                      onPressed: challenge == null
                          ? () async {
                              try {
                                await widget.store.startHostLogin();
                              } catch (_) {
                                // 具体原因由 store.error 呈现（例如没有主持授权）。
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
        ],
      ),
    );
  }
}

/// 大厅：等待开放、加入或观战；主持人可先确认魔典再建局。
class LobbyPage extends StatefulWidget {
  const LobbyPage({super.key, required this.store, this.release});

  final GameStore store;

  /// 发布监控：有更新时在大厅里挂常驻入口（测试与预览可以不传）。
  final ReleaseMonitor? release;

  @override
  State<LobbyPage> createState() => _LobbyPageState();
}

class _LobbyPageState extends State<LobbyPage> {
  List<String>? codex;
  Timer? _ticker;
  bool _ticking = false;

  /// 强制更新时只自动弹一次更新弹窗（弹窗可以关掉，大厅里的入口一直在）。
  bool _mandatoryPrompted = false;

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
    final release = widget.release;
    // 有更新时大厅里要挂常驻入口；发布监控变化（例如 online 回报有更新、
    // 或用户点了「知道了」）都要跟着刷新，因此这里额外监听它。
    if (release == null) return _build(context);
    return AnimatedBuilder(
      animation: release,
      builder: (context, _) => _build(context),
    );
  }

  Widget _build(BuildContext context) {
    final store = widget.store;
    final game = store.lobbyGame;
    // 强制更新：一进大厅就自动弹一次（只在大厅弹，对局中不打扰）。
    // 放在 build 里是因为版本信息可能在进入大厅之后才从 /api/health 回来。
    final release = widget.release;
    if (release != null && release.updateRequired && !_mandatoryPrompted) {
      _mandatoryPrompted = true;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) {
          showUpdateDialog(context, store: store, release: release);
        }
      });
    }
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
                // 大厅里不摆主持人的月代雪立绘：主持人先顶一张随机角色头像，
                // 对局中才固定月代雪（见 RoleAvatar.host）。头像优先用账号的 QQ
                // 头像（服务端随 actor 下发，账号库里就有），取不到时退回中性占位，
                // 不借角色立绘暗示尚未公开的身份。
                RoleAvatar(
                  roleId: store.actor!.isHost ? lobbyAvatarRoleId : null,
                  imageUrl: store.actor!.avatarUrl,
                  size: 48,
                ),
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
                        store.actor!.isHost
                            ? hostLevelName(store.actor!.hostLevel)
                            : '已通过 QQ 登录',
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
            // 更新入口：只要服务端说有新版本就一直在，弹窗关掉也不会消失。
            if (widget.release != null &&
                (widget.release!.updateAvailable ||
                    widget.release!.updateRequired))
              UpdateEntryCard(store: store, release: widget.release!),
            // 公告：大厅轮询顺带更新（见 store.refreshLobby），点开看 markdown 正文。
            AnnouncementSection(store: store),
            // 成就：玩家看自己获得的成就并佩戴；3 级及以上主持才能管理定义与授权。
            if (!store.actor!.isHost || store.actor!.canManageAchievements)
              _LobbyEntry(
                icon: Icons.emoji_events_outlined,
                color: store.actor!.isHost
                    ? context.palette.host
                    : context.palette.accent,
                title: store.actor!.isHost ? '成就管理' : '我的成就',
                subtitle: store.actor!.isHost
                    ? '自定义成就，授权给玩家'
                    : '查看获得的成就并挑一个佩戴',
                onTap: () => Navigator.of(context).push(
                  MaterialPageRoute(
                    builder: (_) => store.actor!.isHost
                        ? AchievementAdminPage(store: store)
                        : MyAchievementsPage(store: store),
                  ),
                ),
              ),
            // 主持授权：4 级起可以授权他人（等级上限由服务端按你的等级给）。
            if (store.actor!.canManageHosts)
              _LobbyEntry(
                icon: Icons.verified_user_outlined,
                color: context.palette.accent,
                title: '主持授权',
                subtitle: '授权或取消 ${hostLevelName(store.actor!.hostLevel)} 的下级主持',
                onTap: () => Navigator.of(context).push(
                  MaterialPageRoute(
                    builder: (_) => HostAuthorizationPage(store: store),
                  ),
                ),
              ),
            // 历史对局：已结束（或被清空）的对局留档在独立库里，跨局保留；任何登录身份可看。
            _LobbyEntry(
              icon: Icons.history_outlined,
              color: context.palette.textSecondary,
              title: '历史对局',
              subtitle: '查看已结束对局的胜负、身份与公开时间线',
              onTap: () => Navigator.of(context).push(
                MaterialPageRoute(
                  builder: (_) => MatchHistoryPage(store: store),
                ),
              ),
            ),
            // 公告管理：只有 5 级（系统管理员）能发布。
            if (store.actor!.isAdmin)
              _LobbyEntry(
                icon: Icons.campaign_outlined,
                color: context.palette.host,
                title: '公告管理',
                subtitle: '发布、编辑与删除全服公告（markdown）',
                onTap: () => Navigator.of(context).push(
                  MaterialPageRoute(
                    builder: (_) => AnnouncementAdminPage(store: store),
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
                        leading: RoleAvatar(
                          roleId: null,
                          size: 40,
                          imageUrl: account.avatarUrl,
                        ),
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

/// 大厅里的功能入口卡片：图标 + 标题 + 一句话说明。
class _LobbyEntry extends StatelessWidget {
  const _LobbyEntry({
    required this.icon,
    required this.color,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  final IconData icon;
  final Color color;
  final String title;
  final String subtitle;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Card(
        child: ListTile(
          contentPadding: EdgeInsets.symmetric(
              horizontal: AppSpacing.lg, vertical: AppSpacing.xs),
          leading: Icon(icon, color: color),
          title: Text(
            title,
            style: TextStyle(
              fontSize: 15,
              fontWeight: FontWeight.w600,
              color: context.palette.text,
            ),
          ),
          subtitle: Text(
            subtitle,
            style:
                TextStyle(fontSize: 12, color: context.palette.textTertiary),
          ),
          trailing: const Icon(Icons.chevron_right),
          onTap: onTap,
        ),
      );
}
