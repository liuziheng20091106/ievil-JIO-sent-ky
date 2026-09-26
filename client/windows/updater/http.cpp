#include "http.h"

#include <bcrypt.h>

#include <vector>

#include <windows.h>
#include <winhttp.h>

namespace upd {
namespace {

std::wstring LastWinHttpError(const wchar_t* what) {
  const DWORD code = ::GetLastError();
  return Format(L"%s失败：%s（错误码 %u）", what, Win32ErrorMessage(code).c_str(),
                static_cast<unsigned int>(code));
}

class WinHttpHandle {
 public:
  WinHttpHandle() = default;
  explicit WinHttpHandle(HINTERNET handle) : handle_(handle) {}
  WinHttpHandle(const WinHttpHandle&) = delete;
  WinHttpHandle& operator=(const WinHttpHandle&) = delete;
  ~WinHttpHandle() {
    if (handle_ != nullptr) {
      ::WinHttpCloseHandle(handle_);
    }
  }
  HINTERNET get() const { return handle_; }
  void reset(HINTERNET handle) {
    if (handle_ != nullptr) {
      ::WinHttpCloseHandle(handle_);
    }
    handle_ = handle;
  }

 private:
  HINTERNET handle_ = nullptr;
};

struct UrlParts {
  std::wstring host;
  std::wstring target;  // path + extra info
  INTERNET_PORT port = INTERNET_DEFAULT_HTTP_PORT;
  bool secure = false;
};

bool CrackUrl(const std::wstring& url, UrlParts* parts, std::wstring* error) {
  URL_COMPONENTS components{};
  components.dwStructSize = sizeof(components);
  components.dwSchemeLength = static_cast<DWORD>(-1);
  components.dwHostNameLength = static_cast<DWORD>(-1);
  components.dwUrlPathLength = static_cast<DWORD>(-1);
  components.dwExtraInfoLength = static_cast<DWORD>(-1);
  if (!::WinHttpCrackUrl(url.c_str(), static_cast<DWORD>(url.size()), 0, &components)) {
    *error = LastWinHttpError(L"解析 URL");
    return false;
  }
  if (components.dwHostNameLength == 0) {
    *error = Format(L"URL 缺少主机名：%s", url.c_str());
    return false;
  }
  parts->host.assign(components.lpszHostName, components.dwHostNameLength);
  parts->target.assign(components.lpszUrlPath, components.dwUrlPathLength);
  if (components.dwExtraInfoLength > 0) {
    parts->target.append(components.lpszExtraInfo, components.dwExtraInfoLength);
  }
  if (parts->target.empty()) {
    parts->target = L"/";
  }
  parts->port = components.nPort;
  parts->secure = components.nScheme == INTERNET_SCHEME_HTTPS;
  return true;
}

// 打开一次请求；调用者负责收尾。
bool OpenRequest(const std::wstring& url, const std::wstring& userAgent, WinHttpHandle* session,
                 WinHttpHandle* connection, WinHttpHandle* request, std::wstring* error) {
  UrlParts parts;
  if (!CrackUrl(url, &parts, error)) {
    return false;
  }
  session->reset(::WinHttpOpen(userAgent.c_str(), WINHTTP_ACCESS_TYPE_AUTOMATIC_PROXY,
                               WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0));
  if (session->get() == nullptr) {
    *error = LastWinHttpError(L"初始化网络会话");
    return false;
  }
  connection->reset(::WinHttpConnect(session->get(), parts.host.c_str(), parts.port, 0));
  if (connection->get() == nullptr) {
    *error = LastWinHttpError(L"连接服务器");
    return false;
  }
  request->reset(::WinHttpOpenRequest(connection->get(), L"GET", parts.target.c_str(), nullptr,
                                      WINHTTP_NO_REFERER, WINHTTP_DEFAULT_ACCEPT_TYPES,
                                      parts.secure ? WINHTTP_FLAG_SECURE : 0));
  if (request->get() == nullptr) {
    *error = LastWinHttpError(L"创建请求");
    return false;
  }
  // 30 秒连接/发送/接收，10 分钟总时长：更新包可能很大。
  ::WinHttpSetTimeouts(request->get(), 30000, 30000, 30000, 600000);
  if (!::WinHttpSendRequest(request->get(), WINHTTP_NO_ADDITIONAL_HEADERS, 0,
                            WINHTTP_NO_REQUEST_DATA, 0, 0, 0)) {
    *error = LastWinHttpError(L"发送请求");
    return false;
  }
  if (!::WinHttpReceiveResponse(request->get(), nullptr)) {
    *error = LastWinHttpError(L"接收响应");
    return false;
  }
  return true;
}

bool QueryStatus(HINTERNET request, DWORD* status, std::wstring* error) {
  DWORD value = 0;
  DWORD length = sizeof(value);
  if (!::WinHttpQueryHeaders(request, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
                             WINHTTP_HEADER_NAME_BY_INDEX, &value, &length,
                             WINHTTP_NO_HEADER_INDEX)) {
    *error = LastWinHttpError(L"读取 HTTP 状态码");
    return false;
  }
  *status = value;
  return true;
}

bool QueryContentLength(HINTERNET request, unsigned long long* length) {
  wchar_t buffer[64] = L"";
  DWORD size = sizeof(buffer);
  if (!::WinHttpQueryHeaders(request, WINHTTP_QUERY_CONTENT_LENGTH, WINHTTP_HEADER_NAME_BY_INDEX,
                             buffer, &size, WINHTTP_NO_HEADER_INDEX)) {
    return false;
  }
  unsigned long long parsed = 0;
  if (!ParseUnsigned(buffer, &parsed)) {
    return false;
  }
  *length = parsed;
  return true;
}

}  // namespace

bool HttpGet(const std::wstring& url, const std::wstring& userAgent, HttpResponse* response,
             std::wstring* error) {
  WinHttpHandle session;
  WinHttpHandle connection;
  WinHttpHandle request;
  if (!OpenRequest(url, userAgent, &session, &connection, &request, error)) {
    return false;
  }
  DWORD status = 0;
  if (!QueryStatus(request.get(), &status, error)) {
    return false;
  }
  std::string body;
  char buffer[8192];
  for (;;) {
    DWORD available = 0;
    if (!::WinHttpQueryDataAvailable(request.get(), &available)) {
      *error = LastWinHttpError(L"读取响应长度");
      return false;
    }
    if (available == 0) {
      break;
    }
    const DWORD want = available < sizeof(buffer) ? available : static_cast<DWORD>(sizeof(buffer));
    DWORD read = 0;
    if (!::WinHttpReadData(request.get(), buffer, want, &read)) {
      *error = LastWinHttpError(L"读取响应内容");
      return false;
    }
    if (read == 0) {
      break;
    }
    body.append(buffer, read);
  }
  if (response != nullptr) {
    response->status = status;
    response->body = body;
  }
  if (status < 200 || status >= 300) {
    *error = Format(L"HTTP 状态码 %u", static_cast<unsigned int>(status));
    return false;
  }
  return true;
}

bool HttpDownloadToFile(const std::wstring& url, const std::wstring& userAgent,
                        const std::wstring& destination, ProgressCallback progress, void* context,
                        std::wstring* error) {
  WinHttpHandle session;
  WinHttpHandle connection;
  WinHttpHandle request;
  if (!OpenRequest(url, userAgent, &session, &connection, &request, error)) {
    return false;
  }
  DWORD status = 0;
  if (!QueryStatus(request.get(), &status, error)) {
    return false;
  }
  if (status < 200 || status >= 300) {
    *error = Format(L"下载失败：HTTP 状态码 %u", static_cast<unsigned int>(status));
    return false;
  }
  unsigned long long total = 0;
  QueryContentLength(request.get(), &total);

  const std::wstring parent = DirectoryOf(destination);
  if (!parent.empty() && !EnsureDir(parent, error)) {
    return false;
  }
  const HANDLE file = ::CreateFileW(LongPath(destination).c_str(), GENERIC_WRITE, 0, nullptr,
                                    CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
  if (file == INVALID_HANDLE_VALUE) {
    *error = Format(L"创建下载文件失败 %s：%s", destination.c_str(),
                    Win32ErrorMessage(::GetLastError()).c_str());
    return false;
  }
  unsigned long long received = 0;
  std::vector<char> buffer(64 * 1024);
  bool ok = true;
  for (;;) {
    DWORD available = 0;
    if (!::WinHttpQueryDataAvailable(request.get(), &available)) {
      *error = LastWinHttpError(L"读取下载长度");
      ok = false;
      break;
    }
    if (available == 0) {
      break;
    }
    const DWORD want =
        available < buffer.size() ? available : static_cast<DWORD>(buffer.size());
    DWORD read = 0;
    if (!::WinHttpReadData(request.get(), buffer.data(), want, &read)) {
      *error = LastWinHttpError(L"读取下载内容");
      ok = false;
      break;
    }
    if (read == 0) {
      break;
    }
    DWORD written = 0;
    if (!::WriteFile(file, buffer.data(), read, &written, nullptr) || written != read) {
      *error = Format(L"写入下载文件失败 %s：%s", destination.c_str(),
                      Win32ErrorMessage(::GetLastError()).c_str());
      ok = false;
      break;
    }
    received += read;
    if (progress != nullptr) {
      const int percent = total > 0 ? static_cast<int>((received * 100) / total) : -1;
      progress(context, percent, Format(L"已下载 %llu / %llu 字节", received, total));
    }
  }
  ::CloseHandle(file);
  if (!ok) {
    std::wstring ignored;
    DeleteFileIfExists(destination, &ignored);
    return false;
  }
  return true;
}

bool Sha256Bytes(const unsigned char* data, size_t length, std::string* hex, std::wstring* error) {
  BCRYPT_ALG_HANDLE algorithm = nullptr;
  BCRYPT_HASH_HANDLE hash = nullptr;
  std::vector<unsigned char> object;
  std::vector<unsigned char> digest;
  bool ok = false;
  do {
    if (!BCRYPT_SUCCESS(::BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0))) {
      *error = L"打开 SHA-256 算法失败";
      break;
    }
    DWORD objectSize = 0;
    DWORD produced = 0;
    if (!BCRYPT_SUCCESS(::BCryptGetProperty(algorithm, BCRYPT_OBJECT_LENGTH,
                                            reinterpret_cast<PUCHAR>(&objectSize), sizeof(objectSize),
                                            &produced, 0))) {
      *error = L"读取 SHA-256 参数失败";
      break;
    }
    DWORD digestSize = 0;
    if (!BCRYPT_SUCCESS(::BCryptGetProperty(algorithm, BCRYPT_HASH_LENGTH,
                                            reinterpret_cast<PUCHAR>(&digestSize), sizeof(digestSize),
                                            &produced, 0))) {
      *error = L"读取 SHA-256 摘要长度失败";
      break;
    }
    object.resize(objectSize);
    digest.resize(digestSize);
    if (!BCRYPT_SUCCESS(::BCryptCreateHash(algorithm, &hash, object.data(), objectSize, nullptr, 0, 0))) {
      *error = L"创建 SHA-256 上下文失败";
      break;
    }
    // BCryptHashData 的长度是 ULONG；分块喂进去，避免超过 4GB 时溢出。
    size_t offset = 0;
    while (offset < length) {
      const size_t remaining = length - offset;
      const ULONG chunk = remaining > 0x40000000u ? 0x40000000u : static_cast<ULONG>(remaining);
      if (!BCRYPT_SUCCESS(::BCryptHashData(hash, const_cast<PUCHAR>(data + offset), chunk, 0))) {
        *error = L"计算 SHA-256 失败";
        break;
      }
      offset += chunk;
    }
    if (offset < length) {
      break;
    }
    if (!BCRYPT_SUCCESS(::BCryptFinishHash(hash, digest.data(), digestSize, 0))) {
      *error = L"结束 SHA-256 计算失败";
      break;
    }
    if (hex != nullptr) {
      *hex = BytesToHexAscii(digest.data(), digest.size());
    }
    ok = true;
  } while (false);
  if (hash != nullptr) {
    ::BCryptDestroyHash(hash);
  }
  if (algorithm != nullptr) {
    ::BCryptCloseAlgorithmProvider(algorithm, 0);
  }
  return ok;
}

bool Sha256File(const std::wstring& path, std::string* hex, std::wstring* error) {
  const HANDLE file = ::CreateFileW(LongPath(path).c_str(), GENERIC_READ,
                                    FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_EXISTING,
                                    FILE_ATTRIBUTE_NORMAL, nullptr);
  if (file == INVALID_HANDLE_VALUE) {
    *error = Format(L"打开文件失败 %s：%s", path.c_str(), Win32ErrorMessage(::GetLastError()).c_str());
    return false;
  }
  BCRYPT_ALG_HANDLE algorithm = nullptr;
  BCRYPT_HASH_HANDLE hash = nullptr;
  std::vector<unsigned char> object;
  std::vector<unsigned char> digest;
  std::vector<unsigned char> buffer(256 * 1024);
  bool ok = false;
  do {
    if (!BCRYPT_SUCCESS(::BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, nullptr, 0))) {
      *error = L"打开 SHA-256 算法失败";
      break;
    }
    DWORD objectSize = 0;
    DWORD produced = 0;
    DWORD digestSize = 0;
    if (!BCRYPT_SUCCESS(::BCryptGetProperty(algorithm, BCRYPT_OBJECT_LENGTH,
                                            reinterpret_cast<PUCHAR>(&objectSize), sizeof(objectSize),
                                            &produced, 0)) ||
        !BCRYPT_SUCCESS(::BCryptGetProperty(algorithm, BCRYPT_HASH_LENGTH,
                                            reinterpret_cast<PUCHAR>(&digestSize), sizeof(digestSize),
                                            &produced, 0))) {
      *error = L"读取 SHA-256 参数失败";
      break;
    }
    object.resize(objectSize);
    digest.resize(digestSize);
    if (!BCRYPT_SUCCESS(::BCryptCreateHash(algorithm, &hash, object.data(), objectSize, nullptr, 0, 0))) {
      *error = L"创建 SHA-256 上下文失败";
      break;
    }
    for (;;) {
      DWORD read = 0;
      if (!::ReadFile(file, buffer.data(), static_cast<DWORD>(buffer.size()), &read, nullptr)) {
        *error = Format(L"读取文件失败 %s：%s", path.c_str(), Win32ErrorMessage(::GetLastError()).c_str());
        break;
      }
      if (read == 0) {
        if (!BCRYPT_SUCCESS(::BCryptFinishHash(hash, digest.data(), digestSize, 0))) {
          *error = L"结束 SHA-256 计算失败";
          break;
        }
        if (hex != nullptr) {
          *hex = BytesToHexAscii(digest.data(), digest.size());
        }
        ok = true;
        break;
      }
      if (!BCRYPT_SUCCESS(::BCryptHashData(hash, buffer.data(), read, 0))) {
        *error = L"计算 SHA-256 失败";
        break;
      }
    }
  } while (false);
  if (hash != nullptr) {
    ::BCryptDestroyHash(hash);
  }
  if (algorithm != nullptr) {
    ::BCryptCloseAlgorithmProvider(algorithm, 0);
  }
  ::CloseHandle(file);
  return ok;
}

}  // namespace upd
