import 'package:flutter_test/flutter_test.dart';
import 'package:seven_double_client/src/message_time.dart';

void main() {
  // 本机时区在不同机器上不同，用 UTC 与固定「现在」把断言写成时区无关。
  final utcNoon = DateTime.utc(2026, 9, 15, 12, 0);

  test('同一天只显示本机时刻', () {
    final local = DateTime(2026, 9, 15, 15, 41);
    final text = formatMessageTime(
      local.toUtc().toIso8601String(),
      now: DateTime(2026, 9, 15, 18, 0),
    );
    expect(text, '15:41');
    expect(text.contains('T'), isFalse, reason: '不能出现原始 ISO 形式');
  });

  test('服务端带 +00:00 偏移的串换算成本机时区', () {
    // 用户截图里的真实值：UTC 15:00:41。
    const raw = '2026-09-15T15:00:41.602060+00:00';
    final text = formatMessageTime(
      raw,
      now: DateTime.utc(2026, 9, 15, 15, 30).toLocal(),
    );
    final expectedLocal = DateTime.utc(2026, 9, 15, 15, 0, 41).toLocal();
    final hh = expectedLocal.hour.toString().padLeft(2, '0');
    final mm = expectedLocal.minute.toString().padLeft(2, '0');
    expect(text, '$hh:$mm');
    expect(text.length, 5, reason: '当天应为 HH:mm');
  });

  test('跨天补日期，跨年补年份', () {
    final yesterday = DateTime(2026, 9, 14, 8, 5);
    expect(
      formatMessageTime(
        yesterday.toUtc().toIso8601String(),
        now: DateTime(2026, 9, 15, 9, 0),
      ),
      '09-14 08:05',
    );
    final lastYear = DateTime(2025, 12, 31, 23, 30);
    expect(
      formatMessageTime(
        lastYear.toUtc().toIso8601String(),
        now: DateTime(2026, 1, 1, 0, 30),
      ),
      '2025-12-31 23:30',
    );
  });

  test('解析失败返回空串而不是原始时间', () {
    expect(formatMessageTime(''), '');
    expect(formatMessageTime('not-a-date'), '');
    expect(formatMessageTime('2026-09-15'), isNotEmpty);
  });

  test('UTC 与本地表示互相换算一致', () {
    final instant = DateTime.utc(2026, 9, 15, 12, 0);
    final asUtc = formatMessageTime(
      instant.toIso8601String(),
      now: utcNoon.toLocal().add(const Duration(hours: 1)),
    );
    final asLocal = formatMessageTime(
      instant.toLocal().toIso8601String(),
      now: utcNoon.toLocal().add(const Duration(hours: 1)),
    );
    expect(asUtc, asLocal);
  });
}
