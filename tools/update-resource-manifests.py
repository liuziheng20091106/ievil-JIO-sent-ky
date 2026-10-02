#!/usr/bin/env python3
"""Rebuild independently published media manifests without touching application updates."""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.app.resource_packs import PACKS, RESOURCES_DIR, ManifestError, update_manifest  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Update published resource pack manifests")
    parser.add_argument("--pack", choices=PACKS, help="Update only this pack")
    parser.add_argument(
        "--resources-dir", type=Path, default=RESOURCES_DIR, help="Resource root directory"
    )
    args = parser.parse_args(argv)
    try:
        for pack in (args.pack,) if args.pack else PACKS:
            manifest = update_manifest(args.resources_dir, pack)
            print(
                f"{pack}: {manifest['version']} ({len(manifest['files'])} files, {manifest['total_size']} bytes)"
            )
    except (ManifestError, OSError) as error:
        print(f"Cannot update resource manifest: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
