import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;
import 'dart:typed_data';
import 'dart:ui' as ui;

import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';
import 'package:lottie/lottie.dart';
import 'package:path/path.dart' as p;

import 'resource_packs.dart';

void _validateLottie(Map<String, dynamic> animation) {
  for (final name in ['w', 'h']) {
    final value = animation[name];
    if (value is! int || value < 1 || value > 8192) {
      throw const FormatException('动画尺寸不合法');
    }
  }
  for (final name in ['fr', 'ip', 'op']) {
    final value = animation[name];
    if (value is! num || !value.isFinite) {
      throw const FormatException('动画时间不合法');
    }
  }
  final rate = animation['fr'] as num;
  final start = animation['ip'] as num;
  final end = animation['op'] as num;
  if (rate < 1 ||
      rate > 120 ||
      start < 0 ||
      end <= start ||
      (end - start) / rate > 60) {
    throw const FormatException('动画时间超出播放限制');
  }
  if (animation['layers'] is! List || animation['assets'] is! List) {
    throw const FormatException('动画图层和资源必须是列表');
  }
  final pending = <Object?>[animation];
  while (pending.isNotEmpty) {
    final value = pending.removeLast();
    if (value is Map) {
      final fontPath = value['fPath'];
      if (value['x'] is String ||
          (fontPath != null &&
              fontPath != '' &&
              fontPath != false &&
              fontPath != 0)) {
        throw const FormatException('动画不允许表达式或外部字体');
      }
      if (value.containsKey('layers')) {
        final layers = value['layers'];
        if (layers is! List ||
            layers.any((layer) =>
                layer is! Map ||
                layer['ty'] is! int ||
                !{0, 1, 2, 3, 4, 5}.contains(layer['ty']))) {
          throw const FormatException('动画包含不支持的图层');
        }
      }
      pending.addAll(value.values);
    } else if (value is List) {
      pending.addAll(value);
    } else if (value is num && !value.isFinite) {
      throw const FormatException('动画数值必须有限');
    }
  }
}

void _checkCurrent(bool Function()? isCurrent) {
  if (isCurrent?.call() == false) throw StateError('Animation superseded');
}

Future<Uint8List> _cachedBytes(
    ResourcePacks resources, String path, bool Function()? isCurrent) async {
  final target = await resources.filePath('animation', path);
  _checkCurrent(isCurrent);
  if (target == null) {
    throw FormatException('动画资源未下载或缓存校验失败：$path');
  }
  final bytes = await File(target).readAsBytes();
  _checkCurrent(isCurrent);
  if (md5.convert(bytes).toString() != p.basename(target)) {
    throw FormatException('动画缓存校验失败：$path');
  }
  return bytes;
}

/// Only the animation manifest can supply scripts and portrait overrides.
Future<LottieComposition> loadAnimationComposition(
    ResourcePacks resources, String scriptPath,
    {Map<String, String> images = const {},
    Map<String, String> texts = const {},
    bool Function()? isCurrent}) async {
  if (!isAnimationScriptPath(scriptPath)) {
    throw const FormatException('不是动画脚本路径');
  }
  final bytes = await _cachedBytes(resources, scriptPath, isCurrent);
  final decoded = jsonDecode(utf8.decode(bytes));
  if (decoded is! Map<String, dynamic>) {
    throw const FormatException('动画脚本必须是 Lottie 对象');
  }
  _validateLottie(decoded);
  final bitmaps = <String, ui.Image>{};
  final assets = decoded['assets'] as List;
  final ids = <String>{};
  for (final asset in assets) {
    if (asset is! Map ||
        asset['id'] is! String ||
        !ids.add(asset['id'] as String)) {
      throw const FormatException('动画资源标识不合法');
    }
  }
  try {
    final additions = <Map<String, dynamic>>[];
    for (final asset in assets) {
      final embedded = asset.containsKey('e') ? asset['e'] : 0;
      if (embedded is! int || embedded != 0) {
        throw const FormatException('动画不允许内嵌图片');
      }
      if (!asset.containsKey('p') && !asset.containsKey('u')) continue;
      final defaultPath = animationImagePath(
          scriptPath, asset.containsKey('u') ? asset['u'] : '', asset['p']);
      final id = asset['id'] as String;
      final override = images[id];
      if (override != null) {
        // Validate a package-root image path, not a script-relative dependency.
        animationImagePath('scripts/override.json', '', override);
      }
      final imageBytes =
          await _cachedBytes(resources, override ?? defaultPath, isCurrent);
      ui.Codec codec;
      try {
        codec = await ui.instantiateImageCodec(imageBytes);
      } catch (_) {
        throw const FormatException('动画图片无法解码');
      }
      late ui.Image bitmap;
      try {
        bitmap = (await codec.getNextFrame()).image;
      } finally {
        codec.dispose();
      }
      if (isCurrent?.call() == false) {
        bitmap.dispose();
        throw StateError('Animation superseded');
      }
      if (override == null) {
        bitmaps[id] = bitmap;
        continue;
      }
      final innerId = '__override_$id';
      if (!ids.add(innerId)) {
        bitmap.dispose();
        throw const FormatException('动画图片标识冲突');
      }
      bitmaps[innerId] = bitmap;
      final width = asset['w'];
      final height = asset['h'];
      if (width is! num || height is! num || width <= 0 || height <= 0) {
        throw const FormatException('动画图片尺寸不合法');
      }
      final scale = math.min(width / bitmap.width, height / bitmap.height);
      additions.add({
        'id': innerId,
        'w': bitmap.width,
        'h': bitmap.height,
        'u': '',
        'p': override,
        'e': 0,
      });
      // Lottie draws intrinsic bitmap dimensions. A containing precomp preserves
      // the template's coordinates without resampling or stretching the PNG.
      asset.remove('p');
      asset.remove('u');
      asset['layers'] = [
        {
          'ty': 2,
          'ind': 1,
          'refId': innerId,
          'ip': decoded['ip'],
          'op': decoded['op'],
          'st': 0,
          'ks': {
            'o': {'a': 0, 'k': 100},
            'r': {'a': 0, 'k': 0},
            'a': {
              'a': 0,
              'k': [0, 0, 0]
            },
            'p': {
              'a': 0,
              'k': [
                (width - bitmap.width * scale) / 2,
                (height - bitmap.height * scale) / 2,
                0
              ]
            },
            's': {
              'a': 0,
              'k': [scale * 100, scale * 100, 100]
            },
          },
        }
      ];
      for (final layers in [
        decoded['layers'],
        ...assets.map((a) => a['layers'])
      ]) {
        if (layers is! List) continue;
        for (final layer in layers) {
          if (layer is Map && layer['refId'] == id && layer['ty'] == 2) {
            layer['ty'] = 0;
            layer['w'] = width;
            layer['h'] = height;
          }
        }
      }
    }
    assets.addAll(additions);
    for (final layers in [
      decoded['layers'],
      ...assets.map((a) => a['layers'])
    ]) {
      if (layers is! List) continue;
      for (final layer in layers) {
        if (layer is! Map || layer['ty'] != 5) continue;
        final replacement = texts[layer['nm']];
        if (replacement == null) continue;
        final keys = layer['t']?['d']?['k'];
        if (keys is! List) throw const FormatException('动画文本不合法');
        for (final key in keys) {
          final document = key['s'] as Map;
          final size = (document['s'] as num).toDouble();
          final box = document['sz'];
          final available = box is List && box.isNotEmpty && box[0] is num
              ? (box[0] as num).toDouble()
              : (decoded['w'] as num).toDouble() * .8;
          final painter = TextPainter(
            text: TextSpan(
                text: replacement,
                style: TextStyle(
                    fontFamily: 'HarmonyOS Sans SC',
                    fontWeight: FontWeight.bold,
                    fontSize: size,
                    letterSpacing: 0)),
            textDirection: TextDirection.ltr,
          )..layout();
          final factor =
              math.min(1.0, available / math.max(1.0, painter.width));
          painter.dispose();
          document['t'] = replacement;
          document['s'] = size * factor;
          document['tr'] = 0;
          document['f'] = 'HarmonyOS Sans SC';
          if (document['lh'] is num) {
            document['lh'] = (document['lh'] as num) * factor;
          }
          final position = document['ps'];
          if (position is List && position.length == 2 && position[1] is num) {
            position[1] = (position[1] as num) * factor;
          }
        }
      }
    }
    final composition =
        LottieComposition.parseJsonBytes(utf8.encode(jsonEncode(decoded)));
    for (final image in composition.images.values) {
      image.loadedImage = bitmaps[image.id];
      if (image.loadedImage == null) {
        throw FormatException('动画图片未下载：${image.id}');
      }
    }
    return composition;
  } catch (_) {
    for (final image in bitmaps.values) {
      image.dispose();
    }
    rethrow;
  }
}

void disposeAnimationComposition(LottieComposition? composition) {
  for (final asset in composition?.images.values ?? <LottieImageAsset>[]) {
    asset.loadedImage?.dispose();
    asset.loadedImage = null;
  }
}

class AnimationPlayer extends StatefulWidget {
  const AnimationPlayer({
    super.key,
    required this.resources,
    required this.scriptPath,
    this.repeat = false,
    this.controller,
    this.onLoaded,
  });
  final ResourcePacks resources;
  final String scriptPath;
  final bool repeat;
  final Animation<double>? controller;
  final ValueChanged<LottieComposition>? onLoaded;

  @override
  State<AnimationPlayer> createState() => _AnimationPlayerState();
}

class _AnimationPlayerState extends State<AnimationPlayer> {
  LottieComposition? _composition;
  Object? _error;
  int _load = 0;

  @override
  void initState() {
    super.initState();
    _reload();
  }

  @override
  void didUpdateWidget(covariant AnimationPlayer oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.resources != widget.resources ||
        oldWidget.scriptPath != widget.scriptPath) {
      _reload();
    }
  }

  Future<void> _reload() async {
    final load = ++_load;
    disposeAnimationComposition(_composition);
    _composition = null;
    _error = null;
    try {
      final composition = await loadAnimationComposition(
          widget.resources, widget.scriptPath,
          isCurrent: () => mounted && load == _load);
      if (!mounted || load != _load) {
        disposeAnimationComposition(composition);
        return;
      }
      setState(() => _composition = composition);
      widget.onLoaded?.call(composition);
    } catch (error) {
      if (mounted && load == _load) setState(() => _error = error);
    }
  }

  @override
  void dispose() {
    ++_load;
    disposeAnimationComposition(_composition);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (_error != null) {
      return Center(
          child: Padding(
        padding: const EdgeInsets.all(24),
        child: Text('动画无法播放：$_error', textAlign: TextAlign.center),
      ));
    }
    final composition = _composition;
    if (composition == null) {
      return const Center(child: CircularProgressIndicator());
    }
    return SizedBox.expand(
        child: Lottie(
      composition: composition,
      controller: widget.controller,
      repeat: widget.repeat,
      fit: BoxFit.contain,
      frameRate: FrameRate.max,
      filterQuality: FilterQuality.medium,
    ));
  }
}

Future<void> showAnimationPreviewDialog(
  BuildContext context, {
  required ResourcePacks resources,
  required String scriptPath,
}) =>
    showDialog<void>(
      context: context,
      builder: (_) =>
          _AnimationPreview(resources: resources, scriptPath: scriptPath),
    );

class _AnimationPreview extends StatefulWidget {
  const _AnimationPreview({required this.resources, required this.scriptPath});
  final ResourcePacks resources;
  final String scriptPath;

  @override
  State<_AnimationPreview> createState() => _AnimationPreviewState();
}

class _AnimationPreviewState extends State<_AnimationPreview>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(vsync: this)
    ..addStatusListener(_statusChanged);
  bool _ready = false;
  bool _playing = false;

  void _statusChanged(AnimationStatus status) {
    if (status == AnimationStatus.completed && mounted) {
      setState(() => _playing = false);
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Dialog.fullscreen(
        child: Scaffold(
          appBar: AppBar(
            automaticallyImplyLeading: false,
            title: Text(widget.scriptPath,
                maxLines: 1, overflow: TextOverflow.ellipsis),
            actions: [
              IconButton(
                tooltip: '重播',
                onPressed: !_ready
                    ? null
                    : () {
                        _controller.forward(from: 0);
                        setState(() => _playing = true);
                      },
                icon: const Icon(Icons.replay),
              ),
              IconButton(
                tooltip: _playing ? '暂停' : '播放',
                onPressed: !_ready
                    ? null
                    : () {
                        if (_playing) {
                          _controller.stop();
                        } else {
                          _controller.forward(
                              from: _controller.isCompleted
                                  ? 0
                                  : _controller.value);
                        }
                        setState(() => _playing = !_playing);
                      },
                icon: Icon(_playing ? Icons.pause : Icons.play_arrow),
              ),
              IconButton(
                tooltip: '关闭动画',
                onPressed: () => Navigator.of(context).pop(),
                icon: const Icon(Icons.close),
              ),
            ],
          ),
          body: AnimationPlayer(
            resources: widget.resources,
            scriptPath: widget.scriptPath,
            controller: _controller,
            onLoaded: (composition) {
              _controller.duration = composition.duration;
              _controller.forward(from: 0);
              setState(() {
                _ready = true;
                _playing = true;
              });
            },
          ),
        ),
      );
}
