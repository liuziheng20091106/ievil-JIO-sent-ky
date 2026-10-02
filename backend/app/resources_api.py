"""Public endpoints for explicitly published, independent media packs."""

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from . import resource_packs

router = APIRouter(prefix="/api/resources")


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
        file = resource_packs.download_file(resource_packs.RESOURCES_DIR, pack, path)
    except (resource_packs.ManifestError, OSError) as error:
        raise resource_error(error) from error
    return FileResponse(file, headers={"Cache-Control": "no-cache"})
