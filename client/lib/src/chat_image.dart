import 'dart:convert';
import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/services.dart';

const maxChatImageBytes = 100 * 1024;
const _imageChannel = MethodChannel('chat_image');

Future<String?> pickChatImage() async {
  final bytes = await _imageChannel.invokeMethod<Uint8List>('pick');
  return bytes == null ? null : compressChatImage(bytes);
}

Future<String> compressChatImage(Uint8List bytes) async {
  if (bytes.isEmpty || bytes.length > 20 * 1024 * 1024) {
    throw const FormatException('请选择20MB以内的图片');
  }
  final buffer = await ui.ImmutableBuffer.fromUint8List(bytes);
  ui.ImageDescriptor? descriptor;
  try {
    descriptor = await ui.ImageDescriptor.encoded(buffer);
    var edge = math.min(1280, math.max(descriptor.width, descriptor.height));
    while (true) {
      final scale = edge / math.max(descriptor.width, descriptor.height);
      final codec = await descriptor.instantiateCodec(
        targetWidth: math.max(1, (descriptor.width * scale).round()),
        targetHeight: math.max(1, (descriptor.height * scale).round()),
      );
      Uint8List compressed;
      try {
        final frame = await codec.getNextFrame();
        try {
          final data =
              await frame.image.toByteData(format: ui.ImageByteFormat.png);
          if (data == null) throw const FormatException('无法压缩这张图片');
          compressed =
              data.buffer.asUint8List(data.offsetInBytes, data.lengthInBytes);
        } finally {
          frame.image.dispose();
        }
      } finally {
        codec.dispose();
      }
      if (compressed.length <= maxChatImageBytes) {
        return 'data:image/png;base64,${base64Encode(compressed)}';
      }
      if (edge == 1) throw const FormatException('无法将图片压缩到100KB以内');
      edge = math.max(1, (edge * .75).floor());
    }
  } finally {
    descriptor?.dispose();
    buffer.dispose();
  }
}
