#pragma once

// 系统集成：注册表安装信息、计划任务、自签名证书、进程查找、目录可写性。

#include <string>
#include <vector>

#include "common.h"

namespace upd {

struct InstallInfo {
  bool found = false;
  std::wstring source;  // current-dir / program-files / registry
  std::wstring installDir;
  std::wstring version;
  std::wstring updaterPath;
  std::wstring uninstallString;
  std::wstring displayName;
  std::wstring publisher;
  bool registryFound = false;
  std::wstring registryInstallLocation;
  std::wstring registryVersion;
};

// ==== 注册表 ====
bool ReadRegistryInstall(InstallInfo* info);
bool WriteRegistryInstall(const std::wstring& installDir, const std::wstring& version,
                          const std::wstring& updaterPath, std::wstring* error);
bool DeleteRegistryInstall(std::wstring* error);
// 按「当前目录 → %ProgramFiles%\MagicJudge → 注册表」的顺序探测已有安装。
bool DetectInstall(InstallInfo* info);

// ==== 计划任务 ====
bool QueryUpdaterTask(std::string* rawOutput, bool* exists, std::wstring* error);
bool UpdaterTaskReady(std::wstring* error);
bool CreateUpdaterTask(const std::wstring& updaterPath, std::wstring* error);
bool RunUpdaterTask(std::wstring* error);
bool DeleteUpdaterTask(std::wstring* error);

// ==== 证书 ====
enum class CertState {
  NotEmbedded,    // self_signed_cert.h 是空占位（没跑过 tools/sign-windows.ps1）
  Trusted,        // 两个系统存储里都已有这张证书
  NeedsInstall,   // 内嵌证书还没进信任库
};

CertState CheckCertificate(std::wstring* error);
bool InstallCertificate(std::wstring* error);
std::wstring CertificateSha256();
bool CertificateEmbedded();

// ==== 快捷方式 ====
// 安装模式（非便携）会创建：开始菜单程序组里的「魔法裁判」+「卸载魔法裁判」，
// 以及可选的桌面快捷方式。卸载时由 RemoveShortcuts 一并删掉。
std::wstring StartMenuFolder();             // %APPDATA%\...\Start Menu\Programs\魔法裁判
std::wstring StartMenuAppShortcutPath();    // 上面的「魔法裁判.lnk」
std::wstring StartMenuUninstallShortcutPath();  // 上面的「卸载魔法裁判.lnk」
std::wstring DesktopShortcutPath();         // 桌面「魔法裁判.lnk」
bool CreateShortcuts(const std::wstring& installDir, const std::wstring& updaterPath,
                     bool desktop, std::wstring* error);
bool RemoveShortcuts(std::wstring* error);

// ==== 其它 ====
// %LOCALAPPDATA%\MagicJudge\Updater.exe 是否与当前这份内容一致（大小 + SHA-256）。
bool UpdaterCopyIsCurrent();
bool EnsureInstalledUpdaterCopy(std::wstring* error);
bool StopProcessByImagePath(const std::wstring& imagePath, int* stopped, std::wstring* error);
bool DirectoryIsWritable(const std::wstring& dir);
std::vector<std::wstring> PersistentDataDirs();
std::wstring RegistryUninstallString(const std::wstring& installDir);

}  // namespace upd
