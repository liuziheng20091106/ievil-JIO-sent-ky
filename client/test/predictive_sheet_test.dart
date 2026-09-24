// 回归检查：行动弹窗（showPredictiveSheet）必须接上 Android 的预测性返回，
// 并且收尾不能把面板留在半途。
//
// 对应用户报告的缺陷：Android 14 上从行动弹窗返回时没有系统预测性返回预览。
// 排查结论：ModalBottomSheetRoute 不经过主题的过渡器，因此框架不给它预测性返回，
// 需要在返回手势里直接驱动面板自己的 AnimationController（见 lib/src/predictive_sheet.dart）。
//
// 这里用真机同款的事件注入（flutter/backgesture 通道）验证机制。真机手感仍需人工确认。
//
// 运行方式（client 目录）：flutter test test/predictive_sheet_test.dart

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:seven_double_client/src/predictive_sheet.dart';

Future<void> backGesture(
  WidgetTester tester,
  String method, [
  Map<String, dynamic>? args,
]) async {
  await tester.binding.defaultBinaryMessenger.handlePlatformMessage(
    'flutter/backgesture',
    const StandardMethodCodec().encodeMethodCall(MethodCall(method, args)),
    (ByteData? _) {},
  );
}

Map<String, dynamic> startArgs(double progress) => <String, dynamic>{
      'touchOffset': <double>[5.0, 300.0],
      'progress': progress,
      'swipeEdge': 0,
    };

/// 打开一个带「行动面板」字样的弹窗，用来观察它的位移。
Future<void> pumpSheet(WidgetTester tester) async {
  await tester.binding.setSurfaceSize(const Size(400, 800));
  addTearDown(() => tester.binding.setSurfaceSize(null));

  await tester.pumpWidget(
    SheetVsyncHost(
      child: MaterialApp(
        navigatorObservers: [PredictiveSheetBack.instance.routeObserver],
        home: Builder(
          builder: (context) => Scaffold(
            body: Center(
              child: FilledButton(
                onPressed: () => showPredictiveSheet<void>(
                  context: context,
                  isScrollControlled: true,
                  builder: (_) => const SizedBox(
                    height: 300,
                    child: Center(child: Text('行动面板')),
                  ),
                ),
                child: const Text('打开'),
              ),
            ),
          ),
        ),
      ),
    ),
  );
  PredictiveSheetBack.instance.start();
  addTearDown(PredictiveSheetBack.instance.stop);

  await tester.tap(find.text('打开'));
  await tester.pumpAndSettle();
  expect(find.text('行动面板'), findsOneWidget);
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  testWidgets('返回手势跟手位移，取消后回原位', (tester) async {
    await pumpSheet(tester);
    final double before = tester.getTopLeft(find.text('行动面板')).dy;

    await backGesture(tester, 'startBackGesture', startArgs(0));
    await tester.pump();
    await backGesture(tester, 'updateBackGestureProgress', <String, dynamic>{
      'x': 100.0,
      'y': 300.0,
      'progress': 0.4,
      'swipeEdge': 0,
    });
    await tester.pump();

    expect(
      tester.getTopLeft(find.text('行动面板')).dy,
      greaterThan(before),
      reason: '面板应随返回手势下移',
    );

    await backGesture(tester, 'cancelBackGesture');
    await tester.pumpAndSettle();
    expect(find.text('行动面板'), findsOneWidget);
    expect(
      tester.getTopLeft(find.text('行动面板')).dy,
      moreOrLessEquals(before, epsilon: 1.0),
      reason: '取消后应回到原位',
    );
  }, variant: TargetPlatformVariant.only(TargetPlatform.android));

  testWidgets('半途松手提交也能收干净，不留下卡死的面板', (tester) async {
    await pumpSheet(tester);

    await backGesture(tester, 'startBackGesture', startArgs(0));
    await tester.pump();
    await backGesture(tester, 'updateBackGestureProgress', <String, dynamic>{
      'x': 100.0,
      'y': 300.0,
      'progress': 0.5,
      'swipeEdge': 0,
    });
    await tester.pump();
    expect(find.text('行动面板'), findsOneWidget);

    await backGesture(tester, 'commitBackGesture');
    await tester.pumpAndSettle();
    expect(
      find.text('行动面板'),
      findsNothing,
      reason: '半途提交也要完整收起：控制器不能在退场动画结束前被释放',
    );
  }, variant: TargetPlatformVariant.only(TargetPlatform.android));

  testWidgets('面板关闭后返回手势不再被接管', (tester) async {
    await pumpSheet(tester);
    await backGesture(tester, 'startBackGesture', startArgs(0));
    await tester.pump();

    Navigator.of(tester.element(find.text('打开'))).pop();
    await tester.pumpAndSettle();
    expect(find.text('行动面板'), findsNothing);

    // 面板已不在栈顶：再来的返回手势不应被面板接管（这里仅断言不抛异常）。
    await backGesture(tester, 'startBackGesture', startArgs(0));
    await tester.pump();
    await backGesture(tester, 'cancelBackGesture');
    await tester.pumpAndSettle();
    expect(find.text('打开'), findsOneWidget);
  }, variant: TargetPlatformVariant.only(TargetPlatform.android));
}
