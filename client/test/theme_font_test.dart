import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:seven_double_client/src/design.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('三档 HarmonyOS Sans SC 字体随包提供且可加载', () async {
    for (final weight in const [400, 500, 700]) {
      final bytes = await rootBundle.load(
        'assets/fonts/HarmonyOS_Sans_SC_${weight == 400 ? 'Regular' : weight == 500 ? 'Medium' : 'Bold'}.ttf',
      );
      expect(bytes.lengthInBytes, greaterThan(1000000),
          reason: 'weight $weight 字体资源过小，可能是占位文件');
      // 首四字节为 TrueType/OpenType 魔数；loadFontFromList 在字体无法解析时抛错。
      final data = ByteData.sublistView(
        Uint8List.fromList(bytes.buffer.asUint8List(0, 4)),
      );
      expect(data.getUint32(0), anyOf(0x00010000, 0x4F54544F, 0x74727565));
      final loader = FontLoader('HarmonyOS Sans SC $weight')
        ..addFont(Future.value(bytes));
      await loader.load();
    }
  });

  testWidgets('主题把 HarmonyOS Sans SC 应用到正文样式', (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: buildAppTheme(),
        home: const Scaffold(body: Center(child: Text('魔法裁判'))),
      ),
    );
    await tester.pumpAndSettle();
    final context = tester.element(find.text('魔法裁判'));
    expect(Theme.of(context).textTheme.bodyMedium!.fontFamily, kAppFontFamily);
    expect(Theme.of(context).textTheme.titleLarge!.fontFamily, kAppFontFamily);
    expect(Theme.of(context).scaffoldBackgroundColor, AppColors.background);
  });
}
