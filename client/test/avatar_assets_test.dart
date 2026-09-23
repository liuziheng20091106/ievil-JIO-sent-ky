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

  // 需求：对局中主持人头像始终是月代雪，大厅则随机一个角色头像。
  test('大厅随机头像取自真实有立绘的角色牌', () async {
    final bytes = await rootBundle.load(hostAvatarAsset);
    expect(bytes.lengthInBytes, greaterThan(1000), reason: '主持人立绘缺失');
    final pool = {for (final role in roleVisuals) if (role.hasArt) role.id};
    expect(pool, isNotEmpty);
    expect(pool.contains(lobbyAvatarRoleId), isTrue,
        reason: '大厅随机头像必须是真实角色，不能落到占位图');
  });

  testWidgets('主持人头像渲染月代雪立绘而不是占位', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
          home: Scaffold(
              body: Center(
                  child: RoleAvatar(roleId: 'host', host: true, size: 64)))),
    );
    await tester.pumpAndSettle();
    final image = tester.widget<Image>(find.byType(Image));
    expect((image.image as AssetImage).assetName, hostAvatarAsset);
  });
}
