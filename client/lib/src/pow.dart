import 'dart:convert';

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

  /// 求解谜题；登录是低频操作，难度 20 以内（服务端上限 19）同步枚举即可。
  /// 返回 null 表示服务端不需要证明。
  Future<int?> solve() async {
    if (!solvable) return null;
    return computeNonce(token, difficulty);
  }
}

/// 枚举 nonce；哈希在本地同步循环里完成，单题难度上限受服务端约束（≤19）。
int computeNonce(String token, int difficulty) {
  final prefix = '0' * difficulty;
  var nonce = 0;
  while (true) {
    final digest = sha256.convert(utf8.encode('$token$nonce')).toString();
    if (digest.startsWith(prefix)) return nonce;
    nonce += 1;
  }
}
