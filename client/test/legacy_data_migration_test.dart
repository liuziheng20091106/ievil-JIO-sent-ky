import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:path/path.dart' as p;
import 'package:seven_double_client/src/store.dart';

/// 应用显示名改动会改变 Windows 的数据目录名，旧登录数据必须能被搬到新目录。
void main() {
  late Directory root;
  late Directory current;
  late Directory legacy;

  setUp(() {
    root = Directory.systemTemp.createTempSync('sd_migrate');
    current = Directory(p.join(root.path, '魔法裁判'))..createSync(recursive: true);
    legacy = Directory(p.join(root.path, 'seven_double_client'))
      ..createSync(recursive: true);
  });

  tearDown(() => root.deleteSync(recursive: true));

  test('补齐缺失的数据文件', () async {
    File(p.join(legacy.path, 'shared_preferences.json')).writeAsStringSync(
        '{"flutter.server_endpoint":"http://127.0.0.1:8000"}');
    File(p.join(legacy.path, 'flutter_secure_storage.dat'))
        .writeAsBytesSync([1, 2, 3]);

    await migrateLegacyWindowsData(
        currentDirectory: current, legacyDirectory: legacy);

    expect(
        File(p.join(current.path, 'shared_preferences.json'))
            .readAsStringSync(),
        contains('server_endpoint'));
    expect(
        File(p.join(current.path, 'flutter_secure_storage.dat'))
            .readAsBytesSync(),
        [1, 2, 3]);
  });

  test('不覆盖当前目录已有的文件', () async {
    File(p.join(legacy.path, 'shared_preferences.json'))
        .writeAsStringSync('legacy');
    File(p.join(current.path, 'shared_preferences.json'))
        .writeAsStringSync('current');

    await migrateLegacyWindowsData(
        currentDirectory: current, legacyDirectory: legacy);

    expect(
        File(p.join(current.path, 'shared_preferences.json'))
            .readAsStringSync(),
        'current');
  });

  test('可重复执行且旧目录不存在时安全跳过', () async {
    File(p.join(legacy.path, 'shared_preferences.json'))
        .writeAsStringSync('legacy');
    await migrateLegacyWindowsData(
        currentDirectory: current, legacyDirectory: legacy);
    await migrateLegacyWindowsData(
        currentDirectory: current, legacyDirectory: legacy);
    expect(
        File(p.join(current.path, 'shared_preferences.json'))
            .readAsStringSync(),
        'legacy');

    legacy.deleteSync(recursive: true);
    await migrateLegacyWindowsData(
        currentDirectory: current, legacyDirectory: legacy);
    expect(
        File(p.join(current.path, 'shared_preferences.json'))
            .readAsStringSync(),
        'legacy');
  });

  test('目录相同时不做任何事', () async {
    File(p.join(current.path, 'shared_preferences.json'))
        .writeAsStringSync('same');
    await migrateLegacyWindowsData(
        currentDirectory: current, legacyDirectory: current);
    expect(
        File(p.join(current.path, 'shared_preferences.json'))
            .readAsStringSync(),
        'same');
  });
}
