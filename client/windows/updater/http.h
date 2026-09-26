#pragma once

// WinHTTP 下载与 SHA-256 校验。

#include <string>

#include "common.h"

namespace upd {

struct HttpResponse {
  DWORD status = 0;
  std::string body;
};

// GET 一个 URL，把响应体读进内存（用于 /api/health 这种小接口）。
bool HttpGet(const std::wstring& url, const std::wstring& userAgent, HttpResponse* response,
             std::wstring* error);

// 下载到文件。progress 可为空。
bool HttpDownloadToFile(const std::wstring& url, const std::wstring& userAgent,
                        const std::wstring& destination, ProgressCallback progress, void* context,
                        std::wstring* error);

// SHA-256 十六进制（小写）。
bool Sha256Bytes(const unsigned char* data, size_t length, std::string* hex, std::wstring* error);
bool Sha256File(const std::wstring& path, std::string* hex, std::wstring* error);

}  // namespace upd
