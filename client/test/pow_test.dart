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
  });
}
