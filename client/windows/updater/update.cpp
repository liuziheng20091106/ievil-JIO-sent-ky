#include "install.h"

#include <cstring>

#include "archive.h"
#include "gui.h"
#include "http.h"
#include "job.h"
#include "system.h"
#include "version.h"

namespace upd {
namespace {

// 替换单文件：被占用时重试若干次；仍失败由调用方决定是否排进重启替换。
bool ReplaceFileWithRetry(const std::wstring& source, const std::wstring& destination,
                          DWORD* lastError) {
  for (unsigned int attempt = 0; attempt < kFileReplaceRetries; ++attempt) {
    if (::CopyFileW(LongPath(source).c_str(), LongPath(destination).c_str(), FALSE)) {
      return true;
    }
    *lastError = ::GetLastError();
    ::Sleep(kFileReplaceDelayMs);
  }
  return false;
}

// 延迟到重启再删/再替换；失败也不影响主流程。
void ScheduleDelete(const std::wstring& path) {
  if (!FileExists(path)) {
    return;
  }
  if (::DeleteFileW(LongPath(path).c_str())) {
    return;
  }
  if (!::MoveFileExW(LongPath(path).c_str(), nullptr, MOVEFILE_DELAY_UNTIL_REBOOT)) {
    LogFormat(L"安排在重启时删除 %s 失败：%s", path.c_str(),
              Win32ErrorMessage(::GetLastError()).c_str());
  }
}

int FailTaskEntry(const std::wstring& message, const std::wstring& target,
                  const std::wstring& backupDir, const std::vector<std::wstring>& backedUp,
                  bool silent, int exitCode) {
  LogError(message);
  for (size_t index = 0; index < backedUp.size(); ++index) {
    const std::wstring source = JoinPath(backupDir, backedUp[index]);
    if (!FileExists(source)) {
      continue;
    }
    std::wstring restoreError;
    if (!CopyFileTo(source, JoinPath(target, backedUp[index]), false, &restoreError)) {
      LogError(restoreError);
    }
  }
  if (!silent) {
    ShowErrorDialog(L"更新失败", message + L"\n\n更新现场已保留，可稍后重试：\n" + backupDir);
  }
  return exitCode;
}

}  // namespace

int RunUpdateApp(const Options& options, const ProgressSink* progress) {
  if (options.target.empty() || options.restart.empty()) {
    LogError(L"--update-app 需要 --target 与 --restart");
    return kExitFailure;
  }

  Options prepareOptions = options;
  prepareOptions.command = L"prepare";
  prepareOptions.silent = true;
  const int prepareResult = RunPrepare(prepareOptions, progress);
  if (prepareResult != kExitOk) {
    LogFormat(L"准备步骤返回 %d，继续尝试更新", prepareResult);
  }

  int exitCode = kExitFailure;
  PackageRef reference;
  std::wstring error;
  if (!ResolvePackage(options, &exitCode, &reference, &error)) {
    LogError(error);
    return exitCode;
  }

  const std::wstring version = reference.version.empty() ? options.tag : reference.version;
  InstallInfo info;
  if (DetectInstall(&info) && !info.version.empty() && !version.empty()) {
    const int comparison = CompareVersionTags(info.version, version);
    if (comparison == 0 || comparison == 1) {
      LogFormat(L"已安装版本 %s 不低于 %s，无需更新", info.version.c_str(), version.c_str());
      return kExitUpToDate;
    }
  }

  UpdateJob job;
  job.packageUrl = reference.url;
  job.sha256 = reference.sha256;
  job.size = reference.size;
  job.target = TrimTrailingSlash(options.target);
  job.restart = options.restart;
  job.version = version;
  job.waitPid = options.waitPid;
  job.silent = options.silent;
  if (!WriteUpdateJob(job, &error)) {
    LogError(error);
    return kExitFailure;
  }
  LogFormat(L"更新任务已写入 %s", JobFilePath().c_str());

  std::wstring taskError;
  if (UpdaterTaskReady(&taskError) && RunUpdaterTask(&taskError)) {
    LogMessage(L"已把更新交给计划任务 MagicJudgeUpdater，Updater 退出");
    return kExitOk;
  }
  LogFormat(L"计划任务不可用（%s），改为提权后自行执行替换", taskError.c_str());

  DWORD childExit = static_cast<DWORD>(kExitFailure);
  std::wstring runError;
  if (!RunElevatedSelf(L"--task-entry --silent --elevated", 0, &childExit, &runError)) {
    LogError(runError);
    return kExitPermission;
  }
  return static_cast<int>(childExit);
}

int RunTaskEntry(const Options& options) {
  std::wstring error;
  UpdateJob job;
  if (!ReadUpdateJob(&job, &error)) {
    LogError(error);
    return kExitFailure;
  }
  const std::wstring target = TrimTrailingSlash(job.target);
  LogFormat(L"计划任务开始更新：目标 %s，版本 %s", target.c_str(),
            job.version.empty() ? L"(未知)" : job.version.c_str());

  if (job.waitPid != 0) {
    LogFormat(L"等待进程 %u 退出（最多 %u 秒）", static_cast<unsigned int>(job.waitPid),
              static_cast<unsigned int>(kWaitPidTimeoutMs / 1000));
    const HANDLE process =
        ::OpenProcess(SYNCHRONIZE | PROCESS_TERMINATE, FALSE, job.waitPid);
    if (process != nullptr) {
      const DWORD wait = ::WaitForSingleObject(process, kWaitPidTimeoutMs);
      if (wait == WAIT_TIMEOUT) {
        LogMessage(L"等待目标进程退出超时，强制结束该进程");
        ::TerminateProcess(process, 0);
        ::WaitForSingleObject(process, 5000);
      }
      ::CloseHandle(process);
    } else {
      LogMessage(L"目标进程已经退出");
    }
    ::Sleep(800);
  }

  int exitCode = kExitFailure;
  if (!DownloadAndVerifyPackage(job.packageUrl, job.sha256, job.size, nullptr, &exitCode, &error)) {
    LogError(error);
    if (!job.silent) {
      ShowErrorDialog(L"更新失败", L"下载或校验更新包失败：\n" + error);
    }
    return exitCode;
  }

  const std::wstring versionSuffix = job.version.empty() ? L"new" : job.version;
  const std::wstring staging = JoinPath(target, kStagingPrefix + versionSuffix);
  const std::wstring backup = JoinPath(target, kBackupDirName);
  const std::wstring packagePath = LocalPackagePath(job.packageUrl);
  std::wstring ignored;
  DeleteTree(staging, L"", &ignored);
  if (!ExtractArchive(packagePath, staging, &error)) {
    LogError(error);
    DeleteTree(staging, L"", &ignored);
    if (!job.silent) {
      ShowErrorDialog(L"更新失败", L"解压更新包失败：\n" + error);
    }
    return kExitFailure;
  }
  const std::wstring payload = LocatePayloadRoot(staging);

  std::vector<std::wstring> files;
  std::vector<std::wstring> directories;
  if (!ListTreeRelative(payload, &files, &directories, &error)) {
    return FailTaskEntry(error, target, backup, std::vector<std::wstring>(), job.silent,
                         kExitFailure);
  }

  // 若更新包里带着正在运行的 Updater 自己（计划任务跑的就是 %LOCALAPPDATA% 那一份），
  // 先把自身改名腾出位置，替换完再安排删除 .old。
  const std::wstring selfPath = ExePath();
  const std::wstring renamedSelf = selfPath + L".old";
  const std::wstring targetUpdater = JoinPath(target, kUpdaterExeName);
  const std::wstring installedUpdater = InstalledUpdaterPath();
  const std::wstring payloadUpdater = JoinPath(payload, kUpdaterExeName);
  const bool copyInstalledUpdater =
      FileExists(payloadUpdater) && _wcsicmp(installedUpdater.c_str(), targetUpdater.c_str()) != 0;
  bool selfNeedsReplace = false;
  for (size_t index = 0; index < files.size(); ++index) {
    if (_wcsicmp(JoinPath(target, files[index]).c_str(), selfPath.c_str()) == 0) {
      selfNeedsReplace = true;
      break;
    }
  }
  if (copyInstalledUpdater && _wcsicmp(installedUpdater.c_str(), selfPath.c_str()) == 0) {
    selfNeedsReplace = true;
  }
  if (selfNeedsReplace) {
    std::wstring ignoredOld;
    DeleteFileIfExists(renamedSelf, &ignoredOld);
    if (!::MoveFileExW(LongPath(selfPath).c_str(), LongPath(renamedSelf).c_str(),
                       MOVEFILE_REPLACE_EXISTING)) {
      LogFormat(L"重命名正在运行的 Updater 失败：%s",
                Win32ErrorMessage(::GetLastError()).c_str());
    }
  }

  DeleteTree(backup, L"", &ignored);
  if (!EnsureDir(backup, &error)) {
    return FailTaskEntry(error, target, backup, std::vector<std::wstring>(), job.silent,
                         kExitFailure);
  }

  bool rebootRequired = false;
  std::vector<std::wstring> backedUp;
  for (size_t index = 0; index < directories.size(); ++index) {
    std::wstring makeError;
    if (!EnsureDir(JoinPath(target, directories[index]), &makeError)) {
      return FailTaskEntry(makeError, target, backup, backedUp, job.silent, kExitFailure);
    }
  }
  for (size_t index = 0; index < files.size(); ++index) {
    const std::wstring source = JoinPath(payload, files[index]);
    const std::wstring destination = JoinPath(target, files[index]);
    if (!EnsureDir(DirectoryOf(destination), &error)) {
      return FailTaskEntry(error, target, backup, backedUp, job.silent, kExitFailure);
    }
    if (FileExists(destination)) {
      if (!CopyFileTo(destination, JoinPath(backup, files[index]), false, &error)) {
        return FailTaskEntry(error, target, backup, backedUp, job.silent, kExitFailure);
      }
      backedUp.push_back(files[index]);
    }
    DWORD replaceError = 0;
    if (!ReplaceFileWithRetry(source, destination, &replaceError)) {
      if (::MoveFileExW(LongPath(source).c_str(), LongPath(destination).c_str(),
                        MOVEFILE_REPLACE_EXISTING | MOVEFILE_DELAY_UNTIL_REBOOT)) {
        rebootRequired = true;
        LogFormat(L"%s 被占用，已安排在下次重启时替换", files[index].c_str());
        continue;
      }
      return FailTaskEntry(
          Format(L"替换 %s 失败：%s", destination.c_str(),
                 Win32ErrorMessage(replaceError).c_str()),
          target, backup, backedUp, job.silent, kExitFailure);
    }
  }

  // 计划任务跑的是 %LOCALAPPDATA%\MagicJudge\Updater.exe，它可能不在安装目录里。
  if (copyInstalledUpdater) {
    std::wstring copyError;
    if (!CopyFileTo(payloadUpdater, installedUpdater, false, &copyError)) {
      LogFormat(L"更新 %s 失败（不影响本次替换）：%s", installedUpdater.c_str(),
                copyError.c_str());
    }
  }
  if (FileExists(renamedSelf)) {
    ScheduleDelete(renamedSelf);
  }

  const std::wstring installedVersion =
      job.version.empty() ? UPDATER_VERSION_STRING : job.version;
  std::wstring registryError;
  if (!WriteRegistryInstall(target, installedVersion, JoinPath(target, kUpdaterExeName),
                            &registryError)) {
    LogError(registryError);
  }

  DeleteTree(staging, L"", &ignored);
  DeleteTree(backup, L"", &ignored);
  DeleteUpdateJob();

  if (!job.restart.empty()) {
    std::wstring restartPath = job.restart;
    if (restartPath.find(L'\\') == std::wstring::npos && restartPath.find(L'/') == std::wstring::npos) {
      restartPath = JoinPath(target, restartPath);
    }
    LaunchApplication(restartPath, target);
  }

  if (rebootRequired) {
    LogMessage(L"部分文件要等重启后才能替换，请重启电脑完成更新");
    if (!job.silent) {
      ShowInfoDialog(L"更新完成", L"部分文件被占用，已安排在下次重启时替换。\n请重启电脑完成更新。");
    }
    return kExitRebootRequired;
  }
  LogMessage(L"更新完成");
  return kExitOk;
}

}  // namespace upd
