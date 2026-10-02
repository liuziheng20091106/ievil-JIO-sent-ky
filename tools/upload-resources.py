#!/usr/bin/env python3
"""Upload published resource contents to R2 under immutable MD5 object keys."""

import argparse
import importlib.util
import json
import mimetypes
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app import storage  # noqa: E402
from backend.app.resource_packs import (  # noqa: E402
    PACKS,
    RESOURCES_DIR,
    load_manifest,
    load_upload_log,
    media_file,
)

spec = importlib.util.spec_from_file_location("package_release", ROOT / "tools/package-release.py")
assert spec is not None and spec.loader is not None
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


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
    log_path = storage.DATA_DIR / "resource-uploads.json"
    upload_log = load_upload_log(log_path)
    log_lock = Lock()
    files = {}
    for pack in PACKS:
        manifest = load_manifest(args.resources_dir, pack)
        for entry in manifest["files"]:
            file = media_file(args.resources_dir / pack, entry["path"], pack)
            if file.stat().st_size != entry["size"] or release.md5_file(file) != entry["md5"]:
                raise ValueError(f"Published resource changed: {pack}/{entry['path']}")
            files.setdefault(entry["md5"], (file, entry["size"]))
    print(
        f"Uploading {len(files)} unique resources to {values['S3_PUBLIC_BASE']}/{prefix}",
        flush=True,
    )

    def publish(item):
        digest, (file, size) = item
        key = f"{prefix}/{digest}"
        url = release.object_url(values, key)
        sha256 = release.sha256_file(file)
        headers = {
            "Content-Type": mimetypes.guess_type(file.name)[0] or "application/octet-stream",
            "Cache-Control": "public, max-age=31536000, immutable",
        }

        def put():
            # ponytail: single PUT holds one file per worker; use multipart for large video packs.
            with file.open("rb") as stream:
                return release._signed_request(
                    values,
                    "PUT",
                    url,
                    sha256,
                    headers,
                    data=stream.read(),
                    timeout=release.part_timeout_of(values),
                )

        release.with_retry(put, f"Upload {key}")
        path = file.relative_to(args.resources_dir).as_posix()
        item = {"key": key, "size": size, "md5": digest, "path": path}
        print(f"Verifying {path} -> {key}", flush=True)
        problems = release.verify_remote(values, [item]) + release.verify_public(values, [item])
        if problems:
            raise ValueError("\n".join(problems))
        with log_lock:
            upload_log[release.public_url(values, key)] = {
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
