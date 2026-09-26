#include "common.h"

#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cwchar>

namespace upd {
namespace {

HANDLE g_console = INVALID_HANDLE_VALUE;
bool g_consoleIsConsole = false;
bool g_consoleReady = false;
std::wstring g_logPath;

CRITICAL_SECTION& Lock() {
  static CRITICAL_SECTION* lock = nullptr;
  if (lock == nullptr) {
    lock = new CRITICAL_SECTION();
    ::InitializeCriticalSection(lock);
  }
  return *lock;
}

void SetError(std::wstring* error, const std::wstring& text) {
  if (error != nullptr) {
    *error = text;
  }
}

void Fail(std::wstring* error, const std::wstring& prefix) {
  const DWORD code = ::GetLastError();
  SetError(error, Format(L"%s：%s（错误码 %u）", prefix.c_str(), Win32ErrorMessage(code).c_str(),
                         static_cast<unsigned int>(code)));
}

bool IsSlash(wchar_t character) { return character == L'\\' || character == L'/'; }

void EnsureConsole() {
  if (g_consoleReady) {
    return;
  }
  g_consoleReady = true;
  // 1) 输出被重定向到文件或管道：直接用继承来的句柄，按 UTF-8 写字节。
  const HANDLE inherited = ::GetStdHandle(STD_OUTPUT_HANDLE);
  if (inherited != nullptr && inherited != INVALID_HANDLE_VALUE) {
    const DWORD type = ::GetFileType(inherited);
    if (type == FILE_TYPE_DISK || type == FILE_TYPE_PIPE) {
      g_console = inherited;
      g_consoleIsConsole = false;
      return;
    }
  }
  // 2) 从 cmd/PowerShell 启动：接上父进程的控制台，用 WriteConsoleW 写宽字符。
  if (::GetConsoleWindow() == nullptr) {
    ::AttachConsole(ATTACH_PARENT_PROCESS);
  }
  if (::GetConsoleWindow() != nullptr) {
    const HANDLE console =
        ::CreateFileW(L"CONOUT$", GENERIC_WRITE, FILE_SHARE_WRITE | FILE_SHARE_READ, nullptr,
                      OPEN_EXISTING, 0, nullptr);
    if (console != INVALID_HANDLE_VALUE) {
      g_console = console;
      g_consoleIsConsole = true;
    }
  }
}

}  // namespace

// ==== 字符串 ====

std::wstring Format(const wchar_t* format, ...) {
  wchar_t buffer[4096];
  buffer[0] = L'\0';
  va_list arguments;
  va_start(arguments, format);
  const int written = _vsnwprintf_s(buffer, _countof(buffer), _TRUNCATE, format, arguments);
  va_end(arguments);
  if (written < 0) {
    // 被截断：buffer 仍是合法的、以 NUL 结尾的字符串。
    return std::wstring(buffer);
  }
  return std::wstring(buffer, static_cast<size_t>(written));
}

std::wstring Utf8ToWide(const std::string& text) {
  if (text.empty()) {
    return std::wstring();
  }
  const int capacity = ::MultiByteToWideChar(CP_UTF8, 0, text.data(), static_cast<int>(text.size()),
                                             nullptr, 0);
  if (capacity <= 0) {
    return std::wstring();
  }
  std::wstring result(static_cast<size_t>(capacity), L'\0');
  ::MultiByteToWideChar(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), result.data(),
                        capacity);
  return result;
}

std::string WideToUtf8(const std::wstring& text) {
  if (text.empty()) {
    return std::string();
  }
  const int capacity = ::WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()),
                                             nullptr, 0, nullptr, nullptr);
  if (capacity <= 0) {
    return std::string();
  }
  std::string result(static_cast<size_t>(capacity), '\0');
  ::WideCharToMultiByte(CP_UTF8, 0, text.data(), static_cast<int>(text.size()), result.data(),
                        capacity, nullptr, nullptr);
  return result;
}

std::wstring ToLower(const std::wstring& text) {
  std::wstring result = text;
  if (!result.empty()) {
    ::CharLowerBuffW(result.data(), static_cast<DWORD>(result.size()));
  }
  return result;
}

bool StartsWithI(const std::wstring& text, const std::wstring& prefix) {
  if (text.size() < prefix.size()) {
    return false;
  }
  return _wcsnicmp(text.c_str(), prefix.c_str(), prefix.size()) == 0;
}

bool EndsWithI(const std::wstring& text, const std::wstring& suffix) {
  if (text.size() < suffix.size()) {
    return false;
  }
  return _wcsnicmp(text.c_str() + (text.size() - suffix.size()), suffix.c_str(), suffix.size()) == 0;
}

bool ContainsI(const std::wstring& text, const std::wstring& needle) {
  if (needle.empty()) {
    return true;
  }
  const std::wstring loweredText = ToLower(text);
  const std::wstring loweredNeedle = ToLower(needle);
  return loweredText.find(loweredNeedle) != std::wstring::npos;
}

bool ContainsAsciiI(const std::string& text, const char* needle) {
  if (needle == nullptr || needle[0] == '\0') {
    return true;
  }
  const size_t needleLength = ::strlen(needle);
  if (text.size() < needleLength) {
    return false;
  }
  for (size_t index = 0; index + needleLength <= text.size(); ++index) {
    bool matched = true;
    for (size_t offset = 0; offset < needleLength; ++offset) {
      char left = text[index + offset];
      char right = needle[offset];
      if (left >= 'A' && left <= 'Z') {
        left = static_cast<char>(left - 'A' + 'a');
      }
      if (right >= 'A' && right <= 'Z') {
        right = static_cast<char>(right - 'A' + 'a');
      }
      if (left != right) {
        matched = false;
        break;
      }
    }
    if (matched) {
      return true;
    }
  }
  return false;
}

std::wstring Trim(const std::wstring& text) {
  size_t begin = 0;
  size_t end = text.size();
  while (begin < end && (text[begin] == L' ' || text[begin] == L'\t' || text[begin] == L'\r' ||
                         text[begin] == L'\n')) {
    ++begin;
  }
  while (end > begin && (text[end - 1] == L' ' || text[end - 1] == L'\t' || text[end - 1] == L'\r' ||
                         text[end - 1] == L'\n')) {
    --end;
  }
  return text.substr(begin, end - begin);
}

std::wstring BytesToHex(const unsigned char* data, size_t length) {
  static const wchar_t kDigits[] = L"0123456789abcdef";
  std::wstring text;
  text.reserve(length * 2);
  for (size_t index = 0; index < length; ++index) {
    text.push_back(kDigits[(data[index] >> 4) & 0x0F]);
    text.push_back(kDigits[data[index] & 0x0F]);
  }
  return text;
}

std::string BytesToHexAscii(const unsigned char* data, size_t length) {
  static const char kDigits[] = "0123456789abcdef";
  std::string text;
  text.reserve(length * 2);
  for (size_t index = 0; index < length; ++index) {
    text.push_back(kDigits[(data[index] >> 4) & 0x0F]);
    text.push_back(kDigits[data[index] & 0x0F]);
  }
  return text;
}

bool HexEqualI(const std::string& left, const std::string& right) {
  if (left.size() != right.size() || left.empty()) {
    return false;
  }
  for (size_t index = 0; index < left.size(); ++index) {
    char a = left[index];
    char b = right[index];
    if (a >= 'A' && a <= 'F') {
      a = static_cast<char>(a - 'A' + 'a');
    }
    if (b >= 'A' && b <= 'F') {
      b = static_cast<char>(b - 'A' + 'a');
    }
    if (a != b) {
      return false;
    }
  }
  return true;
}

bool ParseUnsigned(const std::wstring& text, unsigned long long* value) {
  const std::wstring trimmed = Trim(text);
  if (trimmed.empty() || value == nullptr) {
    return false;
  }
  unsigned long long result = 0;
  for (size_t index = 0; index < trimmed.size(); ++index) {
    const wchar_t character = trimmed[index];
    if (character < L'0' || character > L'9') {
      return false;
    }
    result = result * 10 + static_cast<unsigned long long>(character - L'0');
  }
  *value = result;
  return true;
}

bool ParseDword(const std::wstring& text, DWORD* value) {
  unsigned long long parsed = 0;
  if (!ParseUnsigned(text, &parsed) || value == nullptr) {
    return false;
  }
  *value = static_cast<DWORD>(parsed);
  return true;
}

std::wstring HexToText(const std::string& hex) {
  std::wstring text;
  const std::wstring wide = Utf8ToWide(hex);
  for (size_t index = 0; index + 1 < wide.size(); index += 2) {
    const wchar_t high = wide[index];
    const wchar_t low = wide[index + 1];
    int left = -1;
    int right = -1;
    if (high >= L'0' && high <= L'9') {
      left = static_cast<int>(high - L'0');
    } else if (high >= L'a' && high <= L'f') {
      left = static_cast<int>(high - L'a') + 10;
    } else if (high >= L'A' && high <= L'F') {
      left = static_cast<int>(high - L'A') + 10;
    }
    if (low >= L'0' && low <= L'9') {
      right = static_cast<int>(low - L'0');
    } else if (low >= L'a' && low <= L'f') {
      right = static_cast<int>(low - L'a') + 10;
    } else if (low >= L'A' && low <= L'F') {
      right = static_cast<int>(low - L'A') + 10;
    }
    if (left < 0 || right < 0) {
      return std::wstring();
    }
    text.push_back(static_cast<wchar_t>(left * 16 + right));
  }
  return text;
}

// ==== 路径 ====

std::wstring ExePath() {
  std::vector<wchar_t> buffer(MAX_PATH);
  for (;;) {
    const DWORD written =
        ::GetModuleFileNameW(nullptr, buffer.data(), static_cast<DWORD>(buffer.size()));
    if (written == 0) {
      return std::wstring();
    }
    if (written < buffer.size()) {
      return std::wstring(buffer.data(), written);
    }
    buffer.resize(buffer.size() * 2);
  }
}

std::wstring ExeDirectory() { return DirectoryOf(ExePath()); }

std::wstring CurrentDirectory() {
  std::vector<wchar_t> buffer(MAX_PATH);
  for (;;) {
    const DWORD written = ::GetCurrentDirectoryW(static_cast<DWORD>(buffer.size()), buffer.data());
    if (written == 0) {
      return std::wstring();
    }
    if (written < buffer.size()) {
      return std::wstring(buffer.data(), written);
    }
    buffer.resize(buffer.size() * 2);
  }
}

std::wstring LocalAppDataDir() {
  std::vector<wchar_t> buffer(MAX_PATH);
  for (;;) {
    const DWORD written =
        ::GetEnvironmentVariableW(L"LOCALAPPDATA", buffer.data(), static_cast<DWORD>(buffer.size()));
    if (written == 0) {
      return ExeDirectory();
    }
    if (written < buffer.size()) {
      return std::wstring(buffer.data(), written);
    }
    buffer.resize(buffer.size() * 2);
  }
}

std::wstring RoamingAppDataDir() {
  std::vector<wchar_t> buffer(MAX_PATH);
  for (;;) {
    const DWORD written =
        ::GetEnvironmentVariableW(L"APPDATA", buffer.data(), static_cast<DWORD>(buffer.size()));
    if (written == 0) {
      return ExeDirectory();
    }
    if (written < buffer.size()) {
      return std::wstring(buffer.data(), written);
    }
    buffer.resize(buffer.size() * 2);
  }
}

std::wstring ProgramFilesDir() {
  std::vector<wchar_t> buffer(MAX_PATH);
  for (;;) {
    const DWORD written = ::GetEnvironmentVariableW(L"ProgramFiles", buffer.data(),
                                                    static_cast<DWORD>(buffer.size()));
    if (written == 0) {
      return L"C:\\Program Files";
    }
    if (written < buffer.size()) {
      return std::wstring(buffer.data(), written);
    }
    buffer.resize(buffer.size() * 2);
  }
}

std::wstring ProductLocalDir() { return JoinPath(LocalAppDataDir(), kProductDirName); }

std::wstring DownloadsDir() { return JoinPath(ProductLocalDir(), L"downloads"); }

std::wstring JobFilePath() { return JoinPath(ProductLocalDir(), L"job.json"); }

std::wstring LogFilePath() { return JoinPath(ProductLocalDir(), L"update.log"); }

std::wstring InstalledUpdaterPath() { return JoinPath(ProductLocalDir(), kUpdaterExeName); }

std::wstring JoinPath(const std::wstring& base, const std::wstring& child) {
  if (base.empty()) {
    return child;
  }
  if (child.empty()) {
    return base;
  }
  std::wstring result = base;
  if (!IsSlash(result.back())) {
    result.push_back(L'\\');
  }
  size_t begin = 0;
  while (begin < child.size() && IsSlash(child[begin])) {
    ++begin;
  }
  result.append(child, begin, child.size() - begin);
  return result;
}

std::wstring FileNameOf(const std::wstring& path) {
  const size_t position = path.find_last_of(L"\\/");
  if (position == std::wstring::npos) {
    return path;
  }
  return path.substr(position + 1);
}

std::wstring DirectoryOf(const std::wstring& path) {
  const size_t position = path.find_last_of(L"\\/");
  if (position == std::wstring::npos) {
    return std::wstring();
  }
  if (position == 0) {
    return path.substr(0, 1);
  }
  return path.substr(0, position);
}

std::wstring TrimTrailingSlash(const std::wstring& path) {
  std::wstring result = path;
  while (result.size() > 3 && IsSlash(result.back())) {
    result.pop_back();
  }
  return result;
}

std::wstring LongPath(const std::wstring& path) {
  if (path.size() >= 4 && path.compare(0, 4, L"\\\\?\\") == 0) {
    return path;
  }
  if (path.size() < 240) {
    return path;
  }
  if (path.size() >= 2 && path[1] == L':') {
    return L"\\\\?\\" + path;
  }
  if (path.compare(0, 2, L"\\\\") == 0) {
    return L"\\\\?\\UNC\\" + path.substr(2);
  }
  return path;
}

std::wstring QuoteArgument(const std::wstring& value) {
  std::wstring result = L"\"";
  size_t backslashes = 0;
  for (size_t index = 0; index < value.size(); ++index) {
    const wchar_t character = value[index];
    if (character == L'\\') {
      ++backslashes;
      continue;
    }
    if (character == L'"') {
      result.append(backslashes * 2 + 1, L'\\');
      result.push_back(L'"');
      backslashes = 0;
      continue;
    }
    result.append(backslashes, L'\\');
    backslashes = 0;
    result.push_back(character);
  }
  result.append(backslashes * 2, L'\\');
  result.push_back(L'"');
  return result;
}

// ==== 文件 ====

bool PathExists(const std::wstring& path) {
  const DWORD attributes = ::GetFileAttributesW(LongPath(path).c_str());
  return attributes != INVALID_FILE_ATTRIBUTES;
}

bool FileExists(const std::wstring& path) {
  const DWORD attributes = ::GetFileAttributesW(LongPath(path).c_str());
  return attributes != INVALID_FILE_ATTRIBUTES && (attributes & FILE_ATTRIBUTE_DIRECTORY) == 0;
}

bool DirExists(const std::wstring& path) {
  const DWORD attributes = ::GetFileAttributesW(LongPath(path).c_str());
  return attributes != INVALID_FILE_ATTRIBUTES && (attributes & FILE_ATTRIBUTE_DIRECTORY) != 0;
}

bool EnsureDir(const std::wstring& path, std::wstring* error) {
  const std::wstring target = TrimTrailingSlash(path);
  if (target.empty()) {
    SetError(error, L"目录为空");
    return false;
  }
  if (DirExists(target)) {
    return true;
  }
  std::wstring current;
  size_t index = 0;
  if (target.size() >= 2 && target[1] == L':') {
    current = target.substr(0, 2);
    index = 2;
  }
  for (; index <= target.size(); ++index) {
    if (index == target.size() || IsSlash(target[index])) {
      const bool driveOnly = !current.empty() && current.back() == L':';
      if (!current.empty() && !driveOnly) {
        if (!::CreateDirectoryW(LongPath(current).c_str(), nullptr)) {
          const DWORD code = ::GetLastError();
          if (code != ERROR_ALREADY_EXISTS) {
            SetError(error, Format(L"创建目录失败 %s：%s", current.c_str(),
                                   Win32ErrorMessage(code).c_str()));
            return false;
          }
        }
      }
      if (index < target.size()) {
        current.push_back(L'\\');
      }
    } else {
      current.push_back(target[index]);
    }
  }
  return true;
}

bool DeleteFileIfExists(const std::wstring& path, std::wstring* error) {
  if (!FileExists(path)) {
    return true;
  }
  ::SetFileAttributesW(LongPath(path).c_str(), FILE_ATTRIBUTE_NORMAL);
  if (!::DeleteFileW(LongPath(path).c_str())) {
    if (error != nullptr) {
      *error = Format(L"删除文件失败 %s：%s", path.c_str(), Win32ErrorMessage(::GetLastError()).c_str());
    }
    return false;
  }
  return true;
}

bool DeleteTree(const std::wstring& root, const std::wstring& skipFilePath, std::wstring* error) {
  if (!DirExists(root)) {
    return true;
  }
  bool ok = true;
  std::wstring firstError;
  WIN32_FIND_DATAW data{};
  const std::wstring pattern = JoinPath(root, L"*");
  const HANDLE find = ::FindFirstFileW(LongPath(pattern).c_str(), &data);
  if (find != INVALID_HANDLE_VALUE) {
    do {
      const std::wstring name = data.cFileName;
      if (name == L"." || name == L"..") {
        continue;
      }
      const std::wstring child = JoinPath(root, name);
      if (!skipFilePath.empty() && _wcsicmp(child.c_str(), skipFilePath.c_str()) == 0) {
        continue;
      }
      if ((data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) != 0) {
        if ((data.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0) {
          ::RemoveDirectoryW(LongPath(child).c_str());
          continue;
        }
        std::wstring childError;
        if (!DeleteTree(child, skipFilePath, &childError)) {
          ok = false;
          if (firstError.empty()) {
            firstError = childError;
          }
        }
      } else {
        ::SetFileAttributesW(LongPath(child).c_str(), FILE_ATTRIBUTE_NORMAL);
        if (!::DeleteFileW(LongPath(child).c_str())) {
          ok = false;
          if (firstError.empty()) {
            firstError = Format(L"删除文件失败 %s：%s", child.c_str(),
                                Win32ErrorMessage(::GetLastError()).c_str());
          }
        }
      }
    } while (::FindNextFileW(find, &data) != FALSE);
    ::FindClose(find);
  }
  if (!::RemoveDirectoryW(LongPath(root).c_str())) {
    const DWORD code = ::GetLastError();
    if (code != ERROR_FILE_NOT_FOUND && code != ERROR_PATH_NOT_FOUND) {
      ok = false;
      if (firstError.empty()) {
        firstError = Format(L"删除目录失败 %s：%s", root.c_str(), Win32ErrorMessage(code).c_str());
      }
    }
  }
  if (!ok) {
    SetError(error, firstError);
  }
  return ok;
}

bool DeleteTreeContents(const std::wstring& root, const std::wstring& skipFilePath,
                        std::wstring* error) {
  if (!DirExists(root)) {
    return true;
  }
  bool ok = true;
  std::wstring firstError;
  WIN32_FIND_DATAW data{};
  const std::wstring pattern = JoinPath(root, L"*");
  const HANDLE find = ::FindFirstFileW(LongPath(pattern).c_str(), &data);
  if (find != INVALID_HANDLE_VALUE) {
    do {
      const std::wstring name = data.cFileName;
      if (name == L"." || name == L"..") {
        continue;
      }
      const std::wstring child = JoinPath(root, name);
      if (!skipFilePath.empty() && _wcsicmp(child.c_str(), skipFilePath.c_str()) == 0) {
        continue;
      }
      if ((data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) != 0) {
        std::wstring childError;
        if (!DeleteTree(child, skipFilePath, &childError)) {
          ok = false;
          if (firstError.empty()) {
            firstError = childError;
          }
        }
      } else {
        ::SetFileAttributesW(LongPath(child).c_str(), FILE_ATTRIBUTE_NORMAL);
        if (!::DeleteFileW(LongPath(child).c_str())) {
          ok = false;
          if (firstError.empty()) {
            firstError = Format(L"删除文件失败 %s：%s", child.c_str(),
                                Win32ErrorMessage(::GetLastError()).c_str());
          }
        }
      }
    } while (::FindNextFileW(find, &data) != FALSE);
    ::FindClose(find);
  }
  if (!ok) {
    SetError(error, firstError);
  }
  return ok;
}

bool CopyFileTo(const std::wstring& source, const std::wstring& destination, bool failIfExists,
                std::wstring* error) {
  const std::wstring parent = DirectoryOf(destination);
  if (!parent.empty() && !EnsureDir(parent, error)) {
    return false;
  }
  if (!::CopyFileW(LongPath(source).c_str(), LongPath(destination).c_str(), failIfExists ? TRUE : FALSE)) {
    const DWORD code = ::GetLastError();
    if (code == ERROR_FILE_EXISTS && !failIfExists) {
      return true;
    }
    SetError(error, Format(L"复制文件失败 %s → %s：%s", source.c_str(), destination.c_str(),
                           Win32ErrorMessage(code).c_str()));
    return false;
  }
  return true;
}

bool MoveFileTo(const std::wstring& source, const std::wstring& destination, bool replace,
                std::wstring* error) {
  DWORD flags = MOVEFILE_COPY_ALLOWED;
  if (replace) {
    flags |= MOVEFILE_REPLACE_EXISTING;
  }
  if (!::MoveFileExW(LongPath(source).c_str(), LongPath(destination).c_str(), flags)) {
    const DWORD code = ::GetLastError();
    SetError(error, Format(L"移动文件失败 %s → %s：%s", source.c_str(), destination.c_str(),
                           Win32ErrorMessage(code).c_str()));
    return false;
  }
  return true;
}

bool CopyTree(const std::wstring& source, const std::wstring& destination, std::wstring* error) {
  if (!DirExists(source)) {
    SetError(error, Format(L"源目录不存在：%s", source.c_str()));
    return false;
  }
  if (!EnsureDir(destination, error)) {
    return false;
  }
  const std::wstring pattern = JoinPath(source, L"*");
  WIN32_FIND_DATAW data{};
  const HANDLE find = ::FindFirstFileW(LongPath(pattern).c_str(), &data);
  if (find == INVALID_HANDLE_VALUE) {
    const DWORD code = ::GetLastError();
    if (code == ERROR_FILE_NOT_FOUND) {
      return true;  // 空目录
    }
    SetError(error, Format(L"枚举目录失败 %s：%s", source.c_str(), Win32ErrorMessage(code).c_str()));
    return false;
  }
  bool ok = true;
  std::wstring firstError;
  do {
    const std::wstring name = data.cFileName;
    if (name == L"." || name == L"..") {
      continue;
    }
    const std::wstring child = JoinPath(source, name);
    const std::wstring target = JoinPath(destination, name);
    if ((data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) != 0) {
      if ((data.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0) {
        continue;  // 不跟随符号链接
      }
      std::wstring childError;
      if (!CopyTree(child, target, &childError)) {
        ok = false;
        if (firstError.empty()) {
          firstError = childError;
        }
      }
      continue;
    }
    std::wstring childError;
    if (!CopyFileTo(child, target, false, &childError)) {
      ok = false;
      if (firstError.empty()) {
        firstError = childError;
      }
    }
  } while (::FindNextFileW(find, &data) != FALSE);
  ::FindClose(find);
  if (!ok) {
    SetError(error, firstError);
  }
  return ok;
}

bool ListTreeRelative(const std::wstring& root, std::vector<std::wstring>* files,
                      std::vector<std::wstring>* dirs, std::wstring* error) {
  std::vector<std::wstring> pending;
  pending.push_back(std::wstring());
  bool ok = true;
  while (!pending.empty()) {
    const std::wstring relative = pending.back();
    pending.pop_back();
    const std::wstring absolute = relative.empty() ? root : JoinPath(root, relative);
    WIN32_FIND_DATAW data{};
    const HANDLE find = ::FindFirstFileW(LongPath(JoinPath(absolute, L"*")).c_str(), &data);
    if (find == INVALID_HANDLE_VALUE) {
      const DWORD code = ::GetLastError();
      if (code == ERROR_FILE_NOT_FOUND) {
        continue;
      }
      SetError(error, Format(L"枚举目录失败 %s：%s", absolute.c_str(), Win32ErrorMessage(code).c_str()));
      ok = false;
      break;
    }
    do {
      const std::wstring name = data.cFileName;
      if (name == L"." || name == L"..") {
        continue;
      }
      const std::wstring childRelative = relative.empty() ? name : JoinPath(relative, name);
      if ((data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) != 0) {
        if (dirs != nullptr) {
          dirs->push_back(childRelative);
        }
        pending.push_back(childRelative);
      } else if (files != nullptr) {
        files->push_back(childRelative);
      }
    } while (::FindNextFileW(find, &data) != FALSE);
    ::FindClose(find);
  }
  return ok;
}

unsigned long long FileSizeOf(const std::wstring& path) {
  WIN32_FILE_ATTRIBUTE_DATA data{};
  if (!::GetFileAttributesExW(LongPath(path).c_str(), GetFileExInfoStandard, &data)) {
    return 0;
  }
  return (static_cast<unsigned long long>(data.nFileSizeHigh) << 32) |
         static_cast<unsigned long long>(data.nFileSizeLow);
}

std::wstring Win32ErrorMessage(DWORD code) {
  if (code == 0) {
    return std::wstring();
  }
  LPWSTR buffer = nullptr;
  const DWORD length = ::FormatMessageW(
      FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM | FORMAT_MESSAGE_IGNORE_INSERTS,
      nullptr, code, MAKELANGID(LANG_NEUTRAL, SUBLANG_DEFAULT),
      reinterpret_cast<LPWSTR>(&buffer), 0, nullptr);
  std::wstring message;
  if (length > 0 && buffer != nullptr) {
    message.assign(buffer, length);
    while (!message.empty() && (message.back() == L'\r' || message.back() == L'\n' ||
                                message.back() == L' ' || message.back() == L'.')) {
      message.pop_back();
    }
  }
  if (buffer != nullptr) {
    ::LocalFree(buffer);
  }
  if (message.empty()) {
    message = Format(L"错误码 %u", static_cast<unsigned int>(code));
  }
  return message;
}

bool WriteTextFileUtf8(const std::wstring& path, const std::string& text, std::wstring* error) {
  const std::wstring parent = DirectoryOf(path);
  if (!parent.empty() && !EnsureDir(parent, error)) {
    return false;
  }
  const HANDLE file = ::CreateFileW(LongPath(path).c_str(), GENERIC_WRITE, 0, nullptr, CREATE_ALWAYS,
                                    FILE_ATTRIBUTE_NORMAL, nullptr);
  if (file == INVALID_HANDLE_VALUE) {
    Fail(error, Format(L"写入文件失败 %s", path.c_str()));
    return false;
  }
  DWORD written = 0;
  const BOOL ok = ::WriteFile(file, text.data(), static_cast<DWORD>(text.size()), &written, nullptr);
  ::CloseHandle(file);
  if (ok == FALSE || written != static_cast<DWORD>(text.size())) {
    Fail(error, Format(L"写入文件不完整 %s", path.c_str()));
    return false;
  }
  return true;
}

bool ReadTextFileUtf8(const std::wstring& path, std::string* text, std::wstring* error) {
  const HANDLE file = ::CreateFileW(LongPath(path).c_str(), GENERIC_READ, FILE_SHARE_READ, nullptr,
                                    OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
  if (file == INVALID_HANDLE_VALUE) {
    Fail(error, Format(L"读取文件失败 %s", path.c_str()));
    return false;
  }
  std::string content;
  char buffer[8192];
  for (;;) {
    DWORD read = 0;
    if (!::ReadFile(file, buffer, sizeof(buffer), &read, nullptr)) {
      ::CloseHandle(file);
      Fail(error, Format(L"读取文件内容失败 %s", path.c_str()));
      return false;
    }
    if (read == 0) {
      break;
    }
    content.append(buffer, read);
  }
  ::CloseHandle(file);
  // 去掉 UTF-8 BOM。
  if (content.size() >= 3 && static_cast<unsigned char>(content[0]) == 0xEF &&
      static_cast<unsigned char>(content[1]) == 0xBB &&
      static_cast<unsigned char>(content[2]) == 0xBF) {
    content.erase(0, 3);
  }
  if (text != nullptr) {
    *text = content;
  }
  return true;
}

// ==== 控制台与日志 ====

void SetLogFile(const std::wstring& path) { g_logPath = path; }

void ConsoleWrite(const std::wstring& text) {
  if (text.empty()) {
    return;
  }
  EnsureConsole();
  if (g_console == INVALID_HANDLE_VALUE) {
    return;
  }
  ::EnterCriticalSection(&Lock());
  if (g_consoleIsConsole) {
    DWORD written = 0;
    ::WriteConsoleW(g_console, text.c_str(), static_cast<DWORD>(text.size()), &written, nullptr);
  } else {
    const std::string bytes = WideToUtf8(text);
    DWORD written = 0;
    ::WriteFile(g_console, bytes.data(), static_cast<DWORD>(bytes.size()), &written, nullptr);
  }
  ::LeaveCriticalSection(&Lock());
}

void ConsoleWriteLine(const std::wstring& text) { ConsoleWrite(text + L"\r\n"); }

void ConsoleFlush() {
  if (g_console != INVALID_HANDLE_VALUE && !g_consoleIsConsole) {
    ::FlushFileBuffers(g_console);
  }
}

void LogMessage(const std::wstring& text) {
  SYSTEMTIME now{};
  ::GetLocalTime(&now);
  const std::wstring line =
      Format(L"[%04u-%02u-%02u %02u:%02u:%02u] %s", static_cast<unsigned int>(now.wYear),
             static_cast<unsigned int>(now.wMonth), static_cast<unsigned int>(now.wDay),
             static_cast<unsigned int>(now.wHour), static_cast<unsigned int>(now.wMinute),
             static_cast<unsigned int>(now.wSecond), text.c_str());
  ConsoleWriteLine(line);
  ConsoleFlush();
  if (g_logPath.empty()) {
    return;
  }
  const std::wstring parent = DirectoryOf(g_logPath);
  if (!parent.empty()) {
    std::wstring ignored;
    EnsureDir(parent, &ignored);
  }
  const HANDLE file =
      ::CreateFileW(LongPath(g_logPath).c_str(), FILE_APPEND_DATA,
                    FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL,
                    nullptr);
  if (file == INVALID_HANDLE_VALUE) {
    return;
  }
  const std::string utf8 = WideToUtf8(line + L"\r\n");
  DWORD written = 0;
  ::WriteFile(file, utf8.data(), static_cast<DWORD>(utf8.size()), &written, nullptr);
  ::CloseHandle(file);
}

void LogFormat(const wchar_t* format, ...) {
  wchar_t buffer[4096];
  buffer[0] = L'\0';
  va_list arguments;
  va_start(arguments, format);
  const int written = _vsnwprintf_s(buffer, _countof(buffer), _TRUNCATE, format, arguments);
  va_end(arguments);
  if (written < 0) {
    LogMessage(std::wstring(buffer));
    return;
  }
  LogMessage(std::wstring(buffer, static_cast<size_t>(written)));
}

void LogError(const std::wstring& text) { LogMessage(std::wstring(L"错误：") + text); }

void ReportProgress(const ProgressSink* sink, int percent, const std::wstring& message) {
  if (sink != nullptr && sink->report != nullptr) {
    sink->report(sink->context, percent, message);
    return;
  }
  LogMessage(message);
}

// ==== 进程 ====

bool RunProcess(const std::wstring& commandLine, DWORD timeoutMs, bool captureOutput,
                ProcessResult* result, std::wstring* error) {
  if (result != nullptr) {
    *result = ProcessResult();
  }
  SECURITY_ATTRIBUTES attributes{};
  attributes.nLength = sizeof(attributes);
  attributes.bInheritHandle = TRUE;

  HANDLE readPipe = nullptr;
  HANDLE writePipe = nullptr;
  HANDLE nulHandle = INVALID_HANDLE_VALUE;
  if (captureOutput) {
    if (!::CreatePipe(&readPipe, &writePipe, &attributes, 0)) {
      Fail(error, L"创建管道失败");
      return false;
    }
    ::SetHandleInformation(readPipe, HANDLE_FLAG_INHERIT, 0);
  }

  STARTUPINFOW startup{};
  startup.cb = sizeof(startup);
  PROCESS_INFORMATION process{};
  startup.dwFlags = STARTF_USESHOWWINDOW;
  startup.wShowWindow = SW_HIDE;
  if (captureOutput) {
    nulHandle = ::CreateFileW(L"NUL", GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, &attributes,
                              OPEN_EXISTING, 0, nullptr);
    startup.dwFlags |= STARTF_USESTDHANDLES;
    startup.hStdOutput = writePipe;
    startup.hStdError = writePipe;
    startup.hStdInput = nulHandle;
  }

  std::vector<wchar_t> buffer(commandLine.begin(), commandLine.end());
  buffer.push_back(L'\0');
  const BOOL created = ::CreateProcessW(nullptr, buffer.data(), nullptr, nullptr, captureOutput ? TRUE : FALSE,
                                        CREATE_NO_WINDOW, nullptr, nullptr, &startup, &process);
  if (captureOutput) {
    ::CloseHandle(writePipe);
    if (nulHandle != INVALID_HANDLE_VALUE) {
      ::CloseHandle(nulHandle);
    }
  }
  if (!created) {
    const DWORD code = ::GetLastError();
    if (readPipe != nullptr) {
      ::CloseHandle(readPipe);
    }
    SetError(error, Format(L"启动进程失败：%s", Win32ErrorMessage(code).c_str()));
    return false;
  }
  ::CloseHandle(process.hThread);

  const ULONGLONG deadline = ::GetTickCount64() + (timeoutMs == 0 ? 0 : timeoutMs);
  bool childExited = false;
  bool timedOut = false;
  std::string output;
  char chunk[4096];
  for (;;) {
    if (captureOutput) {
      DWORD available = 0;
      while (::PeekNamedPipe(readPipe, nullptr, 0, nullptr, &available, nullptr) && available > 0) {
        DWORD read = 0;
        const DWORD want = available < sizeof(chunk) ? available : static_cast<DWORD>(sizeof(chunk));
        if (!::ReadFile(readPipe, chunk, want, &read, nullptr) || read == 0) {
          break;
        }
        output.append(chunk, read);
        available -= read;
      }
    }
    if (!childExited) {
      const DWORD wait = ::WaitForSingleObject(process.hProcess, 0);
      if (wait == WAIT_OBJECT_0) {
        childExited = true;
      } else if (wait == WAIT_FAILED) {
        break;
      }
    }
    if (childExited) {
      DWORD remaining = 0;
      const bool more =
          captureOutput && ::PeekNamedPipe(readPipe, nullptr, 0, nullptr, &remaining, nullptr) &&
          remaining > 0;
      if (!more) {
        break;
      }
      continue;
    }
    if (timeoutMs != 0 && ::GetTickCount64() >= deadline) {
      timedOut = true;
      ::TerminateProcess(process.hProcess, 1);
      ::WaitForSingleObject(process.hProcess, 5000);
      break;
    }
    ::Sleep(20);
  }

  if (captureOutput && readPipe != nullptr) {
    ::CloseHandle(readPipe);
  }
  DWORD exitCode = static_cast<DWORD>(-1);
  ::GetExitCodeProcess(process.hProcess, &exitCode);
  ::CloseHandle(process.hProcess);

  if (result != nullptr) {
    result->exitCode = exitCode;
    result->output = output;
    result->timedOut = timedOut;
  }
  if (timedOut) {
    SetError(error, Format(L"命令超时（%u 毫秒）", static_cast<unsigned int>(timeoutMs)));
    return false;
  }
  return true;
}

bool IsProcessElevated() {
  HANDLE token = nullptr;
  if (!::OpenProcessToken(::GetCurrentProcess(), TOKEN_QUERY, &token)) {
    return false;
  }
  TOKEN_ELEVATION elevation{};
  DWORD length = 0;
  const BOOL ok = ::GetTokenInformation(token, TokenElevation, &elevation, sizeof(elevation), &length);
  ::CloseHandle(token);
  return ok != FALSE && elevation.TokenIsElevated != 0;
}

bool RunElevatedSelf(const std::wstring& arguments, DWORD timeoutMs, DWORD* exitCode,
                     std::wstring* error) {
  const std::wstring self = ExePath();
  const std::wstring selfDirectory = ExeDirectory();
  SHELLEXECUTEINFOW info{};
  info.cbSize = sizeof(info);
  info.fMask = SEE_MASK_NOCLOSEPROCESS | SEE_MASK_FLAG_NO_UI | SEE_MASK_NOASYNC;
  info.lpVerb = L"runas";
  info.lpFile = self.c_str();
  info.lpParameters = arguments.c_str();
  info.lpDirectory = selfDirectory.c_str();
  info.nShow = SW_HIDE;
  if (!::ShellExecuteExW(&info)) {
    const DWORD code = ::GetLastError();
    if (code == ERROR_CANCELLED) {
      SetError(error, L"用户取消了 UAC 提权");
    } else {
      SetError(error, Format(L"提权启动失败：%s", Win32ErrorMessage(code).c_str()));
    }
    return false;
  }
  if (info.hProcess == nullptr) {
    SetError(error, L"提权启动没有返回进程句柄");
    return false;
  }
  const DWORD wait = ::WaitForSingleObject(info.hProcess, timeoutMs == 0 ? INFINITE : timeoutMs);
  if (wait == WAIT_TIMEOUT) {
    ::TerminateProcess(info.hProcess, 1);
    ::CloseHandle(info.hProcess);
    SetError(error, L"提权后的进程超时");
    return false;
  }
  DWORD code = static_cast<DWORD>(-1);
  ::GetExitCodeProcess(info.hProcess, &code);
  ::CloseHandle(info.hProcess);
  if (exitCode != nullptr) {
    *exitCode = code;
  }
  return true;
}

}  // namespace upd
