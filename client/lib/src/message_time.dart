/// 时间显示：服务端存的是 UTC 的 ISO-8601 字符串，界面统一换算成本机时区，
/// 并压成精简形式（当天只显示时刻，跨天补日期，跨年补年份）。
library;

import 'package:clock/clock.dart';

/// 把服务端的 `created_at` 转成本机时区的精简文本。
///
/// 无法解析时返回空串：宁可少显示一段文字，也不要把原始 ISO 串丢给用户。
/// 「现在」取自 package:clock，测试可用 withClock 固定，避免跨分钟抖动。
String formatMessageTime(String value, {DateTime? now}) {
  final parsed = DateTime.tryParse(value);
  if (parsed == null) {
    return '';
  }
  final local = parsed.toLocal();
  final current = (now ?? clock.now()).toLocal();
  final hh = local.hour.toString().padLeft(2, '0');
  final mm = local.minute.toString().padLeft(2, '0');
  final time = '$hh:$mm';
  final sameDay = local.year == current.year &&
      local.month == current.month &&
      local.day == current.day;
  if (sameDay) {
    return time;
  }
  final month = local.month.toString().padLeft(2, '0');
  final day = local.day.toString().padLeft(2, '0');
  if (local.year != current.year) {
    return '${local.year}-$month-$day $time';
  }
  return '$month-$day $time';
}
