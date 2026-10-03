#!/usr/bin/env python3
"""Build resource ZIPs and upload resource contents under immutable MD5 object keys."""

import argparse
import importlib.util
import json
import mimetypes
import os
import sys
import tempfile
import urllib.error
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import storage  # noqa: E402
from backend.app.resource_packs import (  # noqa: E402
    PACKS,
    RESOURCES_DIR,
    build_archive,
    load_manifest,
    load_upload_log,
    media_file,
)

spec = importlib.util.spec_from_file_location("package_release", ROOT / "tools/package-release.py")
assert spec is not None and spec.loader is not None
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def cache_config(values):
    token = os.environ.get("CF_API_TOKEN", "").strip() or (values.get("CF_API_TOKEN") or "").strip()
    zone = os.environ.get("CF_ZONE_ID", "").strip() or (values.get("CF_ZONE_ID") or "").strip()
    if not token and not zone:
        return None
    if not token or not zone:
        raise release.ReleaseError("CF_API_TOKEN 和 CF_ZONE_ID 必须同时配置")
    if any(char in token for char in "\r\n"):
        raise release.ReleaseError("CF_API_TOKEN 配置无效")
    return token, zone


def purge_url(values, config, url):
    token, zone = config
    endpoint = (
        "https://api.cloudflare.com/client/v4/zones/"
        f"{urllib.parse.quote(zone, safe='')}/purge_cache"
    )
    try:
        status, _, body = release.request_once(
            endpoint,
            "POST",
            data=json.dumps({"files": [url]}).encode("utf-8"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            timeout=release.timeout_of(values),
            read_body=True,
        )
    except urllib.error.HTTPError as error:
        status = error.code
        error.close()
        raise release.ReleaseError(f"Cloudflare URL 清缓存失败：HTTP {status}") from None
    except OSError:
        raise release.ReleaseError("Cloudflare URL 清缓存请求失败") from None
    try:
        result = json.loads(body)
    except ValueError:
        raise release.ReleaseError("Cloudflare URL 清缓存响应无效") from None
    if status != 200 or not isinstance(result, dict) or result.get("success") is not True:
        raise release.ReleaseError("Cloudflare 未接受 URL 清缓存请求")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resources-dir", type=Path, default=RESOURCES_DIR)
    parser.add_argument("--env", type=Path, default=release.DEFAULT_ENV_FILE)
    parser.add_argument(
        "--prefix",
        default="resources",
        help="Upload object prefix; enable only after successful verification",
    )
    args = parser.parse_args()
    prefix = args.prefix.strip("/")
    if not prefix or "\\" in prefix or any(part in ("", ".", "..") for part in prefix.split("/")):
        raise ValueError("Resource object prefix is invalid")
    values = release.load_env(args.env)
    release.check_config(values, args.env)
    cache = cache_config(values)
    if cache is None:
        print("未配置未清缓存", flush=True)
    log_path = storage.DATA_DIR / "resource-uploads.json"
    load_upload_log(log_path)
    log_lock = Lock()
    files = {}
    archive_dir = storage.DATA_DIR / "resource-archives"
    for pack in PACKS:
        manifest = load_manifest(args.resources_dir, pack)
        for entry in manifest["files"]:
            file = media_file(args.resources_dir / pack, entry["path"], pack)
            if file.stat().st_size != entry["size"] or release.md5_file(file) != entry["md5"]:
                raise ValueError(f"Published resource changed: {pack}/{entry['path']}")
            files.setdefault(entry["md5"], (file, entry["size"], f"{pack}/{entry['path']}"))
        archive = build_archive(args.resources_dir, pack, archive_dir)
        files[archive["md5"]] = (
            archive_dir / f"{archive['md5']}.zip",
            archive["size"],
            f"archives/{pack}.zip",
        )
    print(
        f"Uploading {len(files)} unique resources to {values['S3_PUBLIC_BASE']}/{prefix}",
        flush=True,
    )

    def publish(item):
        digest, (file, size, path) = item
        key = f"{prefix}/{digest}"
        headers = {
            "Content-Type": (
                "application/zip"
                if path.startswith("archives/")
                else mimetypes.guess_type(file.name)[0] or "application/octet-stream"
            ),
            "Cache-Control": "public, max-age=31536000, immutable",
        }
        if path.startswith("archives/"):
            headers["Content-Disposition"] = f'attachment; filename="{Path(path).name}"'

        release.upload(values, file, key, headers=headers)
        item = {"key": key, "size": size, "md5": digest, "path": path}
        print(f"Verifying {path} -> {key}", flush=True)
        problems = release.verify_remote(values, [item])
        if problems:
            raise ValueError("\n".join(problems))
        public_url = release.public_url(values, key)
        if cache is not None:
            purge_url(values, cache, public_url)
        problems = release.verify_public(values, [item])
        if problems:
            raise ValueError("\n".join(problems))
        with log_lock:
            upload_log = load_upload_log(log_path)
            upload_log[public_url] = {
                "path": path,
                "size": size,
                "md5": digest,
            }
            log_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=log_path.parent,
                    prefix=".resource-uploads-",
                    suffix=".tmp",
                    delete=False,
                ) as stream:
                    temporary = Path(stream.name)
                    json.dump(upload_log, stream, ensure_ascii=False, indent=2, sort_keys=True)
                    stream.write("\n")
                temporary.replace(log_path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        return item

    with ThreadPoolExecutor(max_workers=6) as pool:
        published = list(pool.map(publish, files.items()))
    print(
        f"Uploaded and verified {len(published)} objects ({sum(item['size'] for item in published)} bytes)."
    )
    print(f"Verified upload log: {log_path}")
    print(f"Resource base URL: {values['S3_PUBLIC_BASE'].rstrip('/')}/{prefix}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, release.ReleaseError) as error:
        print(f"Resource upload failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
