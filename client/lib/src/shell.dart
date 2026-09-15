import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'action_sheet.dart';
import 'models.dart';
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
  bool get spectator => widget.store.actor!.isSpectator;

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
    final pages = <Widget>[
      ChatActionPage(store: widget.store),
      BoardPage(store: widget.store),
      if (host) HostManagementPage(store: widget.store) else ProfilePage(store: widget.store),
    ];
    final labels = host ? const ['对局', '状态', '管理'] : const ['对局', '状态', '我的'];
    final icons = host
        ? const [Icons.forum_outlined, Icons.grid_view_rounded, Icons.admin_panel_settings_outlined]
        : const [Icons.forum_outlined, Icons.grid_view_rounded, Icons.person_outline];
    final counts = [
      widget.store.unreadMessageCount + widget.store.newActionCount + widget.store.warningCount,
      widget.store.pendingPhaseKey == null ? 0 : 1,
      host ? widget.store.newActionCount : widget.store.privateStateCount,
    ];
    return Scaffold(
      extendBody: true,
      appBar: AppBar(
        title: Text('${widget.store.view!.phaseLabel} · 第${widget.store.view!.day}日'),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 12),
            child: Center(
              child: Tooltip(
                message: widget.store.connectionStatus,
                child: Icon(
                  widget.store.connectionStatus == '已连接' ? Icons.cloud_done_outlined : Icons.cloud_off_outlined,
                  color: widget.store.connectionStatus == '已连接'
                      ? Theme.of(context).colorScheme.primary
                      : Theme.of(context).colorScheme.error,
                ),
              ),
            ),
          ),
        ],
      ),
      body: Stack(
        children: [
          IndexedStack(index: index, children: pages),
          if (widget.store.pendingPhaseKey != null) PhaseOverlay(store: widget.store),
        ],
      ),
      bottomNavigationBar: SafeArea(
        minimum: const EdgeInsets.fromLTRB(20, 0, 20, 14),
        child: Material(
          elevation: 8,
          color: Theme.of(context).colorScheme.surfaceContainer,
          borderRadius: BorderRadius.circular(28),
          clipBehavior: Clip.antiAlias,
          child: NavigationBar(
            backgroundColor: Colors.transparent,
            elevation: 0,
            selectedIndex: index,
            onDestinationSelected: (value) {
              setState(() => index = value);
              if (Platform.isAndroid) HapticFeedback.selectionClick();
              if (value == 0) {
                widget.store.markMessagesRead();
                widget.store.markActionsViewed();
              } else if (value == 2 && !host) {
                widget.store.markPrivateViewed();
              } else if (value == 2 && host) {
                widget.store.markActionsViewed();
              }
            },
            destinations: [
              for (var item = 0; item < 3; item++)
                NavigationDestination(
                  icon: Badge.count(
                    count: counts[item],
                    isLabelVisible: counts[item] > 0,
                    backgroundColor: item == 0 && widget.store.warningCount > 0
                        ? Theme.of(context).colorScheme.error
                        : null,
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
    return Positioned.fill(
      child: AnimatedOpacity(
        opacity: shown ? 1 : 0,
        duration: reduceMotion ? Duration.zero : const Duration(milliseconds: 280),
        child: ColoredBox(
          color: Theme.of(context).colorScheme.primaryContainer.withValues(alpha: .96),
          child: Center(
            child: AnimatedScale(
              scale: shown ? 1 : .9,
              duration: reduceMotion ? Duration.zero : const Duration(milliseconds: 360),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Text('第 ${widget.store.view!.day} 日', style: Theme.of(context).textTheme.headlineMedium),
                  const SizedBox(height: 8),
                  Text(
                    '${widget.store.view!.half == 'night' ? '夜间' : '白天'} · ${widget.store.view!.phaseLabel}',
                    style: Theme.of(context).textTheme.displaySmall,
                    textAlign: TextAlign.center,
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

class ChatActionPage extends StatefulWidget {
  const ChatActionPage({super.key, required this.store});
  final GameStore store;

  @override
  State<ChatActionPage> createState() => _ChatActionPageState();
}

class _ChatActionPageState extends State<ChatActionPage> {
  static const scopes = {
    'all': '全部',
    'public': '公屏',
    'private': '私信',
    'system': '系统',
    'host': '主持人',
  };
  final message = TextEditingController();
  String? sendError;

  @override
  void dispose() {
    message.dispose();
    super.dispose();
  }

  List<ActionDescriptor> get actions {
    final store = widget.store;
    final source = store.actor!.isHost || store.actor!.isSpectator
        ? store.view!.allActions.where((item) => item.id.startsWith('channel.'))
        : store.view!.allActions;
    final seen = <String>{};
    return [for (final item in source) if (seen.add(item.protocolKey)) item];
  }

  @override
  Widget build(BuildContext context) {
    final store = widget.store;
    final keyboard = MediaQuery.viewInsetsOf(context).bottom > 0;
    final channel = store.selectedChannel;
    return Column(
      children: [
        SizedBox(
          height: 52,
          child: ListView(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            scrollDirection: Axis.horizontal,
            children: [
              for (final entry in scopes.entries)
                Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: ChoiceChip(
                    label: Text(entry.value),
                    selected: store.messageScope == entry.key,
                    onSelected: (_) => store.loadMessages(entry.key),
                  ),
                ),
            ],
          ),
        ),
        Expanded(
          child: store.messages.isEmpty
              ? const Center(child: Text('暂无消息'))
              : ListView.builder(
                  reverse: true,
                  padding: const EdgeInsets.fromLTRB(12, 4, 12, 8),
                  itemCount: store.messages.length + (store.hasMoreMessages ? 1 : 0),
                  itemBuilder: (context, reversedIndex) {
                    if (store.hasMoreMessages && reversedIndex == store.messages.length) {
                      return Center(
                        child: TextButton(onPressed: store.loadOlderMessages, child: const Text('加载更早消息')),
                      );
                    }
                    final item = store.messages[store.messages.length - 1 - reversedIndex];
                    return MessageCard(message: item);
                  },
                ),
        ),
        Material(
          elevation: 4,
          color: Theme.of(context).colorScheme.surface,
          child: SafeArea(
            top: false,
            minimum: const EdgeInsets.fromLTRB(12, 8, 12, 92),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: DropdownButtonFormField<String>(
                        initialValue: channel?.id,
                        isExpanded: true,
                        decoration: const InputDecoration(labelText: '发送到', isDense: true),
                        items: [
                          for (final item in store.view!.channels)
                            DropdownMenuItem(
                              value: item.id,
                              child: Text('${item.label}${item.status == 'pending' ? '（待同意）' : item.status == 'ended' ? '（已结束）' : ''}'),
                            ),
                        ],
                        onChanged: (value) {
                          if (value == null) return;
                          store.selectChannel(value);
                          if (Platform.isAndroid) HapticFeedback.selectionClick();
                        },
                      ),
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      flex: 2,
                      child: TextField(
                        controller: message,
                        enabled: channel?.canSend == true && !store.writeBusy,
                        maxLength: 2000,
                        minLines: 1,
                        maxLines: 4,
                        decoration: InputDecoration(
                          labelText: channel?.canSend == true ? '消息' : (channel?.reason.isNotEmpty == true ? channel!.reason : '当前不可发言'),
                          errorText: sendError,
                          counterText: '',
                        ),
                        onSubmitted: (_) => send(),
                      ),
                    ),
                    IconButton.filled(
                      tooltip: '发送',
                      onPressed: channel?.canSend == true && !store.writeBusy ? send : null,
                      icon: const Icon(Icons.send_rounded),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                if (keyboard)
                  Align(
                    alignment: Alignment.centerLeft,
                    child: Badge.count(
                      count: actions.length,
                      isLabelVisible: actions.isNotEmpty,
                      child: OutlinedButton.icon(
                        onPressed: actions.isEmpty ? null : openActionList,
                        icon: const Icon(Icons.bolt_outlined),
                        label: const Text('行动'),
                      ),
                    ),
                  )
                else
                  SizedBox(
                    height: 44,
                    child: actions.isEmpty
                        ? const Align(alignment: Alignment.centerLeft, child: Text('当前没有可用行动'))
                        : ListView.separated(
                            scrollDirection: Axis.horizontal,
                            itemCount: actions.length,
                            separatorBuilder: (_, __) => const SizedBox(width: 8),
                            itemBuilder: (context, item) => ActionButton(
                              action: actions[item],
                              busy: store.writeBusy,
                              onTap: () => showActionForm(context, store, actions[item]),
                            ),
                          ),
                  ),
              ],
            ),
          ),
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

  Future<void> openActionList() async {
    FocusManager.instance.primaryFocus?.unfocus();
    await showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (context) => ListView(
        shrinkWrap: true,
        padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
        children: [
          Text('当前行动', style: Theme.of(context).textTheme.titleLarge),
          for (final action in actions)
            ListTile(
              title: Text(action.shortLabel),
              subtitle: Text(action.label),
              trailing: action.unsupportedReason == null ? const Icon(Icons.chevron_right) : const Icon(Icons.block),
              onLongPress: () => showActionPreview(context, action),
              onTap: () {
                Navigator.pop(context);
                showActionForm(this.context, widget.store, action);
              },
            ),
        ],
      ),
    );
  }
}

class ActionButton extends StatelessWidget {
  const ActionButton({super.key, required this.action, required this.busy, required this.onTap});
  final ActionDescriptor action;
  final bool busy;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Tooltip(
        message: action.unsupportedReason ?? action.label,
        child: OutlinedButton(
          onPressed: busy ? null : onTap,
          onLongPress: () => showActionPreview(context, action),
          style: action.raw['danger'] == true
              ? OutlinedButton.styleFrom(foregroundColor: Theme.of(context).colorScheme.error)
              : null,
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              if (action.unsupportedReason != null) ...[const Icon(Icons.block, size: 16), const SizedBox(width: 4)],
              Text(action.shortLabel),
            ],
          ),
        ),
      );
}

class MessageCard extends StatelessWidget {
  const MessageCard({super.key, required this.message});
  final GameMessage message;

  @override
  Widget build(BuildContext context) {
    final system = message.kind != 'chat';
    return Align(
      alignment: system ? Alignment.center : Alignment.centerLeft,
      child: Card(
        color: system ? Theme.of(context).colorScheme.secondaryContainer : null,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (message.senderName != null)
                Text(message.senderName!, style: Theme.of(context).textTheme.labelLarge),
              Text(message.text),
              if (message.createdAt.isNotEmpty)
                Text(message.createdAt, style: Theme.of(context).textTheme.labelSmall),
            ],
          ),
        ),
      ),
    );
  }
}

class BoardPage extends StatelessWidget {
  const BoardPage({super.key, required this.store});
  final GameStore store;

  @override
  Widget build(BuildContext context) {
    final view = store.view!;
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 110),
      children: [
        Card(
          child: ListTile(
            leading: const Icon(Icons.flag_outlined),
            title: Text('第${view.day}日 · ${view.phaseLabel}'),
            subtitle: Text('状态 ${view.status} · ${store.connectionStatus}'),
            trailing: view.raw['deadline'] == null ? null : Text('截止 ${view.raw['deadline']}'),
          ),
        ),
        const SizedBox(height: 8),
        AnimatedSwitcher(
          duration: MediaQuery.disableAnimationsOf(context) ? Duration.zero : const Duration(milliseconds: 280),
          child: Column(
            key: ValueKey('${view.version}:${view.phase}'),
            children: [
              for (final seat in view.seats) SeatCard(seat: seat),
            ],
          ),
        ),
        if (view.raw['result'] != null)
          Card(
            color: Theme.of(context).colorScheme.tertiaryContainer,
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Text('结算：${view.raw['result']}'),
            ),
          ),
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
    return Card(
      child: ListTile(
        leading: DualAvatar(seat: seat, alive: alive),
        title: Text('${seat['id']}号 · ${seat['name']?.toString().isNotEmpty == true ? seat['name'] : occupied ? '等待命名' : '空席'}'),
        subtitle: Text([
          alive ? '存活' : '已出局',
          if (seat['online'] == true) '在线',
          if (seat['ready'] == true) '已准备',
        ].join(' · ')),
        trailing: Icon(occupied ? Icons.person : Icons.event_seat_outlined),
      ),
    );
  }
}

class DualAvatar extends StatelessWidget {
  const DualAvatar({super.key, required this.seat, required this.alive});
  final Map<String, dynamic> seat;
  final bool alive;

  @override
  Widget build(BuildContext context) {
    // 当前使用的牌画在右上方：两张圆约 50% 重叠，顶层即当前牌。
    final cards = seat['cards'];
    String current = '?';
    String other = '?';
    final currentId = seat['current_card_id']?.toString();
    if (cards is List && cards.isNotEmpty) {
      Map<dynamic, dynamic>? active;
      Map<dynamic, dynamic>? idle;
      for (final raw in cards) {
        if (raw is! Map) continue;
        if (active == null && currentId != null && raw['id']?.toString() == currentId) {
          active = raw;
        } else {
          idle ??= raw;
        }
      }
      active ??= cards.first is Map ? cards.first as Map : null;
      current = active?['role_id']?.toString() ?? '?';
      other = idle?['role_id']?.toString() ?? '?';
    } else {
      current = seat['avatar_role_id']?.toString() ?? '?';
      other = seat['previous_role_id']?.toString() ?? '?';
    }
    final avatars = SizedBox(
      width: 72,
      height: 48,
      child: Stack(
        children: [
          Positioned(left: 0, child: RoleCircle(role: other)),
          Positioned(left: 24, child: RoleCircle(role: current, emphasized: true)),
        ],
      ),
    );
    return alive
        ? avatars
        : ColorFiltered(colorFilter: const ColorFilter.mode(Colors.grey, BlendMode.saturation), child: avatars);
  }
}

class RoleCircle extends StatelessWidget {
  const RoleCircle({super.key, required this.role, this.emphasized = false});
  final String role;
  final bool emphasized;

  @override
  Widget build(BuildContext context) {
    final short = role == '?' ? '?' : String.fromCharCodes(role.runes.take(2));
    return AnimatedContainer(
      duration: MediaQuery.disableAnimationsOf(context) ? Duration.zero : const Duration(milliseconds: 220),
      width: 48,
      height: 48,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        color: emphasized
            ? Theme.of(context).colorScheme.primaryContainer
            : Theme.of(context).colorScheme.secondaryContainer,
        border: Border.all(
          color: emphasized ? Theme.of(context).colorScheme.primary : Theme.of(context).colorScheme.outline,
          width: emphasized ? 2 : 1,
        ),
      ),
      alignment: Alignment.center,
      child: Text(short, style: const TextStyle(fontWeight: FontWeight.bold)),
    );
  }
}

class ProfilePage extends StatelessWidget {
  const ProfilePage({super.key, required this.store});
  final GameStore store;

  @override
  Widget build(BuildContext context) {
    final self = store.view!.self;
    final cards = self['cards'] is List ? self['cards'] as List : const [];
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 110),
      children: [
        Card(
          child: ListTile(
            leading: const CircleAvatar(child: Icon(Icons.person)),
            title: Text(store.actor!.name),
            subtitle: Text(store.actor!.isSpectator ? '观战者 · 只读牌桌' : '${store.actor!.seatId ?? '-'}号玩家'),
          ),
        ),
        const SizedBox(height: 12),
        Text('我的双牌', style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 8),
        if (cards.isEmpty) const Card(child: Padding(padding: EdgeInsets.all(16), child: Text('观战身份没有个人角色牌'))),
        for (final raw in cards)
          if (raw is Map)
            Card(
              child: ListTile(
                leading: RoleCircle(role: raw['role_id']?.toString() ?? '?'),
                title: Text(raw['role_id']?.toString() ?? '未知角色'),
                subtitle: Text([
                  raw['alive'] == false ? '已出局' : '存活',
                  if (raw['id']?.toString() == self['current_card_id']?.toString()) '当前上层',
                  if (raw['uses'] != null) '次数 ${raw['uses']}',
                ].join(' · ')),
              ),
            ),
        const SizedBox(height: 12),
        OutlinedButton.icon(onPressed: store.logout, icon: const Icon(Icons.logout), label: const Text('退出登录')),
      ],
    );
  }
}

class HostManagementPage extends StatelessWidget {
  const HostManagementPage({super.key, required this.store});
  final GameStore store;

  @override
  Widget build(BuildContext context) {
    final view = store.view!;
    final tasks = view.host['tasks'] is List ? view.host['tasks'] as List : const [];
    final groups = <String, List<ActionDescriptor>>{
      '当前待办': [],
      '流程': [],
      '玩家': [],
      '私密信息': [],
      '纠错': [],
    };
    final seen = <String>{};
    for (final action in view.allActions) {
      if (!seen.add(action.protocolKey)) continue;
      groups[_managementGroup(action)]!.add(action);
    }
    return ListView(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 110),
      children: [
        Card(
          color: tasks.isEmpty
              ? Theme.of(context).colorScheme.primaryContainer
              : Theme.of(context).colorScheme.errorContainer,
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('${view.phaseLabel} · ${view.raw['auto_advance'] == true ? '自动推进' : '手动推进'}',
                    style: Theme.of(context).textTheme.titleLarge),
                const SizedBox(height: 6),
                Text(tasks.isEmpty ? '当前没有阻塞项' : '真正阻塞项 ${tasks.length} 项'),
              ],
            ),
          ),
        ),
        for (final entry in groups.entries) ...[
          Padding(
            padding: const EdgeInsets.fromLTRB(4, 18, 4, 6),
            child: Text(entry.key, style: Theme.of(context).textTheme.titleMedium),
          ),
          if (entry.key == '当前待办')
            if (tasks.isEmpty)
              const Card(child: ListTile(title: Text('无待办')))
            else
              for (final raw in tasks)
                Card(child: ListTile(leading: const Icon(Icons.pending_actions), title: Text(_taskLabel(raw)))),
          if (entry.value.isEmpty && entry.key != '当前待办')
            const Card(child: ListTile(title: Text('当前无可用操作')))
          else
            Wrap(
              spacing: 8,
              runSpacing: 8,
              children: [
                for (final action in entry.value)
                  ActionButton(
                    action: action,
                    busy: store.writeBusy,
                    onTap: () => showActionForm(context, store, action),
                  ),
              ],
            ),
        ],
        if (view.seats.isNotEmpty) ...[
          Padding(
            padding: const EdgeInsets.fromLTRB(4, 18, 4, 6),
            child: Text('席位代操作', style: Theme.of(context).textTheme.titleMedium),
          ),
          const Card(
            child: ListTile(
              leading: Icon(Icons.visibility_outlined),
              title: Text('先读取席位当前视角，再选择该视角实际可用的行动'),
            ),
          ),
          Wrap(
            spacing: 8,
            children: [
              for (final seat in view.seats)
                OutlinedButton(
                  onPressed: seat['occupied'] == true && !store.writeBusy
                      ? () => _showSeatActions(context, store, seat['id'].toString())
                      : null,
                  child: Text('${seat['id']}号'),
                ),
            ],
          ),
        ],
      ],
    );
  }

  static String _taskLabel(dynamic raw) {
    if (raw is Map) return (raw['title'] ?? raw['label'] ?? raw['kind'] ?? raw).toString();
    return raw.toString();
  }

  static String _managementGroup(ActionDescriptor action) {
    final value = '${action.group}:${action.id}';
    if (value.contains('待办') || value.contains('warning')) return '当前待办';
    if (value.contains('私密') || value.contains('channel') || value.contains('information')) return '私密信息';
    if (value.contains('纠错') || value.contains('snapshot') || value.contains('rollback') || value.contains('correct')) {
      return '纠错';
    }
    if (value.contains('玩家') || value.contains('room.kick') || value.contains('room.mute') || value.contains('room.replace')) {
      return '玩家';
    }
    return '流程';
  }

  Future<void> _showSeatActions(BuildContext context, GameStore store, String seatId) async {
    try {
      final perspective = await store.seatPerspective(seatId);
      final actions = perspective.actions.where((action) => !action.id.startsWith('channel.')).toList();
      if (!context.mounted) return;
      await showModalBottomSheet<void>(
        context: context,
        showDragHandle: true,
        builder: (sheetContext) => ListView(
          shrinkWrap: true,
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
          children: [
            Text('$seatId号当前行动', style: Theme.of(sheetContext).textTheme.titleLarge),
            if (actions.isEmpty) const ListTile(title: Text('该席当前没有可代操作的行动')),
            for (final action in actions)
              ListTile(
                title: Text(action.shortLabel),
                subtitle: Text(action.label),
                onLongPress: () => showActionPreview(sheetContext, action),
                onTap: () {
                  Navigator.pop(sheetContext);
                  showActionForm(context, store, action, asSeat: seatId);
                },
              ),
          ],
        ),
      );
    } on ApiException catch (failure) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(failure.message)));
      }
    }
  }
}
