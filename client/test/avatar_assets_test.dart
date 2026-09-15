import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:seven_double_client/src/role_visuals.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('角色立绘资源确实随包提供且可解码', () async {
    final errors = <String>[];
    final previous = FlutterError.onError;
    FlutterError.onError = (details) => errors.add(details.exceptionAsString());
    addTearDown(() => FlutterError.onError = previous);

    final roles = roleVisuals.where((role) => role.hasArt).toList();
    for (final role in roles) {
      final bytes = await rootBundle.load(role.avatarAsset);
      expect(bytes.lengthInBytes, greaterThan(1000), reason: '${role.id} 立绘过小');
      final codec = await ui.instantiateImageCodec(bytes.buffer.asUint8List());
      final frame = await codec.getNextFrame();
      expect(frame.image.width, greaterThan(0), reason: '${role.id} 无法解码');
      expect(frame.image.height, greaterThan(0), reason: '${role.id} 无法解码');
    }
    expect(errors, isEmpty, reason: '解码过程中出现错误：${errors.join(' / ')}');
  });

  testWidgets('头像组件渲染出图片而不是占位', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
          home: Scaffold(
              body: Center(child: RoleAvatar(roleId: 'emma', size: 64)))),
    );
    await tester.pumpAndSettle();
    expect(find.byType(Image), findsOneWidget);
  });
}
