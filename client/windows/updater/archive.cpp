#include "archive.h"

#include "common.h"

namespace upd {
namespace {

// 解压超时：更新包可能上百 MB，给足 20 分钟。
constexpr DWORD kExtractTimeoutMs = 20 * 60 * 1000;

std::wstring SystemDirectory() {
  std::vector<wchar_t> buffer(MAX_PATH);
  for (;;) {
    const UINT written = ::GetSystemDirectoryW(buffer.data(), static_cast<UINT>(buffer.size()));
    if (written == 0) {
      return L"C:\\Windows\\System32";
    }
    if (written < buffer.size()) {
      return std::wstring(buffer.data(), written);
    }
    buffer.resize(buffer.size() * 2);
  }
}

std::wstring PowerShellPath() {
  std::vector<wchar_t> buffer(MAX_PATH);
  for (;;) {
    const DWORD written = ::SearchPathW(nullptr, L"powershell.exe", nullptr,
                                        static_cast<DWORD>(buffer.size()), buffer.data(), nullptr);
    if (written == 0) {
      return std::wstring();
    }
    if (written < buffer.size()) {
      return std::wstring(buffer.data(), written);
    }
    buffer.resize(buffer.size() * 2);
  }
}

bool TryTar(const std::wstring& archivePath, const std::wstring& destination, std::wstring* error) {
  const std::wstring tar = JoinPath(SystemDirectory(), L"tar.exe");
  if (!FileExists(tar)) {
    *error = Format(L"未找到 %s", tar.c_str());
    return false;
  }
  const std::wstring commandLine = QuoteArgument(tar) + L" -xf " + QuoteArgument(archivePath) +
                                   L" -C " + QuoteArgument(destination);
  ProcessResult result;
  std::wstring runError;
  if (!RunProcess(commandLine, kExtractTimeoutMs, true, &result, &runError)) {
    *error = Format(L"tar 解压失败：%s", runError.c_str());
    return false;
  }
  if (result.exitCode != 0) {
    const std::wstring output = Trim(Utf8ToWide(result.output));
    *error = Format(L"tar 解压返回 %u%s%s", static_cast<unsigned int>(result.exitCode),
                    output.empty() ? L"" : L"：", output.c_str());
    return false;
  }
  return true;
}

bool TryExpandArchive(const std::wstring& archivePath, const std::wstring& destination,
                      std::wstring* error) {
  const std::wstring powershell = PowerShellPath();
  if (powershell.empty()) {
    *error = L"未找到 powershell.exe";
    return false;
  }
  // 单引号路径里把 ' 变成 ''；我们自己的路径不会有引号，这里只是防御。
  std::wstring archiveForShell;
  for (size_t index = 0; index < archivePath.size(); ++index) {
    archiveForShell.push_back(archivePath[index]);
    if (archivePath[index] == L'\'') {
      archiveForShell.push_back(L'\'');
    }
  }
  std::wstring destinationForShell;
  for (size_t index = 0; index < destination.size(); ++index) {
    destinationForShell.push_back(destination[index]);
    if (destination[index] == L'\'') {
      destinationForShell.push_back(L'\'');
    }
  }
  const std::wstring script = L"$ErrorActionPreference='Stop'; Expand-Archive -LiteralPath '" +
                              archiveForShell + L"' -DestinationPath '" + destinationForShell +
                              L"' -Force";
  const std::wstring commandLine = QuoteArgument(powershell) +
                                   L" -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command " +
                                   QuoteArgument(script);
  ProcessResult result;
  std::wstring runError;
  if (!RunProcess(commandLine, kExtractTimeoutMs, true, &result, &runError)) {
    *error = Format(L"Expand-Archive 解压失败：%s", runError.c_str());
    return false;
  }
  if (result.exitCode != 0) {
    const std::wstring output = Trim(Utf8ToWide(result.output));
    *error = Format(L"Expand-Archive 返回 %u%s%s", static_cast<unsigned int>(result.exitCode),
                    output.empty() ? L"" : L"：", output.c_str());
    return false;
  }
  return true;
}

}  // namespace

bool ExtractArchive(const std::wstring& archivePath, const std::wstring& destination,
                    std::wstring* error) {
  if (!FileExists(archivePath)) {
    *error = Format(L"更新包不存在：%s", archivePath.c_str());
    return false;
  }
  if (!EnsureDir(destination, error)) {
    return false;
  }
  std::wstring tarError;
  if (TryTar(archivePath, destination, &tarError)) {
    return true;
  }
  LogFormat(L"tar 解压不可用（%s），改用 Expand-Archive", tarError.c_str());
  std::wstring powerShellError;
  if (TryExpandArchive(archivePath, destination, &powerShellError)) {
    return true;
  }
  *error = Format(L"解压失败：%s；备用方式也失败：%s", tarError.c_str(), powerShellError.c_str());
  return false;
}

}  // namespace upd
