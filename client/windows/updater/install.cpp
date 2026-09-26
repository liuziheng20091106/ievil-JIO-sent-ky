#include "install.h"

#include <cstring>

#include "archive.h"
#include "http.h"
#include "job.h"
#include "json.h"
#include "system.h"
#include "version.h"

namespace upd {
namespace {

std::wstring UpdaterUserAgent() {
  return Format(L"magicjudge-updater/%s (windows)", UPDATER_VERSION_STRING);
}

std::wstring ClientUserAgent(const std::wstring& version) {
  return Format(L"seven-double-flutter/%s (windows)", version.c_str());
}

std::wstring UrlOrigin(const std::wstring& url) {
  const size_t scheme = url.find(L"://");
  if (scheme == std::wstring::npos) {
    return std::wstring();
  }
  const size_t slash = url.find(L'/', scheme + 3);
  if (slash == std::wstring::npos) {
    return TrimTrailingSlash(url);
  }
  return url.substr(0, slash);
}

std::wstring ResolveUrl(const std::wstring& base, const std::wstring& path) {
  if (path.empty()) {
    return std::wstring();
  }
  if (StartsWithI(path, L"http://") || StartsWithI(path, L"https://")) {
    return path;
  }
  const std::wstring origin = UrlOrigin(base);
  if (origin.empty()) {
    return path;
  }
  if (path[0] == L'/') {
    return origin + path;
  }
  return origin + L"/" + path;
}

bool LooksLikeDirectPackage(const std::wstring& from) {
  return EndsWithI(from, L".zip") || EndsWithI(from, L".7z") || EndsWithI(from, L".tar");
}

bool ExtractUpdateInfo(const std::string& body, const std::wstring& base, PackageRef* reference) {
  std::wstring url;
  if (!JsonLookupText(body, L"update.url", &url) || url.empty()) {
    return false;
  }
  reference->url = ResolveUrl(base, url);
  std::wstring value;
  if (JsonLookupText(body, L"update.sha256", &value)) {
    reference->sha256 = value;
  }
  if (JsonLookupText(body, L"update.size", &value)) {
    unsigned long long parsed = 0;
    if (ParseUnsigned(value, &parsed)) {
      reference->size = static_cast<long long>(parsed);
    }
  }
  if (JsonLookupText(body, L"update.latest", &value)) {
    reference->version = value;
  }
  return true;
}

bool QueryHealth(const std::wstring& base, const std::wstring& userAgent, PackageRef* reference,
                 bool* httpOk, std::wstring* httpError) {
  HttpResponse response;
  std::wstring requestError;
  const std::wstring healthUrl = TrimTrailingSlash(base) + L"/api/health";
  if (!HttpGet(healthUrl, userAgent, &response, &requestError)) {
    *httpOk = false;
    *httpError = requestError;
    return false;
  }
  *httpOk = true;
  return ExtractUpdateInfo(response.body, base, reference);
}

bool DownloadPackage(const PackageRef& reference, const std::wstring& destination,
                     const ProgressSink* progress, std::wstring* error) {
  const int percent = 10;
  ReportProgress(progress, percent, Format(L"正在下载 %s", reference.url.c_str()));
  return HttpDownloadToFile(reference.url, UpdaterUserAgent(), destination, nullptr, nullptr, error);
}

bool VerifyPackage(const std::wstring& path, const PackageRef& reference, std::wstring* error) {
  if (reference.size > 0) {
    const unsigned long long actual = FileSizeOf(path);
    if (actual != static_cast<unsigned long long>(reference.size)) {
      *error = Format(L"更新包大小不符：期望 %lld 字节，实际 %llu 字节",
                      reference.size, actual);
      return false;
    }
  }
  if (!reference.sha256.empty()) {
    std::string actual;
    std::wstring hashError;
    if (!Sha256File(path, &actual, &hashError)) {
      *error = hashError;
      return false;
    }
    if (!HexEqualI(actual, WideToUtf8(reference.sha256))) {
      *error = Format(L"更新包校验失败：期望 %s，实际 %hs", reference.sha256.c_str(), actual.c_str());
      return false;
    }
  }
  return true;
}

// 已下载且校验通过就不重复下载。
bool EnsurePackageDownloaded(const PackageRef& reference, const std::wstring& path,
                             const ProgressSink* progress, int* exitCode, std::wstring* error) {
  if (FileExists(path) && reference.size > 0 &&
      FileSizeOf(path) == static_cast<unsigned long long>(reference.size)) {
    std::wstring verifyError;
    if (VerifyPackage(path, reference, &verifyError)) {
      ReportProgress(progress, 30, L"已有缓存更新包，跳过下载");
      return true;
    }
    std::wstring ignored;
    DeleteFileIfExists(path, &ignored);
  }
  if (!DownloadPackage(reference, path, progress, error)) {
    *exitCode = kExitNetwork;
    return false;
  }
  if (!VerifyPackage(path, reference, error)) {
    std::wstring ignored;
    DeleteFileIfExists(path, &ignored);
    *exitCode = kExitNetwork;
    return false;
  }
  return true;
}

std::wstring FindSingleChildDirectory(const std::wstring& root) {
  WIN32_FIND_DATAW data{};
  const HANDLE find = ::FindFirstFileW(LongPath(JoinPath(root, L"*")).c_str(), &data);
  if (find == INVALID_HANDLE_VALUE) {
    return std::wstring();
  }
  int directories = 0;
  int files = 0;
  std::wstring directory;
  do {
    const std::wstring name = data.cFileName;
    if (name == L"." || name == L"..") {
      continue;
    }
    if ((data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) != 0) {
      ++directories;
      directory = JoinPath(root, name);
    } else {
      ++files;
    }
  } while (::FindNextFileW(find, &data) != FALSE);
  ::FindClose(find);
  if (directories == 1 && files == 0) {
    return directory;
  }
  return std::wstring();
}

// 更新包里可能多套一层目录，最多下钻三层找 seven_double_client.exe。
std::wstring FindPayloadRoot(const std::wstring& staging) {
  std::wstring current = staging;
  for (int depth = 0; depth < 3; ++depth) {
    if (FileExists(JoinPath(current, kAppExeName))) {
      return current;
    }
    const std::wstring child = FindSingleChildDirectory(current);
    if (child.empty()) {
      return current;
    }
    current = child;
  }
  return current;
}

std::wstring BuildElevatedArguments(const Options& options, bool forceSilent) {
  std::wstring arguments = L"--" + options.command;
  if (!options.from.empty()) {
    arguments += L" --from " + QuoteArgument(options.from);
  }
  if (!options.dir.empty()) {
    arguments += L" --dir " + QuoteArgument(options.dir);
  }
  if (!options.target.empty()) {
    arguments += L" --target " + QuoteArgument(options.target);
  }
  if (!options.restart.empty()) {
    arguments += L" --restart " + QuoteArgument(options.restart);
  }
  if (!options.sha256.empty()) {
    arguments += L" --sha256 " + QuoteArgument(options.sha256);
  }
  if (!options.tag.empty()) {
    arguments += L" --tag " + QuoteArgument(options.tag);
  }
  if (options.size >= 0) {
    arguments += L" --size " + Format(L"%lld", options.size);
  }
  if (options.waitPid != 0) {
    arguments += L" --wait-pid " + Format(L"%u", static_cast<unsigned int>(options.waitPid));
  }
  if (options.toProgramFiles) {
    arguments += L" --to-program-files";
  }
  if (options.purgeData) {
    arguments += L" --purge-data";
  }
  if (options.noLaunch) {
    arguments += L" --no-launch";
  }
  if (forceSilent || options.silent) {
    arguments += L" --silent";
  }
  arguments += L" --elevated";
  return arguments;
}

void DescribePackage(const PackageRef& reference) {
  LogFormat(L"更新包：%s", reference.url.c_str());
  LogFormat(L"校验：sha256=%s size=%lld version=%s",
            reference.sha256.empty() ? L"(无)" : reference.sha256.c_str(), reference.size,
            reference.version.empty() ? L"(未知)" : reference.version.c_str());
}

}  // namespace

std::wstring LocatePayloadRoot(const std::wstring& staging) { return FindPayloadRoot(staging); }

std::wstring LocalPackagePath(const std::wstring& packageUrl) {
  std::wstring fileName = FileNameOf(packageUrl);
  const size_t query = fileName.find(L'?');
  if (query != std::wstring::npos) {
    fileName = fileName.substr(0, query);
  }
  if (fileName.empty()) {
    fileName = L"magicjudge-windows.zip";
  }
  return JoinPath(DownloadsDir(), fileName);
}

bool DownloadAndVerifyPackage(const std::wstring& packageUrl, const std::wstring& sha256, long long size,
                              const ProgressSink* progress, int* exitCode, std::wstring* error) {
  int localExitCode = kExitFailure;
  if (exitCode == nullptr) {
    exitCode = &localExitCode;
  }
  if (packageUrl.empty()) {
    *error = L"更新包地址为空";
    return false;
  }
  PackageRef reference;
  reference.url = packageUrl;
  reference.sha256 = sha256;
  reference.size = size;
  return EnsurePackageDownloaded(reference, LocalPackagePath(packageUrl), progress, exitCode, error);
}

int CompareVersionTags(const std::wstring& left, const std::wstring& right) {
  const std::wstring texts[2] = {left, right};
  int parts[2][3] = {{0, 0, 0}, {0, 0, 0}};
  for (int side = 0; side < 2; ++side) {
    const std::wstring& text = texts[side];
    size_t begin = 0;
    for (int index = 0; index < 3; ++index) {
      const size_t dot = text.find(L'.', begin);
      if (index < 2 && dot == std::wstring::npos) {
        return -2;
      }
      const std::wstring piece =
          dot == std::wstring::npos ? text.substr(begin) : text.substr(begin, dot - begin);
      unsigned long long value = 0;
      if (!ParseUnsigned(Trim(piece), &value)) {
        return -2;
      }
      parts[side][index] = static_cast<int>(value);
      if (dot == std::wstring::npos) {
        break;
      }
      begin = dot + 1;
      if (index == 2) {
        return -2;  // 多出来的第四段不接受
      }
    }
  }
  for (int index = 0; index < 3; ++index) {
    if (parts[0][index] != parts[1][index]) {
      return parts[0][index] > parts[1][index] ? 1 : -1;
    }
  }
  return 0;
}

bool ResolvePackage(const Options& options, int* exitCode, PackageRef* reference,
                    std::wstring* error) {
  *reference = PackageRef();
  *exitCode = kExitFailure;
  if (options.from.empty()) {
    *error = L"缺少 --from 参数（后端地址或更新包直链）";
    return false;
  }
  if (LooksLikeDirectPackage(options.from)) {
    reference->url = options.from;
    reference->sha256 = options.sha256;
    reference->size = options.size;
    reference->version = options.tag;
    *exitCode = kExitOk;
    return true;
  }

  bool httpOk = false;
  std::wstring httpError;
  if (!QueryHealth(options.from, UpdaterUserAgent(), reference, &httpOk, &httpError)) {
    // 兼容只认客户端 UA 的旧后端：拿已知版本再问一次。
    std::wstring knownVersion = options.tag;
    if (knownVersion.empty()) {
      InstallInfo info;
      if (DetectInstall(&info)) {
        knownVersion = info.version;
      }
    }
    if (!knownVersion.empty()) {
      bool fallbackOk = false;
      std::wstring fallbackError;
      if (QueryHealth(options.from, ClientUserAgent(knownVersion), reference, &fallbackOk,
                      &fallbackError)) {
        httpOk = true;
      } else if (fallbackOk) {
        httpOk = true;
      }
    }
  }
  if (reference->url.empty()) {
    if (!httpOk) {
      *error = Format(L"访问 %s/api/health 失败：%s", TrimTrailingSlash(options.from).c_str(),
                      httpError.c_str());
      *exitCode = kExitNetwork;
    } else {
      *error = Format(L"后端没有下发更新包地址（%s/api/health 的 update.url 为空）",
                      TrimTrailingSlash(options.from).c_str());
      *exitCode = kExitFailure;
    }
    return false;
  }
  if (!options.sha256.empty()) {
    reference->sha256 = options.sha256;
  }
  if (options.size >= 0) {
    reference->size = options.size;
  }
  if (!options.tag.empty()) {
    reference->version = options.tag;
  }
  *exitCode = kExitOk;
  return true;
}

int RerunElevated(const Options& options, bool forceSilent) {
  const std::wstring arguments = BuildElevatedArguments(options, forceSilent);
  LogFormat(L"需要管理员权限，提权重跑：%s", arguments.c_str());
  DWORD exitCode = static_cast<DWORD>(kExitFailure);
  std::wstring error;
  if (!RunElevatedSelf(arguments, 0, &exitCode, &error)) {
    LogError(error);
    return kExitPermission;
  }
  LogFormat(L"提权进程退出码 %u", static_cast<unsigned int>(exitCode));
  return static_cast<int>(exitCode);
}

bool LaunchApplication(const std::wstring& exePath, const std::wstring& workingDirectory) {
  if (!FileExists(exePath)) {
    LogFormat(L"未找到可执行文件 %s，跳过启动", exePath.c_str());
    return false;
  }
  const HINSTANCE result =
      ::ShellExecuteW(nullptr, L"open", exePath.c_str(), nullptr,
                      workingDirectory.empty() ? nullptr : workingDirectory.c_str(), SW_SHOWNORMAL);
  if (reinterpret_cast<INT_PTR>(result) <= 32) {
    LogFormat(L"启动 %s 失败（%lld）", exePath.c_str(),
              static_cast<long long>(reinterpret_cast<INT_PTR>(result)));
    return false;
  }
  return true;
}

int RunInstall(const Options& options, const ProgressSink* progress) {
  Options effective = options;
  if (effective.dir.empty()) {
    effective.dir = effective.toProgramFiles ? JoinPath(ProgramFilesDir(), kProductDirName)
                                             : CurrentDirectory();
  }
  effective.dir = TrimTrailingSlash(effective.dir);
  ReportProgress(progress, 0, Format(L"安装目录：%s", effective.dir.c_str()));

  if (!IsProcessElevated() && !DirectoryIsWritable(effective.dir)) {
    ReportProgress(progress, 0, L"目标目录需要管理员权限，正在请求提权");
    return RerunElevated(effective, true);
  }

  std::wstring error;
  if (!EnsureDir(effective.dir, &error)) {
    LogError(error);
    return kExitFailure;
  }

  int exitCode = kExitFailure;
  PackageRef reference;
  if (!ResolvePackage(effective, &exitCode, &reference, &error)) {
    LogError(error);
    return exitCode;
  }
  DescribePackage(reference);

  const std::wstring packagePath = LocalPackagePath(reference.url);
  ReportProgress(progress, 10, L"准备下载更新包");
  if (!EnsurePackageDownloaded(reference, packagePath, progress, &exitCode, &error)) {
    LogError(error);
    return exitCode;
  }
  ReportProgress(progress, 60, L"下载完成，正在解压");

  const std::wstring staging = JoinPath(effective.dir, L".install-staging");
  std::wstring ignored;
  DeleteTree(staging, L"", &ignored);
  if (!ExtractArchive(packagePath, staging, &error)) {
    LogError(error);
    DeleteTree(staging, L"", &ignored);
    return kExitFailure;
  }
  const std::wstring payload = LocatePayloadRoot(staging);
  if (!CopyTree(payload, effective.dir, &error)) {
    // 覆盖正在运行的游戏会失败（文件被占用）：先结束它，再试一次。
    const std::wstring appExe = JoinPath(effective.dir, kAppExeName);
    int stopped = 0;
    std::wstring stopError;
    if (!StopProcessByImagePath(appExe, &stopped, &stopError)) {
      LogError(stopError);
    }
    if (stopped > 0) {
      ReportProgress(progress, 70, Format(L"已结束 %d 个正在运行的程序，正在重试", stopped));
      ::Sleep(800);
    }
    std::wstring retryError;
    if (!CopyTree(payload, effective.dir, &retryError)) {
      LogError(retryError);
      DeleteTree(staging, L"", &ignored);
      return kExitFailure;
    }
  }
  DeleteTree(staging, L"", &ignored);
  ReportProgress(progress, 80, L"文件已就位");

  const std::wstring targetUpdater = JoinPath(effective.dir, kUpdaterExeName);
  const std::wstring selfPath = ExePath();
  std::wstring copyError;
  if (_wcsicmp(selfPath.c_str(), targetUpdater.c_str()) != 0) {
    if (!CopyFileTo(selfPath, targetUpdater, false, &copyError)) {
      LogError(copyError);
    }
  }
  // 安装/更新后 %LOCALAPPDATA%\MagicJudge\Updater.exe 必须是同一份（计划任务跑的就是它）。
  const std::wstring installedUpdater = InstalledUpdaterPath();
  if (_wcsicmp(selfPath.c_str(), installedUpdater.c_str()) != 0) {
    if (CopyFileTo(selfPath, installedUpdater, false, &copyError)) {
      LogFormat(L"已把 Updater 复制到 %s", installedUpdater.c_str());
    } else {
      LogError(copyError);
    }
  }

  const std::wstring version = reference.version.empty() ? UPDATER_VERSION_STRING : reference.version;
  if (!WriteRegistryInstall(effective.dir, version, targetUpdater, &error)) {
    LogError(error);
    return kExitFailure;
  }
  ReportProgress(progress, 90, L"已写入注册表安装信息");

  Options prepareOptions = effective;
  prepareOptions.command = L"prepare";
  const int prepareResult = RunPrepare(prepareOptions, progress);
  if (prepareResult != kExitOk) {
    ReportProgress(progress, 95, L"证书或计划任务未就绪：应用内自动更新暂不可用");
  }

  ReportProgress(progress, 100, L"安装完成");
  if (!effective.silent && !effective.noLaunch) {
    LaunchApplication(JoinPath(effective.dir, kAppExeName), effective.dir);
  }
  return kExitOk;
}

int RunPrepare(const Options& options, const ProgressSink* progress) {
  std::wstring error;
  const CertState certState = CheckCertificate(&error);
  const bool taskReady = UpdaterTaskReady(&error);
  const bool updaterCopyReady = UpdaterCopyIsCurrent();
  const bool needCertificate = certState == CertState::NeedsInstall;
  const bool needTask = !taskReady;
  const bool needCopy = !updaterCopyReady;

  if (options.dryRun) {
    ConsoleWriteLine(L"prepare_dry_run=1");
    ConsoleWriteLine(Format(L"certificate=%s", certState == CertState::Trusted ? L"trusted"
                                                    : certState == CertState::NotEmbedded
                                                        ? L"not-embedded"
                                                        : L"needs-install"));
    ConsoleWriteLine(Format(L"certificate_sha256=%s", CertificateSha256().c_str()));
    ConsoleWriteLine(Format(L"updater_copy=%s", updaterCopyReady ? L"ready" : L"missing"));
    ConsoleWriteLine(Format(L"updater_copy_path=%s", InstalledUpdaterPath().c_str()));
    ConsoleWriteLine(Format(L"scheduled_task=%s", taskReady ? L"ready" : L"missing"));
    ConsoleWriteLine(Format(L"elevated=%s", IsProcessElevated() ? L"1" : L"0"));
    ConsoleWriteLine(Format(L"plan=%s", (needCertificate || needTask) && !IsProcessElevated()
                                           ? L"install-certificate-and-task-elevated"
                                           : L"install-certificate-and-task"));
    if (certState == CertState::NotEmbedded) {
      ConsoleWriteLine(L"certificate_note=内嵌证书为空，请先运行 tools/sign-windows.ps1 再重新编译");
    }
    return kExitOk;
  }

  if (!needCertificate && !needTask && !needCopy) {
    if (certState == CertState::NotEmbedded) {
      LogMessage(L"警告：没有内嵌证书，已跳过证书安装；请先运行 tools/sign-windows.ps1 再重新编译");
    } else {
      LogMessage(L"证书与计划任务都已就绪，无需改动");
    }
    return kExitOk;
  }

  // 副本存在也要比内容（大小 + SHA-256）：旧构建或坏文件都要刷新。
  {
    std::wstring copyError;
    if (!EnsureInstalledUpdaterCopy(&copyError)) {
      LogError(copyError);
      if (needCopy) {
        return kExitFailure;
      }
    }
  }

  if (needCertificate || needTask) {
    if (!IsProcessElevated()) {
      Options elevated = options;
      elevated.command = L"prepare";
      // 提权后的子进程必须无界面，否则会再弹一个窗口。
      elevated.silent = true;
      return RerunElevated(elevated, true);
    }
    if (needCertificate) {
      std::wstring certError;
      if (!InstallCertificate(&certError)) {
        LogError(certError);
        return kExitPermission;
      }
      LogMessage(L"已把自签名证书写入「受信任的根证书颁发机构」与「受信任的发布者」");
    } else if (certState == CertState::NotEmbedded) {
      LogMessage(L"警告：没有内嵌证书，已跳过证书安装；请先运行 tools/sign-windows.ps1 再重新编译");
    }
    if (needTask) {
      std::wstring taskError;
      if (!CreateUpdaterTask(InstalledUpdaterPath(), &taskError)) {
        LogError(taskError);
        return kExitPermission;
      }
      LogFormat(L"已创建计划任务 %s", kTaskName);
    }
  } else if (certState == CertState::NotEmbedded) {
    LogMessage(L"警告：没有内嵌证书，已跳过证书安装；请先运行 tools/sign-windows.ps1 再重新编译");
  }

  ReportProgress(progress, 100, L"准备完成");
  return kExitOk;
}

int RunUninstall(const Options& options, const ProgressSink* progress) {
  InstallInfo info;
  if (!options.skipProgramFiles) {
    DetectInstall(&info);
  }
  const std::wstring dir = options.skipProgramFiles
                               ? std::wstring()
                               : (options.dir.empty() ? TrimTrailingSlash(info.installDir)
                                                      : TrimTrailingSlash(options.dir));
  int failures = 0;

  if (!dir.empty() && DirExists(dir)) {
    ReportProgress(progress, 10, Format(L"正在关闭 %s", kAppExeName));
    int stopped = 0;
    std::wstring stopError;
    if (!StopProcessByImagePath(JoinPath(dir, kAppExeName), &stopped, &stopError)) {
      LogError(stopError);
      ++failures;
    } else if (stopped > 0) {
      ReportProgress(progress, 20, Format(L"已结束 %d 个正在运行的程序", stopped));
    }
    Sleep(300);
    const std::wstring keep = JoinPath(dir, kUpdaterExeName);
    std::wstring deleteError;
    ReportProgress(progress, 40, Format(L"正在删除 %s", dir.c_str()));
    if (!DeleteTreeContents(dir, keep, &deleteError)) {
      LogError(deleteError);
      ++failures;
    }
    // 目录空了就顺手删掉；Updater.exe 还在里面时会失败，属正常。
    ::RemoveDirectoryW(LongPath(dir).c_str());
  } else {
    ReportProgress(progress, 20, L"没有找到安装目录，跳过程序文件删除");
  }

  if (options.purgeData) {
    const std::vector<std::wstring> dataDirs = PersistentDataDirs();
    for (size_t index = 0; index < dataDirs.size(); ++index) {
      if (!DirExists(dataDirs[index])) {
        continue;
      }
      ReportProgress(progress, 60, Format(L"正在删除持久化数据 %s", dataDirs[index].c_str()));
      std::wstring dataError;
      if (!DeleteTree(dataDirs[index], L"", &dataError)) {
        LogError(dataError);
        ++failures;
      }
    }
  }

  ReportProgress(progress, 80, L"正在清理注册表与计划任务");
  std::wstring registryError;
  if (!DeleteRegistryInstall(&registryError)) {
    LogError(registryError);
    ++failures;
  }
  std::wstring taskError;
  if (!DeleteUpdaterTask(&taskError)) {
    LogError(taskError);
    ++failures;
  }
  DeleteUpdateJob();
  std::wstring downloadError;
  DeleteTree(DownloadsDir(), L"", &downloadError);

  ReportProgress(progress, 100, failures == 0 ? L"卸载完成（Updater.exe 自身保留）"
                                              : L"卸载完成，但有文件未能删除");
  return failures == 0 ? kExitOk : kExitFailure;
}

int RunCheckInstall(const Options& options) {
  InstallInfo info;
  bool detected = false;
  std::wstring dir;
  if (options.dir.empty()) {
    // 不给 --dir 时按「当前目录 → %ProgramFiles%\MagicJudge → 注册表」探测。
    detected = DetectInstall(&info);
    dir = info.installDir;
  } else {
    // 给了 --dir 就只看这个目录，注册表信息仍然照读（供脚本参考）。
    dir = TrimTrailingSlash(options.dir);
    ReadRegistryInstall(&info);
    detected = FileExists(JoinPath(dir, kAppExeName));
    if (detected) {
      info.found = true;
      info.source = L"dir";
      info.installDir = dir;
      if (info.version.empty()) {
        info.version = info.registryVersion;
      }
      if (info.updaterPath.empty()) {
        info.updaterPath = JoinPath(dir, kUpdaterExeName);
      }
    } else {
      info.source.clear();
      info.installDir.clear();
      info.updaterPath.clear();
    }
  }

  ConsoleWriteLine(Format(L"installed=%d", detected ? 1 : 0));
  ConsoleWriteLine(Format(L"source=%s", info.source.c_str()));
  ConsoleWriteLine(Format(L"install_dir=%s", dir.c_str()));
  ConsoleWriteLine(Format(L"version=%s", info.version.c_str()));
  ConsoleWriteLine(Format(L"updater_path=%s", info.updaterPath.c_str()));
  ConsoleWriteLine(Format(L"registry_present=%d", info.registryFound ? 1 : 0));
  ConsoleWriteLine(Format(L"registry_install_location=%s", info.registryInstallLocation.c_str()));
  ConsoleWriteLine(Format(L"registry_version=%s", info.registryVersion.c_str()));
  ConsoleWriteLine(Format(L"uninstall_string=%s", info.uninstallString.c_str()));
  ConsoleWriteLine(Format(L"display_name=%s", info.displayName.c_str()));
  ConsoleWriteLine(Format(L"app_exe_exists=%d",
                          (!dir.empty() && FileExists(JoinPath(dir, kAppExeName))) ? 1 : 0));
  ConsoleFlush();
  return detected ? kExitOk : kExitUpToDate;
}

}  // namespace upd
