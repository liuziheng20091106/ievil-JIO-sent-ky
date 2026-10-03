#!/usr/bin/env python3
"""发布脚本：把 Windows 发行目录打成 zip，与安卓 APK、更新器一起上传到 S3 兼容存储。

配置写在仓库根目录的 `package-release.env`（dotenv 写法、UTF-8、不入库，
模板见 `package-release.env`），进程环境变量优先于该文件，便于临时覆盖。

上传使用 AWS Signature V4，只用标准库（hmac/hashlib/urllib），不引入新依赖；
兼容 Cloudflare R2（region 填 `auto`）、MinIO 等任何 S3 兼容端点。上传完成后
逐个回读远端对象核对大小与 ETag，最后写两处后端下发的配置：

- `data/downloads.json`：网页首页「下载游戏」的两条链接；
- `data/updates.json`：客户端应用内更新的「平台 + 版本区间」清单（见
  `tools/update_manifest.py`），刷新每个平台兜底区间的 latest/url/size/sha256。

用法：

    package-release.cmd                     # 打包 + 上传 + 校验 + 更新下载与更新清单
    package-release.cmd --dry-run           # 只打包并打印将上传的对象，不联网
    package-release.cmd --skip-zip          # 复用已有 zip，只做上传
    package-release.cmd --skip-upload       # 复用已上传的对象，只做校验与配置刷新
    package-release.cmd --no-updater        # 不上传 Updater.exe
    package-release.cmd --no-updates        # 不刷新 data/updates.json
    .venv\\Scripts\\python.exe tools\\package-release.py --help

对象键一律带实际发行版本号（取自 `client/lib/src/client_version.dart` 的 kClientVersion，
例如 `releases/app-release-1.1.0.apk`），本地构建产物名不变，pubspec 的系列版本不参与命名。
实测自定义域会缓存同名对象（连 query 都忽略），复用键会让客户端与更新器下到上一版旧包。
上传后除对象存储回读外，还会用真实 GET 回读一次对外地址，长度对不上就判失败。
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

# 同目录的 update_manifest.py：直接运行本脚本时 sys.path[0] 就是 tools/，
# 但被别的入口（例如检查脚本）importlib 加载时不一定，这里显式补一次。
sys.path.insert(0, str(Path(__file__).resolve().parent))
import update_manifest  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

WINDOWS_RELEASE = ROOT / "client" / "build" / "windows" / "x64" / "runner" / "Release"
WINDOWS_EXE = WINDOWS_RELEASE / "seven_double_client.exe"
WINDOWS_ZIP = WINDOWS_RELEASE / "魔法裁判Windows.zip"
UPDATER = WINDOWS_RELEASE / "Updater.exe"
APK = ROOT / "client" / "build" / "app" / "outputs" / "flutter-apk" / "app-release.apk"
DEFAULT_ENV_FILE = ROOT / "package-release.env"

# 网页首页「下载游戏」的条目名，与 data/downloads.json 里的 name 对应。
# Windows 安装程序（Updater.exe）是**独立发布产物**：双击运行、填服务器地址即自动下载
# 安装最新版本，装完自带静默更新与卸载入口；便携版是解压即用的整包。
WINDOWS_INSTALLER_LABEL = "Windows 安装程序"
WINDOWS_LABEL = "Windows 便携版"
ANDROID_LABEL = "安卓版"
# 以前用过、现在还可能在 data/downloads.json 里的名字：发布时一并替换，避免网页出现重复项。
LEGACY_DOWNLOAD_LABELS = ("Windows 版",)

REQUIRED_KEYS = ("S3_ENDPOINT", "S3_ACCESS_KEY_ID", "S3_SECRET_ACCESS_KEY", "S3_BUCKET")
DEFAULTS = {
    "S3_REGION": "auto",
    "S3_PREFIX": "releases",
    "S3_PUBLIC_BASE": "https://s3.tkcloud.online",
    "S3_TIMEOUT": "300",
    "S3_PART_TIMEOUT": "30",
}
# 端点里云厂商占位符（Cloudflare R2 控制台常给带 * 的示例）与掩码占位符都视为未填写。
PLACEHOLDER_CHARS = "*<>"

CHUNK = 1024 * 1024
SIGNING_SERVICE = "s3"
# 刚上传完的自定义域可能短暂 403/404，对外校验按这个次数与间隔重试。
PUBLIC_VERIFY_ATTEMPTS = 6
PUBLIC_VERIFY_DELAY_SECONDS = 5
# 对外校验必须显式带 UA：实测自定义域（Cloudflare）直接 403 掉 `Python-urllib/x.y`，
# 而客户端自己的 UA（seven-double-flutter/…、magicjudge-updater/…）与这个 UA 都能正常下载。
PUBLIC_VERIFY_AGENT = "MagicJudgeReleaseCheck/1.0"


# 分片上传参数：实测单连接 PUT 只有 ~0.2 MB/s，拆片并发能吃满带宽。
# 2026-09-27 拿 43.9MB 的 Windows 包与 51.4MB 的 APK 各量了两组：
#   8MB × 6  → 15.3s（2.9 MB/s）／16.9s（3.0 MB/s）
#   5MB × 12 → 18.4s（2.4 MB/s）／18.5s（2.8 MB/s）
# 聚合速度稳定卡在 ~3 MB/s（本机上行瓶颈），拆得更碎、加更多并发只会让单片更慢，
# 所以维持 8MB × 6；要提速得先换上行，不是调这两个数。
MULTIPART_THRESHOLD = 8 * 1024 * 1024  # 超过这个大小走分片上传
MULTIPART_PART_SIZE = 8 * 1024 * 1024
MULTIPART_CONCURRENCY = 6
# 聚合速度低于这个值且总用时明显偏长时提示一句：多半是本机上行被占用或对象存储抖动。
SLOW_UPLOAD_BYTES_PER_SECOND = 1536 * 1024
SLOW_UPLOAD_MIN_SECONDS = 30


class ReleaseError(Exception):
    """发布流程中可以直接读懂的失败原因。"""


def log(message: str = "") -> None:
    print(message, flush=True)


def load_env(path: Path) -> dict:
    """读 dotenv 风格配置；`KEY=VALUE`、`#` 开头为注释，支持单双引号包裹。"""
    values = dict(DEFAULTS)
    if path.exists():
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.split(" #", 1)[0].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if key:
                values[key] = value
    for key in list(values):
        # 进程环境变量优先，便于发布时临时指定另一套端点或前缀。
        if key in os.environ and os.environ[key].strip():
            values[key] = os.environ[key].strip()
    return values


def check_config(values: dict, env_path: Path) -> None:
    """正式上传前的配置校验：缺项或仍是掩码占位符就停下来，不要发出半截请求。"""
    if not env_path.exists():
        raise ReleaseError(
            f"缺少配置文件 {env_path}\n"
            "请按 AGENTS.md「运行与验证」一节创建它，填入 S3 端点、密钥与 bucket。"
        )
    missing = []
    for key in REQUIRED_KEYS:
        value = (values.get(key) or "").strip()
        if not value:
            missing.append(key)
        elif any(ch in value for ch in PLACEHOLDER_CHARS):
            missing.append(f"{key}（仍是占位符 {value}）")
    if missing:
        raise ReleaseError(f"配置文件 {env_path} 还没填完：\n  - " + "\n  - ".join(missing))
    endpoint = values["S3_ENDPOINT"]
    if not endpoint.startswith(("http://", "https://")):
        raise ReleaseError(f"S3_ENDPOINT 必须以 http:// 或 https:// 开头，现在是 {endpoint}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def md5_file(path: Path) -> str:
    digest = hashlib.md5()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(CHUNK), b""):
            digest.update(block)
    return digest.hexdigest()


def human(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} GB"


def fingerprint(paths) -> dict:
    """文件的大小 + mtime，用来判断打包期间发行目录有没有被改动。"""
    result = {}
    for path in paths:
        try:
            stat = path.stat()
            result[path] = (stat.st_size, stat.st_mtime_ns)
        except OSError:
            result[path] = None
    return result


def make_zip(zip_path: Path, source_dir: Path) -> None:
    """把 Windows 发行目录整体打成一个 zip（不夹带目录里已有的 *.zip）。

    flutter build 还在跑时发行目录会被逐文件重写，打进去的会是新旧混合的半成品；
    所以打包前后各取一次指纹，只要有一个文件变了就拒绝出包。
    """
    files = sorted(p for p in source_dir.rglob("*") if p.is_file())
    top_zips = [p for p in files if p.parent == source_dir and p.suffix.lower() == ".zip"]
    for stray in top_zips:
        log(f"  跳过发行目录里已有的压缩包：{stray.name}")
    files = [p for p in files if p.suffix.lower() != ".zip" or p.parent != source_dir]
    if not any(p == WINDOWS_EXE for p in files):
        raise ReleaseError(
            f"{WINDOWS_RELEASE} 里没有 seven_double_client.exe\n"
            "请先 flutter build windows --release；若构建正在进行，等它结束再发布。"
        )

    tmp = zip_path.with_name(zip_path.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    total = sum(p.stat().st_size for p in files)
    log(f"打包 {len(files)} 个文件（原始 {human(total)}）→ {zip_path.name}")
    before = fingerprint(files)
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            archive.write(path, path.relative_to(source_dir).as_posix())
    after = fingerprint(files)
    changed = [p for p in files if before[p] != after[p]]
    if changed:
        tmp.unlink(missing_ok=True)
        preview = "、".join(p.name for p in changed[:3])
        raise ReleaseError(
            f"打包过程中发行目录被改动了 {len(changed)} 个文件（{preview}…）\n"
            "多半是 flutter build 还在跑，等构建结束再重试。"
        )
    os.replace(tmp, zip_path)


def _sign(key: bytes, message: str) -> bytes:
    return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()


def build_signature(
    values: dict,
    method: str,
    canonical_uri: str,
    host: str,
    payload_hash: str,
    extra: dict,
    query: str = "",
) -> tuple[str, str]:
    """按 AWS SigV4 计算请求头，返回 (x-amz-date 的值, Authorization 头的值)。

    ``query`` 是规范查询串（参数按字典序、值按 RFC3986 编码，见 :func:`canonical_query`）；
    不带参数的请求传空串。分片上传的 ``?partNumber`` / ``?uploadId`` / ``?uploads``
    都必须参与签名，否则 S3 端会因规范请求不一致而 403。
    """
    now = datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    region = values["S3_REGION"]
    scope = f"{date_stamp}/{region}/s3/aws4_request"

    headers = {"host": host, "x-amz-content-sha256": payload_hash, "x-amz-date": amz_date}
    for name, value in extra.items():
        headers[name.lower()] = " ".join(str(value).split())

    signed_names = sorted(headers)
    canonical_headers = "".join(f"{name}:{headers[name]}\n" for name in signed_names)
    signed_header_list = ";".join(signed_names)
    canonical_request = "\n".join(
        [method, canonical_uri, query, canonical_headers, signed_header_list, payload_hash]
    )
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )
    key = _sign(("AWS4" + values["S3_SECRET_ACCESS_KEY"]).encode("utf-8"), date_stamp)
    key = _sign(key, region)
    key = _sign(key, SIGNING_SERVICE)
    key = _sign(key, "aws4_request")
    signature = hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = (
        f"AWS4-HMAC-SHA256 Credential={values['S3_ACCESS_KEY_ID']}/{scope}, "
        f"SignedHeaders={signed_header_list}, Signature={signature}"
    )
    return amz_date, authorization


def timeout_of(values: dict) -> int:
    raw = str(values.get("S3_TIMEOUT") or "300").strip()
    try:
        return max(1, int(float(raw)))
    except ValueError as error:
        raise ReleaseError(f"S3_TIMEOUT 不是数字：{raw}") from error


def part_timeout_of(values: dict) -> int:
    """分片 PUT 的 socket 超时：多久没有任何进展就放弃这条连接、重传该片。

    不能跟别的请求共用 `S3_TIMEOUT`（默认 300s）：2026-09-27 实测出现过 43.9MB 的包
    上传 293.8s（聚合 153 KB/s，像是一条连接卡住不动），而同一个文件、同一套参数
    健康时只要 15.3s。健康分片实测 6-16s 就能传完 8MB，所以默认 30s 无进展就换连接重传。
    """
    raw = str(values.get("S3_PART_TIMEOUT") or "30").strip()
    try:
        return max(1, int(float(raw)))
    except ValueError as error:
        raise ReleaseError(f"S3_PART_TIMEOUT 不是数字：{raw}") from error


def part_ranges(size: int, part_size: int) -> list[tuple[int, int, int]]:
    """把 size 按 part_size 切成 `(片号, 偏移, 长度)`；片号从 1 起，最后一片可以短。"""
    ranges = []
    offset = 0
    number = 1
    while offset < size:
        length = min(part_size, size - offset)
        ranges.append((number, offset, length))
        number += 1
        offset += length
    return ranges


def object_url(values: dict, key: str) -> str:
    """路径式寻址：端点/bucket/键。键里的中文与空格按 RFC3986 百分号编码。"""
    endpoint = values["S3_ENDPOINT"].rstrip("/")
    path = urllib.parse.quote(f"{values['S3_BUCKET']}/{key}", safe="/~")
    return f"{endpoint}/{path}"


def describe_http_error(error: urllib.error.HTTPError) -> str:
    try:
        body = error.read().decode("utf-8", "replace").strip()
    except Exception:  # pragma: no cover - 读响应体失败不影响报错
        body = ""
    detail = f"HTTP {error.code} {error.reason}"
    if body:
        detail += f"：{body[:400]}"
    if error.code in (401, 403):
        detail += "\n  （密钥或权限问题：核对 S3_ACCESS_KEY_ID / S3_SECRET_ACCESS_KEY 有没有写反）"
    return detail


def request_once(
    url: str,
    method: str,
    data=None,
    headers: dict | None = None,
    timeout: int = 300,
    read_body: bool = False,
):
    request = urllib.request.Request(url, data=data, method=method)
    for name, value in (headers or {}).items():
        request.add_header(name, value)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        # 保留 HTTPMessage 原样：它的 get() 不区分大小写，S3 各实现的头名拼写并不统一。
        body = response.read() if read_body else b""
        return response.status, response.headers, body


def canonical_query(params: dict) -> str:
    """SigV4 规范查询串：参数按名字排序，名字与值都按 RFC3986 编码。"""
    encoded = [
        (urllib.parse.quote(str(name), safe="-_.~"), urllib.parse.quote(str(value), safe="-_.~"))
        for name, value in params.items()
    ]
    return "&".join(f"{name}={value}" for name, value in sorted(encoded))


def content_type_of(local: Path) -> str:
    """发布对象的 Content-Type：zip 与 apk 各自的固定值。"""
    return (
        "application/zip"
        if local.suffix.lower() == ".zip"
        else "application/vnd.android.package-archive"
    )


def with_retry(action, what: str, attempts: int = 3):
    """网络抖动重试；4xx 是配置或权限问题，重试没有意义，直接报错。"""
    last = None
    for attempt in range(1, attempts + 1):
        try:
            return action()
        except urllib.error.HTTPError as error:
            if error.code < 500:
                raise ReleaseError(f"{what} 失败：{describe_http_error(error)}") from error
            last = error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last = error
        if attempt < attempts:
            delay = 2 * attempt
            log(f"  {what} 第 {attempt} 次失败（{last}），{delay}s 后重试")
            time.sleep(delay)
    raise ReleaseError(f"{what} 连续 {attempts} 次失败：{last}")


def _signed_request(
    values: dict,
    method: str,
    url: str,
    payload_hash: str,
    extra: dict,
    query_params: dict | None = None,
    data=None,
    read_body: bool = False,
    timeout: int | None = None,
):
    """构造并发送一个 SigV4 签名请求，返回 (status, headers, body)。

    `timeout` 缺省用 `S3_TIMEOUT`；分片 PUT 会传 `S3_PART_TIMEOUT`，避免一条卡住的
    连接按整次请求的超时（默认 300s）干等。
    """
    split = urllib.parse.urlsplit(url)
    query = canonical_query(query_params) if query_params else ""
    amz_date, authorization = build_signature(
        values, method, split.path, split.netloc, payload_hash, extra, query
    )
    target = f"{url}?{query}" if query else url
    headers = {
        **extra,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
        "Authorization": authorization,
    }
    return request_once(
        target, method, data, headers, timeout or timeout_of(values), read_body=read_body
    )


def _s3_object_put(values: dict, local: Path, key: str) -> None:
    """小文件一次性 PUT（Updater.exe 这类）。"""
    url = object_url(values, key)
    size = local.stat().st_size
    payload_hash = sha256_file(local)
    content_type = content_type_of(local)
    extra = {"Content-Type": content_type}

    log(f"上传 {key}（{human(size)}）…")
    started = time.monotonic()

    def send():
        # 每次尝试都重新签名；文件句柄在 send 里打开，重试时从头开始读。
        with local.open("rb") as handle:
            return _signed_request(
                values,
                "PUT",
                url,
                payload_hash,
                extra,
                data=handle.read(size),
            )

    status, _, _ = with_retry(send, f"上传 {key}")
    elapsed = time.monotonic() - started
    speed = size / elapsed if elapsed > 0 else 0
    log(f"  完成 HTTP {status}，用时 {elapsed:.1f}s（{human(int(speed))}/s）")


def _s3_multipart_put(values: dict, local: Path, key: str) -> None:
    """大文件分片并发上传：8MB/片 × 6 路，单片失败整片重传，不需要断点续传。"""
    url = object_url(values, key)
    size = local.stat().st_size
    content_type = content_type_of(local)
    part_timeout = part_timeout_of(values)

    # 1) 发起分片上传。x-amz-content-sha256 用 UNSIGNED-PAYLOAD，免去逐片算哈希。
    empty = hashlib.sha256(b"").hexdigest()
    started = time.monotonic()

    def create():
        return _signed_request(
            values,
            "POST",
            url,
            empty,
            {"Content-Type": content_type},
            {"uploads": ""},
            read_body=True,
        )

    status, _, body = with_retry(create, f"发起分片上传 {key}")
    # CreateMultipartUpload 的响应体是 XML，UploadId 在 <UploadId>…</UploadId> 里。
    match = re.search(r"<UploadId>([^<]+)</UploadId>", body.decode("utf-8", "replace"))
    if status != 200 or not match:
        raise ReleaseError(f"发起分片上传 {key} 失败：HTTP {status}，响应里没有 UploadId")
    upload_id = match.group(1)
    log(
        f"分片上传 {key}（{human(size)}，{MULTIPART_PART_SIZE // (1024 * 1024)}MB/片 × "
        f"{MULTIPART_CONCURRENCY} 路，{part_timeout}s 无进展换连接重传）…"
    )

    # 2) 计算分片并并发 PUT（partNumber 从 1 开始，除最后一片外都必须等长）。
    parts = part_ranges(size, MULTIPART_PART_SIZE)

    uploaded_etags: dict[int, str] = {}
    part_seconds: dict[int, float] = {}
    failures: list[str] = []

    def send_part(number: int, offset: int, length: int) -> tuple[int, str, float]:
        with local.open("rb") as handle:
            handle.seek(offset)
            block = handle.read(length)
            if len(block) != length:
                raise ReleaseError(f"读取分片 {number} 时文件变短了，重试发布")
        digest = hashlib.sha256(block).hexdigest()
        started_part = time.monotonic()

        def attempt():
            _, response_headers, _ = _signed_request(
                values,
                "PUT",
                url,
                digest,
                {},
                {"partNumber": number, "uploadId": upload_id},
                data=block,
                timeout=part_timeout,
            )
            return response_headers.get("ETag") or ""

        etag = with_retry(attempt, f"上传分片 {number}")
        return number, etag.strip('"'), time.monotonic() - started_part

    with ThreadPoolExecutor(max_workers=MULTIPART_CONCURRENCY) as pool:
        futures = [pool.submit(send_part, *item) for item in parts]
        for future in as_completed(futures):
            try:
                number, etag, seconds = future.result()
                uploaded_etags[number] = etag
                part_seconds[number] = seconds
            except Exception as error:  # noqa: BLE001 - 汇总后统一报错
                failures.append(str(error))

    if failures or len(uploaded_etags) != len(parts):
        # 有失败分片就放弃整个上传（abort 清掉服务端残留），用户重跑即可。
        try:
            _signed_request(
                values,
                "DELETE",
                url,
                empty,
                {},
                {"uploadId": upload_id},
            )
        except Exception:  # pragma: no cover - 清理失败不影响报错
            pass
        detail = "；".join(failures[:3]) or "有分片没有上传成功"
        raise ReleaseError(f"分片上传 {key} 失败：{detail}")

    # 3) 合并分片。
    complete_xml = (
        "<CompleteMultipartUpload>"
        + "".join(
            f"<Part><PartNumber>{number}</PartNumber><ETag>{uploaded_etags[number]}</ETag></Part>"
            for number in sorted(uploaded_etags)
        )
        + "</CompleteMultipartUpload>"
    )
    payload = complete_xml.encode("utf-8")
    body_hash = hashlib.sha256(payload).hexdigest()

    def complete():
        _, response_headers, _ = _signed_request(
            values,
            "POST",
            url,
            body_hash,
            {},
            {"uploadId": upload_id},
            data=payload,
        )
        return response_headers

    with_retry(complete, f"合并分片 {key}")
    elapsed = time.monotonic() - started
    speed = size / elapsed if elapsed > 0 else 0
    slowest = max(part_seconds.values()) if part_seconds else 0
    log(
        f"  完成，用时 {elapsed:.1f}s（{human(int(speed))}/s，{len(parts)} 片，"
        f"最慢一片 {slowest:.1f}s）"
    )
    if elapsed >= SLOW_UPLOAD_MIN_SECONDS and speed < SLOW_UPLOAD_BYTES_PER_SECOND:
        log(
            "  提示：本次明显慢于实测基线（8MB×6 约 3 MB/s），多半是本机上行被占用"
            "或对象存储侧抖动；分片超过 "
            f"{part_timeout}s 没有进展会自动换连接重传，重跑发布即可。"
        )


def upload(values: dict, local: Path, key: str) -> dict:
    """按大小选上传方式：大文件分片并发，小文件单次 PUT。返回远端元信息。"""
    size = local.stat().st_size
    if size > MULTIPART_THRESHOLD:
        _s3_multipart_put(values, local, key)
    else:
        _s3_object_put(values, local, key)
    return {
        "key": key,
        "size": size,
        "etag": "",
        "md5": md5_file(local),
    }


def head_object(values: dict, key: str) -> dict:
    url = object_url(values, key)
    split = urllib.parse.urlsplit(url)
    empty_hash = hashlib.sha256(b"").hexdigest()

    def send():
        amz_date, authorization = build_signature(
            values, "HEAD", split.path, split.netloc, empty_hash, {}
        )
        headers = {
            "x-amz-content-sha256": empty_hash,
            "x-amz-date": amz_date,
            "Authorization": authorization,
        }
        status, response_headers, _ = request_once(url, "HEAD", None, headers, timeout_of(values))
        return status, response_headers

    _, response_headers = with_retry(send, f"回读 {key}")
    return response_headers


def verify_remote(values: dict, uploaded: dict) -> list[str]:
    """上传后逐个回读远端对象：大小必须一致，ETag 与本地 MD5 不一致时只提示。"""
    problems = []
    for item in uploaded:
        label = f"{item['path']} -> {item['key']}" if "path" in item else item["key"]
        headers = head_object(values, item["key"])
        remote_size = int(headers.get("Content-Length") or -1)
        remote_etag = (headers.get("ETag") or "").strip('"')
        if remote_size != item["size"]:
            problems.append(f"{label} 大小不一致：本地 {item['size']}，远端 {remote_size}")
            log(f"  校验失败 {label}：本地 {item['size']} B，远端 {remote_size} B")
            continue
        note = "" if remote_etag == item["md5"] else f"，与本地 MD5 不同（{item['md5']}）"
        log(f"  校验通过 {label}：{remote_size} B，ETag {remote_etag or '缺失'}{note}")
    return problems


def public_url(values: dict, key: str) -> str:
    base = values["S3_PUBLIC_BASE"].rstrip("/")
    return f"{base}/{urllib.parse.quote(key, safe='/~')}"


def verify_public(values: dict, uploaded: list[dict]) -> list[str]:
    """回读「对外地址」：CDN 会缓存同名旧对象，所以只取 1 字节比对总长度。

    必须走真实 GET（而不是 HEAD）：实测 Cloudflare 对 HEAD 不回缓存、对 GET 回缓存，
    只测 HEAD 会漏掉「客户端下到上一版旧包」这种事故。

    刚上传完的自定义域可能短暂返回 403/404，按短退避重试；缓存的旧404需要清理CDN，
    不能靠重传对象消除。长度不一致不重试——那正是要被拦住的缓存旧对象。
    """
    base = values["S3_PUBLIC_BASE"].rstrip("/")
    problems = []
    for item in uploaded:
        url = f"{base}/{urllib.parse.quote(item['key'], safe='/~')}"
        label = f"{item.get('path', item['key'])} ({url})"
        total = -1
        cache = ""
        failure = None
        for attempt in range(1, PUBLIC_VERIFY_ATTEMPTS + 1):
            request = urllib.request.Request(
                url, headers={"Range": "bytes=0-0", "User-Agent": PUBLIC_VERIFY_AGENT}
            )
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    content_range = response.headers.get("Content-Range") or ""
                    if "/" in content_range:
                        total = int(content_range.rsplit("/", 1)[-1])
                    else:
                        total = int(response.headers.get("Content-Length") or -1)
                    cache = response.headers.get("cf-cache-status") or ""
                failure = None
                break
            except (urllib.error.HTTPError, urllib.error.URLError, OSError, ValueError) as error:
                failure = error
                total = -1
                cache = ""
                if isinstance(error, urllib.error.HTTPError):
                    cache = ", ".join(
                        f"{name}={error.headers[name]}"
                        for name in ("CF-Cache-Status", "Age", "Cache-Control", "CF-Ray")
                        if error.headers.get(name)
                    )
                    error.close()
                detail = f"{label} 取不到：{error}{('，' + cache) if cache else ''}"
                if attempt < PUBLIC_VERIFY_ATTEMPTS:
                    log(f"  {detail}；第 {attempt} 次，{PUBLIC_VERIFY_DELAY_SECONDS}s 后重试")
                    time.sleep(PUBLIC_VERIFY_DELAY_SECONDS)
        if failure is not None:
            problems.append(detail)
            continue
        if total != item["size"]:
            problems.append(
                f"{label} 对外长度 {total} 与本地 {item['size']} 不一致（CDN 缓存了旧对象）"
            )
            continue
        log(f"  对外可下载 {label}：{total} B{('，' + cache) if cache else ''}")
    return problems


def update_downloads(path: Path, entries: list[dict]) -> None:
    """把网页首页的下载链接写进 data/downloads.json，保留其它手工条目。

    本次写入的名字连同 [LEGACY_DOWNLOAD_LABELS] 里改名前的老名字一起替换掉，
    这样升级到「安装程序 + 便携版」的新结构后网页不会同时列出新旧两套链接。
    """
    existing = []
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("downloads"), list):
                existing = [item for item in data["downloads"] if isinstance(item, dict)]
        except (OSError, ValueError) as error:
            raise ReleaseError(f"{path} 不是合法的 JSON，未改动：{error}") from error
    names = {entry["name"] for entry in entries}
    merged = [
        item
        for item in existing
        if item.get("name") not in names and item.get("name") not in LEGACY_DOWNLOAD_LABELS
    ] + entries
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"downloads": merged}, ensure_ascii=False, indent=2) + "\n"
    path.write_text(payload, encoding="utf-8")
    for entry in entries:
        log(f"  下载项 {entry['name']} → {entry['url']}")
    log(f"已更新下载链接 {path}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="打包 Windows 发行并连同安卓 APK 上传到 S3 兼容存储。"
    )
    parser.add_argument("--env", type=Path, default=DEFAULT_ENV_FILE, help="配置文件路径")
    parser.add_argument("--dry-run", action="store_true", help="只打包并打印计划，不联网、不改配置")
    parser.add_argument("--skip-zip", action="store_true", help="跳过打包，直接复用已有 zip")
    parser.add_argument(
        "--skip-upload", action="store_true", help="复用已上传的对象，只做校验与配置刷新"
    )
    parser.add_argument("--no-downloads", action="store_true", help="不更新 data/downloads.json")
    parser.add_argument("--no-updater", action="store_true", help="不上传 Updater.exe")
    parser.add_argument("--no-updates", action="store_true", help="不刷新 data/updates.json")
    parser.add_argument(
        "--data-dir", type=Path, default=None, help="data 目录（默认 GAME_DATA_DIR 或 ./data）"
    )
    args = parser.parse_args(argv)

    values = load_env(args.env)
    data_dir = args.data_dir or Path(os.environ.get("GAME_DATA_DIR") or (ROOT / "data"))
    downloads_path = data_dir / "downloads.json"
    updates_path = data_dir / "updates.json"

    log(f"发布配置：{args.env}")
    try:
        if not args.dry_run:
            check_config(values, args.env)

        if not WINDOWS_EXE.exists():
            raise ReleaseError(
                f"缺少 Windows 发行产物 {WINDOWS_EXE}\n请先执行 flutter build windows --release"
            )
        if not APK.exists():
            raise ReleaseError(
                f"缺少安卓发行 APK {APK}\n请先执行 flutter build apk --release --target-platform android-arm64"
            )
        if not args.no_updater and not UPDATER.exists():
            raise ReleaseError(
                f"缺少 Windows 更新器 {UPDATER}\n它随 flutter build windows --release 一起构建；"
                "确实不需要时用 --no-updater 跳过"
            )

        if args.skip_zip:
            if not WINDOWS_ZIP.exists():
                raise ReleaseError(f"--skip-zip 需要已有 {WINDOWS_ZIP}")
            log(f"复用已有压缩包 {WINDOWS_ZIP.name}")
        else:
            make_zip(WINDOWS_ZIP, WINDOWS_RELEASE)
        log(f"  压缩后 {human(WINDOWS_ZIP.stat().st_size)}")

        prefix = values["S3_PREFIX"].strip("/")

        def key_for(name: str) -> str:
            return f"{prefix}/{name}" if prefix else name

        def versioned(path: Path) -> str:
            """对象键必须带版本号：CDN 会把同名对象缓存住（连 query 都忽略），
            复用同一个键会让客户端与更新器下到上一版的旧包。"""
            return key_for(f"{path.stem}-{version}{path.suffix}")

        version = update_manifest.client_version()
        uploads = [
            (WINDOWS_ZIP, versioned(WINDOWS_ZIP)),
            (APK, versioned(APK)),
        ]
        if args.no_updater:
            log("--no-updater：本次不上传 Updater.exe")
        else:
            uploads.append((UPDATER, versioned(UPDATER)))

        if args.dry_run:
            log("\n--dry-run：不会上传，也不会改动 downloads.json / updates.json")
            for local, key in uploads:
                log(f"  将上传 {local}（{human(local.stat().st_size)}）→ {key}")
                log(f"    对外地址 {public_url(values, key)}")
            log(f"  将刷新 {updates_path}（客户端版本 {version}）")
            return 0

        if args.skip_upload:
            log("\n--skip-upload：复用已经上传的对象，只做对外校验与配置刷新")
            uploaded = [
                {"key": key, "size": local.stat().st_size, "etag": "", "md5": ""}
                for local, key in uploads
            ]
        else:
            log(f"\n上传到 {values['S3_ENDPOINT']} 的 bucket {values['S3_BUCKET']} …")
            uploaded = [upload(values, local, key) for local, key in uploads]

            log("\n回读校验（对象存储）：")
            problems = verify_remote(values, uploaded)
            if problems:
                raise ReleaseError("上传结果与本地不一致：\n  - " + "\n  - ".join(problems))

        log("\n回读校验（对外地址）：")
        public_problems = verify_public(values, uploaded)
        if public_problems:
            raise ReleaseError(
                "对外地址拿到的不是刚上传的对象（多半是 CDN 缓存了旧文件）：\n  - "
                + "\n  - ".join(public_problems)
                + "\n请确认对象键带版本号，或清理 CDN 缓存后重试"
            )

        if args.no_downloads:
            log("\n--no-downloads：跳过 data/downloads.json")
        else:
            download_entries = []
            if not args.no_updater:
                download_entries.append(
                    {
                        "name": WINDOWS_INSTALLER_LABEL,
                        "url": public_url(values, versioned(UPDATER)),
                        "note": "双击运行，填入服务器地址即可自动安装最新版本；装好后自带静默更新与卸载入口。",
                    }
                )
            download_entries.append(
                {
                    "name": WINDOWS_LABEL,
                    "url": public_url(values, versioned(WINDOWS_ZIP)),
                    "note": "解压即用，不含安装程序；同样支持应用内更新。",
                }
            )
            download_entries.append(
                {
                    "name": ANDROID_LABEL,
                    "url": public_url(values, versioned(APK)),
                    "note": "下载后直接安装；应用内可自动更新。",
                }
            )
            update_downloads(downloads_path, download_entries)

        if args.no_updates:
            log("\n--no-updates：跳过 data/updates.json")
        else:
            # 应用内更新清单：只刷新两个平台兜底区间的下载信息与版本号，
            # 手工写的更新日志（notes）、minimum、guide_url 与更窄的区间条目都保留。
            windows_entry = {
                "platform": "windows",
                "url": public_url(values, versioned(WINDOWS_ZIP)),
                "size": WINDOWS_ZIP.stat().st_size,
                "sha256": sha256_file(WINDOWS_ZIP),
            }
            if not args.no_updater:
                windows_entry["updater_url"] = public_url(values, versioned(UPDATER))
            log(f"\n刷新应用内更新清单（客户端版本 {version}）：")
            update_manifest.refresh_manifest(
                updates_path,
                version,
                [
                    windows_entry,
                    {
                        "platform": "android",
                        "url": public_url(values, versioned(APK)),
                        "size": APK.stat().st_size,
                        "sha256": sha256_file(APK),
                    },
                ],
                log=log,
            )
    except (ReleaseError, update_manifest.ManifestError) as error:
        log(f"\n发布失败：{error}")
        return 1

    log("\n已发布到 S3：")
    for _, key in uploads:
        log(f"  {public_url(values, key)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
