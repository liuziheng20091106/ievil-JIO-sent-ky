#pragma once

// 解压更新包：优先用系统自带 bsdtar（C:\Windows\System32\tar.exe，支持 zip），
// 失败时退回 PowerShell 的 Expand-Archive。不引第三方库。

#include <string>

namespace upd {

bool ExtractArchive(const std::wstring& archivePath, const std::wstring& destination,
                    std::wstring* error);

}  // namespace upd
