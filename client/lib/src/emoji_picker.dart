import 'dart:async';

import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'design.dart';
import 'emoji.dart';

/// 最近使用的表情 id：最近一次使用在最前，最多 [recentEmojiLimit] 个。
/// 落盘在 shared_preferences，重启应用、退出登录都不丢——这是本机偏好，
/// 与账号和对局无关（同 shell.dart 的聊天设置）。
final recentEmojiIds = <String>[];

/// 「最近」分组的上限：再多也用不到，落盘的内容也就这么长。
const int recentEmojiLimit = 16;

const String recentEmojiPreferenceKey = 'emoji_recent_ids';

/// 落盘用的偏好实例：由 [loadRecentEmojiIds] 在启动时注入（测试里可以没有，
/// 那样只留内存记录）。
SharedPreferences? _recentPreferences;

/// 启动时读一次落盘的最近使用记录（main.dart 拿到偏好之后调用）。
/// 表里认不出的 id 直接丢掉：表情总表由 temp/gen_emoji.py 重新生成过，
/// 上一版记下的 id 在这一版可能已经不存在。
void loadRecentEmojiIds(SharedPreferences preferences) {
  _recentPreferences = preferences;
  final stored =
      preferences.getStringList(recentEmojiPreferenceKey) ?? const <String>[];
  recentEmojiIds
    ..clear()
    ..addAll(
      stored.where((id) => emojiFaceById(id) != null).take(recentEmojiLimit),
    );
}

/// 记一次使用：置顶、去重、截断，然后落盘。由面板在点选表情时调用。
void rememberRecentEmoji(String id) {
  recentEmojiIds
    ..remove(id)
    ..insert(0, id);
  if (recentEmojiIds.length > recentEmojiLimit) {
    recentEmojiIds.removeRange(recentEmojiLimit, recentEmojiIds.length);
  }
  final preferences = _recentPreferences;
  if (preferences == null) return;
  unawaited(preferences.setStringList(
    recentEmojiPreferenceKey,
    List<String>.of(recentEmojiIds),
  ));
}

/// 表情面板打开期间的返回拦截：返回键先收面板。
///
/// 面板占的是输入区，玩家按返回想收掉的通常只是面板；没有这一层时，聊天页在根路由上
/// 会被整个收走（Android 上就是退出应用），行动表单会连同已填内容一起被收起。
/// 只在面板打开时挂上（关掉面板这个作用域就消失），所以 canPop 恒为假：
/// 一次返回固定用来收面板，收完之后返回恢复原样。Android 14+ 的预测性返回也据此让路，
/// 见 predictive_sheet.dart 对 `RoutePopDisposition.doNotPop` 的判断。
class EmojiPanelScope extends StatelessWidget {
  const EmojiPanelScope({super.key, required this.onClose, required this.child});

  /// 本次返回该做的事：收起面板。
  final VoidCallback onClose;

  final Widget child;

  @override
  Widget build(BuildContext context) => PopScope(
        canPop: false,
        onPopInvokedWithResult: (didPop, _) {
          if (!didPop) onClose();
        },
        child: child,
      );
}

/// 表情面板：经典 / 超级 / 最近分组 + 名称与拼音搜索。
/// 面板本身不持有输入框，插入动作由调用方在 [onPick] 里完成。
class EmojiPicker extends StatefulWidget {
  const EmojiPicker({
    super.key,
    required this.onPick,
    this.recentFirst = false,
    this.height = 236,
  });

  final ValueChanged<EmojiFace> onPick;

  /// 打开面板时默认落在「最近」分组：取值来自本机设置
  /// （`GameStore.emojiRecentFirst`，默认开启）。没有记录时「最近」是空的，
  /// 仍然从经典开始——分组按钮那时也不显示。
  final bool recentFirst;

  final double height;

  @override
  State<EmojiPicker> createState() => _EmojiPickerState();
}

class _EmojiPickerState extends State<EmojiPicker> {
  static const _groups = <({String key, String label})>[
    (key: 'classic', label: '经典'),
    (key: 'super', label: '超级'),
    (key: 'recent', label: '最近'),
  ];

  final search = TextEditingController();

  /// 当前分组：只在这里（面板刚建好时）按设置与记录定一次，之后全由用户点选决定，
  /// 设置改动不会把已经打开的面板拽走。
  late String group =
      widget.recentFirst && recentEmojiIds.isNotEmpty ? 'recent' : 'classic';
  String query = '';

  @override
  void dispose() {
    search.dispose();
    super.dispose();
  }

  List<EmojiFace> get faces {
    final keyword = query.trim();
    if (keyword.isNotEmpty) {
      // 中文按名称包含匹配，拼音按前缀匹配：既能搜「微笑」，也能搜 wx / weixiao。
      final lower = keyword.toLowerCase();
      return emojiFaces
          .where((face) =>
              face.name.contains(keyword) ||
              face.pinyin.any((word) => word.startsWith(lower)))
          .toList();
    }
    if (group == 'recent') {
      return recentEmojiIds
          .map(emojiFaceById)
          .whereType<EmojiFace>()
          .toList();
    }
    return emojiFaces.where((face) => face.superFace == (group == 'super')).toList();
  }

  void pick(EmojiFace face) {
    rememberRecentEmoji(face.id);
    setState(() {});
    widget.onPick(face);
  }

  @override
  Widget build(BuildContext context) {
    final list = faces;
    return Container(
      height: widget.height,
      decoration: BoxDecoration(
        color: context.palette.surfaceMuted,
        border: Border(top: BorderSide(color: context.palette.border)),
      ),
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(
                AppSpacing.md, AppSpacing.sm, AppSpacing.md, 0),
            child: Row(
              children: [
                Expanded(
                  child: SizedBox(
                    height: 38,
                    child: TextField(
                      controller: search,
                      textInputAction: TextInputAction.search,
                      style: TextStyle(fontSize: 13, color: context.palette.text),
                      decoration: InputDecoration(
                        isDense: true,
                        hintText: '搜索表情名或拼音',
                        hintStyle: TextStyle(
                            fontSize: 13, color: context.palette.textTertiary),
                        prefixIcon: Icon(Icons.search,
                            size: 16, color: context.palette.textTertiary),
                        prefixIconConstraints: const BoxConstraints(
                            minWidth: 34, minHeight: 34),
                        contentPadding: const EdgeInsets.symmetric(vertical: 8),
                        filled: true,
                        fillColor: context.palette.surface,
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(AppRadius.field),
                          borderSide: BorderSide(color: context.palette.border),
                        ),
                      ),
                      onChanged: (value) => setState(() => query = value),
                    ),
                  ),
                ),
                const SizedBox(width: AppSpacing.sm),
                for (final item in _groups)
                  // 「最近」没有内容时不占位，避免一个永远点不出东西的分组。
                  if (item.key != 'recent' || recentEmojiIds.isNotEmpty)
                    Padding(
                      padding: const EdgeInsets.only(left: AppSpacing.xs),
                      child: FilterChip(
                        label: Text(item.label),
                        labelStyle: const TextStyle(fontSize: 12),
                        selected: query.isEmpty && group == item.key,
                        showCheckmark: false,
                        visualDensity: VisualDensity.compact,
                        onSelected: (_) => setState(() {
                          group = item.key;
                          // 切分组即退出搜索，否则分组点了没反应。
                          query = '';
                          search.clear();
                        }),
                      ),
                    ),
              ],
            ),
          ),
          Expanded(
            child: list.isEmpty
                ? Center(
                    child: Text(
                      query.trim().isEmpty ? '这里还没有表情' : '没有匹配的表情',
                      style: TextStyle(
                          fontSize: 12, color: context.palette.textTertiary),
                    ),
                  )
                : GridView.builder(
                    padding: const EdgeInsets.all(AppSpacing.sm),
                    gridDelegate:
                        const SliverGridDelegateWithMaxCrossAxisExtent(
                      maxCrossAxisExtent: 46,
                      mainAxisSpacing: 2,
                      crossAxisSpacing: 2,
                    ),
                    itemCount: list.length,
                    itemBuilder: (context, index) {
                      final face = list[index];
                      return InkWell(
                        borderRadius: BorderRadius.circular(AppRadius.field),
                        onTap: () => pick(face),
                        child: Padding(
                          padding: const EdgeInsets.all(7),
                          // 原图 128×128，按 64 解码就够面板用，避免 325 张全尺寸进内存。
                          child: Image.asset(
                            face.asset,
                            cacheWidth: 64,
                            cacheHeight: 64,
                            filterQuality: FilterQuality.medium,
                          ),
                        ),
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }
}
