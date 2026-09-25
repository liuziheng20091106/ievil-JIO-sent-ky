import 'package:flutter/material.dart';

import 'design.dart';
import 'emoji.dart';

/// 最近使用的表情 id：只保留本次会话内的顺序，退出应用即清空。
/// 不落盘是有意的——本机可能先后登录多个账号，表情使用记录不属于任何对局数据。
final recentEmojiIds = <String>[];

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
  const EmojiPicker({super.key, required this.onPick, this.height = 236});

  final ValueChanged<EmojiFace> onPick;
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
  String group = 'classic';
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
    recentEmojiIds
      ..remove(face.id)
      ..insert(0, face.id);
    if (recentEmojiIds.length > 16) recentEmojiIds.removeRange(16, recentEmojiIds.length);
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
