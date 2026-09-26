import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'design.dart';

/// 登录前工作量证明的计算进度卡片。
///
/// 为什么不是进度条：服务端难度是「期望尝试次数」（十六进制前缀 N 位 ≈ 16^N 次），
/// 实际耗时服从指数分布——解出来的那一刻可能在任何一次尝试上。画一个百分比
/// 进度条只会骗人，所以这里展示**真实计数与耗时**：环上跑动的彗尾表示还在算，
/// 数字让等待有依据。
class PowProgressPanel extends StatefulWidget {
  const PowProgressPanel({
    super.key,
    required this.attempts,
    required this.difficulty,
    required this.startedAt,
  });

  /// isolate 回报的已尝试次数（真实值，不是估算）。
  final int attempts;
  final int difficulty;

  /// 本机开始计算的时间；为空时按「刚开始」显示。
  final DateTime? startedAt;

  @override
  State<PowProgressPanel> createState() => _PowProgressPanelState();
}

class _PowProgressPanelState extends State<PowProgressPanel>
    with SingleTickerProviderStateMixin {
  late final AnimationController _spin = AnimationController(
    vsync: this,
    duration: const Duration(milliseconds: 1600),
  )..repeat();
  // 耗时文字每 200ms 刷一次就够：跟每帧重排整棵子树比起来便宜得多，
  // 环的旋转由 painter 的 repaint 单独驱动，不触发 widget 重建。
  Timer? _clock;

  @override
  void initState() {
    super.initState();
    _clock = Timer.periodic(const Duration(milliseconds: 200), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _clock?.cancel();
    _spin.dispose();
    super.dispose();
  }

  Duration get _elapsed {
    final start = widget.startedAt;
    if (start == null) return Duration.zero;
    final value = DateTime.now().difference(start);
    return value.isNegative ? Duration.zero : value;
  }

  @override
  Widget build(BuildContext context) {
    final palette = context.palette;
    final elapsed = _elapsed;
    // 环里的十六进制取尝试次数的低位字节：它每算一次就变，
    // 看起来像滚动中的计数器；取高位的话在解出来之前几乎一直是 00。
    final counterHex = (widget.attempts & 0xff).toRadixString(16).padLeft(2, '0').toUpperCase();
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(AppSpacing.lg),
      decoration: BoxDecoration(
        color: palette.accentSoft,
        borderRadius: BorderRadius.circular(AppRadius.card),
        border: Border.all(color: palette.accent.withValues(alpha: 0.24)),
      ),
      child: Row(
        children: [
          SizedBox.square(
            dimension: 64,
            child: Stack(
              alignment: Alignment.center,
              children: [
                RepaintBoundary(
                  child: CustomPaint(
                    size: const Size.square(64),
                    painter: _CometRingPainter(
                      spin: _spin,
                      accent: palette.accent,
                      track: palette.accent.withValues(alpha: 0.16),
                    ),
                  ),
                ),
                Text(
                  counterHex,
                  style: TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w700,
                    fontFeatures: const [FontFeature.tabularFigures()],
                    color: palette.accent,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: AppSpacing.lg),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '工作量证明',
                  style: TextStyle(
                    fontSize: 15,
                    fontWeight: FontWeight.w600,
                    color: palette.text,
                  ),
                ),
                const SizedBox(height: AppSpacing.xs),
                Text(
                  '已尝试 ${_thousands(widget.attempts)} 次 · 用时 ${_seconds(elapsed)}',
                  style: TextStyle(
                    fontSize: 13,
                    fontFeatures: const [FontFeature.tabularFigures()],
                    color: palette.textSecondary,
                  ),
                ),
                const SizedBox(height: AppSpacing.xs),
                Text(
                  '这用来抵挡脚本刷登录接口，通常几秒内完成，请不要关闭页面',
                  style: TextStyle(fontSize: 12, color: palette.textTertiary),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// 旋转的彗尾弧：主弧带一点渐隐的尾巴，比 CircularProgressIndicator 更有“在算”的感觉。
class _CometRingPainter extends CustomPainter {
  _CometRingPainter({
    required this.spin,
    required this.accent,
    required this.track,
  }) : super(repaint: spin);

  final Animation<double> spin;
  final Color accent;
  final Color track;

  @override
  void paint(Canvas canvas, Size size) {
    final center = size.center(Offset.zero);
    final radius = size.shortestSide / 2 - 3;
    final rect = Rect.fromCircle(center: center, radius: radius);
    final trackPaint = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 3
      ..color = track;
    canvas.drawCircle(center, radius, trackPaint);

    // 主弧 + 两段拖尾：越靠后越短越淡，形成彗尾。
    final head = spin.value * 2 * math.pi - math.pi / 2;
    void arc(double start, double sweep, double width, double alpha) {
      final paint = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = width
        ..strokeCap = StrokeCap.round
        ..color = accent.withValues(alpha: alpha);
      canvas.drawArc(rect, start, sweep, false, paint);
    }

    const mainSweep = math.pi * 0.52;
    arc(head, mainSweep, 3, 0.95);
    arc(head - math.pi * 0.08, mainSweep * 0.55, 3, 0.42);
    arc(head - math.pi * 0.15, mainSweep * 0.28, 3, 0.18);
  }

  @override
  bool shouldRepaint(covariant _CometRingPainter old) =>
      old.accent != accent || old.track != track;
}

/// 12345 -> 12,345：尝试次数会到几十万，分组读起来才不费劲。
String _thousands(int value) {
  final digits = value.toString();
  final buffer = StringBuffer();
  for (var i = 0; i < digits.length; i++) {
    if (i > 0 && (digits.length - i) % 3 == 0) buffer.write(',');
    buffer.write(digits[i]);
  }
  return buffer.toString();
}

/// 12.3 秒 / 2 分 05 秒：难度调高后等待可能跨分钟，纯秒数会越来越难读。
String _seconds(Duration elapsed) {
  if (elapsed.inSeconds < 60) {
    return '${(elapsed.inMilliseconds / 1000).toStringAsFixed(1)} 秒';
  }
  final minutes = elapsed.inMinutes;
  final seconds = elapsed.inSeconds % 60;
  return '$minutes 分 ${seconds.toString().padLeft(2, '0')} 秒';
}
