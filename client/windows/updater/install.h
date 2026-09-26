#pragma once

// 各子命令的实现入口。返回值就是进程退出码（见 ExitCode）。

#include <string>

#include "common.h"

namespace upd {

// 无参数：下载器 / 安装向导（GUI，见 gui.h）。
int RunInstallerEntry(const Options& options);

int RunInstall(const Options& options, const ProgressSink* progress);
int RunPrepare(const Options& options, const ProgressSink* progress);
int RunUninstall(const Options& options, const ProgressSink* progress);
int RunCheckInstall(const Options& options);
int RunUpdateApp(const Options& options, const ProgressSink* progress);
int RunTaskEntry(const Options& options);

// 内部共用：解析后端地址或直链得到更新包；提权重跑；启动安装好的程序。
struct PackageRef {
  std::wstring url;
  std::wstring sha256;
  long long size = -1;
  std::wstring version;
};

bool ResolvePackage(const Options& options, int* exitCode, PackageRef* reference,
                    std::wstring* error);
// 下载并校验更新包（已缓存且校验通过则跳过）。失败时 exitCode 为 2（网络）。
bool DownloadAndVerifyPackage(const std::wstring& packageUrl, const std::wstring& sha256,
                              long long size, const ProgressSink* progress, int* exitCode,
                              std::wstring* error);
// 更新包在本地的落盘路径：%LOCALAPPDATA%\MagicJudge\downloads\<文件名>。
std::wstring LocalPackagePath(const std::wstring& packageUrl);
// 解压目录里真正的载荷根（包里可能多套一层目录）。
std::wstring LocatePayloadRoot(const std::wstring& staging);
// 三段版本比较；任一侧不是 x.y.z 时返回 -2（无法比较）。
int CompareVersionTags(const std::wstring& left, const std::wstring& right);
int RerunElevated(const Options& options, bool forceSilent);
bool LaunchApplication(const std::wstring& exePath, const std::wstring& workingDirectory);

}  // namespace upd
