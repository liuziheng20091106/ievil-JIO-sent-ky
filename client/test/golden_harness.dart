/// golden 测试共用的小工具：把真实界面渲染出来既方便肉眼确认，也防止布局被改坏。
///
/// 测试环境默认没有可用字形（中文与图标都会渲染成方框），所以每个 golden 套件都要
/// 先加载内置字体与 Material 图标字体，这里统一一份。
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:seven_double_client/src/design.dart';

Future<void> loadBundledFonts() async {
  TestWidgetsFlutterBinding.ensureInitialized();
  for (final weight in const [400, 500, 700]) {
    final name = weight == 400
        ? 'Regular'
        : weight == 500
            ? 'Medium'
            : 'Bold';
    final bytes = await rootBundle.load('assets/fonts/HarmonyOS_Sans_SC_$name.ttf');
    final loader = FontLoader(kAppFontFamily)..addFont(Future.value(bytes));
    await loader.load();
  }
  final root = Platform.environment['FLUTTER_ROOT'];
  final iconPaths = <String>[
    if (root != null)
      '$root/bin/cache/artifacts/material_fonts/materialicons-regular.otf',
    r'C:\src\flutter\bin\cache\artifacts\material_fonts\materialicons-regular.otf',
  ];
  for (final path in iconPaths) {
    final file = File(path);
    if (file.existsSync()) {
      final bytes = ByteData.view(file.readAsBytesSync().buffer);
      await (FontLoader('MaterialIcons')..addFont(Future.value(bytes))).load();
      break;
    }
  }
}

/// 固定成手机竖屏尺寸并把界面渲染出来。
Future<void> pumpPhone(WidgetTester tester, Widget page) async {
  await tester.binding.setSurfaceSize(const Size(420, 880));
  tester.view.physicalSize = const Size(420, 880);
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.reset);
  await tester.pumpWidget(MaterialApp(
    debugShowCheckedModeBanner: false,
    theme: buildAppTheme(),
    home: page,
  ));
  await tester.pump(const Duration(milliseconds: 600));
}
