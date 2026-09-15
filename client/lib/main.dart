import 'package:flutter/material.dart';

import 'src/shell.dart';
import 'src/store.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final store = await GameStore.create();
  runApp(SevenDoubleApp(store: store));
}

/// 界面统一使用 HarmonyOS Sans SC（简体中文，随包内置）。
const appFontFamily = 'HarmonyOS Sans SC';
const appTitle = '魔法裁判';

class SevenDoubleApp extends StatelessWidget {
  const SevenDoubleApp({super.key, required this.store});

  final GameStore store;

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: appTitle,
        debugShowCheckedModeBanner: false,
        theme: ThemeData(
          fontFamily: appFontFamily,
          colorScheme: ColorScheme.fromSeed(
            seedColor: const Color(0xff6d5dfc),
            brightness: Brightness.light,
          ),
          useMaterial3: true,
          scaffoldBackgroundColor: const Color(0xfff7f6fb),
          inputDecorationTheme: const InputDecorationTheme(border: OutlineInputBorder()),
        ),
        darkTheme: ThemeData(
          fontFamily: appFontFamily,
          colorScheme: ColorScheme.fromSeed(
            seedColor: const Color(0xff9c8cff),
            brightness: Brightness.dark,
          ),
          useMaterial3: true,
        ),
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
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    if (store.endpoint == null) return EndpointPage(store: store);
    if (store.actor == null) return LoginPage(store: store);
    if (store.gameId == null) return LobbyPage(store: store);
    if (store.view == null) {
      return Scaffold(
        appBar: AppBar(title: const Text('正在进入对局')),
        body: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (store.error == null) const CircularProgressIndicator(),
              if (store.error != null) ...[
                Text(store.error!, textAlign: TextAlign.center),
                const SizedBox(height: 12),
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
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 480),
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    Text('连接服务器', style: Theme.of(context).textTheme.headlineMedium),
                    const SizedBox(height: 8),
                    const Text('局域网可使用 HTTP；公网地址必须使用 HTTPS。'),
                    const SizedBox(height: 20),
                    TextField(
                      controller: controller,
                      keyboardType: TextInputType.url,
                      autocorrect: false,
                      decoration: InputDecoration(
                        labelText: '服务根地址',
                        hintText: 'https://game.example.com',
                        errorText: error,
                      ),
                      onSubmitted: (_) => submit(),
                    ),
                    const SizedBox(height: 12),
                    FilledButton(onPressed: submit, child: const Text('继续')),
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
      if (mounted && Navigator.of(context).canPop()) Navigator.pop(context);
    } catch (failure) {
      if (mounted) setState(() => error = failure.toString().replaceFirst('FormatException: ', ''));
    }
  }
}

class LoginPage extends StatefulWidget {
  const LoginPage({super.key, required this.store});
  final GameStore store;

  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage> with SingleTickerProviderStateMixin {
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
        title: const Text(appTitle),
        actions: [
          IconButton(
            tooltip: '更换服务器',
            onPressed: () => Navigator.of(context).push(MaterialPageRoute(
              builder: (_) => EndpointPage(store: widget.store),
            )),
            icon: const Icon(Icons.dns_outlined),
          ),
        ],
        bottom: TabBar(
          controller: tabs,
          tabs: const [Tab(text: '玩家 / 观战'), Tab(text: '主持人')],
        ),
      ),
      body: TabBarView(
        controller: tabs,
        children: [
          Center(
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 520),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.groups_2_outlined, size: 64),
                    const SizedBox(height: 16),
                    Text(
                      challenge == null ? '使用 QQ 群完成身份验证' : '请在指定 QQ 群发送',
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                    const SizedBox(height: 12),
                    if (challenge != null)
                      SelectableText(
                        '活动登录 ${challenge['code']}',
                        style: Theme.of(context).textTheme.headlineMedium,
                      ),
                    const SizedBox(height: 20),
                    FilledButton.icon(
                      onPressed: challenge == null
                          ? () async {
                              try {
                                await widget.store.startPlayerLogin();
                              } catch (_) {}
                            }
                          : null,
                      icon: const Icon(Icons.verified_user_outlined),
                      label: Text(challenge == null ? '获取登录码' : '等待群内验证…'),
                    ),
                    if (widget.store.error != null) ...[
                      const SizedBox(height: 12),
                      Text(widget.store.error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
                    ],
                  ],
                ),
              ),
            ),
          ),
          Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 420),
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    TextField(
                      controller: password,
                      obscureText: true,
                      decoration: const InputDecoration(labelText: '主持人密码'),
                      onSubmitted: (_) => loginHost(),
                    ),
                    const SizedBox(height: 12),
                    FilledButton(
                      onPressed: hostBusy ? null : loginHost,
                      child: Text(hostBusy ? '登录中…' : '登录'),
                    ),
                    if (widget.store.error != null) ...[
                      const SizedBox(height: 12),
                      Text(widget.store.error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
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
    if (password.text.isEmpty) return;
    setState(() => hostBusy = true);
    try {
      await widget.store.hostLogin(password.text);
    } catch (_) {
      // The store exposes the server reason without clearing the password.
    } finally {
      if (mounted) setState(() => hostBusy = false);
    }
  }
}

class LobbyPage extends StatelessWidget {
  const LobbyPage({super.key, required this.store});
  final GameStore store;

  @override
  Widget build(BuildContext context) {
    final game = store.lobbyGame;
    return Scaffold(
      appBar: AppBar(
        title: const Text('对局大厅'),
        actions: [IconButton(onPressed: store.logout, tooltip: '退出登录', icon: const Icon(Icons.logout))],
      ),
      body: RefreshIndicator(
        onRefresh: store.refreshLobby,
        child: ListView(
          padding: const EdgeInsets.all(24),
          children: [
            Text('你好，${store.actor!.name}', style: Theme.of(context).textTheme.headlineSmall),
            const SizedBox(height: 20),
            if (game == null)
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(20),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('当前没有可用对局'),
                      if (store.actor!.isHost) ...[
                        const SizedBox(height: 12),
                        FilledButton(
                          onPressed: store.writeBusy ? null : () => confirmCreate(context),
                          child: const Text('创建对局'),
                        ),
                      ],
                    ],
                  ),
                ),
              )
            else
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(20),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('当前对局', style: Theme.of(context).textTheme.titleLarge),
                      const SizedBox(height: 8),
                      Text('阶段：${game.phase}  ·  空席：${game.seatsAvailable}'),
                      Text(game.joinOpen ? '已开放加入' : '尚未开放加入'),
                      const SizedBox(height: 16),
                      Wrap(
                        spacing: 12,
                        runSpacing: 8,
                        children: [
                          FilledButton(
                            onPressed: game.canJoinPlayer && !store.writeBusy
                                ? () => store.participate('player')
                                : null,
                            child: const Text('加入游戏'),
                          ),
                          OutlinedButton(
                            onPressed: game.canJoinSpectator && !store.writeBusy
                                ? () => store.participate('spectator')
                                : null,
                            child: const Text('观战'),
                          ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
            if (store.error != null) ...[
              const SizedBox(height: 12),
              Text(store.error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
            ],
          ],
        ),
      ),
    );
  }

  Future<void> confirmCreate(BuildContext context) async {
    final confirmed = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (context) => AlertDialog(
        title: const Text('创建新对局'),
        content: const Text('将使用服务器默认魔典创建一局。创建后仍需在管理页明确开放加入。'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context, false), child: const Text('取消')),
          FilledButton(onPressed: () => Navigator.pop(context, true), child: const Text('确认创建')),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await store.createGame();
    } catch (_) {}
  }
}
