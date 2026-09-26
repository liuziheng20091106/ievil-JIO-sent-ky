#pragma once

// Updater 的公共工具：字符串、路径、文件、进程、日志。
// 全项目只用 Windows API + CRT：不引第三方库，也不用 std::filesystem
// （它靠异常报错，而本目标编译时定义了 _HAS_EXCEPTIONS=0）。

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif

#include <windows.h>

// WIN32_LEAN_AND_MEAN 会把 shellapi.h 排除在 windows.h 之外，这里显式带上
// （提权用 ShellExecuteExW、启动程序用 ShellExecuteW）。
#include <shellapi.h>

#include <string>
#include <vector>

namespace upd {

// ==== 常量 ====
inline constexpr const wchar_t* kDisplayName = L"魔法裁判";
inline constexpr const wchar_t* kPublisher = L"MagicJudge";
inline constexpr const wchar_t* kDefaultBackend = L"https://super.tkcloud.online:447";
inline constexpr const wchar_t* kAppExeName = L"seven_double_client.exe";
inline constexpr const wchar_t* kUpdaterExeName = L"Updater.exe";
inline constexpr const wchar_t* kTaskName = L"MagicJudgeUpdater";
inline constexpr const wchar_t* kProductDirName = L"MagicJudge";
inline constexpr const wchar_t* kRegistryProductKey = L"Software\\MagicJudge\\MagicJudge";
inline constexpr const wchar_t* kRegistryUninstallKey =
    L"Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\MagicJudge";
inline constexpr const wchar_t* kStagingPrefix = L".update-";
inline constexpr const wchar_t* kBackupDirName = L".update-backup";

// 等被替换进程退出的上限；超时就强杀。
inline constexpr DWORD kWaitPidTimeoutMs = 60000;
// 单文件替换的重试次数与间隔。
inline constexpr unsigned int kFileReplaceRetries = 6;
inline constexpr DWORD kFileReplaceDelayMs = 500;

// 退出码：0 成功 / 1 一般失败 / 2 网络失败 / 3 权限不足 / 4 已安装或已最新 / 5 需要重启。
enum ExitCode {
  kExitOk = 0,
  kExitFailure = 1,
  kExitNetwork = 2,
  kExitPermission = 3,
  kExitUpToDate = 4,
  kExitRebootRequired = 5,
};

// 命令行解析结果。
struct Options {  std::wstring command;   // install / update-app / prepare / task-entry / uninstall / check-install / version / help
  std::wstring from;      // 后端地址或更新包直链
  std::wstring dir;       // 安装目录
  std::wstring target;    // --update-app 的要替换目录
  std::wstring restart;   // --update-app 更新完要启动的 exe
  std::wstring sha256;    // 可选：显式校验值
  std::wstring tag;       // 可选：显式版本号
  long long size = -1;    // 可选：显式大小
  DWORD waitPid = 0;      // 可选：等这个 pid 退出后再替换
  bool silent = false;
  bool dryRun = false;
  bool toProgramFiles = false;
  bool purgeData = false;
  bool elevated = false;  // 提权后的自调用标记，避免 UAC 递归
  bool noLaunch = false;
  bool skipProgramFiles = false;  // 卸载时只清数据，不动程序文件
};

// 进度上报：命令行路径传 nullptr（走日志），GUI 路径传回调（走消息）。
using ProgressCallback = void (*)(void* context, int percent, const std::wstring& message);
struct ProgressSink {
  ProgressCallback report = nullptr;
  void* context = nullptr;
};
void ReportProgress(const ProgressSink* sink, int percent, const std::wstring& message);

// ==== 字符串 ====
std::wstring Format(const wchar_t* format, ...);
std::wstring Utf8ToWide(const std::string& text);
std::string WideToUtf8(const std::wstring& text);
std::wstring ToLower(const std::wstring& text);
bool StartsWithI(const std::wstring& text, const std::wstring& prefix);
bool EndsWithI(const std::wstring& text, const std::wstring& suffix);
bool ContainsI(const std::wstring& text, const std::wstring& needle);
bool ContainsAsciiI(const std::string& text, const char* needle);
std::wstring Trim(const std::wstring& text);
std::wstring BytesToHex(const unsigned char* data, size_t length);
std::string BytesToHexAscii(const unsigned char* data, size_t length);
bool HexEqualI(const std::string& left, const std::string& right);
bool ParseUnsigned(const std::wstring& text, unsigned long long* value);
bool ParseDword(const std::wstring& text, DWORD* value);
std::wstring HexToText(const std::string& hex);  // 调试用；非法输入返回空

// ==== 路径 ====
std::wstring ExePath();
std::wstring ExeDirectory();
std::wstring CurrentDirectory();
std::wstring LocalAppDataDir();
std::wstring RoamingAppDataDir();
std::wstring ProgramFilesDir();
std::wstring ProductLocalDir();       // %LOCALAPPDATA%\MagicJudge
std::wstring DownloadsDir();          // %LOCALAPPDATA%\MagicJudge\downloads
std::wstring JobFilePath();           // %LOCALAPPDATA%\MagicJudge\job.json
std::wstring LogFilePath();           // %LOCALAPPDATA%\MagicJudge\update.log
std::wstring InstalledUpdaterPath();  // %LOCALAPPDATA%\MagicJudge\Updater.exe
std::wstring JoinPath(const std::wstring& base, const std::wstring& child);
std::wstring FileNameOf(const std::wstring& path);
std::wstring DirectoryOf(const std::wstring& path);
std::wstring TrimTrailingSlash(const std::wstring& path);
std::wstring LongPath(const std::wstring& path);  // 需要时加 \\?\ 前缀
std::wstring QuoteArgument(const std::wstring& value);

// ==== 文件 ====
bool PathExists(const std::wstring& path);
bool FileExists(const std::wstring& path);
bool DirExists(const std::wstring& path);
bool EnsureDir(const std::wstring& path, std::wstring* error);
bool DeleteFileIfExists(const std::wstring& path, std::wstring* error);
bool DeleteTree(const std::wstring& root, const std::wstring& skipFilePath, std::wstring* error);
bool DeleteTreeContents(const std::wstring& root, const std::wstring& skipFilePath, std::wstring* error);
bool CopyTree(const std::wstring& source, const std::wstring& destination, std::wstring* error);
bool CopyFileTo(const std::wstring& source, const std::wstring& destination, bool failIfExists,
                std::wstring* error);
bool MoveFileTo(const std::wstring& source, const std::wstring& destination, bool replace,
                std::wstring* error);
// 列出 root 下的相对路径；files/dirs 可传 nullptr。
bool ListTreeRelative(const std::wstring& root, std::vector<std::wstring>* files,
                      std::vector<std::wstring>* dirs, std::wstring* error);
unsigned long long FileSizeOf(const std::wstring& path);
std::wstring Win32ErrorMessage(DWORD code);
bool WriteTextFileUtf8(const std::wstring& path, const std::string& text, std::wstring* error);
bool ReadTextFileUtf8(const std::wstring& path, std::string* text, std::wstring* error);

// ==== 控制台与日志 ====
void SetLogFile(const std::wstring& path);  // 传空字符串＝不写日志文件
void LogMessage(const std::wstring& text);
void LogFormat(const wchar_t* format, ...);
void LogError(const std::wstring& text);
void ConsoleWrite(const std::wstring& text);
void ConsoleWriteLine(const std::wstring& text);
void ConsoleFlush();

// ==== 进程 ====
struct ProcessResult {
  DWORD exitCode = static_cast<DWORD>(-1);
  std::string output;
  bool timedOut = false;
};

bool RunProcess(const std::wstring& commandLine, DWORD timeoutMs, bool captureOutput,
                ProcessResult* result, std::wstring* error);
bool IsProcessElevated();
// 用 runas 提权启动自己；arguments 是命令行参数部分。
bool RunElevatedSelf(const std::wstring& arguments, DWORD timeoutMs, DWORD* exitCode,
                     std::wstring* error);

}  // namespace upd
