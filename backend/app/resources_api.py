"""Public endpoints for explicitly published, independent media packs."""

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from starlette.types import Receive, Scope, Send

from . import resource_packs, storage

router = APIRouter(prefix="/api/resources")
available_resource_urls: set[str] = set()


def remote_available(url: str) -> bool:
    if url not in available_resource_urls:
        request = Request(
            url,
            headers={"Range": "bytes=0-0", "User-Agent": "MagicJudgeReleaseCheck/1.0"},
        )
        try:
            with urlopen(request, timeout=5) as response:
                if response.status in (200, 206):
                    available_resource_urls.add(url)
        except HTTPError as error:
            error.close()
        except URLError, OSError:
            pass
    return url in available_resource_urls


class ResourceDownload(FileResponse):
    active_downloads = 0

    def __init__(self, file, remote_url=None, *, filename=None):
        super().__init__(file, headers={"Cache-Control": "no-cache"}, filename=filename)
        self.remote_url = remote_url

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # One worker/event loop; retain the slot until the complete response is sent.
        ResourceDownload.active_downloads += 1
        try:
            if (
                ResourceDownload.active_downloads > 3
                and self.remote_url is not None
                and await run_in_threadpool(remote_available, self.remote_url)
            ):
                await RedirectResponse(
                    self.remote_url, status_code=302, headers={"Cache-Control": "no-cache"}
                )(scope, receive, send)
            else:
                await super().__call__(scope, receive, send)
        finally:
            ResourceDownload.active_downloads -= 1


def download_response(file, entry: dict, *, filename=None) -> ResourceDownload:
    try:
        configuration = (storage.DATA_DIR / "resource-downloads.json").read_text(encoding="utf-8")
    except FileNotFoundError:
        return ResourceDownload(file, filename=filename)
    except (OSError, UnicodeError) as error:
        raise HTTPException(503, "Resource download configuration is invalid") from error
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
    try:
        uploaded = resource_packs.load_upload_log(storage.DATA_DIR / "resource-uploads.json").get(
            download_url
        )
    except resource_packs.ManifestError, OSError:
        uploaded = None
    if uploaded is None or uploaded["md5"] != entry["md5"] or uploaded["size"] != entry["size"]:
        download_url = None
    return ResourceDownload(file, download_url, filename=filename)


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
        manifest = resource_packs.load_manifest(resource_packs.RESOURCES_DIR, pack)
        entry = next((item for item in manifest["files"] if item["path"] == path), None)
        if entry is None:
            raise FileNotFoundError("Resource file is not published")
        file = resource_packs.media_file(
            resource_packs.pack_directory(resource_packs.RESOURCES_DIR, pack), path, pack
        )
        if file.stat().st_size != entry["size"]:
            raise resource_packs.ManifestError("Resource size changed; regenerate the manifest")
        return download_response(file, entry)
    except (resource_packs.ManifestError, OSError) as error:
        raise resource_error(error) from error


@router.get("/{pack}/archive")
def get_archive(pack: str):
    try:
        metadata = resource_packs.load_archive(storage.DATA_DIR / "resource-archives", pack)
        return {
            **metadata,
            "url": f"/api/resources/{pack}/archive/files/{metadata['md5']}.zip",
        }
    except (resource_packs.ManifestError, OSError) as error:
        raise resource_error(error) from error


@router.get("/{pack}/archive/files/{digest}.zip")
def get_archive_file(pack: str, digest: str):
    try:
        if not resource_packs.MD5_PATTERN.fullmatch(digest):
            raise FileNotFoundError("Invalid resource archive")
        directory = storage.DATA_DIR / "resource-archives"
        metadata = resource_packs.load_archive(directory, pack)
        if digest != metadata["md5"]:
            raise FileNotFoundError("Resource archive is not published")
        return download_response(directory / f"{digest}.zip", metadata, filename=f"{pack}.zip")
    except (resource_packs.ManifestError, OSError) as error:
        raise resource_error(error) from error
