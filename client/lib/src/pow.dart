import 'dart:convert';
import 'dart:isolate';

import 'package:crypto/crypto.dart';

/// 登录挑战接口的工作量证明（与服务端 backend/app/pow_guard.py 对应）。
///
/// 服务端签发 HMAC 谜题令牌后，客户端枚举 nonce 找到使
/// sha256(token + nonce) 十六进制串前 [difficulty] 位为 '0' 的解，
/// 创建登录挑战时把 token 与 nonce 一起提交回服务端。
/// 服务端未开启防护（required=false）时不领题也不计算。
class PowPuzzle {
  PowPuzzle({required this.required, this.token = '', this.difficulty = 0});

  factory PowPuzzle.fromJson(Map<String, dynamic> json) {
    final required = json['required'] == true;
    if (!required) return PowPuzzle(required: false);
    return PowPuzzle(
      required: true,
      token: json['token']?.toString() ?? '',
      difficulty: json['difficulty'] is int ? json['difficulty'] as int : 0,
    );
  }

  final bool required;
  final String token;
  final int difficulty;

  bool get solvable => required && token.isNotEmpty && difficulty > 0;

  /// 在独立 isolate 里求解：枚举是 CPU 密集的同步循环，
  /// 直接在主 isolate 跑会把整个 UI（包括 Android 的 ANR 判定）卡死。
  /// 返回 null 表示服务端不需要证明。
  Future<int?> solve() async {
    if (!solvable) return null;
    return Isolate.run(() => computeNonce(token, difficulty));
  }
}

/// 枚举 nonce；十六进制前缀每 +1 位计算量 ×16，服务端难度上限 8。
int computeNonce(String token, int difficulty) {
  final prefix = '0' * difficulty;
  var nonce = 0;
  while (true) {
    final digest = sha256.convert(utf8.encode('$token$nonce')).toString();
    if (digest.startsWith(prefix)) return nonce;
    nonce += 1;
  }
}

