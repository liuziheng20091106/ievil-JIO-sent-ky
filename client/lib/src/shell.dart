import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'action_sheet.dart';
import 'achievements.dart';
import 'app_icons.dart';
import 'design.dart';
import 'message_time.dart';
import 'models.dart';
import 'participant_menu.dart';
import 'picks.dart';
import 'role_visuals.dart';
import 'store.dart';

class GameShell extends StatefulWidget {
  const GameShell({super.key, required this.store});
  final GameStore store;

  @override
  State<GameShell> createState() => _GameShellState();
}

class _GameShellState extends State<GameShell> with WidgetsBindingObserver {
  final GlobalKey<ScaffoldState> _scaffold = GlobalKey<ScaffoldState>();
  int index = 0;
  int lastActions = 0;
  int lastWarnings = 0;

  /// 已经按当前宽屏档位登记过「已查看」的页面；0 表示窄屏单页布局。
  /// 只在档位变化时登记一次，避免每帧写偏好引起重复重建。
  int viewedTier = 0;
  AppLifecycleState lifecycle = AppLifecycleState.resumed;

  bool get host => widget.store.actor!.isHost;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    lastActions = widget.store.newActionCount;
    lastWarnings = widget.store.warningCount;
    widget.store.addListener(onStoreChanged);
    if (widget.store.pendingRoleId != null) {
      WidgetsBinding.instance.addPostFrameCallback((_) => onStoreChanged());
    }
  }

  @override
  void dispose() {
    widget.store.removeListener(onStoreChanged);
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) => lifecycle = state;

  void onStoreChanged() {
    final store = widget.store;
    final needsAttention =
        store.newActionCount > lastActions || store.warningCount > lastWarnings;
    lastActions = store.newActionCount;
    lastWarnings = store.warningCount;
    if (needsAttention &&
        !host &&
        store.view?.status != 'ended' &&
        lifecycle == AppLifecycleState.resumed &&
        Platform.isAndroid) {
      HapticFeedback.heavyImpact();
    }
    final enteredRole = store.pendingRoleId;
    if (enteredRole != null) {
      store.pendingRoleId = null;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) showRoleIntro(context, store, enteredRole);
      });
    }
    if (mounted) setState(() {});
  }

  /// 宽屏同屏显示的页面直接算作已查看：对局栏始终可见，三栏时「我的/管理」也可见。
  /// 窄屏（tier 0）仍由底栏选择触发，保持原来的角标语义。
  void markVisiblePages(int tier) {
    if (tier == viewedTier) return;
    viewedTier = tier;
    if (tier == 0) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      widget.store.markMessagesRead();
      widget.store.markActionsViewed();
      if (tier >= 3) markThirdPageViewed();
    });
  }

  /// 「我的/管理」栏可见（三栏同屏或抽屉已打开）时清掉它的待办角标。
  void markThirdPageViewed() {
    if (host) {
      widget.store.markActionsViewed();
    } else {
      widget.store.markPrivateViewed();
    }
  }

  @override
  Widget build(BuildContext context) {
    final store = widget.store;
    final view = store.view;
    final actor = store.actor;
    // 返回大厅（returnToLobby）会先清空视图再让上层切页；这一步为空的瞬间不重建整页，
    // 避免在路由切换前用空视图构建对局界面。
    if (view == null || actor == null) {
      return const Scaffold(
        body: Center(child: CircularProgressIndicator()),
      );
    }
    final ended = view.status == 'ended';
    final labels = host ? const ['对局', '状态', '管理'] : const ['对局', '状态', '我的'];
    final icons = host
        ? const [
            Icons.forum_outlined,
            Icons.grid_view_rounded,
            Icons.admin_panel_settings_outlined
          ]
        : const [
            Icons.forum_outlined,
            Icons.grid_view_rounded,
            Icons.person_outline
          ];
    final counts = [
      store.unreadMessageCount + store.newActionCount + store.warningCount,
      store.pendingPhaseKey == null ? 0 : 1,
      host ? store.newActionCount : store.privateStateCount,
    ];
    final urgent = store.warningCount > 0 || store.newActionCount > 0;
    // 软键盘打开即进入「只留输入区」：小屏上标题栏、筛选、快捷工具与底栏一起把
    // 消息和输入框挤没，这里把它们全部让位给消息列表与输入区。
    final typing = MediaQuery.viewInsetsOf(context).bottom > 0;
    return LayoutBuilder(
      builder: (context, constraints) {
        // 平板/电脑屏幕够宽就同屏显示多栏，不再让底栏把页面藏起来：
        // 达到 dualPane 后状态与对局并排，达到 triplePane 再接上「我的/管理」。
        final threePane = constraints.maxWidth >= AppBreakpoints.triplePane;
        final twoPane = constraints.maxWidth >= AppBreakpoints.dualPane;
        // 多栏布局有自己的栏位标题，键盘聚焦只在单页窄屏生效。
        final focusTyping = typing && !twoPane;
        markVisiblePages(twoPane ? (threePane ? 3 : 2) : 0);
        final inset = twoPane
            ? AppSpacing.lg
            : focusTyping
                ? AppSpacing.sm
                : AppSpacing.bottomBar;
        final chat = ChatActionPage(
          store: store,
          bottomInset: inset,
          typing: focusTyping,
        );
        final board = BoardPage(store: store, bottomInset: inset);
        final third = host
            ? HostManagementPage(store: store, bottomInset: inset)
            : ProfilePage(store: store, bottomInset: inset);
        return Scaffold(
          key: _scaffold,
          extendBody: !twoPane,
          appBar: focusTyping ? null : AppBar(
            title: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  ended ? '本局已落幕' : view.phaseLabel,
                  style:  TextStyle(
                      fontSize: 17,
                      fontWeight: FontWeight.w600,
                      color: context.palette.text),
                ),
                Text(
                  ended
                      ? '结局可只读查看'
                      : '第 ${view.day} 日 · ${view.half == 'night' ? '夜间' : '白天'}',
                  style:  TextStyle(
                      fontSize: 12, color: context.palette.textTertiary),
                ),
              ],
            ),
            actions: [
              if (ended)
                Padding(
                  padding: const EdgeInsets.only(right: AppSpacing.sm),
                  child: TextButton.icon(
                    onPressed: store.writeBusy
                        ? null
                        : () => returnToLobby(context, store),
                    icon: const Icon(Icons.meeting_room_outlined, size: 18),
                    label: const Text('返回大厅'),
                  ),
                ),
              // 两栏时「我的/管理」收进右侧抽屉，入口保留该页的待办角标。
              if (twoPane && !threePane)
                Padding(
                  padding:  EdgeInsets.only(right: AppSpacing.sm),
                  child: IconButton(
                    tooltip: labels[2],
                    onPressed: () => _scaffold.currentState?.openEndDrawer(),
                    icon: Badge.count(
                      count: counts[2],
                      isLabelVisible: counts[2] > 0,
                      backgroundColor: context.palette.accent,
                      child: Icon(icons[2], color: context.palette.text),
                    ),
                  ),
                ),
              Padding(
                padding: const EdgeInsets.only(right: AppSpacing.lg),
                child: Center(
                  child: Tooltip(
                    message: '连接状态：${store.connectionStatus}',
                    child: Container(
                      width: 34,
                      height: 34,
                      decoration: BoxDecoration(
                        color: store.connectionStatus == '已连接'
                            ? context.palette.successSoft
                            : context.palette.warningSoft,
                        shape: BoxShape.circle,
                      ),
                      child: Icon(
                        store.connectionStatus == '已连接'
                            ? Icons.cloud_done_outlined
                            : Icons.cloud_off_outlined,
                        size: 18,
                        color: store.connectionStatus == '已连接'
                            ? context.palette.success
                            : context.palette.warning,
                      ),
                    ),
                  ),
                ),
              ),
            ],
          ),
          endDrawer: twoPane && !threePane
              ? Drawer(
                  width: 380,
                  child: SafeArea(
                    child: PaneFrame(
                      label: labels[2],
                      count: counts[2],
                      trailing: IconButton(
                        tooltip: '收起',
                        onPressed: () =>
                            _scaffold.currentState?.closeEndDrawer(),
                        icon: const Icon(Icons.close, size: 18),
                      ),
                      child: third,
                    ),
                  ),
                )
              : null,
          onEndDrawerChanged: (open) {
            if (open) markThirdPageViewed();
          },
          body: Stack(
            children: [
              if (twoPane)
                Row(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    SizedBox(
                        width: 340,
                        child: PaneFrame(label: '状态', child: board)),
                    const PaneDivider(),
                    Expanded(
                      child: PaneFrame(
                        label: '对局',
                        count: counts[0],
                        urgent: urgent,
                        child: chat,
                      ),
                    ),
                    if (threePane) ...[
                      const PaneDivider(),
                      SizedBox(
                        width: 360,
                        child: PaneFrame(
                          label: labels[2],
                          count: counts[2],
                          child: third,
                        ),
                      ),
                    ],
                  ],
                )
              else if (focusTyping)
                // 聚焦输入时没有标题栏，消息列表要自己避开状态栏。
                SafeArea(
                  bottom: false,
                  child: IndexedStack(
                      index: index, children: [chat, board, third]),
                )
              else
                IndexedStack(index: index, children: [chat, board, third]),
              // 键盘聚焦时不弹阶段动画：它盖满整屏，会挡住正在输入的内容。
              if (!focusTyping && store.pendingPhaseKey != null)
                PhaseOverlay(store: store),
            ],
          ),
          bottomNavigationBar: (twoPane || focusTyping)
              ? null
              : SafeArea(
                  minimum:  EdgeInsets.fromLTRB(20, 0, 20, 14),
                  child: Material(
                    elevation: 10,
                    shadowColor: Colors.black.withValues(alpha: .10),
                    color: context.palette.surface,
                    borderRadius: BorderRadius.circular(AppRadius.sheet),
                    clipBehavior: Clip.antiAlias,
                    child: NavigationBar(
                      backgroundColor: Colors.transparent,
                      elevation: 0,
                      selectedIndex: index,
                      onDestinationSelected: (value) {
                        setState(() => index = value);
                        if (Platform.isAndroid) HapticFeedback.selectionClick();
                        if (value == 0) {
                          store.markMessagesRead();
                          store.markActionsViewed();
                        } else if (value == 2 && !host) {
                          store.markPrivateViewed();
                        } else if (value == 2 && host) {
                          store.markActionsViewed();
                        }
                      },
                      destinations: [
                        for (var item = 0; item < 3; item++)
                          NavigationDestination(
                            icon: Badge.count(
                              count: counts[item],
                              isLabelVisible: counts[item] > 0,
                              backgroundColor: item == 0 && urgent
                                  ? context.palette.danger
                                  : context.palette.accent,
                              child: Icon(icons[item]),
                            ),
                            label: labels[item],
                          ),
                      ],
                    ),
                  ),
                ),
        );
      },
    );
  }
}

/// 宽屏栏位标题条：说明这一栏是什么，并把该页待办数量留在标题上。
class PaneFrame extends StatelessWidget {
  const PaneFrame({
    super.key,
    required this.label,
    required this.child,
    this.count = 0,
    this.urgent = false,
    this.trailing,
  });

  final String label;
  final Widget child;
  final int count;
  final bool urgent;
  final Widget? trailing;

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Container(
            height: 46,
            padding:  EdgeInsets.symmetric(horizontal: AppSpacing.lg),
            decoration:  BoxDecoration(
              color: context.palette.background,
              border: Border(bottom: BorderSide(color: context.palette.border)),
            ),
            child: Row(
              children: [
                Text(
                  label,
                  style:  TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                      color: context.palette.textSecondary),
                ),
                 Spacer(),
                if (count > 0)
                  Tag(
                    '$count',
                    color: urgent ? context.palette.danger : context.palette.accent,
                    background:
                        urgent ? context.palette.dangerSoft : context.palette.accentSoft,
                  ),
                if (trailing != null) trailing!,
              ],
            ),
          ),
          Expanded(child: child),
        ],
      );
}

/// 宽屏栏位之间的细分隔线。
class PaneDivider extends StatelessWidget {
  const PaneDivider({super.key});

  @override
  Widget build(BuildContext context) =>  VerticalDivider(
        width: 1,
        thickness: 1,
        color: context.palette.border,
      );
}

/// 从已终止的对局返回主界面（大厅）：主持人可在此建下一局，其他身份等待新局。
/// 对局记录在服务器上保持只读，这里只解除本设备对它的绑定。
Future<void> returnToLobby(BuildContext context, GameStore store) async {
  try {
    await store.returnToLobby();
  } on ApiException catch (failure) {
    if (context.mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(failure.message)));
    }
  }
}

/// 阶段变化的整屏动画；首次进入与重连不重复旧动画。
class PhaseOverlay extends StatefulWidget {
  const PhaseOverlay({super.key, required this.store});
  final GameStore store;

  @override
  State<PhaseOverlay> createState() => _PhaseOverlayState();
}

class _PhaseOverlayState extends State<PhaseOverlay> {
  bool shown = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      setState(() => shown = true);
      Future<void>.delayed(const Duration(milliseconds: 1450), () {
        if (mounted) widget.store.acknowledgePhase();
      });
    });
  }

  @override
  Widget build(BuildContext context) {
    final reduceMotion = MediaQuery.disableAnimationsOf(context);
    final view = widget.store.view!;
    final night = view.half == 'night';
    return Positioned.fill(
      child: AnimatedOpacity(
        opacity: shown ? 1 : 0,
        duration:
            reduceMotion ? Duration.zero :  Duration(milliseconds: 260),
        child: ColoredBox(
          color: context.palette.surface,
          child: Center(
            child: AnimatedScale(
              scale: shown ? 1 : .92,
              duration: reduceMotion
                  ? Duration.zero
                  :  Duration(milliseconds: 340),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Container(
                    width: 88,
                    height: 88,
                    decoration: BoxDecoration(
                      color: night ? context.palette.accentSoft : context.palette.hostSoft,
                      shape: BoxShape.circle,
                    ),
                    child: Icon(
                      night ? Icons.nightlight_round : Icons.wb_sunny_outlined,
                      size: 40,
                      color: night ? context.palette.accent : context.palette.host,
                    ),
                  ),
                   SizedBox(height: AppSpacing.xl),
                  Text(
                    '第 ${view.day} 日',
                    style:  TextStyle(
                        fontSize: 15, color: context.palette.textTertiary),
                  ),
                   SizedBox(height: AppSpacing.sm),
                  Text(
                    view.phaseLabel,
                    style:  TextStyle(
                        fontSize: 30,
                        fontWeight: FontWeight.w700,
                        color: context.palette.text),
                  ),
                   SizedBox(height: AppSpacing.sm),
                  Text(
                    night ? '夜间' : '白天',
                    style:  TextStyle(
                        fontSize: 14, color: context.palette.textSecondary),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

/// 对局页：上方消息、下方输入与行动入口。
class ChatActionPage extends StatefulWidget {
  const ChatActionPage({
    super.key,
    required this.store,
    this.bottomInset = AppSpacing.bottomBar,
    this.typing = false,
  });
  final GameStore store;

  /// 底部为悬浮底栏预留的高度；宽屏没有底栏，由外壳传入更小的值。
  final double bottomInset;

  /// 软键盘是否正打开：为真时隐藏页内除输入区以外的全部控件。
  final bool typing;

  @override
  State<ChatActionPage> createState() => _ChatActionPageState();
}

class _ChatActionPageState extends State<ChatActionPage> {
  static const scopes = {
    'all': ('全部', Icons.all_inbox_outlined),
    'public': ('公屏', Icons.campaign_outlined),
    'private': ('私信', Icons.lock_outline),
    'system': ('系统', Icons.info_outline),
    'host': ('主持人', Icons.workspace_premium_outlined),
  };
  final message = TextEditingController();
  final scroll = ScrollController();
  String? sendError;
  int lastCount = 0;

  @override
  void initState() {
    super.initState();
    widget.store.addListener(onStore);
    lastCount = widget.store.messages.length;
  }

  @override
  void dispose() {
    widget.store.removeListener(onStore);
    message.dispose();
    scroll.dispose();
    super.dispose();
  }

  void onStore() {
    final count = widget.store.messages.length;
    if (count != lastCount) {
      lastCount = count;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted && scroll.hasClients) {
          scroll.animateTo(
            scroll.position.maxScrollExtent,
            duration: const Duration(milliseconds: 220),
            curve: Curves.easeOut,
          );
        }
      });
    }
  }

  List<ActionDescriptor> get actions {
    final store = widget.store;
    final source = store.actor!.isHost || store.actor!.isSpectator
        ? store.view!.allActions.where((item) => item.id.startsWith('channel.'))
        : store.view!.allActions;
    final seen = <String>{};
    return [
      for (final item in source)
        if (seen.add(item.protocolKey)) item
    ];
  }

  @override
  Widget build(BuildContext context) {
    final store = widget.store;
    final typing = widget.typing;
    final channel = store.selectedChannel;
    return Column(
      children: [
        // 键盘打开后页内只留输入区：筛选、阶段进度、主持人快捷工具、傀儡面板与
        // 常驻提示全部让位，消息列表继续占满剩余空间，边打字边看上下文。
        if (!typing)
          SizedBox(
            height: 54,
            child: ListView(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.md, AppSpacing.sm, AppSpacing.md, AppSpacing.sm),
              scrollDirection: Axis.horizontal,
              children: [
                for (final entry in scopes.entries)
                  Padding(
                    padding:  EdgeInsets.only(right: AppSpacing.sm),
                    child: FilterChip(
                      avatar: Icon(
                        entry.value.$2,
                        size: 15,
                        color: store.messageScope == entry.key
                            ? context.palette.accent
                            : context.palette.textTertiary,
                      ),
                      label: Text(entry.value.$1),
                      selected: store.messageScope == entry.key,
                      showCheckmark: false,
                      onSelected: (_) => store.loadMessages(entry.key),
                    ),
                  ),
              ],
            ),
          ),
        if (!typing && store.view!.phase == 'discussion')
          _DiscussionProgressCard(view: store.view!),
        if (!typing && store.actor!.isHost) _HostQuickTools(store: store),
        Expanded(
          child: store.messages.isEmpty
              ? const EmptyState(
                  icon: Icons.chat_bubble_outline,
                  title: '当前筛选范围没有消息',
                  detail: '切换上方筛选可以查看公屏、私信与系统信息。',
                )
              : ListView.builder(
                  controller: scroll,
                  padding: const EdgeInsets.fromLTRB(AppSpacing.lg,
                      AppSpacing.sm, AppSpacing.lg, AppSpacing.md),
                  itemCount:
                      store.messages.length + (store.hasMoreMessages ? 1 : 0),
                  itemBuilder: (context, index) {
                    if (store.hasMoreMessages && index == 0) {
                      return Center(
                        child: TextButton(
                          onPressed: store.loadOlderMessages,
                          child: const Text('加载更早消息'),
                        ),
                      );
                    }
                    final item =
                        store.messages[index - (store.hasMoreMessages ? 1 : 0)];
                    return MessageBubble(
                      message: item,
                      self: store.actor?.id,
                      store: store,
                      onAvatar: (senderId) {
                        final ref = participantRefFor(store, senderId);
                        if (ref != null) showAvatarMenu(context, store, ref);
                      },
                    );
                  },
                ),
        ),
        if (!typing && store.view!.puppetSpectator)
          const Padding(
            padding: EdgeInsets.fromLTRB(
                AppSpacing.md, AppSpacing.sm, AppSpacing.md, 0),
            child: _PuppetNoticeCard(),
          ),
        if (!typing)
          for (final panel in store.view!.puppetControls)
            if (panel.actions.isNotEmpty)
              _PuppetActionPanel(store: store, panel: panel),
        _Composer(
          store: store,
          channel: channel,
          controller: message,
          typing: typing,
          actions: actions,
          bottomInset: widget.bottomInset,
          error: sendError,
          onSend: send,
          onClearError: () => setState(() => sendError = null),
        ),
      ],
    );
  }

  Future<void> send() async {
    final text = message.text;
    if (text.trim().isEmpty) return;
    setState(() => sendError = null);
    try {
      await widget.store.sendMessage(text);
      message.clear();
    } on ApiException catch (failure) {
      if (mounted) setState(() => sendError = failure.message);
    }
  }
}

/// 输入区：频道选择 + 输入框 + 行动入口。键盘弹出时只保留紧凑行动入口。
class _Composer extends StatelessWidget {
  const _Composer({
    required this.store,
    required this.channel,
    required this.controller,
    required this.typing,
    required this.actions,
    required this.bottomInset,
    required this.onSend,
    required this.onClearError,
    this.error,
  });

  final GameStore store;
  final GameChannel? channel;
  final TextEditingController controller;

  /// 软键盘已打开：行动入口收成一个按钮，不再横向铺开。
  final bool typing;
  final List<ActionDescriptor> actions;
  final double bottomInset;
  final VoidCallback onSend;
  final VoidCallback onClearError;
  final String? error;

  @override
  Widget build(BuildContext context) {
    final canSend = channel?.canSend == true && !store.writeBusy;
    return Material(
      color: context.palette.surface,
      child: SafeArea(
        top: false,
        minimum: EdgeInsets.fromLTRB(
            AppSpacing.md, AppSpacing.sm, AppSpacing.md, bottomInset),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            // 发送目标与发送按钮同处文本框上方，文本框整行展开不再被挤压。
            Row(
              children: [
                Expanded(child: _ChannelButton(store: store, channel: channel)),
                const SizedBox(width: AppSpacing.sm),
                _SendButton(enabled: canSend, onSend: onSend),
              ],
            ),
            const SizedBox(height: AppSpacing.sm),
            TextField(
              controller: controller,
              enabled: canSend,
              maxLength: 2000,
              minLines: 1,
              maxLines: 4,
              decoration: InputDecoration(
                hintText: canSend ? '说点什么…' : '当前不可发言',
                errorText: error,
                counterText: '',
                isDense: true,
                contentPadding:
                    const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
              ),
              onChanged: (_) => onClearError(),
              onSubmitted: (_) => onSend(),
            ),
            if (!canSend && (channel?.reason.isNotEmpty ?? false))
              Padding(
                padding:  EdgeInsets.only(top: AppSpacing.sm),
                child: Row(
                  children: [
                     Icon(Icons.info_outline,
                        size: 14, color: context.palette.textTertiary),
                     SizedBox(width: AppSpacing.xs),
                    Expanded(
                      child: Text(
                        channel!.reason,
                        style:  TextStyle(
                            fontSize: 12, color: context.palette.textTertiary),
                      ),
                    ),
                  ],
                ),
              ),
            if (actions.isNotEmpty) ...[
              const Padding(
                padding: EdgeInsets.symmetric(vertical: AppSpacing.md),
                child: DashedDivider(),
              ),
              SizedBox(
                height: 42,
                child: typing
                    ? Align(
                        alignment: Alignment.centerLeft,
                        child: Badge.count(
                          count: actions.length,
                          backgroundColor: context.palette.accent,
                          child: FilledButton.tonalIcon(
                            onPressed: () =>
                                openActionPicker(context, store, actions),
                            icon: const Icon(Icons.bolt_outlined, size: 18),
                            label: const Text('行动'),
                          ),
                        ),
                      )
                    : ListView.separated(
                        scrollDirection: Axis.horizontal,
                        itemCount: actions.length,
                        separatorBuilder: (_, __) =>
                            const SizedBox(width: AppSpacing.sm),
                        itemBuilder: (context, index) => ActionChipButton(
                          action: actions[index],
                          busy: store.writeBusy,
                          onTap: () =>
                              showActionForm(context, store, actions[index]),
                        ),
                      ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

/// 虚线分隔符：用于把文本框与行动区分开。
class DashedDivider extends StatelessWidget {
  const DashedDivider({super.key, this.dash = 5, this.gap = 4, this.color});

  final double dash;
  final double gap;
  final Color? color;

  @override
  Widget build(BuildContext context) => SizedBox(
        height: 1,
        width: double.infinity,
        child: CustomPaint(
          painter: _DashedLinePainter(
            color: color ?? context.palette.borderStrong,
            dash: dash,
            gap: gap,
          ),
        ),
      );
}

class _DashedLinePainter extends CustomPainter {
  const _DashedLinePainter({
    required this.color,
    required this.dash,
    required this.gap,
  });

  final Color color;
  final double dash;
  final double gap;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = color
      ..strokeWidth = 1;
    var start = 0.0;
    while (start < size.width) {
      final end = (start + dash).clamp(0.0, size.width);
      canvas.drawLine(Offset(start, 0), Offset(end, 0), paint);
      start = end + gap;
    }
  }

  @override
  bool shouldRepaint(covariant _DashedLinePainter oldDelegate) =>
      oldDelegate.color != color ||
      oldDelegate.dash != dash ||
      oldDelegate.gap != gap;
}

class _SendButton extends StatelessWidget {
  const _SendButton({required this.enabled, required this.onSend});
  final bool enabled;
  final VoidCallback onSend;

  @override
  Widget build(BuildContext context) => SizedBox(
        width: 46,
        height: 46,
        child: FilledButton(
          onPressed: enabled ? onSend : null,
          style: FilledButton.styleFrom(
            padding: EdgeInsets.zero,
            shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(AppRadius.field)),
          ),
          child: const Icon(Icons.arrow_upward_rounded, size: 20),
        ),
      );
}

class _ChannelButton extends StatelessWidget {
  const _ChannelButton({required this.store, required this.channel});
  final GameStore store;
  final GameChannel? channel;

  @override
  Widget build(BuildContext context) {
    final targets = store.sendTargets;
    final label = channel?.label ?? '公开讨论';
    return Tooltip(
      message: '选择发送频道',
      child: Material(
        color: context.palette.surfaceMuted,
        borderRadius: BorderRadius.circular(AppRadius.field),
        child: InkWell(
          borderRadius: BorderRadius.circular(AppRadius.field),
          onTap: targets.isEmpty
              ? null
              : () async {
                  final picked = await showModalBottomSheet<
                      ({GameChannel channel, String? asSeat})>(
                    context: context,
                    useSafeArea: true,
                    builder: (context) => _ChannelSheet(store: store),
                  );
                  if (picked != null) {
                    // 傀儡频道自带 as_seat：选中即切换发言身份，草稿随之隔离。
                    store.selectChannel(picked.channel.id,
                        asSeat: picked.asSeat);
                  }
                },
          child: Container(
            height: 46,
            padding: const EdgeInsets.symmetric(horizontal: 12),
            // 整行展开：发送目标名称要完整显示，不被左侧固定宽度截断。
            width: double.infinity,
            child: Row(
              children: [
                Icon(
                  store.activeAsSeat != null
                      ? Icons.smart_toy_outlined
                      : _channelIcon(channel?.id),
                  size: 16,
                  color: context.palette.textSecondary,
                ),
                 SizedBox(width: 6),
                Expanded(
                  child: Text(
                    label.replaceFirst('私密 · ', ''),
                    overflow: TextOverflow.ellipsis,
                    style:  TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w500,
                        color: context.palette.text),
                  ),
                ),
                 Icon(Icons.expand_more,
                    size: 16, color: context.palette.textTertiary),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

IconData _channelIcon(String? channelId) => channelId == 'public'
    ? Icons.campaign_outlined
    : channelId == 'system'
        ? Icons.info_outline
        : Icons.lock_outline;

/// 傀儡席玩家的常驻提示：本次行动由魔女梅露露代为执行，自己只读旁观。
/// 与主持人警告共用 dangerSoft 卡片样式。
class _PuppetNoticeCard extends StatelessWidget {
  const _PuppetNoticeCard();

  @override
  Widget build(BuildContext context) => Card(
        color: context.palette.dangerSoft,
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Row(
            children: [
               Icon(Icons.smart_toy_outlined,
                  color: context.palette.danger),
               SizedBox(width: AppSpacing.md),
              Expanded(
                child: Text(
                  '你当前是傀儡，由魔女梅露露代为行动',
                  style: TextStyle(fontSize: 13, color: context.palette.text),
                ),
              ),
            ],
          ),
        ),
      );
}

/// 自由发言结束请求的公开进度；集满六个不同席位后系统 10 秒自动进入提名。
class _DiscussionProgressCard extends StatelessWidget {
  const _DiscussionProgressCard({required this.view});
  final GameView view;

  @override
  Widget build(BuildContext context) => Card(
        color: context.palette.accentSoft,
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.lg),
          child: Row(
            children: [
               Icon(Icons.how_to_vote_outlined,
                  color: context.palette.accent),
               SizedBox(width: AppSpacing.md),
              Expanded(
                child: Text(
                  '已有 ${view.discussionEndRequests.length}/6 名玩家请求结束自由发言'
                  '${view.autoAdvanceAt == null ? '；集满六人后 10 秒自动进入提名' : '，将在 ${_deadlineText(view.autoAdvanceAt)} 自动进入提名'}',
                  style: TextStyle(fontSize: 13, color: context.palette.text),
                ),
              ),
            ],
          ),
        ),
      );
}

/// 魔女梅露露的傀儡代操作面板：标题写明席位，动作一律以该席位身份提交。
class _PuppetActionPanel extends StatelessWidget {
  const _PuppetActionPanel({required this.store, required this.panel});
  final GameStore store;
  final PuppetPanel panel;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(
            AppSpacing.md, AppSpacing.sm, AppSpacing.md, 0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '傀儡视角 · ${panel.seatId}号 ${panel.name}',
              style: TextStyle(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                  color: context.palette.textTertiary),
            ),
            const SizedBox(height: AppSpacing.xs),
            SizedBox(
              height: 42,
              child: ListView.separated(
                scrollDirection: Axis.horizontal,
                itemCount: panel.actions.length,
                separatorBuilder: (_, __) => const SizedBox(width: AppSpacing.sm),
                itemBuilder: (context, index) {
                  final action = panel.actions[index];
                  return ActionChipButton(
                    action: action,
                    busy: store.writeBusy,
                    onTap: () => showActionForm(
                      context,
                      store,
                      action,
                      asSeat: panel.seatId,
                    ),
                  );
                },
              ),
            ),
          ],
        ),
      );
}

class _ChannelSheet extends StatelessWidget {
  const _ChannelSheet({required this.store});
  final GameStore store;

  @override
  Widget build(BuildContext context) => SafeArea(
        top: false,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
             Padding(
              padding: EdgeInsets.fromLTRB(
                  AppSpacing.xl, 0, AppSpacing.xl, AppSpacing.md),
              child: Text(
                '选择发送频道',
                style: TextStyle(
                    fontSize: 20,
                    fontWeight: FontWeight.w600,
                    color: context.palette.text),
              ),
            ),
            Flexible(
              child: ListView(
                shrinkWrap: true,
                padding: const EdgeInsets.fromLTRB(
                    AppSpacing.md, 0, AppSpacing.md, AppSpacing.lg),
                children: [
                  // 已结束的私信不再占用频道列表；历史消息仍在消息流里可见。
                  // 傀儡频道排在自己的频道之后，标签已带 `*`，选中即以该席位发言。
                  for (final target in store.sendTargets
                      .where((item) => item.channel.status != 'ended'))
                    ListTile(
                      leading: Icon(
                        target.asSeat != null
                            ? Icons.smart_toy_outlined
                            : _channelIcon(target.channel.id),
                        color: target.channel.canSend
                            ? context.palette.accent
                            : context.palette.textTertiary,
                      ),
                      title: Text(target.channel.label),
                      subtitle: target.channel.canSend
                          ? null
                          : Text(target.channel.reason.isEmpty
                              ? '只读'
                              : target.channel.reason),
                      trailing: target.channel.id == store.activeChannelId &&
                              target.asSeat == store.activeAsSeat
                          ?  Icon(Icons.check, color: context.palette.accent)
                          : null,
                      enabled: target.channel.canSend,
                      onTap: () => Navigator.pop(context, target),
                    ),
                ],
              ),
            ),
          ],
        ),
      );
}

/// 行动短名按钮：图标 + 短名。
/// 主持人专用：在对局页直接执行最常用的房间管理，不必切到“管理”页。
/// 只列出服务端当前真实给出的动作，缺席的自动隐藏。
class _HostQuickTools extends StatelessWidget {
  const _HostQuickTools({required this.store});
  final GameStore store;

  ActionDescriptor? _find(String id) {
    for (final action in store.view?.allActions ?? const <ActionDescriptor>[]) {
      if (action.id == id) return action;
    }
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final advance = _find('host.advance');
    final auto = _find('host.auto');
    final warn = _find('host.warn');
    final mute = _find('room.mute');
    final create = _find('channel.create');
    final openJoin = _find('room.open_join');
    final tools = <_QuickTool>[
      if (openJoin != null)
        _QuickTool(
          action: openJoin,
          label: openJoin.shortLabel,
          icon: Icons.person_add_alt_outlined,
        ),
      if (advance != null)
        _QuickTool(
          action: advance,
          label: '推进',
          icon: Icons.play_circle_outline,
        ),
      if (auto != null)
        _QuickTool(
          action: auto,
          label: auto.shortLabel,
          icon: Icons.motion_photos_auto_outlined,
        ),
      if (warn != null)
        _QuickTool(
          action: warn,
          label: '警告',
          icon: Icons.timer_outlined,
        ),
      if (mute != null)
        _QuickTool(
          action: mute,
          label: '禁言',
          icon: Icons.volume_off_outlined,
        ),
      if (create != null)
        _QuickTool(
          action: create,
          label: create.shortLabel,
          icon: Icons.forum_outlined,
        ),
    ];
    if (tools.isEmpty) {
      return const SizedBox.shrink();
    }
    return SizedBox(
      height: 38,
      child: ListView.separated(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.fromLTRB(
          AppSpacing.md,
          0,
          AppSpacing.md,
          AppSpacing.sm,
        ),
        itemCount: tools.length,
        separatorBuilder: (_, __) => const SizedBox(width: AppSpacing.sm),
        itemBuilder: (context, index) => tools[index].build(context, store),
      ),
    );
  }
}

class _QuickTool {
  const _QuickTool({
    required this.action,
    required this.label,
    required this.icon,
  });

  final ActionDescriptor action;
  final String label;
  final IconData icon;

  Widget build(BuildContext context, GameStore store) {
    final danger = action.raw['danger'] == true;
    final tint = danger ? context.palette.danger : context.palette.textSecondary;
    final enabled = !store.writeBusy && action.unsupportedReason == null;
    return Material(
      color: context.palette.surfaceMuted,
      borderRadius: BorderRadius.circular(AppRadius.chip),
      child: InkWell(
        borderRadius: BorderRadius.circular(AppRadius.chip),
        onTap: enabled ? () => showActionForm(context, store, action) : null,
        child: Padding(
          padding:  EdgeInsets.symmetric(horizontal: 12),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon,
                  size: 15, color: enabled ? tint : context.palette.textTertiary),
               SizedBox(width: 6),
              Text(
                label,
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w500,
                  color: enabled ? context.palette.text : context.palette.textTertiary,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class ActionChipButton extends StatelessWidget {
  const ActionChipButton(
      {super.key,
      required this.action,
      required this.busy,
      required this.onTap});

  final ActionDescriptor action;
  final bool busy;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final danger = action.raw['danger'] == true;
    final unsupported = action.unsupportedReason;
    final tint = actionTint(context, action.group, danger: danger);
    return Tooltip(
      message: unsupported ?? action.label,
      child: Material(
        color: unsupported != null
            ? context.palette.surfaceMuted
            : tint.withValues(alpha: .10),
        borderRadius: BorderRadius.circular(AppRadius.chip),
        child: InkWell(
          borderRadius: BorderRadius.circular(AppRadius.chip),
          onTap: busy || unsupported != null ? null : onTap,
          child: Padding(
            padding:  EdgeInsets.symmetric(horizontal: 14, vertical: 9),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                if (unsupported != null)
                   Icon(Icons.block, size: 16, color: context.palette.danger)
                else
                  ActionIcon(actionId: action.id, size: 17, color: tint),
                 SizedBox(width: 7),
                Text(
                  action.shortLabel,
                  style: TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w600,
                    color: unsupported != null
                        ? context.palette.textTertiary
                        : danger
                            ? context.palette.danger
                            : context.palette.text,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// 打开行动选择器（自绘，带图标）。
Future<void> openActionPicker(
  BuildContext context,
  GameStore store,
  List<ActionDescriptor> actions,
) async {
  final picked = await showActionPicker(context, actions: actions, title: '当前可用行动');
  if (picked == null || !context.mounted) return;
  await showActionForm(context, store, picked);
}

/// 消息气泡：自己靠右、他人靠左、系统居中。
/// 点击头像打开该发送者的快捷菜单（看技能、私信、主持人管理）。
class MessageBubble extends StatelessWidget {
  const MessageBubble({
    super.key,
    required this.message,
    this.self,
    this.store,
    this.onAvatar,
  });

  final GameMessage message;
  final String? self;
  final GameStore? store;
  final ValueChanged<String?>? onAvatar;

  @override
  Widget build(BuildContext context) {
    final system = message.kind != 'chat';
    if (system) {
      return Padding(
        padding:  EdgeInsets.symmetric(vertical: AppSpacing.sm),
        child: Center(
          child: Container(
            constraints:  BoxConstraints(maxWidth: 420),
            padding:  EdgeInsets.symmetric(horizontal: 14, vertical: 8),
            decoration: BoxDecoration(
              color: context.palette.surfaceMuted,
              borderRadius: BorderRadius.circular(AppRadius.chip),
            ),
            child: Text(
              _systemText,
              textAlign: TextAlign.center,
              style:  TextStyle(
                  fontSize: 13, color: context.palette.textSecondary, height: 1.5),
            ),
          ),
        ),
      );
    }
    final mine = self != null && message.raw['sender_id']?.toString() == self;
    // 发送者佩戴的成就：服务端按参与者 id 下发，取不到就不显示徽章。
    final badge = store?.equippedFor(message.senderId);
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
      child: Row(
        mainAxisAlignment:
            mine ? MainAxisAlignment.end : MainAxisAlignment.start,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (!mine) ...[
            GestureDetector(
              behavior: HitTestBehavior.opaque,
              onTap:
                  onAvatar == null ? null : () => onAvatar!(message.senderId),
              child: RoleAvatar(
                roleId: message.avatarRoleId,
                host: message.senderId == 'host',
                size: 38,
              ),
            ),
            const SizedBox(width: AppSpacing.sm),
          ],
          Flexible(
            child: Column(
              crossAxisAlignment:
                  mine ? CrossAxisAlignment.end : CrossAxisAlignment.start,
              children: [
                if (message.senderName != null && !mine)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 3, left: 2),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        GestureDetector(
                          behavior: HitTestBehavior.opaque,
                          onTap: onAvatar == null
                              ? null
                              : () => onAvatar!(message.senderId),
                          child: Text(
                            message.senderName!,
                            style:  TextStyle(
                                fontSize: 12, color: context.palette.textTertiary),
                          ),
                        ),
                        // 佩戴的成就紧跟在昵称右边，底色就是稀有度颜色。
                        if (badge != null) ...[
                          const SizedBox(width: 6),
                          AchievementBadge(
                            name: badge.name,
                            rarity: badge.rarity,
                            dense: true,
                          ),
                        ],
                      ],
                    ),
                  ),
                if (mine && badge != null)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 3, right: 2),
                    child: AchievementBadge(
                      name: badge.name,
                      rarity: badge.rarity,
                      dense: true,
                    ),
                  ),
                Container(
                  padding:
                       EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                  decoration: BoxDecoration(
                    color: mine ? context.palette.accent : context.palette.surface,
                    borderRadius: BorderRadius.circular(AppRadius.card),
                    border: mine ? null : Border.all(color: context.palette.border),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (message.channelId != 'public')
                        Padding(
                          padding: const EdgeInsets.only(bottom: AppSpacing.xs),
                          child: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Icon(
                                message.channelId == 'information'
                                    ? Icons.info_outline
                                    : Icons.lock_outline,
                                size: 12,
                                color: mine
                                    ? Colors.white70
                                    : context.palette.textTertiary,
                              ),
                              const SizedBox(width: 4),
                              Text(
                                message.channelId == 'information'
                                    ? '系统信息'
                                    : '私信',
                                style: TextStyle(
                                  fontSize: 11,
                                  color: mine
                                      ? Colors.white70
                                      : context.palette.textTertiary,
                                ),
                              ),
                            ],
                          ),
                        ),
                      Text(
                        message.text,
                        style: TextStyle(
                          fontSize: 15,
                          height: 1.5,
                          color: mine ? context.palette.onAccent : context.palette.text,
                        ),
                      ),
                      if (_time.isNotEmpty) ...[
                         SizedBox(height: AppSpacing.xs),
                        Text(
                          _time,
                          style: TextStyle(
                            fontSize: 11,
                            color:
                                mine ? Colors.white70 : context.palette.textTertiary,
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  /// 本机时区的精简时间；解析失败时返回空串，不显示原始时间串。
  String get _time => formatMessageTime(message.createdAt);

  /// 系统消息在正文后附一个精简时间，方便对照阶段变化。
  String get _systemText =>
      _time.isEmpty ? message.text : '${message.text} · $_time';
}

/// 状态页：牌桌 + 阶段信息。
class BoardPage extends StatefulWidget {
  const BoardPage({
    super.key,
    required this.store,
    this.bottomInset = AppSpacing.bottomBar,
  });
  final GameStore store;

  /// 底部为悬浮底栏预留的高度；宽屏由外壳传入更小的值。
  final double bottomInset;

  @override
  State<BoardPage> createState() => _BoardPageState();
}

class _BoardPageState extends State<BoardPage> {
  Timer? _ticker;
  bool _loading = false;

  GameStore get store => widget.store;

  @override
  void initState() {
    super.initState();
    _load();
    _ticker = Timer.periodic(const Duration(seconds: 10), (_) => _load());
  }

  @override
  void dispose() {
    _ticker?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    // 与大厅同一个理由：慢响应时跳过这一拍，避免轮询叠加。
    if (!mounted || _loading) return;
    _loading = true;
    try {
      await widget.store.loadOnline(gameId: widget.store.view?.id);
    } finally {
      _loading = false;
    }
  }

  List<OnlineAccount> _others() => store.online
      .where((account) => account.id != store.actor?.accountId)
      .toList(growable: false);

  Widget _inviteTrailing(BuildContext context, OnlineAccount account) {
    final actor = store.actor;
    final canInvite =
        actor != null && !actor.isSpectator && account.available && !account.invited;
    if (account.invited) {
      return  Tag('已邀请');
    }
    if (!canInvite) {
      return Tag(
        '不可邀请',
        color: context.palette.textTertiary,
        background: context.palette.surfaceMuted,
      );
    }
    return FilledButton(
      onPressed: store.writeBusy ? null : () => _invite(context, account),
      child: const Text('邀请'),
    );
  }

  Future<void> _invite(BuildContext context, OnlineAccount account) async {
    try {
      await store.inviteAccount(account.id);
      if (context.mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text('已邀请 ${account.name}')));
      }
    } on ApiException catch (failure) {
      if (context.mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(failure.message)));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final view = store.view!;
    final result = view.raw['result'];
    return ListView(
      padding: EdgeInsets.fromLTRB(
        AppSpacing.lg,
        AppSpacing.sm,
        AppSpacing.lg,
        widget.bottomInset,
      ),
      children: [
        Card(
          child: Padding(
            padding:  EdgeInsets.all(AppSpacing.lg),
            child: Row(
              children: [
                Container(
                  width: 46,
                  height: 46,
                  decoration: BoxDecoration(
                    color: view.half == 'night'
                        ? context.palette.accentSoft
                        : context.palette.hostSoft,
                    borderRadius: BorderRadius.circular(AppRadius.field),
                  ),
                  child: Icon(
                    view.half == 'night'
                        ? Icons.nightlight_round
                        : Icons.wb_sunny_outlined,
                    color: view.half == 'night'
                        ? context.palette.accent
                        : context.palette.host,
                  ),
                ),
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '第 ${view.day} 日 · ${view.phaseLabel}',
                        style:  TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.w600,
                            color: context.palette.text),
                      ),
                       SizedBox(height: 2),
                      Text(
                        '已准备 ${view.raw['ready_count'] ?? 0} 人 · 连接${store.connectionStatus}',
                        style:  TextStyle(
                            fontSize: 12, color: context.palette.textTertiary),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
        SectionTitle(
          '牌桌',
          subtitle: '每席两张角色牌，当前使用的牌在上层；点击席位可快捷操作。',
        ),
        AnimatedSwitcher(
          duration: MediaQuery.disableAnimationsOf(context)
              ? Duration.zero
              : const Duration(milliseconds: 260),
          child: Column(
            key: ValueKey('${view.version}:${view.phase}'),
            children: [
              for (final seat in view.seats)
                Padding(
                  padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                  child: SeatCard(
                    seat: seat,
                    onTap: seat['participant_id'] == null
                        ? null
                        : () {
                            final ref = participantRefFor(
                              store,
                              seat['participant_id']?.toString(),
                            );
                            if (ref != null) {
                              showAvatarMenu(context, store, ref);
                            }
                          },
                  ),
                ),
            ],
          ),
        ),
        if (view.status != 'ended') ...[
          const SectionTitle('在线玩家',
              subtitle: '邀请在线账号入席；对方需等主持人开放加入后才能接受。'),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(AppSpacing.md),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (_others().isEmpty)
                     Padding(
                      padding: EdgeInsets.all(AppSpacing.sm),
                      child: Text(
                        '当前没有其他人在线。',
                        style: TextStyle(
                            fontSize: 13, color: context.palette.textTertiary),
                      ),
                    ),
                  for (final account in _others())
                    ListTile(
                      leading:  RoleAvatar(roleId: null, size: 40),
                      title: Text(account.name),
                      trailing: _inviteTrailing(context, account),
                    ),
                ],
              ),
            ),
          ),
        ],
        if (result is Map && result.isNotEmpty) ...[
           SectionTitle('结算'),
          Card(
            color: context.palette.hostSoft,
            child: Padding(
              padding:  EdgeInsets.all(AppSpacing.lg),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                       Icon(Icons.emoji_events_outlined,
                          color: context.palette.host),
                       SizedBox(width: AppSpacing.md),
                      Expanded(
                        child: Text(
                          _resultTitle(result),
                          style:  TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.w600,
                            color: context.palette.text,
                          ),
                        ),
                      ),
                    ],
                  ),
                  if (result['reason']?.toString().isNotEmpty == true) ...[
                     SizedBox(height: AppSpacing.sm),
                    Text(
                      result['reason'].toString(),
                      style:  TextStyle(
                          fontSize: 14, height: 1.5, color: context.palette.text),
                    ),
                  ],
                  // 对局终止或分出胜负后，本局只读；这里给出回到主界面的入口。
                  if (view.status == 'ended') ...[
                    const SizedBox(height: AppSpacing.lg),
                    FilledButton.icon(
                      onPressed: store.writeBusy
                          ? null
                          : () => returnToLobby(context, store),
                      icon:  Icon(Icons.meeting_room_outlined, size: 18),
                      label:  Text('返回主界面（大厅）'),
                    ),
                     SizedBox(height: AppSpacing.sm),
                     Text(
                      '本局记录在主持人开启下一局前仍可只读查看；返回大厅后，主持人可建立新一局。',
                      style: TextStyle(
                          fontSize: 12, color: context.palette.textTertiary),
                    ),
                  ],
                ],
              ),
            ),
          ),
        ],
      ],
    );
  }
}

/// 结算标题：终止对局不再显示成一个阵营获胜。
String _resultTitle(Map<dynamic, dynamic> result) =>
    switch (result['winner']?.toString() ?? '') {
      'good' => '好人获胜',
      'witch' => '魔女获胜',
      'aborted' => '本局已终止',
      final other when other.isNotEmpty => other,
      _ => '本局已结束',
    };

class SeatCard extends StatelessWidget {
  const SeatCard({super.key, required this.seat, this.onTap});
  final Map<String, dynamic> seat;

  /// 点击整张席位卡打开该席位的快捷菜单。
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final occupied = seat['occupied'] == true;
    final alive = seat['alive'] != false;
    final name = seat['name']?.toString() ?? '';
    // 仅主持人/观战视角下发 cards；其中 witch 标记用于红框提示魔女化角色。
    final cards = seat['cards'];
    final witches = cards is List
        ? cards
            .whereType<Map>()
            .where((card) => card['witch'] == true)
            .map((card) =>
                roleVisual(card['role_id']?.toString())?.name ??
                card['role_id']?.toString() ??
                '')
            .where((label) => label.isNotEmpty)
            .toList()
        : const <String>[];
    return Card(
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(AppRadius.card),
        child: Padding(
          padding: const EdgeInsets.all(AppSpacing.md),
          child: Row(
            children: [
              DualAvatar(seat: seat, alive: alive),
              const SizedBox(width: AppSpacing.md),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Text(
                          '${seat['id']} 号',
                          style:  TextStyle(
                              fontSize: 15,
                              fontWeight: FontWeight.w600,
                              color: context.palette.text),
                        ),
                         SizedBox(width: AppSpacing.sm),
                        Flexible(
                          child: Text(
                            name.isNotEmpty ? name : (occupied ? '等待命名' : '空席'),
                            overflow: TextOverflow.ellipsis,
                            style:  TextStyle(
                                fontSize: 14, color: context.palette.textSecondary),
                          ),
                        ),
                      ],
                    ),
                     SizedBox(height: AppSpacing.xs),
                    Wrap(
                      spacing: AppSpacing.sm,
                      runSpacing: AppSpacing.xs,
                      children: [
                        Tag(
                          alive ? '存活' : '已出局',
                          color: alive
                              ? context.palette.success
                              : context.palette.textSecondary,
                          background: alive
                              ? context.palette.successSoft
                              : context.palette.surfaceMuted,
                        ),
                        if (seat['online'] == true)
                           Tag('在线', icon: Icons.wifi_tethering),
                        if (seat['ready'] == true)
                           Tag('已准备', icon: Icons.check),
                        for (final label in witches)
                          Tag('$label · 魔女',
                              color: context.palette.danger,
                              background: context.palette.dangerSoft),
                      ],
                    ),
                  ],
                ),
              ),
              if (onTap != null)
                 Icon(
                  Icons.chevron_right,
                  size: 20,
                  color: context.palette.textTertiary,
                ),
            ],
          ),
        ),
      ),
    );
  }
}

/// 从服务端已授权的字段解出「当前使用的牌」与「下层牌」。
/// 主持人/观战视角用 `cards` 与 `current_card_id`，其他视角回落到公开的
/// `avatar_role_id`/`previous_role_id`，不猜测未公开的牌。
({String? current, String? other}) dualRoleIds(Map<String, dynamic> seat) {
  final cards = seat['cards'];
  final currentId = seat['current_card_id']?.toString();
  if (cards is List && cards.isNotEmpty) {
    Map<dynamic, dynamic>? active;
    Map<dynamic, dynamic>? idle;
    for (final raw in cards) {
      if (raw is! Map) continue;
      if (active == null &&
          currentId != null &&
          raw['id']?.toString() == currentId) {
        active = raw;
      } else {
        idle ??= raw;
      }
    }
    active ??= cards.first is Map ? cards.first as Map : null;
    return (
      current: active?['role_id']?.toString(),
      other: idle?['role_id']?.toString(),
    );
  }
  return (
    current: seat['avatar_role_id']?.toString(),
    other: seat['previous_role_id']?.toString(),
  );
}

/// 每席两张圆头像，约 50% 重叠，当前使用的牌在上层。
/// `size` 是单张头像直径，`overlap` 是两张的重叠宽度；紧凑入口按比例一起缩小。
class DualAvatar extends StatelessWidget {
  const DualAvatar({
    super.key,
    required this.seat,
    required this.alive,
    this.size = 46,
    this.overlap = 24,
  });

  final Map<String, dynamic> seat;
  final bool alive;
  final double size;
  final double overlap;

  @override
  Widget build(BuildContext context) {
    final roles = dualRoleIds(seat);
    final current = roles.current;
    final other = roles.other;
    final avatars = SizedBox(
      width: size + overlap,
      height: size,
      child: Stack(
        clipBehavior: Clip.none,
        children: [
          Positioned(
              left: 0,
              top: 2,
              child: _LayeredAvatar(
                  roleId: other,
                  size: size,
                  dead: !alive,
                  front: false,
                  overlap: overlap)),
          Positioned(
              left: overlap,
              top: 0,
              child: _LayeredAvatar(
                  roleId: current,
                  size: size,
                  dead: !alive,
                  front: true,
                  overlap: overlap)),
        ],
      ),
    );
    return Tooltip(
      message: current == null
          ? '未公开'
          : '当前牌：${roleVisual(current)?.name ?? current}',
      child: avatars,
    );
  }
}

class _LayeredAvatar extends StatelessWidget {
  const _LayeredAvatar({
    required this.roleId,
    required this.size,
    required this.dead,
    required this.front,
    required this.overlap,
  });

  final String? roleId;
  final double size;
  final bool dead;
  final bool front;

  /// 两张头像的重叠宽度，用来按比例决定描边粗细。
  final double overlap;

  @override
  Widget build(BuildContext context) => Container(
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: context.palette.surface,
          boxShadow: front
              ? [
                  BoxShadow(
                      color: Colors.black.withValues(alpha: .10),
                      blurRadius: 6,
                      offset:  Offset(0, 2))
                ]
              : null,
        ),
        child: RoleAvatar(
          roleId: roleId,
          size: size,
          dead: dead,
          border: Border.all(
            color: front ? context.palette.accent : context.palette.border,
            // 桌上大图保持原观感；紧凑入口按尺寸等比收细，避免糊成一团。
            width: overlap >= 23 ? (front ? 2 : 1.5) : 1.25,
          ),
        ),
      );
}

/// 截止时间：服务端给的是 Unix 秒浮点，直接渲染会变成
/// 「请在 1771234567.89 前完成操作」。统一换算成本机时间显示。
String _deadlineText(Object? value) {
  final epoch = value is num ? value.toDouble() : double.tryParse('$value');
  if (epoch == null) return '规定时间';
  return formatMessageTime(
    DateTime.fromMillisecondsSinceEpoch((epoch * 1000).round(), isUtc: true)
        .toIso8601String(),
  );
}

/// 我的页：账号、双牌、退出。
class ProfilePage extends StatelessWidget {
  const ProfilePage({
    super.key,
    required this.store,
    this.bottomInset = AppSpacing.bottomBar,
  });
  final GameStore store;

  /// 底部为悬浮底栏预留的高度；宽屏由外壳传入更小的值。
  final double bottomInset;

  @override
  Widget build(BuildContext context) {
    final view = store.view!;
    final self = view.self;
    final cards = self['cards'] is List ? self['cards'] as List : const [];
    final currentId = self['current_card_id']?.toString();
    final public = view.public;
    final declarations = public["declarations"] is List
        ? public["declarations"] as List
        : const [];
    final actor = store.actor!;
    return ListView(
      padding: EdgeInsets.fromLTRB(
        AppSpacing.lg,
        AppSpacing.sm,
        AppSpacing.lg,
        bottomInset,
      ),
      children: [
        Card(
          child: Padding(
            padding: const EdgeInsets.all(AppSpacing.lg),
            child: Row(
              children: [
                AppLogo(size: 52),
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        actor.name,
                        style:  TextStyle(
                            fontSize: 17,
                            fontWeight: FontWeight.w600,
                            color: context.palette.text),
                      ),
                       SizedBox(height: 2),
                      Text(
                        actor.isHost
                            ? '主持人'
                            : actor.isSpectator
                                ? '观战者 · 只读牌桌'
                                : '${actor.seatId ?? '-'} 号玩家',
                        style:  TextStyle(
                            fontSize: 13, color: context.palette.textTertiary),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
        if (view.statuses.isNotEmpty) ...[
           SectionTitle('当前状态', subtitle: '状态与权限由服务器实时计算。'),
          for (final status in view.statuses)
            Card(
              color: switch (status['tone']?.toString()) {
                'danger' => context.palette.dangerSoft,
                'warning' => context.palette.warningSoft,
                'success' => context.palette.successSoft,
                _ => context.palette.accentSoft,
              },
              child: ListTile(
                title: Text(status['title']?.toString() ?? ''),
                subtitle: Text(status['text']?.toString() ?? ''),
              ),
            ),
          const SizedBox(height: AppSpacing.sm),
        ],
        // 13 水是本席位的只读状态：本夜持有就常驻显示，夜末过期后自动消失。
        if (self['water'] == true) ...[
          Card(
            color: context.palette.accentSoft,
            child: ListTile(
              leading: Icon(Icons.water_drop_outlined,
                  color: context.palette.accent),
              title: const Text('持有本夜13水（本夜未用会过期）'),
              subtitle: const Text('使用后直接进入本夜预结算，无需主持人裁定。'),
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
        ],
        if (declarations.isNotEmpty) ...[
          const SectionTitle('当前公开技能声明', subtitle: '开放声明可在行动面板质疑。'),
          for (final raw in declarations)
            if (raw is Map)
              Card(
                child: ListTile(
                  title: Text('${raw['seat_id']}号 · ${raw['label'] ?? ''}'),
                  subtitle: Text('${raw['summary'] ?? ''} · ${raw['status'] == 'open' ? '可质疑' : '已停止'}'),
                ),
              ),
           SizedBox(height: AppSpacing.sm),
        ],
        // 当日目击名单：服务端只在白天到投票结束前后发给死者与主持人，常驻卡片显示。
        if (view.raw['witness'] is Map) ...[
           SectionTitle(
            '当日目击名单',
            subtitle: '昨夜出局者的目击结果，投票结束前常驻。',
          ),
          Card(
            color: context.palette.accentSoft,
            child: Padding(
              padding:  EdgeInsets.all(AppSpacing.lg),
              child: Row(
                children: [
                   Icon(Icons.visibility_outlined,
                      size: 20, color: context.palette.accent),
                   SizedBox(width: AppSpacing.md),
                  Expanded(
                    child: Text(
                      view.raw['witness']['text']?.toString() ?? '',
                      style:  TextStyle(
                        fontSize: 15,
                        fontWeight: FontWeight.w600,
                        color: context.palette.text,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
          const SizedBox(height: AppSpacing.md),
        ],
        SectionTitle(
          '我的双牌',
          subtitle: actor.isSpectator ? '观战身份没有个人角色牌' : '当前使用的牌在上层。',
        ),
        if (cards.isEmpty)
          const EmptyState(
              icon: Icons.style_outlined,
              title: '还没有角色牌',
              detail: '全员首次准备后系统才会私下发牌。')
        else
          for (final raw in cards)
            if (raw is Map)
              Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                child: _OwnCard(
                  card:
                      raw.map((key, value) => MapEntry(key.toString(), value)),
                  isCurrent: raw['id']?.toString() == currentId,
                ),
              ),
        // 可可魔典、玛格破译、雪莉绑定、13水、证物等私密情报都在 view.information 里；
        // 服务端已按权限裁剪，这里按收到顺序逐条留档，玩家不必翻聊天记录。
        if (view.raw['information'] is List &&
            (view.raw['information'] as List).isNotEmpty) ...[
          const SectionTitle(
            '私密情报记录',
            subtitle: '仅你能看到；按收到顺序保留。',
          ),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(AppSpacing.md),
              child: Column(
                children: [
                  for (final raw in view.raw['information'] as List)
                    if (raw is Map)
                      Padding(
                        padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              raw['title']?.toString() ?? '游戏信息',
                              style:  TextStyle(
                                  fontSize: 13,
                                  fontWeight: FontWeight.w600,
                                  color: context.palette.textSecondary),
                            ),
                            if (raw['text']?.toString().isNotEmpty == true)
                              Text(
                                raw['text'].toString(),
                                style:  TextStyle(
                                    fontSize: 14, color: context.palette.text),
                              ),
                          ],
                        ),
                      ),
                ],
              ),
            ),
          ),
        ],
        if (self['honoka_upper'] is List) ...[
          const SectionTitle(
            '已准备玩家的上层角色',
            subtitle: '穗乃香开局前获知，仅你看得到。',
          ),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(AppSpacing.md),
              child: Column(
                children: [
                  for (final raw in self['honoka_upper'] as List)
                    if (raw is Map)
                      ListTile(
                        dense: true,
                        contentPadding: EdgeInsets.zero,
                        title: Text(
                          '${raw['seat_id']}号 ${raw['name']}',
                          style:  TextStyle(
                              fontSize: 14, color: context.palette.text),
                        ),
                        trailing: Text(
                          roleVisual(raw['role_id']?.toString())?.name ??
                              raw['role_id']?.toString() ??
                              '未知',
                          style:  TextStyle(
                              fontSize: 14,
                              fontWeight: FontWeight.w600,
                              color: context.palette.accent),
                        ),
                      ),
                ],
              ),
            ),
          ),
        ],
        if (self['warning_deadline'] != null) ...[
           SizedBox(height: AppSpacing.md),
          Card(
            color: context.palette.dangerSoft,
            child: Padding(
              padding:  EdgeInsets.all(AppSpacing.lg),
              child: Row(
                children: [
                   Icon(Icons.timer_outlined, color: context.palette.danger),
                   SizedBox(width: AppSpacing.md),
                  Expanded(
                    child: Text(
                      '主持人已警告，请在 ${_deadlineText(self['warning_deadline'])} 前完成操作。',
                      style:
                           TextStyle(fontSize: 13, color: context.palette.text),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
        const SizedBox(height: AppSpacing.xl),
        OutlinedButton.icon(
          onPressed: store.logout,
          icon: const Icon(Icons.logout, size: 18),
          label: const Text('退出登录'),
        ),
      ],
    );
  }
}

class _OwnCard extends StatelessWidget {
  const _OwnCard({required this.card, required this.isCurrent});
  final Map<String, dynamic> card;
  final bool isCurrent;

  @override
  Widget build(BuildContext context) {
    final role = roleVisual(card['role_id']?.toString());
    final alive = card['alive'] != false;
    final uses = card['uses'];
    return Card(
      child: Container(
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(AppRadius.card),
          border: Border.all(
              color: isCurrent ? context.palette.accent : Colors.transparent,
              width: 2),
        ),
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Row(
          children: [
            RoleAvatar(
                roleId: card['role_id']?.toString(), size: 56, dead: !alive),
            const SizedBox(width: AppSpacing.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Text(
                        role?.name ?? card['role_id']?.toString() ?? '未知',
                        style:  TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.w600,
                            color: context.palette.text),
                      ),
                      const SizedBox(width: AppSpacing.sm),
                      if (isCurrent) Tag('当前上层'),
                    ],
                  ),
                   SizedBox(height: AppSpacing.xs),
                  Wrap(
                    spacing: AppSpacing.sm,
                    runSpacing: AppSpacing.xs,
                    children: [
                      Tag(
                        alive ? '存活' : '已出局',
                        color:
                            alive ? context.palette.success : context.palette.textSecondary,
                        background: alive
                            ? context.palette.successSoft
                            : context.palette.surfaceMuted,
                      ),
                      if (card['witch'] == true)
                         Tag('魔女化',
                            color: context.palette.danger,
                            background: context.palette.dangerSoft),
                      if (card['injured'] == true)
                         Tag('负伤',
                            color: context.palette.warning,
                            background: context.palette.warningSoft),
                      if (uses is Map && uses.isNotEmpty)
                        Tag(
                          uses.entries
                              .map((e) => '${e.key} ${e.value}')
                              .join(' · '),
                          color: context.palette.textSecondary,
                          background: context.palette.surfaceMuted,
                        ),
                    ],
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// 主持人管理页：待办 / 流程 / 玩家 / 私密信息 / 纠错 + 席位代操作。
class HostManagementPage extends StatefulWidget {
  const HostManagementPage({
    super.key,
    required this.store,
    this.bottomInset = AppSpacing.bottomBar,
  });
  final GameStore store;

  /// 底部为悬浮底栏预留的高度；宽屏由外壳传入更小的值。
  final double bottomInset;

  @override
  State<HostManagementPage> createState() => _HostManagementPageState();
}

class _HostManagementPageState extends State<HostManagementPage> {
  static const groups = ['当前待办', '流程', '玩家', '私密信息', '纠错'];

  /// 代操作入口的状态：已读取的席位行动数（null 表示还没有读取结果），
  /// 以及正在读取视角的席位。读取结果按对局版本缓存，版本一变就作废。
  final Map<String, int> _seatActionCounts = <String, int>{};
  String? _loadingSeat;
  int _countsVersion = -1;

  GameStore get _store => widget.store;

  @override
  void initState() {
    super.initState();
    // 首帧后再预读，避免在 build 期间触发网络与状态更新。
    WidgetsBinding.instance.addPostFrameCallback((_) => _preloadSeatActions());
  }

  /// 预读各席位的视角，把可代操作的行动数直接显示在入口上。
  /// 预读失败（离线、预览、服务端拒绝）不打扰主持人，点击时再给出真实原因。
  Future<void> _preloadSeatActions() async {
    if (!mounted) return;
    final store = _store;
    if (store.api == null || store.view == null) return;
    final seats = store.view!.seats
        .where((seat) => seat['occupied'] == true)
        .toList(growable: false);
    for (final seat in seats) {
      final id = seat['id']?.toString();
      if (id == null) continue;
      try {
        await _refreshSeatActions(id);
      } on ApiException {
        return;
      }
      if (!mounted) return;
    }
  }

  /// 读取一个席位的视角并只保留可代操作的行动；返回过滤后的列表。
  Future<List<ActionDescriptor>> _refreshSeatActions(String seatId,
      {bool showProgress = false}) async {
    final store = _store;
    if (showProgress && mounted) setState(() => _loadingSeat = seatId);
    try {
      final perspective = await store.seatPerspective(seatId);
      final actions = seatActionsOf(perspective.actions);
      if (!mounted) return actions;
      setState(() {
        if (store.view != null) _countsVersion = store.view!.version;
        _seatActionCounts[seatId] = actions.length;
      });
      return actions;
    } finally {
      // 无论成功还是失败都清掉进度；失败原因由调用方提示。
      if (mounted && _loadingSeat == seatId) {
        setState(() => _loadingSeat = null);
      }
    }
  }

  Map<String, _SeatTileSlot> get _seatTiles {
    final store = _store;
    final view = store.view;
    if (view == null) return const {};
    if (_countsVersion != view.version) {
      _countsVersion = view.version;
      _seatActionCounts.clear();
    }
    return {
      for (final seat in view.seats)
        if (seat['id'] != null)
          seat['id'].toString(): _SeatTileSlot(
            loading: _loadingSeat == seat['id'].toString(),
            count: _seatActionCounts[seat['id'].toString()],
          ),
    };
  }

  @override
  Widget build(BuildContext context) {
    final store = widget.store;
    final view = store.view!;
    final tasks =
        view.host['tasks'] is List ? view.host['tasks'] as List : const [];
    final blocking =
        tasks.where((task) => task is Map && task['blocking'] == true).length;
    final codex = view.host['codex'] is List
        ? (view.host['codex'] as List).map((e) => e.toString()).toList()
        : const <String>[];

    final buckets = <String, List<ActionDescriptor>>{
      for (final name in groups) name: []
    };
    final seen = <String>{};
    for (final action in view.allActions) {
      if (!seen.add(action.protocolKey)) continue;
      buckets[_groupOf(action)]!.add(action);
    }

    return ListView(
      padding: EdgeInsets.fromLTRB(
        AppSpacing.lg,
        AppSpacing.sm,
        AppSpacing.lg,
        widget.bottomInset,
      ),
      children: [
        Card(
          color: blocking > 0 ? context.palette.dangerSoft : context.palette.successSoft,
          child: Padding(
            padding:  EdgeInsets.all(AppSpacing.lg),
            child: Row(
              children: [
                Icon(
                  blocking > 0
                      ? Icons.pending_actions_outlined
                      : Icons.check_circle_outline,
                  color: blocking > 0 ? context.palette.danger : context.palette.success,
                ),
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '${view.phaseLabel} · 第 ${view.day} 日',
                        style:  TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.w600,
                            color: context.palette.text),
                      ),
                       SizedBox(height: 2),
                      Text(
                        blocking > 0 ? '有 $blocking 项待办阻塞推进' : '没有阻塞项，可以推进',
                        style:  TextStyle(
                            fontSize: 13, color: context.palette.textSecondary),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
        SectionTitle(
          '本局魔典',
          subtitle:
              codex.isEmpty ? '未读取到魔典名单' : '共 ${codex.length} 名角色，开场时随机排列。',
        ),
        Card(
          child: Padding(
            padding:  EdgeInsets.all(AppSpacing.md),
            child: codex.isEmpty
                ?  Text('未读取到魔典名单',
                    style: TextStyle(color: context.palette.textTertiary))
                : Wrap(
                    spacing: AppSpacing.sm,
                    runSpacing: AppSpacing.sm,
                    children: [
                      for (final id in codex)
                        Chip(
                          avatar: RoleAvatar(roleId: id, size: 22),
                          label: Text(roleVisual(id)?.name ?? id),
                        ),
                    ],
                  ),
          ),
        ),
        for (final group in groups) ...[
          SectionTitle(group),
          if (group == '当前待办')
            if (tasks.isEmpty)
               Card(
                child: Padding(
                  padding: EdgeInsets.all(AppSpacing.lg),
                  child: Text('当前没有待办。',
                      style: TextStyle(color: context.palette.textTertiary)),
                ),
              )
            else
              for (final raw in tasks)
                if (raw is Map)
                  Padding(
                    padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                    child: _TaskCard(
                      task: raw
                          .map((key, value) => MapEntry(key.toString(), value)),
                      store: store,
                      onRun: (actionId, payload) => _runTask(actionId, payload),
                    ),
                  ),
          if (buckets[group]!.isNotEmpty)
            Wrap(
              spacing: AppSpacing.sm,
              runSpacing: AppSpacing.sm,
              children: [
                for (final action in buckets[group]!)
                  ActionChipButton(
                    action: action,
                    busy: store.writeBusy,
                    onTap: () => showActionForm(context, store, action),
                  ),
              ],
            )
          else if (group != '当前待办')
             Padding(
              padding: EdgeInsets.symmetric(vertical: AppSpacing.sm),
              child: Text('当前无可用操作',
                  style:
                      TextStyle(color: context.palette.textTertiary, fontSize: 13)),
            ),
        ],
        SectionTitle('对局日志', subtitle: '仅主持人可见；按时间记录全部关键操作。'),
        if (view.host['log'] is List &&
            (view.host['log'] as List).isNotEmpty)
          Card(
            child: Padding(
              padding: const EdgeInsets.all(AppSpacing.md),
              child: Column(
                children: [
                  for (final raw in view.host['log'] as List)
                    if (raw is Map)
                      Padding(
                        padding: const EdgeInsets.only(bottom: AppSpacing.xs),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              '第${raw['day']}天',
                              style:  TextStyle(
                                  fontSize: 12,
                                  color: context.palette.textTertiary),
                            ),
                            const SizedBox(width: AppSpacing.sm),
                            Expanded(
                              child: Text(
                                raw['text']?.toString() ?? '',
                                style: TextStyle(
                                  fontSize: 13,
                                  height: 1.45,
                                  color: _logColor(context,
                                      raw['kind']?.toString()),
                                ),
                              ),
                            ),
                          ],
                        ),
                      ),
                ],
              ),
            ),
          )
        else
           Card(
            child: Padding(
              padding: EdgeInsets.all(AppSpacing.lg),
              child: Text('还没有日志记录。',
                  style: TextStyle(color: context.palette.textTertiary)),
            ),
          ),
        SectionTitle('席位代操作', subtitle: '先读取该席位当前视角，再提交它实际可用的行动。'),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(AppSpacing.md),
            child: _seatTiles.isNotEmpty
                ? Wrap(
                    spacing: AppSpacing.sm,
                    runSpacing: AppSpacing.sm,
                    children: [
                      for (final seat in view.seats)
                        _SeatActionTile(
                          seat: seat,
                          slot: _seatTiles[seat['id']?.toString()],
                          onTap: seat['occupied'] == true && !store.writeBusy
                              ? () => _seatActions(seat['id'].toString())
                              : null,
                        ),
                    ],
                  )
                :  Text('本局还没有可以代操作的席位。',
                    style:
                        TextStyle(fontSize: 13, color: context.palette.textTertiary)),
          ),
        ),
      ],
    );
  }

  static Color _logColor(BuildContext context, String? kind) => switch (kind) {
        'death' => context.palette.danger,
        'vote' => context.palette.host,
        'phase' => context.palette.accent,
        'system' => context.palette.info,
        'host' => context.palette.textTertiary,
        _ => context.palette.textSecondary,
      };

  /// 主持人待办可能同时存在多条同动作条目（多份 host.resolve 裁定并存）。
  /// 必须按待办自带的 payload 匹配动作描述：只按 id 兜底到第一个会把
  /// A 待办的表单提交成 B 待办的裁定；找不到匹配说明视图已过期，禁止兜底。
  Future<void> _runTask(String actionId, Map<String, dynamic> payload) async {
    final candidates = (widget.store.view?.allActions ??
            const <ActionDescriptor>[])
        .where((item) => item.id == actionId)
        .toList();
    ActionDescriptor? matched;
    for (final action in candidates) {
      final matches = payload.entries.every(
        (entry) => action.payload[entry.key] == entry.value,
      );
      if (matches) {
        matched = action;
        break;
      }
    }
    if (!mounted) return;
    if (matched == null) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('该待办已变化，请刷新状态后重试')),
      );
      return;
    }
    await showActionForm(context, widget.store, matched, initial: payload);
  }

  Future<void> _seatActions(String seatId) async {
    final store = widget.store;
    if (_loadingSeat != null) return;
    try {
      // 优先用预读结果；没有预读结果才在点击时读一次，并显示读取进度。
      final actions = _seatActionCounts.containsKey(seatId)
          ? seatActionsOf((await store.seatPerspective(seatId)).actions)
          : await _refreshSeatActions(seatId, showProgress: true);
      if (!mounted) return;
      if (actions.isEmpty) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('该席位当前没有可代操作的行动')),
        );
        return;
      }
      final picked = await showActionPicker(
        context,
        actions: actions,
        title: '$seatId 号当前行动',
      );
      if (picked == null || !mounted) return;
      await showActionForm(context, store, picked, asSeat: seatId);
    } on ApiException catch (failure) {
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(SnackBar(content: Text(failure.message)));
      }
    }
  }

  static String _groupOf(ActionDescriptor action) {
    final value = '${action.group}:${action.id}';
    if (value.contains('待办') ||
        value.contains('warning') ||
        action.raw['blocking'] == true) {
      return '当前待办';
    }
    if (value.contains('私密') ||
        value.contains('channel') ||
        value.contains('information')) {
      return '私密信息';
    }
    if (value.contains('纠错') ||
        value.contains('snapshot') ||
        value.contains('rewind')) {
      return '纠错';
    }
    if (value.contains('房间管理') ||
        value.contains('room.') ||
        value.contains('玩家') ||
        value.contains('surrender')) {
      return '玩家';
    }
    return '流程';
  }
}

/// 席位代操作里可提交的行动：频道动作属于私信管理，不属于该席位的游戏行动。
List<ActionDescriptor> seatActionsOf(Iterable<ActionDescriptor> actions) =>
    actions.where((action) => !action.id.startsWith('channel.')).toList();

/// 代操作入口的读取状态：`count` 为空表示还没读到该席位的视角。
class _SeatTileSlot {
  const _SeatTileSlot({this.loading = false, this.count});

  final bool loading;
  final int? count;
}

/// 单个席位的代操作入口：双头像 + 席位号 + 当前可代操作的行动数。
/// 只显示服务端已授权的牌面；未占用的席位不可点击。
class _SeatActionTile extends StatelessWidget {
  const _SeatActionTile({required this.seat, this.slot, this.onTap});

  static const double width = 104;
  static const double _avatarSize = 30;

  final Map<String, dynamic> seat;
  final _SeatTileSlot? slot;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final id = seat['id']?.toString() ?? '-';
    final occupied = seat['occupied'] == true;
    final alive = seat['alive'] != false;
    final name = seat['name']?.toString() ?? '';
    final loading = slot?.loading == true;
    final count = slot?.count;
    final enabled = onTap != null;

    final stripWidth = _avatarSize * 1.5;
    final strip = SizedBox(
      width: stripWidth,
      height: _avatarSize,
      child: occupied
          ? DualAvatar(
              seat: seat,
              alive: alive,
              size: _avatarSize,
              overlap: _avatarSize * .5,
            )
          : Center(
              child: Container(
                width: _avatarSize,
                height: _avatarSize,
                alignment: Alignment.center,
                decoration: BoxDecoration(
                  shape: BoxShape.circle,
                  color: context.palette.surfaceMuted,
                  border: Border.all(color: context.palette.border, width: 1.5),
                ),
                child:  Text('?',
                    style: TextStyle(
                        fontSize: _avatarSize * .45,
                        fontWeight: FontWeight.w600,
                        color: context.palette.textTertiary)),
              ),
            ),
    );

    final (String value, Color valueColor) = !occupied
        ? ('空席', context.palette.textTertiary)
        : !alive
            ? ('已出局', context.palette.textSecondary)
            : loading
                ? ('读取中', context.palette.textTertiary)
                : count == null
                    ? ('点击读取', context.palette.textTertiary)
                    : count == 0
                        ? ('无可用行动', context.palette.textTertiary)
                        : ('$count 项行动', context.palette.accent);

    return Semantics(
      button: enabled,
      enabled: enabled,
      label: '$id 号${occupied ? ' · ${name.isEmpty ? '等待命名' : name}' : ' · 空席'}'
          '${count != null ? ' · $value' : ''}',
      child: Tooltip(
        message: occupied
            ? '$id 号${name.isEmpty ? '' : ' · $name'}；${slot?.count == null ? '点击读取该席位视角' : value}'
            : '$id 号空席，暂无可代操作的身份',
        child: Material(
          color: context.palette.surfaceMuted,
          borderRadius: BorderRadius.circular(AppRadius.field),
          child: InkWell(
            borderRadius: BorderRadius.circular(AppRadius.field),
            onTap: onTap,
            child: Container(
              width: width,
              padding:  EdgeInsets.symmetric(
                  horizontal: AppSpacing.sm, vertical: AppSpacing.sm),
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(AppRadius.field),
                border: Border.all(
                  color: enabled ? context.palette.border : context.palette.borderStrong,
                ),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      Text('$id 号',
                          style: TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                            color: enabled
                                ? context.palette.text
                                : context.palette.textTertiary,
                          )),
                       Spacer(),
                      if (loading)
                         SizedBox(
                          width: 12,
                          height: 12,
                          child: CircularProgressIndicator(strokeWidth: 2),
                        )
                      else if (count == 0)
                         Icon(Icons.check_rounded,
                            size: 13, color: context.palette.textTertiary)
                      else if (count != null)
                        Container(
                          padding:  EdgeInsets.symmetric(
                              horizontal: 5, vertical: 1),
                          decoration: BoxDecoration(
                            color: context.palette.accentSoft,
                            borderRadius: BorderRadius.circular(AppRadius.chip),
                          ),
                          child: Text('$count',
                              style:  TextStyle(
                                fontSize: 11,
                                fontWeight: FontWeight.w600,
                                color: context.palette.accent,
                              )),
                        ),
                    ],
                  ),
                  const SizedBox(height: AppSpacing.xs),
                  Row(
                    children: [
                      strip,
                      const SizedBox(width: AppSpacing.sm),
                      Expanded(
                        child: Text(
                          occupied ? (name.isEmpty ? '等待命名' : name) : '—',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: TextStyle(
                            fontSize: 12,
                            color: enabled
                                ? context.palette.textSecondary
                                : context.palette.textTertiary,
                          ),
                        ),
                      ),
                    ],
                  ),
                   SizedBox(height: 6),
                  Text(value,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w600,
                        color: enabled ? valueColor : context.palette.textTertiary,
                      )),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _TaskCard extends StatelessWidget {
  const _TaskCard(
      {required this.task, required this.store, required this.onRun});

  final Map<String, dynamic> task;
  final GameStore store;
  final void Function(String actionId, Map<String, dynamic> payload) onRun;

  @override
  Widget build(BuildContext context) {
    final actionId = task['action']?.toString() ?? '';
    final payload = task['payload'] is Map
        ? (task['payload'] as Map)
            .map((key, value) => MapEntry(key.toString(), value))
        : <String, dynamic>{};
    final blocking = task['blocking'] == true;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(AppSpacing.md),
        child: Row(
          children: [
            ActionIconBadge(
                actionId: actionId, group: '待办', danger: blocking, size: 40),
            const SizedBox(width: AppSpacing.md),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    task['title']?.toString() ?? '',
                    style:  TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                        color: context.palette.text),
                  ),
                  if (task['detail']?.toString().isNotEmpty == true) ...[
                     SizedBox(height: 2),
                    Text(
                      task['detail'].toString(),
                      style:  TextStyle(
                          fontSize: 12, color: context.palette.textTertiary),
                    ),
                  ],
                ],
              ),
            ),
            if (blocking)
               Padding(
                padding: EdgeInsets.only(right: AppSpacing.md),
                child: Tag('阻塞',
                    color: context.palette.danger, background: context.palette.dangerSoft),
              ),
            TextButton(
              onPressed: actionId.isEmpty || store.writeBusy
                  ? null
                  : () => onRun(actionId, payload),
              child: const Text('处理'),
            ),
          ],
        ),
      ),
    );
  }
}
