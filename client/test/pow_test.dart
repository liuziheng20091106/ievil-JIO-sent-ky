import 'dart:convert';

import 'package:crypto/crypto.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:seven_double_client/src/pow.dart';

void main() {
  group('PowPuzzle 解析', () {
    test('required=false：未开启防护，不需要求解', () {
      final puzzle = PowPuzzle.fromJson({'required': false});
      expect(puzzle.required, isFalse);
      expect(puzzle.solvable, isFalse);
      expect(puzzle.solve(), completion(isNull));
    });

    test('required=true：带令牌与难度', () {
      final puzzle = PowPuzzle.fromJson({
        'required': true,
        'token': 'v1.123.4.abc.deadbeef',
        'difficulty': 4,
      });
      expect(puzzle.required, isTrue);
      expect(puzzle.token, 'v1.123.4.abc.deadbeef');
      expect(puzzle.difficulty, 4);
      expect(puzzle.solvable, isTrue);
    });

    test('字段缺失或形状不对：按不可解处理而不是抛异常', () {
      expect(PowPuzzle.fromJson({'required': true}).solvable, isFalse);
      expect(
        PowPuzzle.fromJson({'required': true, 'difficulty': 3}).solvable,
        isFalse,
      );
      expect(
        PowPuzzle.fromJson({
          'required': true,
          'token': '',
          'difficulty': 3,
        }).solvable,
        isFalse,
      );
    });
  });

  group('computeNonce', () {
    test('找到的解满足 sha256(token+nonce) 前缀为 difficulty 个 0', () {
      for (final difficulty in [1, 2, 3]) {
        final token = 'v1.123.4.testtoken.deadbeef';
        final nonce = computeNonce(token, difficulty);
        final digest = sha256.convert(utf8.encode('$token$nonce')).toString();
        expect(digest.substring(0, difficulty), '0' * difficulty);
      }
    });

    test('确定性：同一输入两次结果一致', () {
      const token = 'v1.99.2.token.deadbeef';
      expect(computeNonce(token, 2), computeNonce(token, 2));
    });

    test('solve 走 isolate：UI 不被阻塞，结果与同步计算一致', () async {
      final puzzle = PowPuzzle(required: true, token: 'v1.123.4.isolate.deadbeef', difficulty: 3);
      final nonce = await puzzle.solve().timeout(const Duration(seconds: 30));
      final digest = sha256.convert(utf8.encode('${puzzle.token}$nonce')).toString();
      expect(digest.substring(0, 3), '000');
    });

    test('求解过程按节流回报真实尝试次数（递增且都是 512 的倍数）', () {
      const token = 'v1.123.4.progress.deadbeef';
      final reported = <int>[];
      final nonce = computeNonce(
        token,
        3,
        onProgress: reported.add,
        progressInterval: Duration.zero,
      );
      expect(nonce, greaterThan(0));
      expect(reported, isNotEmpty);
      // 汇报的是真实已尝试次数：严格递增、步进为 512、且都不超过最终解。
      for (var i = 0; i < reported.length; i++) {
        expect(reported[i] % 512, 0);
        expect(reported[i], lessThanOrEqualTo(nonce));
        if (i > 0) expect(reported[i], greaterThan(reported[i - 1]));
      }
      // 解本身没被算漏：哈希满足难度，且最后一次汇报不晚于它。
      final digest = sha256.convert(utf8.encode('$token$nonce')).toString();
      expect(digest.substring(0, 3), '000');
    });

    test('默认节流下不会为短任务发大量消息', () {
      const token = 'v1.123.4.throttle.deadbeef';
      final reported = <int>[];
      computeNonce(token, 2, onProgress: reported.add);
      // 难度 2 平均几百上千次就出解：默认 120ms 窗口内最多一两条，
      // 绝不会每 512 次就发一条（那会把 isolate 消息通道刷爆）。
      expect(reported.length, lessThanOrEqualTo(1));
    });
  });
}
