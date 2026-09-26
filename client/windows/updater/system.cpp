#include "system.h"

#include <tlhelp32.h>
#include <wincrypt.h>

#include <cstring>

#include "http.h"

// 内嵌的自签名证书：由 tools/sign-windows.ps1 生成。
// - self_signed_cert.local.h：脚本生成的真实证书（不入库，已 gitignore）；
// - self_signed_cert.h：入库的空占位，保证 git clone 后直接编译通过。
// 两个都不存在时用内联的空定义兜底。
#if __has_include("self_signed_cert.local.h")
#include "self_signed_cert.local.h"
#elif __has_include("self_signed_cert.h")
#include "self_signed_cert.h"
#else
namespace upd {
inline constexpr unsigned char kSelfSignedCertBytes[] = {0x00};
inline constexpr unsigned int kSelfSignedCertLength = 0;
inline constexpr char kSelfSignedCertSha256[] = "";
}  // namespace upd
#endif

namespace upd {
namespace {

bool ReadStringValue(HKEY key, const wchar_t* name, std::wstring* value) {
  DWORD type = 0;
  DWORD size = 0;
  if (::RegQueryValueExW(key, name, nullptr, &type, nullptr, &size) != ERROR_SUCCESS) {
    return false;
  }
  if (type != REG_SZ && type != REG_EXPAND_SZ) {
    return false;
  }
  if (size == 0) {
    *value = std::wstring();
    return true;
  }
  std::vector<wchar_t> buffer(static_cast<size_t>(size) / sizeof(wchar_t) + 1, L'\0');
  if (::RegQueryValueExW(key, name, nullptr, &type, reinterpret_cast<LPBYTE>(buffer.data()),
                         &size) != ERROR_SUCCESS) {
    return false;
  }
  buffer.back() = L'\0';
  *value = std::wstring(buffer.data());
  return true;
}

bool WriteStringValue(HKEY key, const wchar_t* name, const std::wstring& value) {
  const DWORD bytes = static_cast<DWORD>((value.size() + 1) * sizeof(wchar_t));
  return ::RegSetValueExW(key, name, 0, REG_SZ, reinterpret_cast<const BYTE*>(value.c_str()),
                          bytes) == ERROR_SUCCESS;
}

bool WriteDwordValue(HKEY key, const wchar_t* name, DWORD value) {
  return ::RegSetValueExW(key, name, 0, REG_DWORD, reinterpret_cast<const BYTE*>(&value),
                          sizeof(value)) == ERROR_SUCCESS;
}

std::wstring DecodeConsoleOutput(const std::string& raw) {
  if (raw.size() >= 2 && static_cast<unsigned char>(raw[0]) == 0xFF &&
      static_cast<unsigned char>(raw[1]) == 0xFE) {
    const size_t count = (raw.size() - 2) / sizeof(wchar_t);
    std::wstring text(count, L'\0');
    if (count > 0) {
      ::memcpy(text.data(), raw.data() + 2, count * sizeof(wchar_t));
    }
    return text;
  }
  size_t offset = 0;
  if (raw.size() >= 3 && static_cast<unsigned char>(raw[0]) == 0xEF &&
      static_cast<unsigned char>(raw[1]) == 0xBB && static_cast<unsigned char>(raw[2]) == 0xBF) {
    offset = 3;
  }
  const char* data = raw.data() + offset;
  const int length = static_cast<int>(raw.size() - offset);
  if (length <= 0) {
    return std::wstring();
  }
  int capacity =
      ::MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, data, length, nullptr, 0);
  UINT codePage = CP_UTF8;
  if (capacity <= 0) {
    codePage = CP_ACP;
    capacity = ::MultiByteToWideChar(codePage, 0, data, length, nullptr, 0);
  }
  if (capacity <= 0) {
    return std::wstring();
  }
  std::wstring text(static_cast<size_t>(capacity), L'\0');
  ::MultiByteToWideChar(codePage, 0, data, length, text.data(), capacity);
  return text;
}

bool ComputeCertSha256(PCCERT_CONTEXT context, std::string* hex) {
  std::wstring error;
  return Sha256Bytes(context->pbCertEncoded, context->cbCertEncoded, hex, &error);
}

bool StoreHasCertificate(const wchar_t* storeName, const std::string& wantedHex,
                         std::wstring* error) {
  HCERTSTORE store = ::CertOpenStore(CERT_STORE_PROV_SYSTEM_W, 0, 0,
                                     CERT_SYSTEM_STORE_LOCAL_MACHINE, storeName);
  if (store == nullptr) {
    *error = Format(L"打开证书存储 %s 失败：%s", storeName,
                    Win32ErrorMessage(::GetLastError()).c_str());
    return false;
  }
  bool found = false;
  PCCERT_CONTEXT context = nullptr;
  while ((context = ::CertEnumCertificatesInStore(store, context)) != nullptr) {
    std::string hex;
    if (ComputeCertSha256(context, &hex) && HexEqualI(hex, wantedHex)) {
      found = true;
      break;
    }
  }
  ::CertCloseStore(store, 0);
  return found;
}

bool AddCertificateToStore(const wchar_t* storeName, const unsigned char* bytes,
                           unsigned int length, std::wstring* error) {
  HCERTSTORE store = ::CertOpenStore(CERT_STORE_PROV_SYSTEM_W, 0, 0,
                                     CERT_SYSTEM_STORE_LOCAL_MACHINE, storeName);
  if (store == nullptr) {
    *error = Format(L"打开证书存储 %s 失败：%s", storeName,
                    Win32ErrorMessage(::GetLastError()).c_str());
    return false;
  }
  const BOOL added = ::CertAddEncodedCertificateToStore(
      store, X509_ASN_ENCODING | PKCS_7_ASN_ENCODING, bytes, length,
      CERT_STORE_ADD_REPLACE_EXISTING, nullptr);
  const DWORD code = ::GetLastError();
  ::CertCloseStore(store, 0);
  if (added == FALSE) {
    *error = Format(L"写入证书存储 %s 失败：%s", storeName, Win32ErrorMessage(code).c_str());
    return false;
  }
  return true;
}

std::wstring ProgramFilesCandidate() {
  return JoinPath(ProgramFilesDir(), kProductDirName);
}

}  // namespace

// ==== 注册表 ====

bool ReadRegistryInstall(InstallInfo* info) {
  HKEY key = nullptr;
  if (::RegOpenKeyExW(HKEY_CURRENT_USER, kRegistryProductKey, 0, KEY_READ, &key) != ERROR_SUCCESS) {
    return false;
  }
  info->registryFound = true;
  ReadStringValue(key, L"InstallLocation", &info->registryInstallLocation);
  ReadStringValue(key, L"Version", &info->registryVersion);
  ReadStringValue(key, L"UpdaterPath", &info->updaterPath);
  ReadStringValue(key, L"UninstallString", &info->uninstallString);
  ReadStringValue(key, L"DisplayName", &info->displayName);
  ReadStringValue(key, L"Publisher", &info->publisher);
  ::RegCloseKey(key);
  return true;
}

std::wstring RegistryUninstallString(const std::wstring& installDir) {
  return QuoteArgument(JoinPath(installDir, kUpdaterExeName)) + L" --uninstall";
}

bool WriteRegistryInstall(const std::wstring& installDir, const std::wstring& version,
                          const std::wstring& updaterPath, std::wstring* error) {
  const std::wstring uninstallString = RegistryUninstallString(installDir);
  const std::wstring displayIcon = JoinPath(installDir, kAppExeName);
  HKEY key = nullptr;
  if (::RegCreateKeyExW(HKEY_CURRENT_USER, kRegistryProductKey, 0, nullptr,
                        REG_OPTION_NON_VOLATILE, KEY_WRITE, nullptr, &key,
                        nullptr) != ERROR_SUCCESS) {
    *error = Format(L"创建注册表键失败：%s", Win32ErrorMessage(::GetLastError()).c_str());
    return false;
  }
  bool ok = true;
  ok = WriteStringValue(key, L"InstallLocation", installDir) && ok;
  ok = WriteStringValue(key, L"Version", version) && ok;
  ok = WriteStringValue(key, L"UpdaterPath", updaterPath) && ok;
  ok = WriteStringValue(key, L"UninstallString", uninstallString) && ok;
  ok = WriteStringValue(key, L"DisplayName", kDisplayName) && ok;
  ok = WriteStringValue(key, L"Publisher", kPublisher) && ok;
  ::RegCloseKey(key);

  HKEY uninstallKey = nullptr;
  if (::RegCreateKeyExW(HKEY_CURRENT_USER, kRegistryUninstallKey, 0, nullptr,
                        REG_OPTION_NON_VOLATILE, KEY_WRITE, nullptr, &uninstallKey,
                        nullptr) != ERROR_SUCCESS) {
    *error = Format(L"创建卸载注册表键失败：%s", Win32ErrorMessage(::GetLastError()).c_str());
    return false;
  }
  ok = WriteStringValue(uninstallKey, L"DisplayName", kDisplayName) && ok;
  ok = WriteStringValue(uninstallKey, L"Publisher", kPublisher) && ok;
  ok = WriteStringValue(uninstallKey, L"DisplayVersion", version) && ok;
  ok = WriteStringValue(uninstallKey, L"DisplayIcon", displayIcon) && ok;
  ok = WriteStringValue(uninstallKey, L"InstallLocation", installDir) && ok;
  ok = WriteStringValue(uninstallKey, L"UninstallString", uninstallString) && ok;
  ok = WriteDwordValue(uninstallKey, L"NoModify", 1) && ok;
  ok = WriteDwordValue(uninstallKey, L"NoRepair", 1) && ok;
  ::RegCloseKey(uninstallKey);

  if (!ok) {
    *error = L"写入注册表安装信息失败";
  }
  return ok;
}

bool DeleteRegistryInstall(std::wstring* error) {
  bool ok = true;
  DWORD code = ::RegDeleteTreeW(HKEY_CURRENT_USER, kRegistryUninstallKey);
  if (code != ERROR_SUCCESS && code != ERROR_FILE_NOT_FOUND && code != ERROR_PATH_NOT_FOUND) {
    ok = false;
    *error = Format(L"删除注册表键失败 %s：%s", kRegistryUninstallKey, Win32ErrorMessage(code).c_str());
  }
  code = ::RegDeleteTreeW(HKEY_CURRENT_USER, kRegistryProductKey);
  if (code != ERROR_SUCCESS && code != ERROR_FILE_NOT_FOUND && code != ERROR_PATH_NOT_FOUND) {
    ok = false;
    if (error->empty()) {
      *error = Format(L"删除注册表键失败 %s：%s", kRegistryProductKey,
                      Win32ErrorMessage(code).c_str());
    }
  }
  // 父键空了就顺手删掉，失败无所谓。
  ::RegDeleteKeyW(HKEY_CURRENT_USER, L"Software\\MagicJudge");
  return ok;
}

bool DetectInstall(InstallInfo* info) {
  *info = InstallInfo();
  ReadRegistryInstall(info);

  struct Candidate {
    std::wstring path;
    const wchar_t* source;
  };
  std::vector<Candidate> candidates;
  Candidate current;
  current.path = ExeDirectory();
  current.source = L"current-dir";
  candidates.push_back(current);
  Candidate programFiles;
  programFiles.path = ProgramFilesCandidate();
  programFiles.source = L"program-files";
  candidates.push_back(programFiles);
  Candidate fromRegistry;
  fromRegistry.path = info->registryInstallLocation;
  fromRegistry.source = L"registry";
  candidates.push_back(fromRegistry);

  for (size_t index = 0; index < candidates.size(); ++index) {
    if (candidates[index].path.empty()) {
      continue;
    }
    if (FileExists(JoinPath(candidates[index].path, kAppExeName))) {
      info->found = true;
      info->source = candidates[index].source;
      info->installDir = TrimTrailingSlash(candidates[index].path);
      break;
    }
  }
  if (!info->found && info->registryFound && !info->registryInstallLocation.empty()) {
    info->found = true;
    info->source = L"registry";
    info->installDir = TrimTrailingSlash(info->registryInstallLocation);
  }
  if (info->found) {
    if (info->version.empty()) {
      info->version = info->registryVersion;
    }
    if (info->updaterPath.empty()) {
      info->updaterPath = JoinPath(info->installDir, kUpdaterExeName);
    }
    if (info->displayName.empty()) {
      info->displayName = kDisplayName;
    }
  }
  return info->found;
}

// ==== 计划任务 ====

bool QueryUpdaterTask(std::string* rawOutput, bool* exists, std::wstring* error) {
  const std::wstring commandLine =
      L"schtasks.exe /Query /TN " + QuoteArgument(kTaskName) + L" /XML";
  ProcessResult result;
  if (!RunProcess(commandLine, 60000, true, &result, error)) {
    return false;
  }
  if (rawOutput != nullptr) {
    *rawOutput = result.output;
  }
  if (exists != nullptr) {
    *exists = result.exitCode == 0;
  }
  return true;
}

bool UpdaterTaskReady(std::wstring* error) {
  std::wstring localError;
  if (error == nullptr) {
    error = &localError;
  }
  std::string output;
  bool exists = false;
  if (!QueryUpdaterTask(&output, &exists, error)) {
    return false;
  }
  if (!exists) {
    return false;
  }
  const std::wstring text = DecodeConsoleOutput(output);
  if (ContainsI(text, InstalledUpdaterPath()) && ContainsI(text, L"--task-entry")) {
    return true;
  }
  // schtasks 的输出按控制台代码页编码；用户名含中文时整条路径可能被毁掉，
  // 那就只认「MagicJudge\Updater.exe + --task-entry」这个组合。
  return ContainsAsciiI(output, "magicjudge\\updater.exe") &&
         ContainsAsciiI(output, "--task-entry");
}

bool CreateUpdaterTask(const std::wstring& updaterPath, std::wstring* error) {
  const std::wstring action = QuoteArgument(updaterPath) + L" --task-entry";
  const std::wstring commandLine = L"schtasks.exe /Create /F /RL HIGHEST /SC ONCE /ST 00:00 /TN " +
                                   QuoteArgument(kTaskName) + L" /TR " + QuoteArgument(action);
  ProcessResult result;
  if (!RunProcess(commandLine, 60000, true, &result, error)) {
    return false;
  }
  if (result.exitCode != 0) {
    const std::wstring output = Trim(DecodeConsoleOutput(result.output));
    *error = Format(L"创建计划任务 %s 失败（schtasks 返回 %u）%s%s", kTaskName,
                    static_cast<unsigned int>(result.exitCode),
                    output.empty() ? L"" : L"：", output.c_str());
    return false;
  }
  return true;
}

bool RunUpdaterTask(std::wstring* error) {
  const std::wstring commandLine = L"schtasks.exe /Run /TN " + QuoteArgument(kTaskName);
  ProcessResult result;
  if (!RunProcess(commandLine, 60000, true, &result, error)) {
    return false;
  }
  if (result.exitCode != 0) {
    const std::wstring output = Trim(DecodeConsoleOutput(result.output));
    *error = Format(L"启动计划任务 %s 失败（schtasks 返回 %u）%s%s", kTaskName,
                    static_cast<unsigned int>(result.exitCode),
                    output.empty() ? L"" : L"：", output.c_str());
    return false;
  }
  return true;
}

bool DeleteUpdaterTask(std::wstring* error) {
  const std::wstring commandLine =
      L"schtasks.exe /Delete /F /TN " + QuoteArgument(kTaskName);
  ProcessResult result;
  if (!RunProcess(commandLine, 60000, true, &result, error)) {
    return false;
  }
  // 任务本来就不存在也算成功。
  if (result.exitCode != 0) {
    const std::wstring output = DecodeConsoleOutput(result.output);
    if (ContainsI(output, L"找不到") || ContainsAsciiI(result.output, "cannot find") ||
        ContainsAsciiI(result.output, "not exist")) {
      return true;
    }
    *error = Format(L"删除计划任务 %s 失败（schtasks 返回 %u）：%s", kTaskName,
                    static_cast<unsigned int>(result.exitCode), Trim(output).c_str());
    return false;
  }
  return true;
}

// ==== 证书 ====

bool CertificateEmbedded() { return kSelfSignedCertLength > 0; }

std::wstring CertificateSha256() {
  if (!CertificateEmbedded()) {
    return std::wstring();
  }
  if (kSelfSignedCertSha256[0] != '\0') {
    return Utf8ToWide(kSelfSignedCertSha256);
  }
  std::string hex;
  std::wstring error;
  if (!Sha256Bytes(kSelfSignedCertBytes, kSelfSignedCertLength, &hex, &error)) {
    return std::wstring();
  }
  return Utf8ToWide(hex);
}

CertState CheckCertificate(std::wstring* error) {
  std::wstring localError;
  if (error == nullptr) {
    error = &localError;
  }
  if (!CertificateEmbedded()) {
    return CertState::NotEmbedded;
  }
  std::string hex;
  if (!Sha256Bytes(kSelfSignedCertBytes, kSelfSignedCertLength, &hex, error)) {
    return CertState::NeedsInstall;
  }
  // 打不开存储（例如没提权）也当作「需要安装」，交给提权流程去处理。
  std::wstring storeError;
  const bool inRoot = StoreHasCertificate(L"ROOT", hex, &storeError);
  const bool inPublisher = StoreHasCertificate(L"TrustedPublisher", hex, &storeError);
  if (inRoot && inPublisher) {
    return CertState::Trusted;
  }
  return CertState::NeedsInstall;
}

bool InstallCertificate(std::wstring* error) {
  std::wstring localError;
  if (error == nullptr) {
    error = &localError;
  }
  if (!CertificateEmbedded()) {
    *error = L"没有内嵌的自签名证书（请先运行 tools/sign-windows.ps1 再重新编译）";
    return false;
  }
  if (!AddCertificateToStore(L"ROOT", kSelfSignedCertBytes, kSelfSignedCertLength, error)) {
    return false;
  }
  if (!AddCertificateToStore(L"TrustedPublisher", kSelfSignedCertBytes, kSelfSignedCertLength,
                             error)) {
    return false;
  }
  return true;
}

// ==== 其它 ====

bool UpdaterCopyIsCurrent() {
  const std::wstring source = ExePath();
  const std::wstring target = InstalledUpdaterPath();
  if (_wcsicmp(source.c_str(), target.c_str()) == 0) {
    return true;
  }
  if (!FileExists(target) || FileSizeOf(target) != FileSizeOf(source)) {
    return false;
  }
  std::string sourceHash;
  std::string targetHash;
  std::wstring hashError;
  return Sha256File(source, &sourceHash, &hashError) &&
         Sha256File(target, &targetHash, &hashError) && HexEqualI(sourceHash, targetHash);
}

bool EnsureInstalledUpdaterCopy(std::wstring* error) {
  const std::wstring source = ExePath();
  const std::wstring target = InstalledUpdaterPath();
  if (_wcsicmp(source.c_str(), target.c_str()) == 0) {
    return true;
  }
  if (!EnsureDir(DirectoryOf(target), error)) {
    return false;
  }
  bool sameContent = false;
  if (FileExists(target) && FileSizeOf(target) == FileSizeOf(source)) {
    // 只看大小不够：同尺寸的不同构建也要覆盖（比较 SHA-256）。
    std::string sourceHash;
    std::string targetHash;
    std::wstring hashError;
    sameContent = Sha256File(source, &sourceHash, &hashError) &&
                  Sha256File(target, &targetHash, &hashError) &&
                  HexEqualI(sourceHash, targetHash);
  }
  if (sameContent) {
    return true;
  }
  if (!::CopyFileW(LongPath(source).c_str(), LongPath(target).c_str(), FALSE)) {
    const DWORD code = ::GetLastError();
    if (code == ERROR_SHARING_VIOLATION || code == ERROR_ACCESS_DENIED) {
      // 旧副本正在被计划任务跑着，换不掉也不算致命：下次更新会替换它。
      LogFormat(L"%s 正在使用中，暂时无法刷新（%s）", target.c_str(),
                Win32ErrorMessage(code).c_str());
      return true;
    }
    *error = Format(L"复制 Updater 到 %s 失败：%s", target.c_str(), Win32ErrorMessage(code).c_str());
    return false;
  }
  LogFormat(L"已把 Updater 复制到 %s", target.c_str());
  return true;
}

bool StopProcessByImagePath(const std::wstring& imagePath, int* stopped, std::wstring* error) {
  if (stopped != nullptr) {
    *stopped = 0;
  }
  const std::wstring wanted = TrimTrailingSlash(imagePath);
  const std::wstring imageName = FileNameOf(wanted);
  const HANDLE snapshot = ::CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
  if (snapshot == INVALID_HANDLE_VALUE) {
    *error = Format(L"枚举进程失败：%s", Win32ErrorMessage(::GetLastError()).c_str());
    return false;
  }
  PROCESSENTRY32W entry{};
  entry.dwSize = sizeof(entry);
  bool ok = true;
  if (::Process32FirstW(snapshot, &entry)) {
    do {
      if (_wcsicmp(entry.szExeFile, imageName.c_str()) != 0) {
        continue;
      }
      const HANDLE process = ::OpenProcess(
          PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_TERMINATE | SYNCHRONIZE, FALSE,
          entry.th32ProcessID);
      if (process == nullptr) {
        continue;
      }
      std::vector<wchar_t> buffer(MAX_PATH * 4);
      DWORD size = static_cast<DWORD>(buffer.size());
      if (::QueryFullProcessImageNameW(process, 0, buffer.data(), &size) &&
          _wcsicmp(TrimTrailingSlash(std::wstring(buffer.data(), size)).c_str(), wanted.c_str()) ==
              0) {
        if (::TerminateProcess(process, 0)) {
          ::WaitForSingleObject(process, 5000);
          if (stopped != nullptr) {
            *stopped = *stopped + 1;
          }
        } else {
          ok = false;
          *error = Format(L"结束进程失败 %s：%s", buffer.data(),
                          Win32ErrorMessage(::GetLastError()).c_str());
        }
      }
      ::CloseHandle(process);
    } while (::Process32NextW(snapshot, &entry));
  }
  ::CloseHandle(snapshot);
  return ok;
}

bool DirectoryIsWritable(const std::wstring& dir) {
  std::wstring error;
  if (!EnsureDir(dir, &error)) {
    return false;
  }
  const std::wstring probe = JoinPath(dir, L".magicjudge-write-probe");
  const HANDLE file = ::CreateFileW(LongPath(probe).c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS,
                                    FILE_ATTRIBUTE_TEMPORARY | FILE_FLAG_DELETE_ON_CLOSE, nullptr);
  if (file == INVALID_HANDLE_VALUE) {
    return false;
  }
  ::CloseHandle(file);
  return true;
}

std::vector<std::wstring> PersistentDataDirs() {
  std::vector<std::wstring> dirs;
  const std::wstring roaming = RoamingAppDataDir();
  const std::wstring local = LocalAppDataDir();
  dirs.push_back(JoinPath(roaming, L"魔法裁判"));
  dirs.push_back(JoinPath(local, L"魔法裁判"));
  dirs.push_back(JoinPath(roaming, L"seven_double_client"));
  dirs.push_back(JoinPath(local, L"seven_double_client"));
  return dirs;
}

}  // namespace upd
