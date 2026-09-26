#pragma once

// 空证书占位：入库的那一份，保证 git clone 之后
// `flutter build windows --release` 能直接编译通过。
//
// 真实证书由 tools/sign-windows.ps1 写到**另一个文件**
// `self_signed_cert.local.h`（不入库，已 gitignore）；system.cpp 用
// `__has_include("self_signed_cert.local.h")` 优先包含它，没有才用本文件。
//
// 发布流程：
//   1. pwsh -File tools/sign-windows.ps1        （生成证书 + 写 self_signed_cert.local.h）
//   2. cd client; flutter build windows --release
//   3. pwsh -File tools/sign-windows.ps1 -SignOnly
// 收尾（把工作区还原成干净状态）：
//   pwsh -File tools/sign-windows.ps1 -RestorePlaceholder
//
// 没跑第 1 步就编译出来的 Updater 在 --prepare 时会明确提示
// 「证书为空，请先运行 tools/sign-windows.ps1」，并跳过证书安装。
// 真实证书的字节格式见同目录的 self_signed_cert.h.template。

namespace upd {

inline constexpr unsigned char kSelfSignedCertBytes[] = {0x00};
inline constexpr unsigned int kSelfSignedCertLength = 0;
inline constexpr char kSelfSignedCertSha256[] = "";

}  // namespace upd
