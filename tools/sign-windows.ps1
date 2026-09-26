#Requires -Version 5.1
<#
.SYNOPSIS
  给魔法裁判 Windows 客户端生成自签名代码签名证书、导出公钥到 Updater 的证书头文件，并给两个 exe 签名。

.DESCRIPTION
  默认行为（不带开关）：
    1. 在 Cert:\CurrentUser\My 里找一张主题匹配的自签名代码签名证书；没有就新建一张；
    2. 把证书 DER（只含公钥证书）写到
         client/windows/updater/self_signed_cert.local.h
       该文件**不入库**（已 gitignore）；入库的 self_signed_cert.h 永远是「空证书占位」，
       system.cpp 用 __has_include 优先包含 .local.h；
    3. 把 .cer/.pfx 导出到仓库**外面**（默认 %LOCALAPPDATA%\MagicJudge\dev-certs\），
       私钥绝不落在工作区里；
    4. 给 client/build/windows/x64/runner/Release 下的 seven_double_client.exe 与 Updater.exe 签名。

  发布流程（顺序很重要：证书要先写进头文件再编译，Updater 才是内嵌证书的版本）：
    pwsh -File tools/sign-windows.ps1                 # 生成证书 + 写 self_signed_cert.local.h
    cd client; flutter build windows --release        # 编译（内嵌证书）
    pwsh -File tools/sign-windows.ps1 -SignOnly       # 只签名

  收尾（把工作区还原成干净状态、并清掉测试证书）：
    pwsh -File tools/sign-windows.ps1 -RestorePlaceholder   # 只删 .local.h
    pwsh -File tools/sign-windows.ps1 -Uninstall            # 删 .local.h + 证书库里的证书 + 导出的 .cer/.pfx

.PARAMETER RestorePlaceholder
  删掉生成的 self_signed_cert.local.h（源码随即回落到入库的空占位头文件）。

.PARAMETER Uninstall
  清理：RestorePlaceholder + 删掉当前用户证书库与系统信任库里本脚本建的证书
  + 删掉导出目录（.cer/.pfx）。

.PARAMETER Trust
  顺便把证书导入 LocalMachine\Root 与 LocalMachine\TrustedPublisher（需要管理员）。
  正常部署不需要：Updater 的 --prepare 会自己提权完成这一步。

.PARAMETER SignOnly
  只用现有证书给 exe 签名，不改证书、不写头文件。

.PARAMETER OutputDirectory
  .cer/.pfx 的导出目录，默认 %LOCALAPPDATA%\MagicJudge\dev-certs（仓库外）。

.EXAMPLE
  pwsh -File tools/sign-windows.ps1
.EXAMPLE
  pwsh -File tools/sign-windows.ps1 -RestorePlaceholder
.EXAMPLE
  pwsh -File tools/sign-windows.ps1 -Uninstall
#>
[CmdletBinding()]
param(
  [string]$Subject = 'CN=MagicJudge',
  [string]$FriendlyName = 'MagicJudge Windows 自签名代码签名证书',
  [string]$PfxPassword = 'magicjudge-dev',
  [string]$OutputDirectory = '',
  [string]$ReleaseDirectory = '',
  [switch]$Trust,
  [switch]$SignOnly,
  [switch]$RestorePlaceholder,
  [switch]$Placeholder,
  [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$updaterDirectory = Join-Path $repoRoot 'client\windows\updater'
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
  # 私钥放在仓库外，绝不进工作区。
  $OutputDirectory = Join-Path $env:LOCALAPPDATA 'MagicJudge\dev-certs'
}
if ([string]::IsNullOrWhiteSpace($ReleaseDirectory)) {
  $ReleaseDirectory = Join-Path $repoRoot 'client\build\windows\x64\runner\Release'
}
$placeholderHeaderPath = Join-Path $updaterDirectory 'self_signed_cert.h'
$localHeaderPath = Join-Path $updaterDirectory 'self_signed_cert.local.h'
$cerPath = Join-Path $OutputDirectory 'MagicJudge.cer'
$pfxPath = Join-Path $OutputDirectory 'MagicJudge.pfx'

function Write-Utf8NoBom {
  param([string]$Path, [string]$Text)
  $parent = Split-Path -Parent $Path
  if (-not (Test-Path $parent)) {
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
  }
  $encoding = New-Object System.Text.UTF8Encoding($false)
  [System.IO.File]::WriteAllText($Path, $Text, $encoding)
}

function Get-HexLower {
  param([byte[]]$Bytes)
  return (($Bytes | ForEach-Object { $_.ToString('x2') }) -join '')
}

function Get-PlaceholderHeaderText {
  # 与入库的 self_signed_cert.h 保持一致（LF 换行、无 BOM）。
  $lines = @(
    '#pragma once',
    '',
    '// 空证书占位：入库的那一份，保证 git clone 之后',
    '// `flutter build windows --release` 能直接编译通过。',
    '//',
    '// 真实证书由 tools/sign-windows.ps1 写到**另一个文件**',
    '// `self_signed_cert.local.h`（不入库，已 gitignore）；system.cpp 用',
    '// `__has_include("self_signed_cert.local.h")` 优先包含它，没有才用本文件。',
    '//',
    '// 发布流程：',
    '//   1. pwsh -File tools/sign-windows.ps1        （生成证书 + 写 self_signed_cert.local.h）',
    '//   2. cd client; flutter build windows --release',
    '//   3. pwsh -File tools/sign-windows.ps1 -SignOnly',
    '// 收尾（把工作区还原成干净状态）：',
    '//   pwsh -File tools/sign-windows.ps1 -RestorePlaceholder',
    '//',
    '// 没跑第 1 步就编译出来的 Updater 在 --prepare 时会明确提示',
    '// 「证书为空，请先运行 tools/sign-windows.ps1」，并跳过证书安装。',
    '// 真实证书的字节格式见同目录的 self_signed_cert.h.template。',
    '',
    'namespace upd {',
    '',
    'inline constexpr unsigned char kSelfSignedCertBytes[] = {0x00};',
    'inline constexpr unsigned int kSelfSignedCertLength = 0;',
    'inline constexpr char kSelfSignedCertSha256[] = "";',
    '',
    '}  // namespace upd'
  )
  return (($lines -join "`n") + "`n")
}

function Write-PlaceholderHeader {
  # 占位头文件永远保持入库版本；同时删掉可能存在的真实证书头文件。
  Write-Utf8NoBom -Path $placeholderHeaderPath -Text (Get-PlaceholderHeaderText)
  if (Test-Path $localHeaderPath) {
    Remove-Item -Force $localHeaderPath
    Write-Host "已删除 $localHeaderPath（源码回落到空证书占位）。"
  }
  Write-Host "已把 $placeholderHeaderPath 写回空证书占位。"
}

function Write-CertificateHeader {
  param([System.Security.Cryptography.X509Certificates.X509Certificate2]$Certificate)
  $raw = $Certificate.RawData
  $sha256 = [System.Security.Cryptography.SHA256]::Create().ComputeHash($raw)
  $lines = New-Object System.Collections.Generic.List[string]
  for ($index = 0; $index -lt $raw.Length; $index += 12) {
    $end = [Math]::Min($index + 11, $raw.Length - 1)
    $chunk = @()
    for ($offset = $index; $offset -le $end; $offset++) {
      $chunk += ('0x{0:x2}' -f $raw[$offset])
    }
    $lines.Add('    ' + ($chunk -join ', ') + ',')
  }
  $text = @()
  $text += '#pragma once'
  $text += ''
  $text += '// 本文件由 tools/sign-windows.ps1 生成，不入库（已 gitignore）。'
  $text += '// 只含公钥证书，不含私钥；私钥在仓库外的 .pfx 里。'
  $text += "// 主题：$($Certificate.Subject)"
  $text += "// 指纹（SHA-256）：$(Get-HexLower $sha256)"
  $text += '// Updater 的 --prepare 用它在 LocalMachine\Root 与'
  $text += '// LocalMachine\TrustedPublisher 里比指纹，缺失时安装。'
  $text += ''
  $text += 'namespace upd {'
  $text += ''
  $text += 'inline constexpr unsigned char kSelfSignedCertBytes[] = {'
  $text += $lines.ToArray()
  $text += '};'
  $text += ''
  $text += "inline constexpr unsigned int kSelfSignedCertLength = $($raw.Length);"
  $text += ''
  $text += "inline constexpr char kSelfSignedCertSha256[] = `"$(Get-HexLower $sha256)`";"
  $text += ''
  $text += '}  // namespace upd'
  Write-Utf8NoBom -Path $localHeaderPath -Text (($text -join "`n") + "`n")
  Write-Host "已写入 $localHeaderPath（$($raw.Length) 字节，SHA-256 $(Get-HexLower $sha256)）。"
}

function Get-CodeSigningCertificate {
  param([switch]$Create)
  $existing = Get-ChildItem Cert:\CurrentUser\My |
    Where-Object { $_.Subject -eq $Subject -and $_.HasPrivateKey -and $_.NotAfter -gt (Get-Date) } |
    Sort-Object NotAfter -Descending |
    Select-Object -First 1
  if ($null -ne $existing) {
    return $existing
  }
  if (-not $Create) {
    return $null
  }
  Write-Host "当前用户证书库里没有可用的自签名代码签名证书，正在新建：$Subject"
  return New-SelfSignedCertificate `
    -Type CodeSigningCert `
    -Subject $Subject `
    -FriendlyName $FriendlyName `
    -CertStoreLocation Cert:\CurrentUser\My `
    -NotAfter (Get-Date).AddYears(10) `
    -KeyUsage DigitalSignature `
    -KeyExportPolicy Exportable `
    -KeyAlgorithm RSA `
    -KeyLength 2048 `
    -TextExtension @('2.5.29.37={text}1.3.6.1.5.5.7.3.3')
}

function Get-SignableFiles {
  $names = @('seven_double_client.exe', 'Updater.exe')
  $files = @()
  foreach ($name in $names) {
    $path = Join-Path $ReleaseDirectory $name
    if (Test-Path $path) {
      $files += $path
    } else {
      Write-Warning "没有找到 $path，跳过它的签名（先 flutter build windows --release）。"
    }
  }
  return $files
}

function Invoke-Signing {
  param([System.Security.Cryptography.X509Certificates.X509Certificate2]$Certificate)
  $files = @(Get-SignableFiles)
  if ($files.Count -eq 0) {
    Write-Warning '没有可签名的 exe。'
    return
  }
  foreach ($file in $files) {
    $signature = $null
    try {
      $signature = Set-AuthenticodeSignature -FilePath $file -Certificate $Certificate `
        -HashAlgorithm SHA256 -ErrorAction Stop
    } catch {
      Write-Warning "带 SHA256 参数签名失败（$($_.Exception.Message)），改用默认算法重试。"
      $signature = Set-AuthenticodeSignature -FilePath $file -Certificate $Certificate
    }
    $check = Get-AuthenticodeSignature -FilePath $file
    $signer = '(无)'
    if ($null -ne $check.SignerCertificate) {
      $signer = $check.SignerCertificate.Subject
    }
    Write-Host ("已签名 {0}`n    状态：{1}`n    签名者：{2}" -f $file, $check.Status, $signer)
    if ($check.Status -ne 'Valid') {
      Write-Host '    （自签名证书不在本机信任库里时状态不会是 Valid；Updater --prepare 会把它装进信任库，或加 -Trust 现在装。）'
    }
  }
}

function Remove-CertificateFromStore {
  param([string]$StorePath, [string]$Thumbprint)
  $item = Get-ChildItem $StorePath -ErrorAction SilentlyContinue |
    Where-Object { $_.Thumbprint -eq $Thumbprint }
  if ($null -ne $item) {
    $item | Remove-Item -Force -ErrorAction SilentlyContinue
    Write-Host "已从 $StorePath 删除证书 $Thumbprint。"
  }
}

function Invoke-Uninstall {
  $certificates = @()
  $certificates += Get-ChildItem Cert:\CurrentUser\My |
    Where-Object { $_.Subject -eq $Subject }
  $localMachine = @('Cert:\LocalMachine\Root', 'Cert:\LocalMachine\TrustedPublisher')
  foreach ($store in $localMachine) {
    $certificates += Get-ChildItem $store -ErrorAction SilentlyContinue |
      Where-Object { $_.Subject -eq $Subject }
  }
  $thumbprints = @($certificates | Select-Object -ExpandProperty Thumbprint -Unique)
  foreach ($thumbprint in $thumbprints) {
    Remove-CertificateFromStore -StorePath 'Cert:\LocalMachine\Root' -Thumbprint $thumbprint
    Remove-CertificateFromStore -StorePath 'Cert:\LocalMachine\TrustedPublisher' -Thumbprint $thumbprint
    Remove-CertificateFromStore -StorePath 'Cert:\CurrentUser\My' -Thumbprint $thumbprint
  }
  if ($thumbprints.Count -eq 0) {
    Write-Host '没有找到本脚本主题的证书。'
  }
  if (Test-Path $OutputDirectory) {
    Remove-Item -Recurse -Force $OutputDirectory
    Write-Host "已删除导出目录 $OutputDirectory（.cer/.pfx 不再留在磁盘上）。"
  }
  Write-PlaceholderHeader
}

# ==== 主流程 ====

if ($Uninstall) {
  Invoke-Uninstall
  return
}

if ($RestorePlaceholder -or $Placeholder) {
  Write-PlaceholderHeader
  return
}

$certificate = $null
if ($SignOnly) {
  if (Test-Path $pfxPath) {
    $secure = ConvertTo-SecureString -String $PfxPassword -AsPlainText -Force
    $certificate = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2(
      $pfxPath, $secure, 'Exportable,PersistKeySet')
    Write-Host "使用 $pfxPath 里的证书：$($certificate.Subject)"
  } else {
    $certificate = Get-CodeSigningCertificate
  }
  if ($null -eq $certificate) {
    throw "找不到可用证书；先不带 -SignOnly 跑一次本脚本。"
  }
} else {
  $certificate = Get-CodeSigningCertificate -Create
  New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
  Export-Certificate -Cert $certificate -FilePath $cerPath -Type CERT | Out-Null
  $secure = ConvertTo-SecureString -String $PfxPassword -AsPlainText -Force
  Export-PfxCertificate -Cert $certificate -FilePath $pfxPath -Password $secure | Out-Null
  Write-Host "已把证书导出到 $OutputDirectory（仓库外，含私钥，不要拷进工作区）。"
  Write-CertificateHeader -Certificate $certificate
  if ($Trust) {
    Import-Certificate -FilePath $cerPath -CertStoreLocation 'Cert:\LocalMachine\Root' | Out-Null
    Import-Certificate -FilePath $cerPath -CertStoreLocation 'Cert:\LocalMachine\TrustedPublisher' | Out-Null
    Write-Host '已把证书导入 LocalMachine\Root 与 LocalMachine\TrustedPublisher。'
  }
}

Invoke-Signing -Certificate $certificate
