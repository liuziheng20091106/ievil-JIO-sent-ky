import 'dart:async';
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

  /// 在独立 isolate 里求解，并按 [onAttempts] 回报已尝试次数
  /// （约每 120ms 一次，不是每次尝试都发消息）。
  ///
  /// 用 isolate 而不是主 isolate：枚举是 CPU 密集的同步循环，跑在 UI 线程上
  /// 会把界面连同 Android 的 ANR 判定一起卡死。回报的次数是真实计数，
  /// 供登录页展示等待进度——难度 4 只是「期望」3.3 万次，个别用户可能撞上更久。
  /// 返回 null 表示服务端不需要证明。
  Future<int?> solve({void Function(int attempts)? onAttempts}) async {
    if (!solvable) return null;
    return _spawnSolver(token, difficulty, onAttempts);
  }
}

/// 在独立 isolate 中求解；不再需要进度时调用方可忽略 [onAttempts]。
Future<int> _spawnSolver(
  String token,
  int difficulty,
  void Function(int attempts)? onAttempts,
) async {
  final receive = ReceivePort();
  final completer = Completer<int>();
  late final StreamSubscription<dynamic> subscription;
  subscription = receive.listen((Object? message) {
    if (message is int) {
      if (!completer.isCompleted) completer.complete(message);
    } else if (message is Map && message['attempts'] is int) {
      onAttempts?.call(message['attempts'] as int);
    }
  });
  Isolate? worker;
  try {
    worker = await Isolate.spawn<List<Object?>>(
      _powWorker,
      <Object?>[receive.sendPort, token, difficulty],
    );
    return await completer.future;
  } finally {
    // 结果已到（或异常）就收掉通道与 isolate，别留下常驻的工作线程。
    await subscription.cancel();
    receive.close();
    worker?.kill(priority: Isolate.immediate);
  }
}

/// isolate 入口必须是顶层函数；只回传次数与最终 nonce，不做任何 IO。
void _powWorker(List<Object?> args) {
  final send = args[0] as SendPort;
  final token = args[1] as String;
  final difficulty = args[2] as int;
  final nonce = computeNonce(
    token,
    difficulty,
    onProgress: (attempts) => send.send(<String, int>{'attempts': attempts}),
  );
  send.send(nonce);
}

/// 枚举 nonce，返回首个使 sha256(token+nonce) 以 [difficulty] 个 '0' 开头的值。
///
/// 十六进制前缀每 +1 位计算量 ×16（不是 ×2），服务端难度上限 8。
/// [onProgress] 按 [progressInterval] 节流回报次数，避免每轮循环都跨界发消息；
/// 测试把它设成 [Duration.zero] 就能看到每一次汇报。
int computeNonce(
  String token,
  int difficulty, {
  void Function(int attempts)? onProgress,
  Duration progressInterval = const Duration(milliseconds: 120),
}) {
  final prefix = '0' * difficulty;
  var nonce = 0;
  var lastReport = DateTime.now();
  while (true) {
    final digest = sha256.convert(utf8.encode('$token$nonce')).toString();
    if (digest.startsWith(prefix)) return nonce;
    nonce += 1;
    // 每 512 次才看一次时钟：读时钟比哈希本身贵，不能每轮都读。
    if (onProgress != null && nonce % 512 == 0) {
      final now = DateTime.now();
      if (now.difference(lastReport) >= progressInterval) {
        lastReport = now;
        onProgress(nonce);
      }
    }
  }
}
