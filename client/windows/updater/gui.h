#pragma once

// Win32 原生界面：安装向导、卸载确认、提示与错误弹窗。

#include <string>

#include "common.h"

namespace upd {

// 「已经安装过」时的选择：返回 0=更新到最新 / 1=卸载 / 2=退出 / 3=下载便携版。
inline constexpr int kInstalledChoiceUpdate = 0;
inline constexpr int kInstalledChoiceUninstall = 1;
inline constexpr int kInstalledChoiceQuit = 2;
inline constexpr int kInstalledChoicePortable = 3;

int ShowInstalledChoiceDialog(const std::wstring& installDir, const std::wstring& version);
void ShowErrorDialog(const std::wstring& title, const std::wstring& text);
void ShowInfoDialog(const std::wstring& title, const std::wstring& text);
int RunInstallWizard(const Options& options);
int RunUninstallWizard(const Options& options);

}  // namespace upd
