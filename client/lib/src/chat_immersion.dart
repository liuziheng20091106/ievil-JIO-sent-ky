import 'dart:async';

import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// Listens without consuming input, including pointers over dialog routes.
class ChatImmersionSession extends StatefulWidget {
  const ChatImmersionSession({
    super.key,
    required this.enabled,
    required this.active,
    required this.builder,
  });

  final bool enabled;
  final bool active;
  final Widget Function(BuildContext, double, VoidCallback) builder;

  @override
  State<ChatImmersionSession> createState() => _ChatImmersionSessionState();
}

class _ChatImmersionSessionState extends State<ChatImmersionSession>
    with SingleTickerProviderStateMixin, WidgetsBindingObserver {
  late final AnimationController _visibility = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 500),
    value: 1,
  );
  Timer? _idle;
  bool _foreground = true;

  bool get _running => widget.enabled && widget.active && _foreground;

  @override
  void initState() {
    super.initState();
    final binding = WidgetsBinding.instance;
    _foreground = binding.lifecycleState == null ||
        binding.lifecycleState == AppLifecycleState.resumed;
    binding.addObserver(this);
    GestureBinding.instance.pointerRouter.addGlobalRoute(_onPointer);
    HardwareKeyboard.instance.addHandler(_onKey);
    _activity();
  }

  @override
  void didUpdateWidget(ChatImmersionSession oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.enabled != widget.enabled ||
        oldWidget.active != widget.active) {
      _activity();
    }
  }

  void _activity() {
    _idle?.cancel();
    if (_visibility.status != AnimationStatus.forward &&
        (_visibility.value < 1 ||
            _visibility.status == AnimationStatus.reverse)) {
      _visibility.forward();
    }
    if (_running) {
      _idle = Timer(const Duration(seconds: 15), () {
        if (mounted && _running) _visibility.reverse();
      });
    }
  }

  void _onPointer(PointerEvent event) {
    if (event is PointerDownEvent ||
        event is PointerMoveEvent ||
        event is PointerHoverEvent ||
        event is PointerSignalEvent ||
        event is PointerUpEvent ||
        event is PointerPanZoomStartEvent ||
        event is PointerPanZoomUpdateEvent ||
        event is PointerPanZoomEndEvent) {
      _activity();
    }
  }

  bool _onKey(KeyEvent event) {
    _activity();
    return false;
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    _foreground = state == AppLifecycleState.resumed;
    _activity();
  }

  @override
  void dispose() {
    _idle?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    GestureBinding.instance.pointerRouter.removeGlobalRoute(_onPointer);
    HardwareKeyboard.instance.removeHandler(_onKey);
    _visibility.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: _visibility,
        builder: (context, _) => widget.builder(
            context, Curves.easeInOut.transform(_visibility.value), _activity),
      );
}

/// Collapses layout while retaining the child element, focus and draft.
class ImmersionChrome extends StatelessWidget {
  const ImmersionChrome({
    super.key,
    required this.visibility,
    required this.child,
  });

  final double visibility;
  final Widget child;

  @override
  Widget build(BuildContext context) => IgnorePointer(
        ignoring: visibility < 1,
        child: ExcludeSemantics(
          excluding: visibility == 0,
          child: ClipRect(
            child: Align(
              alignment: Alignment.topCenter,
              heightFactor: visibility,
              child: Opacity(opacity: visibility, child: child),
            ),
          ),
        ),
      );
}

class ImmersionAppBar extends StatelessWidget implements PreferredSizeWidget {
  const ImmersionAppBar({
    super.key,
    required this.visibility,
    required this.child,
  });

  final double visibility;
  final AppBar child;

  @override
  Size get preferredSize =>
      Size.fromHeight(child.preferredSize.height * visibility);

  @override
  Widget build(BuildContext context) {
    final height =
        child.preferredSize.height + MediaQuery.paddingOf(context).top;
    return IgnorePointer(
      ignoring: visibility < 1,
      child: ExcludeSemantics(
        excluding: visibility == 0,
        child: ClipRect(
          child: OverflowBox(
            alignment: Alignment.topCenter,
            minHeight: height,
            maxHeight: height,
            child: Opacity(opacity: visibility, child: child),
          ),
        ),
      ),
    );
  }
}
