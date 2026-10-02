import 'dart:async';
import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:flutter_test/flutter_test.dart';
import 'package:seven_double_client/src/chat_image.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  test('复杂图片压缩至100KB且仍可解码，保持比例', () async {
    final random = Random(17);
    final pixels = Uint8List(1024 * 512 * 4);
    for (var i = 0; i < pixels.length; i += 4) {
      pixels[i] = random.nextInt(256);
      pixels[i + 1] = random.nextInt(256);
      pixels[i + 2] = random.nextInt(256);
      pixels[i + 3] = 255;
    }
    final decoded = Completer<ui.Image>();
    ui.decodeImageFromPixels(
        pixels, 1024, 512, ui.PixelFormat.rgba8888, decoded.complete);
    final source = await decoded.future;
    final original = await source.toByteData(format: ui.ImageByteFormat.png);
    source.dispose();
    expect(original!.lengthInBytes, greaterThan(maxChatImageBytes));
    final dataUrl = await compressChatImage(original.buffer.asUint8List());
    final bytes = base64Decode(dataUrl.split(',').last);
    expect(bytes.length, lessThanOrEqualTo(maxChatImageBytes));
    final codec = await ui.instantiateImageCodec(bytes);
    final frame = await codec.getNextFrame();
    expect(frame.image.width, lessThan(1024));
    expect(frame.image.width / frame.image.height, closeTo(2, .02));
    frame.image.dispose();
    codec.dispose();
  });

  test('空图片和无效图片返回错误', () async {
    await expectLater(compressChatImage(Uint8List(0)), throwsFormatException);
    await expectLater(
        compressChatImage(Uint8List.fromList([1, 2, 3])), throwsException);
  });
}
