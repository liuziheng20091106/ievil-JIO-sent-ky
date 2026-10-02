import 'package:flutter/material.dart';
import 'package:flutter/scheduler.dart';
import 'package:lottie/lottie.dart';

import 'animation_player.dart';
import 'models.dart';
import 'resource_packs.dart';
import 'store.dart';

/// Placed above the root Navigator, including its dialogs and modal sheets.
class GameAnimationOverlay extends StatefulWidget {
  const GameAnimationOverlay({super.key, required this.store, this.resources});
  final GameStore store;
  final ResourcePacks? resources;

  @override
  State<GameAnimationOverlay> createState() => _GameAnimationOverlayState();
}

class _GameAnimationOverlayState extends State<GameAnimationOverlay>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller = AnimationController(vsync: this)
    ..addStatusListener(_statusChanged);
  LottieComposition? _composition;
  int _generation = 0;

  @override
  void initState() {
    super.initState();
    widget.store.gameAnimation.addListener(_requestChanged);
  }

  @override
  void didUpdateWidget(covariant GameAnimationOverlay oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.store != widget.store ||
        oldWidget.resources != widget.resources) {
      oldWidget.store.gameAnimation.removeListener(_requestChanged);
      widget.store.gameAnimation.addListener(_requestChanged);
      ++_generation;
      _clear();
    }
  }

  void _statusChanged(AnimationStatus status) {
    if (status == AnimationStatus.completed) {
      widget.store.gameAnimation.value = null;
    }
  }

  void _clear() {
    _controller.stop();
    disposeAnimationComposition(_composition);
    _composition = null;
    if (!mounted) return;
    if (SchedulerBinding.instance.schedulerPhase ==
        SchedulerPhase.persistentCallbacks) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) setState(() {});
      });
    } else {
      setState(() {});
    }
  }

  void _requestChanged() {
    final generation = ++_generation;
    _clear();
    final request = widget.store.gameAnimation.value;
    if (request != null) _load(request, generation);
  }

  Future<void> _load(GameAnimationRequest request, int generation) async {
    try {
      final api = widget.store.api;
      final resources = widget.resources ??
          (api == null ? null : await ResourcePacks.create(api));
      if (resources == null || !mounted || generation != _generation) return;
      final composition = await loadAnimationComposition(
          resources, request.script,
          images: request.images,
          texts: request.texts,
          isCurrent: () =>
              mounted &&
              generation == _generation &&
              request.gameId == widget.store.gameId);
      if (!mounted ||
          generation != _generation ||
          request.gameId != widget.store.gameId) {
        disposeAnimationComposition(composition);
        return;
      }
      _controller.duration = composition.duration;
      setState(() => _composition = composition);
      _controller.forward(from: 0);
    } catch (_) {
      // Live effects are optional; only the manual preview reports cache errors.
    }
  }

  @override
  void dispose() {
    ++_generation;
    widget.store.gameAnimation.removeListener(_requestChanged);
    _controller.dispose();
    disposeAnimationComposition(_composition);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final composition = _composition;
    if (composition == null) return const SizedBox.shrink();
    return Positioned.fill(
      child: IgnorePointer(
        child: Stack(fit: StackFit.expand, children: [
          AnimatedBuilder(
            animation: _controller,
            builder: (_, __) {
              final elapsed =
                  _controller.value * composition.duration.inMilliseconds;
              final remaining =
                  (1 - _controller.value) * composition.duration.inMilliseconds;
              final fade = (elapsed < remaining ? elapsed : remaining) / 200;
              return ColoredBox(
                key: const ValueKey('game-animation-mask'),
                color: Colors.black.withValues(alpha: .55 * fade.clamp(0, 1)),
              );
            },
          ),
          Lottie(
            key: const ValueKey('game-animation-body'),
            composition: composition,
            controller: _controller,
            repeat: false,
            fit: BoxFit.contain,
            frameRate: FrameRate.max,
            filterQuality: FilterQuality.medium,
          ),
        ]),
      ),
    );
  }
}
