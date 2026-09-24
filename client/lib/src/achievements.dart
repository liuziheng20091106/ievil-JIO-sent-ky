import 'package:flutter/material.dart';

import 'design.dart';
import 'models.dart';
import 'store.dart';

/// 成就的展示层：稀有度色板、徽章与头像摘要。
///
/// 成就本身由主持人授权、服务端保存（独立成就库）；客户端只负责按稀有度上色：
/// 1-10 共十种底色，数字越大越稀有、颜色越醒目。

const achievementRarityMax = 10;

/// 稀有度的一档配色：底色就是徽章背景，白字在十种底色上都保持可读。
class AchievementRarity {
  const AchievementRarity(this.background);

  final Color background;
  Color get foreground => Colors.white;

  static const _colors = <int, AchievementRarity>{
    1: AchievementRarity(Color(0xFF8A9099)), // 灰
    2: AchievementRarity(Color(0xFF3F9C4F)), // 绿
    3: AchievementRarity(Color(0xFF17A09B)), // 青
    4: AchievementRarity(Color(0xFF2F6FED)), // 蓝
    5: AchievementRarity(Color(0xFF5B4BE0)), // 靛
    6: AchievementRarity(Color(0xFF9B4DE0)), // 紫
    7: AchievementRarity(Color(0xFFD6389A)), // 玫红
    8: AchievementRarity(Color(0xFFE0701E)), // 橙
    9: AchievementRarity(Color(0xFFD0322E)), // 红
    10: AchievementRarity(Color(0xFFA87A0A)), // 金
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
    return Container(
      padding: EdgeInsets.symmetric(
        horizontal: dense ? 6 : 10,
        vertical: dense ? 2 : 4,
      ),
      decoration: BoxDecoration(
        color: style.background,
        borderRadius: BorderRadius.circular(AppRadius.chip),
      ),
      child: ConstrainedBox(
        constraints: BoxConstraints(maxWidth: dense ? 132 : 220),
        child: Text(
          name,
          overflow: TextOverflow.ellipsis,
          style: TextStyle(
            fontSize: dense ? 10.5 : 12,
            height: 1.3,
            fontWeight: FontWeight.w600,
            color: style.foreground,
          ),
        ),
      ),
    );
  }
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
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(AppRadius.field),
      child: Container(
        width: 40,
        height: 36,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: style.background,
          borderRadius: BorderRadius.circular(AppRadius.field),
          border: selected
              ? Border.all(color: context.palette.text, width: 2)
              : null,
        ),
        child: Text(
          '$value',
          style: TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w700,
            color: style.foreground,
          ),
        ),
      ),
    );
  }
}

/// 头像菜单里的成就摘要：总成就数 + 最稀有的 5 个（名称 + 详细内容）。
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
            '最稀有的 ${value.top.length} 个',
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
