import 'package:flutter/material.dart';

import 'src/app_icons.dart';
import 'src/design.dart';
import 'src/picks.dart';
import 'src/role_visuals.dart';
import 'src/shell.dart';
import 'src/store.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final store = await GameStore.create();
  runApp(SevenDoubleApp(store: store));
}

class SevenDoubleApp extends StatelessWidget {
  const SevenDoubleApp({super.key, required this.store});

  final GameStore store;

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: kAppTitle,
        debugShowCheckedModeBanner: false,
        theme: buildAppTheme(),
        home: AnimatedBuilder(
          animation: store,
          builder: (context, _) => AppGate(store: store),
        ),
      );
}

class AppGate extends StatelessWidget {
  const AppGate({super.key, required this.store});

  final GameStore store;

  @override
  Widget build(BuildContext context) {
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
        appBar: AppBar(title: const Text('正在进入对局')),
        body: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (store.error == null) const CircularProgressIndicator(),
              if (store.error != null) ...[
                const Icon(
                  Icons.cloud_off_outlined,
                  size: 40,
                  color: AppColors.textTertiary,
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
                    const Center(child: AppLogo(size: 88, rounded: true)),
                    const SizedBox(height: AppSpacing.xl),
                    const Text(
                      kAppTitle,
                      textAlign: TextAlign.center,
                      style: TextStyle(
                        fontSize: 28,
                        fontWeight: FontWeight.w700,
                        color: AppColors.text,
                      ),
                    ),
                    const SizedBox(height: AppSpacing.sm),
                    const Text(
                      '七人双角色 · 由真人主持人主持的魔女审判',
                      textAlign: TextAlign.center,
                      style: TextStyle(
                          fontSize: 14, color: AppColors.textTertiary),
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

  @override
  Widget build(BuildContext context) {
    final challenge = widget.store.challengeInfo;
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
            icon: const Icon(Icons.dns_outlined),
          ),
        ],
        bottom: TabBar(
          controller: tabs,
          indicatorColor: AppColors.accent,
          labelColor: AppColors.accent,
          unselectedLabelColor: AppColors.textTertiary,
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
                    const AppLogo(size: 88, rounded: true),
                    const SizedBox(height: AppSpacing.xl),
                    Text(
                      challenge == null ? '使用 QQ 群完成身份验证' : '请在指定 QQ 群发送',
                      style: const TextStyle(
                        fontSize: 18,
                        fontWeight: FontWeight.w600,
                        color: AppColors.text,
                      ),
                    ),
                    const SizedBox(height: AppSpacing.md),
                    if (challenge != null)
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 20,
                          vertical: 16,
                        ),
                        decoration: BoxDecoration(
                          color: AppColors.accentSoft,
                          borderRadius: BorderRadius.circular(AppRadius.card),
                        ),
                        child: Column(
                          children: [
                            const Text(
                              '活动登录',
                              style: TextStyle(
                                fontSize: 13,
                                color: AppColors.textSecondary,
                              ),
                            ),
                            const SizedBox(height: AppSpacing.xs),
                            SelectableText(
                              '${challenge['code']}',
                              style: const TextStyle(
                                fontSize: 34,
                                fontWeight: FontWeight.w700,
                                letterSpacing: 6,
                                color: AppColors.accent,
                              ),
                            ),
                          ],
                        ),
                      ),
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
                      const SizedBox(height: AppSpacing.md),
                      Text(
                        widget.store.error!,
                        textAlign: TextAlign.center,
                        style: const TextStyle(
                          color: AppColors.danger,
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
                constraints: const BoxConstraints(maxWidth: 420),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Container(
                      padding: const EdgeInsets.all(AppSpacing.lg),
                      decoration: BoxDecoration(
                        color: AppColors.hostSoft,
                        borderRadius: BorderRadius.circular(AppRadius.card),
                      ),
                      child: const Row(
                        children: [
                          Icon(
                            Icons.workspace_premium_outlined,
                            color: AppColors.host,
                          ),
                          SizedBox(width: AppSpacing.md),
                          Expanded(
                            child: Text(
                              '主持人可以查看本局全部角色与私密信息，请勿共享登录会话。',
                              style: TextStyle(
                                fontSize: 13,
                                color: AppColors.textSecondary,
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
                      const SizedBox(height: AppSpacing.md),
                      Text(
                        widget.store.error!,
                        style: const TextStyle(
                          color: AppColors.danger,
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
                        style: const TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.w600,
                          color: AppColors.text,
                        ),
                      ),
                      Text(
                        store.actor!.isHost ? '主持人' : '已通过 QQ 登录',
                        style: const TextStyle(
                          fontSize: 13,
                          color: AppColors.textTertiary,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
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
                  padding: const EdgeInsets.all(AppSpacing.lg),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          const Icon(
                            Icons.casino_outlined,
                            color: AppColors.accent,
                          ),
                          const SizedBox(width: AppSpacing.sm),
                          const Text(
                            '当前对局',
                            style: TextStyle(
                              fontSize: 17,
                              fontWeight: FontWeight.w600,
                              color: AppColors.text,
                            ),
                          ),
                          const Spacer(),
                          Tag(
                            game.joinOpen ? '已开放加入' : '未开放',
                            color: game.joinOpen
                                ? AppColors.success
                                : AppColors.textSecondary,
                            background: game.joinOpen
                                ? AppColors.successSoft
                                : AppColors.surfaceMuted,
                          ),
                        ],
                      ),
                      const SizedBox(height: AppSpacing.md),
                      Row(
                        children: [
                          const Icon(
                            Icons.event_seat_outlined,
                            size: 16,
                            color: AppColors.textTertiary,
                          ),
                          const SizedBox(width: AppSpacing.xs),
                          Text(
                            '空席 ${game.seatsAvailable} / 7',
                            style: const TextStyle(
                              fontSize: 13,
                              color: AppColors.textSecondary,
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
            if (store.error != null) ...[
              const SizedBox(height: AppSpacing.md),
              Text(
                store.error!,
                style: const TextStyle(color: AppColors.danger, fontSize: 13),
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
        icon: const Icon(
          Icons.auto_stories_outlined,
          color: AppColors.accent,
        ),
        title: const Text('确认魔典并建局'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('本局魔典（${chosen.length} 名）：'),
            const SizedBox(height: AppSpacing.sm),
            Wrap(
              spacing: AppSpacing.sm,
              runSpacing: AppSpacing.sm,
              children: [
                for (final id in chosen)
                  Tag(
                    roleVisual(id)?.name ?? id,
                    color: AppColors.textSecondary,
                    background: AppColors.surfaceMuted,
                  ),
              ],
            ),
            const SizedBox(height: AppSpacing.md),
            const Text(
              '建立七席空局。建局后请点击「开放加入」，玩家才能主动入席。',
              style: TextStyle(fontSize: 13, color: AppColors.textTertiary),
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
