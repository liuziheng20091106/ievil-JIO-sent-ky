#pragma once

// Updater 自己的版本号。由 CMake 从 client/pubspec.yaml 的版本名注入
// （见 client/windows/updater/CMakeLists.txt），不再手改这里：
// 客户端版本与更新器版本始终一致，UA、日志与注册表里显示的都是同一个版本。
// 直接用 CMake 单独编译这个目标（没走 Flutter 构建）时才回落到下面的默认值。
#ifndef UPDATER_VERSION_STRING
#define UPDATER_VERSION_STRING L"0.0.0"
#endif
