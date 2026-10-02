#!/usr/bin/env python3
"""Upload published resource contents to R2 under immutable MD5 object keys."""

import argparse
import importlib.util
import mimetypes
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.resource_packs import PACKS, RESOURCES_DIR, load_manifest, media_file  # noqa: E402

spec = importlib.util.spec_from_file_location("package_release", ROOT / "tools/package-release.py")
assert spec is not None and spec.loader is not None
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resources-dir", type=Path, default=RESOURCES_DIR)
    parser.add_argument("--env", type=Path, default=release.DEFAULT_ENV_FILE)
    args = parser.parse_args()
    values = release.load_env(args.env)
    release.check_config(values, args.env)
    files = {}
    for pack in PACKS:
        manifest = load_manifest(args.resources_dir, pack)
        for entry in manifest["files"]:
            file = media_file(args.resources_dir / pack, entry["path"], pack)
            if file.stat().st_size != entry["size"] or release.md5_file(file) != entry["md5"]:
                raise ValueError(f"Published resource changed: {pack}/{entry['path']}")
            files.setdefault(entry["md5"], (file, entry["size"]))
    print(
        f"Uploading {len(files)} unique resources to {values['S3_PUBLIC_BASE']}/resources",
        flush=True,
    )

    def publish(item):
        digest, (file, size) = item
        key = f"resources/{digest}"
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
        item = {"key": key, "size": size, "md5": digest}
        print(
            f"Verifying {file.relative_to(args.resources_dir).as_posix()} -> {key}", flush=True
        )
        problems = release.verify_remote(values, [item]) + release.verify_public(values, [item])
        if problems:
            raise ValueError("\n".join(problems))
        return item

    with ThreadPoolExecutor(max_workers=6) as pool:
        published = list(pool.map(publish, files.items()))
    print(
        f"Uploaded and verified {len(published)} objects ({sum(item['size'] for item in published)} bytes)."
    )
    print(f"Resource base URL: {values['S3_PUBLIC_BASE'].rstrip('/')}/resources")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, release.ReleaseError) as error:
        print(f"Resource upload failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
