import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'action_sheet.dart';
import 'app_icons.dart';
import 'design.dart';
import 'models.dart';
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
  int index = 0;
  int lastActions = 0;
  int lastWarnings = 0;
  AppLifecycleState lifecycle = AppLifecycleState.resumed;

  bool get host => widget.store.actor!.isHost;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    lastActions = widget.store.newActionCount;
    lastWarnings = widget.store.warningCount;
    widget.store.addListener(onStoreChanged);
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
    if (mounted) setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final store = widget.store;
    final pages = <Widget>[
      ChatActionPage(store: store),
      BoardPage(store: store),
      if (host) HostManagementPage(store: store) else ProfilePage(store: store),
    ];
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
    return Scaffold(
      extendBody: true,
      appBar: AppBar(
        title: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              store.view!.phaseLabel,
              style: const TextStyle(
                  fontSize: 17,
                  fontWeight: FontWeight.w600,
                  color: AppColors.text),
            ),
            Text(
              '第 ${store.view!.day} 日 · ${store.view!.half == 'night' ? '夜间' : '白天'}',
              style:
                  const TextStyle(fontSize: 12, color: AppColors.textTertiary),
            ),
          ],
        ),
        actions: [
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
                        ? AppColors.successSoft
                        : AppColors.warningSoft,
                    shape: BoxShape.circle,
                  ),
                  child: Icon(
                    store.connectionStatus == '已连接'
                        ? Icons.cloud_done_outlined
                        : Icons.cloud_off_outlined,
                    size: 18,
                    color: store.connectionStatus == '已连接'
                        ? AppColors.success
                        : AppColors.warning,
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
      body: Stack(
        children: [
          IndexedStack(index: index, children: pages),
          if (store.pendingPhaseKey != null) PhaseOverlay(store: store),
        ],
      ),
      bottomNavigationBar: SafeArea(
        minimum: const EdgeInsets.fromLTRB(20, 0, 20, 14),
        child: Material(
          elevation: 10,
          shadowColor: Colors.black.withValues(alpha: .10),
          color: AppColors.surface,
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
                        ? AppColors.danger
                        : AppColors.accent,
                    child: Icon(icons[item]),
                  ),
                  label: labels[item],
                ),
            ],
          ),
        ),
      ),
    );
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
            reduceMotion ? Duration.zero : const Duration(milliseconds: 260),
        child: ColoredBox(
          color: AppColors.surface,
          child: Center(
            child: AnimatedScale(
              scale: shown ? 1 : .92,
              duration: reduceMotion
                  ? Duration.zero
                  : const Duration(milliseconds: 340),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Container(
                    width: 88,
                    height: 88,
                    decoration: BoxDecoration(
                      color: night ? AppColors.accentSoft : AppColors.hostSoft,
                      shape: BoxShape.circle,
                    ),
                    child: Icon(
                      night ? Icons.nightlight_round : Icons.wb_sunny_outlined,
                      size: 40,
                      color: night ? AppColors.accent : AppColors.host,
                    ),
                  ),
                  const SizedBox(height: AppSpacing.xl),
                  Text(
                    '第 ${view.day} 日',
                    style: const TextStyle(
                        fontSize: 15, color: AppColors.textTertiary),
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  Text(
                    view.phaseLabel,
                    style: const TextStyle(
                        fontSize: 30,
                        fontWeight: FontWeight.w700,
                        color: AppColors.text),
                  ),
                  const SizedBox(height: AppSpacing.sm),
                  Text(
                    night ? '夜间' : '白天',
                    style: const TextStyle(
                        fontSize: 14, color: AppColors.textSecondary),
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
  const ChatActionPage({super.key, required this.store});
  final GameStore store;

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
    final keyboard = MediaQuery.viewInsetsOf(context).bottom > 0;
    final channel = store.selectedChannel;
    return Column(
      children: [
        SizedBox(
          height: 54,
          child: ListView(
            padding: const EdgeInsets.fromLTRB(
                AppSpacing.md, AppSpacing.sm, AppSpacing.md, AppSpacing.sm),
            scrollDirection: Axis.horizontal,
            children: [
              for (final entry in scopes.entries)
                Padding(
                  padding: const EdgeInsets.only(right: AppSpacing.sm),
                  child: FilterChip(
                    avatar: Icon(
                      entry.value.$2,
                      size: 15,
                      color: store.messageScope == entry.key
                          ? AppColors.accent
                          : AppColors.textTertiary,
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
                    return MessageBubble(message: item, self: store.actor?.id);
                  },
                ),
        ),
        _Composer(
          store: store,
          channel: channel,
          controller: message,
          keyboard: keyboard,
          actions: actions,
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
    required this.keyboard,
    required this.actions,
    required this.onSend,
    required this.onClearError,
    this.error,
  });

  final GameStore store;
  final GameChannel? channel;
  final TextEditingController controller;
  final bool keyboard;
  final List<ActionDescriptor> actions;
  final VoidCallback onSend;
  final VoidCallback onClearError;
  final String? error;

  @override
  Widget build(BuildContext context) {
    final canSend = channel?.canSend == true && !store.writeBusy;
    return Material(
      color: AppColors.surface,
      child: SafeArea(
        top: false,
        minimum: const EdgeInsets.fromLTRB(
            AppSpacing.md, AppSpacing.sm, AppSpacing.md, AppSpacing.bottomBar),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            if (actions.isNotEmpty)
              SizedBox(
                height: 42,
                child: keyboard
                    ? Align(
                        alignment: Alignment.centerLeft,
                        child: Badge.count(
                          count: actions.length,
                          backgroundColor: AppColors.accent,
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
            const SizedBox(height: AppSpacing.sm),
            Row(
              children: [
                _ChannelButton(store: store, channel: channel),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: TextField(
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
                      contentPadding: const EdgeInsets.symmetric(
                          horizontal: 16, vertical: 12),
                    ),
                    onChanged: (_) => onClearError(),
                    onSubmitted: (_) => onSend(),
                  ),
                ),
                const SizedBox(width: AppSpacing.sm),
                _SendButton(enabled: canSend, onSend: onSend),
              ],
            ),
            if (!canSend && (channel?.reason.isNotEmpty ?? false))
              Padding(
                padding: const EdgeInsets.only(top: AppSpacing.sm),
                child: Row(
                  children: [
                    const Icon(Icons.info_outline,
                        size: 14, color: AppColors.textTertiary),
                    const SizedBox(width: AppSpacing.xs),
                    Expanded(
                      child: Text(
                        channel!.reason,
                        style: const TextStyle(
                            fontSize: 12, color: AppColors.textTertiary),
                      ),
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
    final channels = store.view!.channels;
    final label = channel?.label ?? '公开讨论';
    return Tooltip(
      message: '选择发送频道',
      child: Material(
        color: AppColors.surfaceMuted,
        borderRadius: BorderRadius.circular(AppRadius.field),
        child: InkWell(
          borderRadius: BorderRadius.circular(AppRadius.field),
          onTap: channels.isEmpty
              ? null
              : () async {
                  final picked = await showModalBottomSheet<GameChannel>(
                    context: context,
                    useSafeArea: true,
                    builder: (context) => _ChannelSheet(store: store),
                  );
                  if (picked != null) store.selectChannel(picked.id);
                },
          child: Container(
            height: 46,
            padding: const EdgeInsets.symmetric(horizontal: 12),
            constraints: const BoxConstraints(maxWidth: 132),
            child: Row(
              children: [
                Icon(
                  channel?.id == 'public'
                      ? Icons.campaign_outlined
                      : channel?.id == 'system'
                          ? Icons.info_outline
                          : Icons.lock_outline,
                  size: 16,
                  color: AppColors.textSecondary,
                ),
                const SizedBox(width: 6),
                Flexible(
                  child: Text(
                    label.replaceFirst('私密 · ', ''),
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w500,
                        color: AppColors.text),
                  ),
                ),
                const Icon(Icons.expand_more,
                    size: 16, color: AppColors.textTertiary),
              ],
            ),
          ),
        ),
      ),
    );
  }
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
            const Padding(
              padding: EdgeInsets.fromLTRB(
                  AppSpacing.xl, 0, AppSpacing.xl, AppSpacing.md),
              child: Text(
                '选择发送频道',
                style: TextStyle(
                    fontSize: 20,
                    fontWeight: FontWeight.w600,
                    color: AppColors.text),
              ),
            ),
            Flexible(
              child: ListView(
                shrinkWrap: true,
                padding: const EdgeInsets.fromLTRB(
                    AppSpacing.md, 0, AppSpacing.md, AppSpacing.lg),
                children: [
                  for (final item in store.view!.channels)
                    ListTile(
                      leading: Icon(
                        item.id == 'public'
                            ? Icons.campaign_outlined
                            : item.id == 'system'
                                ? Icons.info_outline
                                : Icons.lock_outline,
                        color: item.canSend
                            ? AppColors.accent
                            : AppColors.textTertiary,
                      ),
                      title: Text(item.label),
                      subtitle: item.canSend
                          ? null
                          : Text(item.reason.isEmpty ? '只读' : item.reason),
                      trailing: item.id == store.selectedChannelId
                          ? const Icon(Icons.check, color: AppColors.accent)
                          : null,
                      enabled: item.canSend,
                      onTap: () => Navigator.pop(context, item),
                    ),
                ],
              ),
            ),
          ],
        ),
      );
}

/// 行动短名按钮：图标 + 短名。
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
    final tint = actionTint(action.group, danger: danger);
    return Tooltip(
      message: unsupported ?? action.label,
      child: Material(
        color: unsupported != null
            ? AppColors.surfaceMuted
            : tint.withValues(alpha: .10),
        borderRadius: BorderRadius.circular(AppRadius.chip),
        child: InkWell(
          borderRadius: BorderRadius.circular(AppRadius.chip),
          onTap: busy || unsupported != null ? null : onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 9),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                if (unsupported != null)
                  const Icon(Icons.block, size: 16, color: AppColors.danger)
                else
                  ActionIcon(actionId: action.id, size: 17, color: tint),
                const SizedBox(width: 7),
                Text(
                  action.shortLabel,
                  style: TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w600,
                    color: unsupported != null
                        ? AppColors.textTertiary
                        : danger
                            ? AppColors.danger
                            : AppColors.text,
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
  final picked =
      await showActionPicker(context, actions: actions, title: '当前可用行动');
  if (picked == null || !context.mounted) return;
  await showActionForm(context, store, picked);
}

/// 消息气泡：自己靠右、他人靠左、系统居中。
class MessageBubble extends StatelessWidget {
  const MessageBubble({super.key, required this.message, this.self});

  final GameMessage message;
  final String? self;

  @override
  Widget build(BuildContext context) {
    final system = message.kind != 'chat';
    if (system) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
        child: Center(
          child: Container(
            constraints: const BoxConstraints(maxWidth: 420),
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
            decoration: BoxDecoration(
              color: AppColors.surfaceMuted,
              borderRadius: BorderRadius.circular(AppRadius.chip),
            ),
            child: Text(
              message.text,
              textAlign: TextAlign.center,
              style: const TextStyle(
                  fontSize: 13, color: AppColors.textSecondary, height: 1.5),
            ),
          ),
        ),
      );
    }
    final mine = self != null && message.raw['sender_id']?.toString() == self;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
      child: Row(
        mainAxisAlignment:
            mine ? MainAxisAlignment.end : MainAxisAlignment.start,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (!mine) ...[
            RoleAvatar(roleId: message.avatarRoleId, size: 36),
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
                    child: Text(
                      message.senderName!,
                      style: const TextStyle(
                          fontSize: 12, color: AppColors.textTertiary),
                    ),
                  ),
                Container(
                  padding:
                      const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                  decoration: BoxDecoration(
                    color: mine ? AppColors.accent : AppColors.surface,
                    borderRadius: BorderRadius.circular(AppRadius.card),
                    border: mine ? null : Border.all(color: AppColors.border),
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
                                    : AppColors.textTertiary,
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
                                      : AppColors.textTertiary,
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
                          color: mine ? AppColors.onAccent : AppColors.text,
                        ),
                      ),
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
}

/// 状态页：牌桌 + 阶段信息。
class BoardPage extends StatelessWidget {
  const BoardPage({super.key, required this.store});
  final GameStore store;

  @override
  Widget build(BuildContext context) {
    final view = store.view!;
    final result = view.raw['result'];
    return ListView(
      padding: const EdgeInsets.fromLTRB(
        AppSpacing.lg,
        AppSpacing.sm,
        AppSpacing.lg,
        AppSpacing.bottomBar,
      ),
      children: [
        Card(
          child: Padding(
            padding: const EdgeInsets.all(AppSpacing.lg),
            child: Row(
              children: [
                Container(
                  width: 46,
                  height: 46,
                  decoration: BoxDecoration(
                    color: view.half == 'night'
                        ? AppColors.accentSoft
                        : AppColors.hostSoft,
                    borderRadius: BorderRadius.circular(AppRadius.field),
                  ),
                  child: Icon(
                    view.half == 'night'
                        ? Icons.nightlight_round
                        : Icons.wb_sunny_outlined,
                    color: view.half == 'night'
                        ? AppColors.accent
                        : AppColors.host,
                  ),
                ),
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '第 ${view.day} 日 · ${view.phaseLabel}',
                        style: const TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.w600,
                            color: AppColors.text),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        '已准备 ${view.raw['ready_count'] ?? 0} 人 · 连接${store.connectionStatus}',
                        style: const TextStyle(
                            fontSize: 12, color: AppColors.textTertiary),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
        SectionTitle('牌桌', subtitle: '每席两张角色牌，当前使用的牌在上层。'),
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
                  child: SeatCard(seat: seat),
                ),
            ],
          ),
        ),
        if (result is Map && result.isNotEmpty) ...[
          const SectionTitle('结算'),
          Card(
            color: AppColors.hostSoft,
            child: Padding(
              padding: const EdgeInsets.all(AppSpacing.lg),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  const Icon(Icons.emoji_events_outlined,
                      color: AppColors.host),
                  const SizedBox(width: AppSpacing.md),
                  Expanded(
                    child: Text(
                      '${result['winner'] ?? result['reason'] ?? result}',
                      style: const TextStyle(
                          fontSize: 14, height: 1.5, color: AppColors.text),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ],
    );
  }
}

class SeatCard extends StatelessWidget {
  const SeatCard({super.key, required this.seat});
  final Map<String, dynamic> seat;

  @override
  Widget build(BuildContext context) {
    final occupied = seat['occupied'] == true;
    final alive = seat['alive'] != false;
    final name = seat['name']?.toString() ?? '';
    return Card(
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
                        style: const TextStyle(
                            fontSize: 15,
                            fontWeight: FontWeight.w600,
                            color: AppColors.text),
                      ),
                      const SizedBox(width: AppSpacing.sm),
                      Flexible(
                        child: Text(
                          name.isNotEmpty ? name : (occupied ? '等待命名' : '空席'),
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                              fontSize: 14, color: AppColors.textSecondary),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: AppSpacing.xs),
                  Wrap(
                    spacing: AppSpacing.sm,
                    runSpacing: AppSpacing.xs,
                    children: [
                      Tag(
                        alive ? '存活' : '已出局',
                        color:
                            alive ? AppColors.success : AppColors.textSecondary,
                        background: alive
                            ? AppColors.successSoft
                            : AppColors.surfaceMuted,
                      ),
                      if (seat['online'] == true)
                        const Tag('在线', icon: Icons.wifi_tethering),
                      if (seat['ready'] == true)
                        const Tag('已准备', icon: Icons.check),
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

/// 每席两张圆头像，约 50% 重叠，当前使用的牌在上层。
class DualAvatar extends StatelessWidget {
  const DualAvatar({super.key, required this.seat, required this.alive});

  final Map<String, dynamic> seat;
  final bool alive;

  @override
  Widget build(BuildContext context) {
    final cards = seat['cards'];
    String? current;
    String? other;
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
      current = active?['role_id']?.toString();
      other = idle?['role_id']?.toString();
    } else {
      current = seat['avatar_role_id']?.toString();
      other = seat['previous_role_id']?.toString();
    }
    const size = 46.0;
    final avatars = SizedBox(
      width: size + 24,
      height: size,
      child: Stack(
        clipBehavior: Clip.none,
        children: [
          Positioned(
              left: 0,
              top: 2,
              child: _LayeredAvatar(
                  roleId: other, size: size, dead: !alive, front: false)),
          Positioned(
              left: 24,
              top: 0,
              child: _LayeredAvatar(
                  roleId: current, size: size, dead: !alive, front: true)),
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
  });

  final String? roleId;
  final double size;
  final bool dead;
  final bool front;

  @override
  Widget build(BuildContext context) => Container(
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: AppColors.surface,
          boxShadow: front
              ? [
                  BoxShadow(
                      color: Colors.black.withValues(alpha: .10),
                      blurRadius: 6,
                      offset: const Offset(0, 2))
                ]
              : null,
        ),
        child: RoleAvatar(
          roleId: roleId,
          size: size,
          dead: dead,
          border: Border.all(
            color: front ? AppColors.accent : AppColors.border,
            width: front ? 2 : 1.5,
          ),
        ),
      );
}

/// 我的页：账号、双牌、退出。
class ProfilePage extends StatelessWidget {
  const ProfilePage({super.key, required this.store});
  final GameStore store;

  @override
  Widget build(BuildContext context) {
    final self = store.view!.self;
    final cards = self['cards'] is List ? self['cards'] as List : const [];
    final currentId = self['current_card_id']?.toString();
    final actor = store.actor!;
    return ListView(
      padding: const EdgeInsets.fromLTRB(
        AppSpacing.lg,
        AppSpacing.sm,
        AppSpacing.lg,
        AppSpacing.bottomBar,
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
                        style: const TextStyle(
                            fontSize: 17,
                            fontWeight: FontWeight.w600,
                            color: AppColors.text),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        actor.isHost
                            ? '主持人'
                            : actor.isSpectator
                                ? '观战者 · 只读牌桌'
                                : '${actor.seatId ?? '-'} 号玩家',
                        style: const TextStyle(
                            fontSize: 13, color: AppColors.textTertiary),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ),
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
        if (self['warning_deadline'] != null) ...[
          const SizedBox(height: AppSpacing.md),
          Card(
            color: AppColors.dangerSoft,
            child: Padding(
              padding: const EdgeInsets.all(AppSpacing.lg),
              child: Row(
                children: [
                  const Icon(Icons.timer_outlined, color: AppColors.danger),
                  const SizedBox(width: AppSpacing.md),
                  Expanded(
                    child: Text(
                      '主持人已警告，请在 ${self['warning_deadline']} 前完成操作。',
                      style:
                          const TextStyle(fontSize: 13, color: AppColors.text),
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
              color: isCurrent ? AppColors.accent : Colors.transparent,
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
                        style: const TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.w600,
                            color: AppColors.text),
                      ),
                      const SizedBox(width: AppSpacing.sm),
                      if (isCurrent) const Tag('当前上层'),
                    ],
                  ),
                  const SizedBox(height: AppSpacing.xs),
                  Wrap(
                    spacing: AppSpacing.sm,
                    runSpacing: AppSpacing.xs,
                    children: [
                      Tag(
                        alive ? '存活' : '已出局',
                        color:
                            alive ? AppColors.success : AppColors.textSecondary,
                        background: alive
                            ? AppColors.successSoft
                            : AppColors.surfaceMuted,
                      ),
                      if (card['witch'] == true)
                        const Tag('魔女化',
                            color: AppColors.danger,
                            background: AppColors.dangerSoft),
                      if (card['injured'] == true)
                        const Tag('负伤',
                            color: AppColors.warning,
                            background: AppColors.warningSoft),
                      if (uses is Map && uses.isNotEmpty)
                        Tag(
                          uses.entries
                              .map((e) => '${e.key} ${e.value}')
                              .join(' · '),
                          color: AppColors.textSecondary,
                          background: AppColors.surfaceMuted,
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
  const HostManagementPage({super.key, required this.store});
  final GameStore store;

  @override
  State<HostManagementPage> createState() => _HostManagementPageState();
}

class _HostManagementPageState extends State<HostManagementPage> {
  static const groups = ['当前待办', '流程', '玩家', '私密信息', '纠错'];

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
      padding: const EdgeInsets.fromLTRB(
        AppSpacing.lg,
        AppSpacing.sm,
        AppSpacing.lg,
        AppSpacing.bottomBar,
      ),
      children: [
        Card(
          color: blocking > 0 ? AppColors.dangerSoft : AppColors.successSoft,
          child: Padding(
            padding: const EdgeInsets.all(AppSpacing.lg),
            child: Row(
              children: [
                Icon(
                  blocking > 0
                      ? Icons.pending_actions_outlined
                      : Icons.check_circle_outline,
                  color: blocking > 0 ? AppColors.danger : AppColors.success,
                ),
                const SizedBox(width: AppSpacing.md),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '${view.phaseLabel} · 第 ${view.day} 日',
                        style: const TextStyle(
                            fontSize: 16,
                            fontWeight: FontWeight.w600,
                            color: AppColors.text),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        blocking > 0 ? '有 $blocking 项待办阻塞推进' : '没有阻塞项，可以推进',
                        style: const TextStyle(
                            fontSize: 13, color: AppColors.textSecondary),
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
            padding: const EdgeInsets.all(AppSpacing.md),
            child: codex.isEmpty
                ? const Text('未读取到魔典名单',
                    style: TextStyle(color: AppColors.textTertiary))
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
              const Card(
                child: Padding(
                  padding: EdgeInsets.all(AppSpacing.lg),
                  child: Text('当前没有待办。',
                      style: TextStyle(color: AppColors.textTertiary)),
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
            const Padding(
              padding: EdgeInsets.symmetric(vertical: AppSpacing.sm),
              child: Text('当前无可用操作',
                  style:
                      TextStyle(color: AppColors.textTertiary, fontSize: 13)),
            ),
        ],
        SectionTitle('席位代操作', subtitle: '先读取该席位当前视角，再提交它实际可用的行动。'),
        Wrap(
          spacing: AppSpacing.sm,
          runSpacing: AppSpacing.sm,
          children: [
            for (final seat in view.seats)
              ActionChip(
                avatar: DualAvatar(seat: seat, alive: seat['alive'] != false),
                label: Text('${seat['id']} 号'),
                onPressed: seat['occupied'] == true && !store.writeBusy
                    ? () => _seatActions(seat['id'].toString())
                    : null,
              ),
          ],
        ),
      ],
    );
  }

  Future<void> _runTask(String actionId, Map<String, dynamic> payload) async {
    final action = widget.store.view!.allActions.firstWhere(
      (item) => item.id == actionId,
      orElse: () => widget.store.view!.allActions.first,
    );
    if (!mounted) return;
    await showActionForm(context, widget.store, action);
  }

  Future<void> _seatActions(String seatId) async {
    final store = widget.store;
    try {
      final perspective = await store.seatPerspective(seatId);
      if (!mounted) return;
      final actions = perspective.actions
          .where((action) => !action.id.startsWith('channel.'))
          .toList();
      if (actions.isEmpty) {
        setState(() {});
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
                    style: const TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                        color: AppColors.text),
                  ),
                  if (task['detail']?.toString().isNotEmpty == true) ...[
                    const SizedBox(height: 2),
                    Text(
                      task['detail'].toString(),
                      style: const TextStyle(
                          fontSize: 12, color: AppColors.textTertiary),
                    ),
                  ],
                ],
              ),
            ),
            if (blocking)
              const Padding(
                padding: EdgeInsets.only(right: AppSpacing.md),
                child: Tag('阻塞',
                    color: AppColors.danger, background: AppColors.dangerSoft),
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
