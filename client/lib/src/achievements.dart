import 'dart:ui' as ui;

import 'package:flutter/material.dart';

import 'design.dart';
import 'models.dart';
import 'store.dart';

/// 成就的展示层：稀有度色板、徽章与头像摘要。
///
/// 成就本身由主持人授权、服务端保存（独立成就库）；客户端只负责按稀有度上色：
/// 1-10 共十种底色，数字越大越稀有、颜色越醒目。

const _achievementTextOutline = [
  Shadow(color: Color(0xB3000000), offset: Offset(1, 0)),
  Shadow(color: Color(0xB3000000), offset: Offset(-1, 0)),
  Shadow(color: Color(0xB3000000), offset: Offset(0, 1)),
  Shadow(color: Color(0xB3000000), offset: Offset(0, -1)),
];

const achievementRarityMax = 10;

String achievementRarityLabel(int rarity) => switch (rarity) {
      >= 9 => '专属',
      >= 5 => '特殊',
      _ => '稀有度 $rarity',
    };

/// 稀有度的一档配色：明亮底色，白字用深色轮廓保持可读。
class AchievementRarity {
  const AchievementRarity(this.background, {this.hasShine = false});

  final Color background;
  final Color foreground = Colors.white;
  final bool hasShine;

  static const _colors = <int, AchievementRarity>{
    1: AchievementRarity(Color(0xFF9AA3AF)), // 灰
    2: AchievementRarity(Color(0xFFAE6AE8)), // 紫
    3: AchievementRarity(Color(0xFF4B88F5)), // 蓝
    4: AchievementRarity(Color(0xFF20C7BA), hasShine: true), // 青
    5: AchievementRarity(Color(0xFFA6D989)), // 浅绿
    6: AchievementRarity(Color(0xFFD9B75A)), // 土黄
    7: AchievementRarity(Color(0xFFFF963F)), // 橘
    8: AchievementRarity(Color(0xFFF35B57)), // 红
    9: AchievementRarity(Color(0xFFC8D0DA), hasShine: true), // 银
    10: AchievementRarity(Color(0xFFFFD04F), hasShine: true), // 金
  };

  /// 越界（服务端异常数据或客户端版本落后）时收敛到 1-10，不抛异常。
  static AchievementRarity of(int rarity) {
    final value = rarity < 1
        ? 1
        : rarity > achievementRarityMax
            ? achievementRarityMax
            : rarity;
    return _colors[value]!;
  }
}

/// 成就徽章：稀有度底色 + 成就名。[dense] 用于对局内消息昵称旁。
class AchievementBadge extends StatelessWidget {
  const AchievementBadge({
    super.key,
    required this.name,
    required this.rarity,
    this.dense = false,
  });

  final String name;
  final int rarity;
  final bool dense;

  @override
  Widget build(BuildContext context) {
    final style = AchievementRarity.of(rarity);
    final radius = BorderRadius.circular(AppRadius.chip);
    final content = Padding(
      padding: EdgeInsets.symmetric(
        horizontal: dense ? 6 : 10,
        vertical: dense ? 2 : 4,
      ),
      // 青、银、金的底色与扫光由外层绘制，文字始终在反光上方。
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: dense ? 132 : 220),
        child: Text(
          name,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: TextStyle(
            fontSize: dense ? 10.5 : 12,
            height: 1.3,
            fontWeight: FontWeight.w600,
            color: style.foreground,
            shadows: _achievementTextOutline,
          ),
        ),
      ),
    );
    if (style.hasShine) {
      return _MetallicSurface(
        color: style.background,
        radius: radius,
        child: content,
      );
    }
    return DecoratedBox(
      decoration: BoxDecoration(color: style.background, borderRadius: radius),
      child: content,
    );
  }
}

class _MetallicSurface extends StatefulWidget {
  const _MetallicSurface({
    required this.color,
    required this.radius,
    required this.child,
  });

  final Color color;
  final BorderRadius radius;
  final Widget child;

  @override
  State<_MetallicSurface> createState() => _MetallicSurfaceState();
}

class _MetallicSurfaceState extends State<_MetallicSurface>
    with SingleTickerProviderStateMixin {
  late final _shine = AnimationController(
    vsync: this,
    duration: const Duration(seconds: 4),
  );

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (MediaQuery.disableAnimationsOf(context)) {
      _shine.stop();
      _shine.value = .18;
    } else if (!_shine.isAnimating) {
      _shine.repeat();
    }
  }

  @override
  void dispose() {
    _shine.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => RepaintBoundary(
        child: ClipRRect(
          borderRadius: widget.radius,
          child: CustomPaint(
            painter: _MetallicPainter(_shine, widget.color, widget.radius),
            child: widget.child,
          ),
        ),
      );
}

class _MetallicPainter extends CustomPainter {
  _MetallicPainter(this.shine, this.color, this.radius) : super(repaint: shine);

  final Animation<double> shine;
  final Color color;
  final BorderRadius radius;
  final _backgroundPaint = Paint();
  final _borderPaint = Paint()
    ..style = PaintingStyle.stroke
    ..strokeWidth = 1;
  final _reflectionPaint = Paint();
  final _reflectionBorderPaint = Paint()
    ..style = PaintingStyle.stroke
    ..strokeWidth = 1;
  Size? _size;
  late Rect _rect;
  late RRect _outline;

  static const _reflectionStops = [0.0, .5, 1.0];

  static const _reflectionColors = [
    Colors.transparent,
    Color(0x32FFFFFF),
    Colors.transparent,
  ];
  static const _rimColors = [
    Colors.transparent,
    Color(0xCCFFFFFF),
    Colors.transparent,
  ];

  @override
  void paint(Canvas canvas, Size size) {
    if (_size != size) {
      _size = size;
      _rect = Offset.zero & size;
      _outline = radius.toRRect(_rect).deflate(.5);
      _backgroundPaint.shader = LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: [Color.lerp(color, Colors.black, .12)!, color, color],
        stops: const [0, .45, 1],
      ).createShader(_rect);
      _borderPaint.color = Color.lerp(color, Colors.white, .6)!;
    }
    canvas.drawRect(_rect, _backgroundPaint);
    canvas.drawRRect(_outline, _borderPaint);
    // 扫光经过后留一段停顿；只重绘徽章，不逐帧重建聊天列表。
    if (shine.value >= .42) return;
    final progress = Curves.easeInOut.transform(shine.value / .42);
    final band = size.width * .28 + size.height;
    final x = -band + (size.width + band * 2) * progress;
    final start = Offset(x - band / 2, size.height);
    final end = Offset(x + band / 2, 0);
    _reflectionPaint.shader =
        ui.Gradient.linear(start, end, _reflectionColors, _reflectionStops);
    canvas.drawRect(_rect, _reflectionPaint);
    _reflectionBorderPaint.shader =
        ui.Gradient.linear(start, end, _rimColors, _reflectionStops);
    canvas.drawRRect(_outline, _reflectionBorderPaint);
  }

  @override
  bool shouldRepaint(covariant _MetallicPainter oldDelegate) =>
      oldDelegate.shine != shine ||
      oldDelegate.color != color ||
      oldDelegate.radius != radius;
}

/// 稀有度选择器：十种颜色一目了然，主持人新建/编辑成就时挑档位。
class AchievementRarityPicker extends StatelessWidget {
  const AchievementRarityPicker({
    super.key,
    required this.rarity,
    required this.onChanged,
  });

  final int rarity;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) => Wrap(
        spacing: AppSpacing.sm,
        runSpacing: AppSpacing.sm,
        children: [
          for (var value = 1; value <= achievementRarityMax; value++)
            _RarityChoice(
              value: value,
              selected: value == rarity,
              onTap: () => onChanged(value),
            ),
        ],
      );
}

class _RarityChoice extends StatelessWidget {
  const _RarityChoice({
    required this.value,
    required this.selected,
    required this.onTap,
  });

  final int value;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final style = AchievementRarity.of(value);
    final radius = BorderRadius.circular(AppRadius.field);
    final content = Container(
      width: 40,
      height: 36,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: style.hasShine ? null : style.background,
        borderRadius: radius,
        border:
            selected ? Border.all(color: context.palette.text, width: 2) : null,
      ),
      child: Text(
        '$value',
        style: TextStyle(
          fontSize: 13,
          fontWeight: FontWeight.w700,
          color: style.foreground,
          shadows: _achievementTextOutline,
        ),
      ),
    );
    return InkWell(
      onTap: onTap,
      borderRadius: radius,
      child: style.hasShine
          ? _MetallicSurface(
              color: style.background,
              radius: radius,
              child: content,
            )
          : content,
    );
  }
}

/// 头像菜单里的成就摘要：总成就数 + 优先展示的 5 个（名称 + 详细内容）。
class AchievementSummaryBlock extends StatefulWidget {
  const AchievementSummaryBlock({
    super.key,
    required this.store,
    required this.accountId,
  });

  final GameStore store;
  final String accountId;

  @override
  State<AchievementSummaryBlock> createState() =>
      _AchievementSummaryBlockState();
}

class _AchievementSummaryBlockState extends State<AchievementSummaryBlock> {
  AchievementSummary? summary;
  String? error;
  bool loading = true;

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    final api = widget.store.api;
    if (api == null) {
      setState(() => loading = false);
      return;
    }
    try {
      final value = await api.achievementSummary(widget.accountId);
      if (!mounted) return;
      setState(() {
        summary = value;
        error = null;
        loading = false;
      });
    } on ApiException catch (failure) {
      if (!mounted) return;
      setState(() {
        error = failure.message;
        loading = false;
      });
    } on FormatException catch (failure) {
      if (!mounted) return;
      setState(() {
        error = failure.message;
        loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    if (loading) {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: AppSpacing.md),
        child: Center(
          child: SizedBox(
            width: 18,
            height: 18,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
        ),
      );
    }
    final value = summary;
    if (value == null) {
      return Padding(
        padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
        child: Text(
          error ?? '成就读取失败',
          style: TextStyle(fontSize: 12, color: context.palette.textTertiary),
        ),
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(Icons.emoji_events_outlined,
                size: 16, color: context.palette.accent),
            const SizedBox(width: 6),
            Text(
              '成就 ${value.total} 个',
              style: TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w600,
                color: context.palette.text,
              ),
            ),
            if (value.equipped != null) ...[
              const SizedBox(width: AppSpacing.sm),
              Text(
                '佩戴中',
                style: TextStyle(
                    fontSize: 11, color: context.palette.textTertiary),
              ),
              const SizedBox(width: 4),
              AchievementBadge(
                name: value.equipped!.name,
                rarity: value.equipped!.rarity,
                dense: true,
              ),
            ],
          ],
        ),
        if (value.top.isEmpty)
          Padding(
            padding: const EdgeInsets.only(top: AppSpacing.sm),
            child: Text(
              '还没有获得过成就。',
              style:
                  TextStyle(fontSize: 12, color: context.palette.textTertiary),
            ),
          )
        else ...[
          Padding(
            padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
            child: Divider(height: 1, color: context.palette.border),
          ),
          Text(
            '展示成就 ${value.top.length} 个',
            style: TextStyle(fontSize: 11, color: context.palette.textTertiary),
          ),
          for (final grant in value.top)
            Padding(
              padding: const EdgeInsets.only(top: AppSpacing.sm),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  AchievementBadge(
                    name: grant.name,
                    rarity: grant.rarity,
                    dense: true,
                  ),
                  const SizedBox(width: AppSpacing.sm),
                  Expanded(
                    child: Text(
                      grant.detail,
                      style: TextStyle(
                        fontSize: 12,
                        height: 1.4,
                        color: context.palette.textSecondary,
                      ),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ],
    );
  }
}

/// 服务端给的 ISO 时间 → 本机时区的短日期（列表里看获得时间与最近参赛）。
String achievementStamp(String value, {bool withTime = false}) {
  final parsed = DateTime.tryParse(value);
  if (parsed == null) return '';
  final local = parsed.toLocal();
  String two(int number) => number.toString().padLeft(2, '0');
  final date = '${local.year}-${two(local.month)}-${two(local.day)}';
  return withTime ? '$date ${two(local.hour)}:${two(local.minute)}' : date;
}
