#pragma once

// Updater 自己的发行版本号。由 CMake 从 client/lib/src/client_version.dart 的 kClientVersion 注入
// （见 client/windows/updater/CMakeLists.txt），不再手改这里：
// 客户端版本与更新器版本始终一致，UA、日志与注册表里显示的都是同一个版本。
// 只有绕过此 CMake 配置、未注入版本宏时才回落到下面的默认值。
#ifndef UPDATER_VERSION_STRING
#define UPDATER_VERSION_STRING L"0.0.0"
#endif
