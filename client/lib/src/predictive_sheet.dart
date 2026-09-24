import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

/// 模态底部面板（行动面板 / 行动表单 / 选择器）的预测性返回。
///
/// 为什么需要这个文件，以及为什么这样做（结论都来自真机 + 机制测试）：
///  * Android 13+ 只有清单里声明了 `enableOnBackInvokedCallback`，系统才会把返回手势
///    拆成 start/update/commit 事件、经 `flutter/backgesture` 通道送进 Dart；
///  * 页面路由（`MaterialPageRoute`）由 Flutter 自带的
///    `PredictiveBackPageTransitionsBuilder` 处理，但 `showModalBottomSheet` 创建的
///    `ModalBottomSheetRoute` 不经过主题的过渡器，因此完全没有预测性返回；
///  * 面板位移本来就由 route 的 `AnimationController` 逐帧驱动（框架用
///    `CurvedAnimation(parent: route.animation)` 算位移），所以只要改写这个控制器的值，
///    面板就会跟手，不必复刻 `BottomSheet` 的拖拽物理；
///  * 控制器的 vsync 必须来自树里的 State：`AnimationController` 的构造函数会立刻
///    调用 `vsync.createTicker()`，所以「先建控制器、再挂宿主」是不可能的。
///
/// 接入方式（见 main.dart）：
///  1. `main()` 里调用 [PredictiveSheetBack.start]；
///  2. `MaterialApp` 外面套一层 [SheetVsyncHost]；
///  3. `MaterialApp.navigatorObservers` 加上 [PredictiveSheetBack.routeObserver]；
///  4. 把行动类弹窗的 `showModalBottomSheet` 换成 [showPredictiveSheet]。
///
/// 非 Android（Windows 客户端）不注入控制器，完全保持原有行为。

/// 一个已打开、可能被返回手势接管的面板。
class _SheetSession {
  _SheetSession({required this.navigator, required TickerProvider vsync})
      : controller = AnimationController(
          vsync: vsync,
          // 与框架 BottomSheet 的默认时长一致，不改变现有开合手感。
          duration: const Duration(milliseconds: 250),
          reverseDuration: const Duration(milliseconds: 200),
        );

  final NavigatorState navigator;
  final AnimationController controller;

  /// 本次返回手势是否由本面板接管。
  bool driving = false;
}

/// 跟踪当前栈顶路由：面板上面又压了对话框时，返回手势不该去驱动面板。
class _SheetRouteObserver extends NavigatorObserver {
  Route<dynamic>? top;

  @override
  void didPush(Route<dynamic> route, Route<dynamic>? previousRoute) =>
      top = route;

  @override
  void didPop(Route<dynamic> route, Route<dynamic>? previousRoute) =>
      top = previousRoute;

  @override
  void didRemove(Route<dynamic> route, Route<dynamic>? previousRoute) =>
      top = previousRoute;

  @override
  void didReplace({Route<dynamic>? newRoute, Route<dynamic>? oldRoute}) =>
      top = newRoute;
}

class PredictiveSheetBack with WidgetsBindingObserver {
  PredictiveSheetBack._();

  static final PredictiveSheetBack instance = PredictiveSheetBack._();

  final _SheetRouteObserver _routeObserver = _SheetRouteObserver();

  /// 交给 `MaterialApp.navigatorObservers`。
  NavigatorObserver get routeObserver => _routeObserver;

  TickerProvider? _vsync;
  _SheetSession? _active;

  /// 已关闭面板的控制器先留在这里，下一次打开面板时再释放。
  ///
  /// 不能在 `showModalBottomSheet` 的 future 完成后立刻 dispose：那个 future 在路由
  /// pop 时就完成，而退场动画还没跑完，提前释放会把面板冻在半途。
  _SheetSession? _retired;

  bool _observing = false;

  void start() {
    if (_observing) return;
    _observing = true;
    WidgetsBinding.instance.addObserver(this);
  }

  void stop() {
    if (!_observing) return;
    _observing = false;
    WidgetsBinding.instance.removeObserver(this);
  }

  TickerProvider? get vsync => _vsync;

  void attachVsync(TickerProvider vsync) => _vsync = vsync;

  void detachVsync(TickerProvider vsync) {
    if (identical(_vsync, vsync)) _vsync = null;
  }

  void disposeRetired() {
    _retired?.controller.dispose();
    _retired = null;
  }

  void _activate(_SheetSession session) => _active = session;

  void _deactivate(_SheetSession session) {
    if (identical(_active, session)) _active = null;
    // 退场动画此刻可能还没结束，留到下次打开面板时再释放。
    _retired?.controller.dispose();
    _retired = session;
  }

  /// 当前是否可以被返回手势接管：面板还在，且它就是栈顶路由，并且完全展开。
  bool get _canTakeOver {
    final _SheetSession? session = _active;
    if (session == null) return false;
    if (_routeObserver.top is! ModalBottomSheetRoute<dynamic>) return false;
    final AnimationController controller = session.controller;
    return !controller.isDismissed && controller.isCompleted;
  }

  @override
  bool handleStartBackGesture(PredictiveBackEvent backEvent) {
    final _SheetSession? session = _active;
    if (session == null || !_canTakeOver) return false;
    session.driving = true;
    // 手势 progress 0 表示面板完全展开，1 表示已经收到底。
    session.controller.value = (1 - backEvent.progress).clamp(0.0, 1.0);
    return true;
  }

  @override
  void handleUpdateBackGestureProgress(PredictiveBackEvent backEvent) {
    final _SheetSession? session = _active;
    if (session == null || !session.driving) return;
    session.controller.value = (1 - backEvent.progress).clamp(0.0, 1.0);
  }

  @override
  void handleCancelBackGesture() {
    final _SheetSession? session = _active;
    if (session == null || !session.driving) return;
    session.driving = false;
    if (!session.controller.isCompleted) session.controller.forward();
  }

  @override
  void handleCommitBackGesture() {
    final _SheetSession? session = _active;
    if (session == null || !session.driving) return;
    session.driving = false;
    // 收尾一律交给框架：pop 会走 route 自己的退场过渡。不要在这里手动 reverse 再
    // whenComplete(pop)，也不要在 future 完成时立刻 dispose 控制器。
    if (session.controller.value >= 1) {
      // 手指还没真正收起来就提交：让框架从当前位置补完收起动画。
      session.controller.value = 0.999;
    }
    session.navigator.maybePop();
  }
}

/// 挂在树里的 vsync 提供者。面板控制器在路由建立前就要创建，vsync 只能从这里拿。
class SheetVsyncHost extends StatefulWidget {
  const SheetVsyncHost({super.key, required this.child});

  final Widget child;

  @override
  State<SheetVsyncHost> createState() => _SheetVsyncHostState();
}

class _SheetVsyncHostState extends State<SheetVsyncHost>
    with TickerProviderStateMixin {
  @override
  void initState() {
    super.initState();
    PredictiveSheetBack.instance.attachVsync(this);
  }

  @override
  void dispose() {
    PredictiveSheetBack.instance.detachVsync(this);
    PredictiveSheetBack.instance.disposeRetired();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => widget.child;
}

/// 与 [showModalBottomSheet] 用法一致，额外接上 Android 的预测性返回。
///
/// 拿不到 vsync（例如单测直接 pump 页面）或不在 Android 上时，原样退回
/// [showModalBottomSheet]，行为与改造前完全一致。
Future<T?> showPredictiveSheet<T>({
  required BuildContext context,
  required WidgetBuilder builder,
  bool isScrollControlled = false,
  bool useSafeArea = false,
}) {
  final TickerProvider? vsync = PredictiveSheetBack.instance.vsync;
  // 用 defaultTargetPlatform 而不是 Platform.isAndroid：前者可以在测试里覆写，
  // 后者永远反映运行测试的宿主机。
  if (defaultTargetPlatform != TargetPlatform.android || vsync == null) {
    return showModalBottomSheet<T>(
      context: context,
      builder: builder,
      isScrollControlled: isScrollControlled,
      useSafeArea: useSafeArea,
    );
  }
  final _SheetSession session = _SheetSession(
    navigator: Navigator.of(context),
    vsync: vsync,
  );
  PredictiveSheetBack.instance._activate(session);
  return showModalBottomSheet<T>(
    context: context,
    builder: builder,
    isScrollControlled: isScrollControlled,
    useSafeArea: useSafeArea,
    transitionAnimationController: session.controller,
  ).whenComplete(() => PredictiveSheetBack.instance._deactivate(session));
}
