// 魔法裁判 Updater：安装向导、应用内更新、证书与计划任务准备、卸载。
//
// 入口是 WinMain（/SUBSYSTEM:WINDOWS），所以纯控制台调用不会闪黑框；
// 需要输出时由 common.cpp 里的 EnsureConsole 接上父进程控制台或用重定向句柄。

#include "common.h"
#include "gui.h"
#include "install.h"
#include "system.h"
#include "version.h"

#include <shellapi.h>

namespace upd {
namespace {

struct ParseResult {
  bool ok = true;
  Options options;
  std::wstring error;
};

bool TakeValue(int argc, wchar_t** argv, int* index, std::wstring* value) {
  if (*index + 1 >= argc) {
    return false;
  }
  *index = *index + 1;
  *value = argv[*index];
  return true;
}

ParseResult ParseCommandLine() {
  ParseResult result;
  int argc = 0;
  LPWSTR* argv = ::CommandLineToArgvW(::GetCommandLineW(), &argc);
  if (argv == nullptr) {
    result.ok = false;
    result.error = L"无法解析命令行";
    return result;
  }
  for (int index = 1; index < argc; ++index) {
    const std::wstring argument = argv[index];
    if (argument == L"--install") {
      result.options.command = L"install";
    } else if (argument == L"--update-app") {
      result.options.command = L"update-app";
    } else if (argument == L"--prepare") {
      result.options.command = L"prepare";
    } else if (argument == L"--task-entry") {
      result.options.command = L"task-entry";
    } else if (argument == L"--uninstall") {
      result.options.command = L"uninstall";
    } else if (argument == L"--check-install") {
      result.options.command = L"check-install";
    } else if (argument == L"--version" || argument == L"-v") {
      result.options.command = L"version";
    } else if (argument == L"--help" || argument == L"-h" || argument == L"/?") {
      result.options.command = L"help";
    } else if (argument == L"--silent" || argument == L"-s") {
      result.options.silent = true;
    } else if (argument == L"--dry-run") {
      result.options.dryRun = true;
    } else if (argument == L"--to-program-files") {
      result.options.toProgramFiles = true;
    } else if (argument == L"--portable") {
      result.options.portable = true;
    } else if (argument == L"--desktop-shortcut") {
      result.options.desktopShortcut = true;
    } else if (argument == L"--no-desktop-shortcut") {
      result.options.desktopShortcut = false;
    } else if (argument == L"--purge-data") {
      result.options.purgeData = true;
    } else if (argument == L"--no-launch") {
      result.options.noLaunch = true;
    } else if (argument == L"--elevated") {
      result.options.elevated = true;
    } else if (argument == L"--keep-program-files") {
      result.options.skipProgramFiles = true;
    } else if (argument == L"--from") {
      if (!TakeValue(argc, argv, &index, &result.options.from)) {
        result.ok = false;
        result.error = L"--from 缺少取值";
      }
    } else if (argument == L"--dir") {
      if (!TakeValue(argc, argv, &index, &result.options.dir)) {
        result.ok = false;
        result.error = L"--dir 缺少取值";
      }
    } else if (argument == L"--target") {
      if (!TakeValue(argc, argv, &index, &result.options.target)) {
        result.ok = false;
        result.error = L"--target 缺少取值";
      }
    } else if (argument == L"--restart") {
      if (!TakeValue(argc, argv, &index, &result.options.restart)) {
        result.ok = false;
        result.error = L"--restart 缺少取值";
      }
    } else if (argument == L"--sha256") {
      if (!TakeValue(argc, argv, &index, &result.options.sha256)) {
        result.ok = false;
        result.error = L"--sha256 缺少取值";
      }
    } else if (argument == L"--tag") {
      if (!TakeValue(argc, argv, &index, &result.options.tag)) {
        result.ok = false;
        result.error = L"--tag 缺少取值";
      }
    } else if (argument == L"--wait-pid") {
      std::wstring value;
      if (!TakeValue(argc, argv, &index, &value)) {
        result.ok = false;
        result.error = L"--wait-pid 缺少取值";
      } else {
        DWORD parsed = 0;
        if (ParseDword(value, &parsed)) {
          result.options.waitPid = parsed;
        } else {
          result.ok = false;
          result.error = L"--wait-pid 需要数字";
        }
      }
    } else if (argument == L"--size") {
      std::wstring value;
      if (!TakeValue(argc, argv, &index, &value)) {
        result.ok = false;
        result.error = L"--size 缺少取值";
      } else {
        unsigned long long parsed = 0;
        if (ParseUnsigned(value, &parsed)) {
          result.options.size = static_cast<long long>(parsed);
        } else {
          result.ok = false;
          result.error = L"--size 需要数字";
        }
      }
    } else {
      result.ok = false;
      result.error = L"无法识别的参数：" + argument;
    }
    if (!result.ok) {
      break;
    }
  }
  ::LocalFree(argv);
  return result;
}

void PrintUsage() {
  ConsoleWriteLine(L"魔法裁判 Updater " UPDATER_VERSION_STRING);
  ConsoleWriteLine(L"");
  ConsoleWriteLine(L"用法：");
  ConsoleWriteLine(L"  Updater.exe                                            安装向导（图形界面）");
  ConsoleWriteLine(L"  Updater.exe --install --from <后端地址> [--dir <目录>] [--silent]");
  ConsoleWriteLine(L"      [--to-program-files] [--portable] [--no-desktop-shortcut]");
  ConsoleWriteLine(L"      安装：创建开始菜单快捷方式（含「卸载魔法裁判」），桌面快捷方式默认也建，");
  ConsoleWriteLine(L"            用 --no-desktop-shortcut 关掉；");
  ConsoleWriteLine(L"      加 --portable 只下载解压便携版（不写注册表、不建快捷方式、不装更新组件）。");
  ConsoleWriteLine(L"  Updater.exe --update-app --from <地址> --target <安装目录> --restart <exe> [--wait-pid N] [--silent]");
  ConsoleWriteLine(L"  Updater.exe --prepare [--silent] [--dry-run]");
  ConsoleWriteLine(L"  Updater.exe --task-entry");
  ConsoleWriteLine(L"  Updater.exe --uninstall [--dir <目录>] [--purge-data] [--silent]");
  ConsoleWriteLine(L"  Updater.exe --check-install [--dir <目录>]");
  ConsoleWriteLine(L"  Updater.exe --version | --help");
  ConsoleWriteLine(L"");
  ConsoleWriteLine(L"退出码：0 成功 / 1 一般失败 / 2 网络失败 / 3 权限不足 / 4 已安装或已最新 / 5 需要重启");
  ConsoleFlush();
}

bool IsQuietCommand(const std::wstring& command) {
  return command == L"version" || command == L"help" || command == L"check-install";
}

}  // namespace
}  // namespace upd

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previousInstance, PWSTR commandLine,
                    int showCommand) {
  (void)instance;
  (void)previousInstance;
  (void)commandLine;
  (void)showCommand;

  upd::ParseResult parsed = upd::ParseCommandLine();
  if (!parsed.ok) {
    upd::ConsoleWriteLine(L"参数错误：" + parsed.error);
    upd::PrintUsage();
    return upd::kExitFailure;
  }
  const upd::Options options = parsed.options;

  // --dry-run 要「不做任何改动」，连日志文件都不建。
  if (!upd::IsQuietCommand(options.command) && !options.dryRun) {
    upd::SetLogFile(upd::LogFilePath());
  }

  if (options.command == L"version") {
    upd::ConsoleWriteLine(L"magicjudge-updater " UPDATER_VERSION_STRING);
    upd::ConsoleFlush();
    return upd::kExitOk;
  }
  if (options.command == L"help") {
    upd::PrintUsage();
    return upd::kExitOk;
  }
  if (options.command == L"check-install") {
    return upd::RunCheckInstall(options);
  }

  upd::LogFormat(L"Updater %s 启动：%s", UPDATER_VERSION_STRING, options.command.c_str());
  if (options.elevated) {
    upd::LogMessage(L"（提权后的实例）");
  }

  int result = upd::kExitFailure;
  if (options.command.empty()) {
    result = upd::RunInstallerEntry(options);
  } else if (options.command == L"install") {
    result = upd::RunInstall(options, nullptr);
  } else if (options.command == L"prepare") {
    result = upd::RunPrepare(options, nullptr);
  } else if (options.command == L"update-app") {
    result = upd::RunUpdateApp(options, nullptr);
  } else if (options.command == L"task-entry") {
    result = upd::RunTaskEntry(options);
  } else if (options.command == L"uninstall") {
    if (options.silent) {
      result = upd::RunUninstall(options, nullptr);
    } else {
      result = upd::RunUninstallWizard(options);
    }
  } else {
    upd::ConsoleWriteLine(L"未实现的子命令：" + options.command);
    result = upd::kExitFailure;
  }
  upd::LogFormat(L"退出码 %d", result);
  return result;
}
