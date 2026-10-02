"""Public endpoints for explicitly published, independent media packs."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, RedirectResponse

from . import resource_packs, storage

router = APIRouter(prefix="/api/resources")
available_resource_urls: set[str] = set()


def resource_error(error: Exception) -> HTTPException:
    if isinstance(error, FileNotFoundError):
        return HTTPException(404, "Resource pack or published file not found")
    return HTTPException(503, "Resource manifest is invalid; regenerate the manifest")


@router.get("/{pack}/manifest")
def get_manifest(pack: str):
    try:
        return resource_packs.load_manifest(resource_packs.RESOURCES_DIR, pack)
    except (resource_packs.ManifestError, OSError) as error:
        raise resource_error(error) from error


@router.get("/{pack}/files/{path:path}")
def get_file(pack: str, path: str):
    try:
        if not resource_packs.valid_media_path(path, pack):
            raise FileNotFoundError("Invalid resource path")
        try:
            configuration = (storage.DATA_DIR / "resource-downloads.json").read_text(
                encoding="utf-8"
            )
        except FileNotFoundError:
            configuration = None
        except (OSError, UnicodeError) as error:
            raise HTTPException(503, "Resource download configuration is invalid") from error
        if configuration is None:
            file = resource_packs.download_file(resource_packs.RESOURCES_DIR, pack, path)
            return FileResponse(file, headers={"Cache-Control": "no-cache"})
        manifest = resource_packs.load_manifest(resource_packs.RESOURCES_DIR, pack)
        entry = next((item for item in manifest["files"] if item["path"] == path), None)
        if entry is None:
            raise FileNotFoundError("Resource file is not published")
        file = resource_packs.media_file(
            resource_packs.pack_directory(resource_packs.RESOURCES_DIR, pack), path, pack
        )
        if file.stat().st_size != entry["size"]:
            raise resource_packs.ManifestError("Resource size changed; regenerate the manifest")
        try:
            value = json.loads(configuration)
            base_url = value.get("base_url") if isinstance(value, dict) else None
            if (
                not isinstance(base_url, str)
                or any(
                    character.isspace() or ord(character) < 32 or ord(character) == 127
                    for character in base_url
                )
                or any(character in base_url for character in "\\?#")
            ):
                raise ValueError("Invalid download base URL")
            parsed = urlsplit(base_url)
            if (
                parsed.scheme not in ("http", "https")
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
            ):
                raise ValueError("Invalid download base URL")
            _ = parsed.port
        except (ValueError, RecursionError) as error:
            raise HTTPException(503, "Resource download configuration is invalid") from error
        download_url = f"{base_url.rstrip('/')}/{entry['md5']}"
        if download_url not in available_resource_urls:
            # Probe GET, not HEAD: Cloudflare may cache different results for each method.
            request = Request(
                download_url,
                headers={"Range": "bytes=0-0", "User-Agent": "MagicJudgeReleaseCheck/1.0"},
            )
            try:
                with urlopen(request, timeout=5) as response:
                    if response.status in (200, 206):
                        available_resource_urls.add(download_url)
            except HTTPError as error:
                error.close()
            except URLError, OSError:
                pass
        if download_url not in available_resource_urls:
            return FileResponse(file, headers={"Cache-Control": "no-cache"})
        return RedirectResponse(
            download_url,
            status_code=302,
            headers={"Cache-Control": "no-cache"},
        )
    except (resource_packs.ManifestError, OSError) as error:
        raise resource_error(error) from error
