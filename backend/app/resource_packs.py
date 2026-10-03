"""Shared generation and validation for independently published media packs."""

import hashlib
import json
import math
import re
import tempfile
import zipfile
from pathlib import Path

PACKS = ("animation", "memes")
RESOURCES_DIR = Path(__file__).resolve().parents[2] / "resources"
MEDIA_SUFFIXES = frozenset(
    [
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".bmp",
        ".svg",
        ".avif",
        ".mp3",
        ".wav",
        ".ogg",
        ".flac",
        ".mp4",
        ".webm",
    ]
)
IMAGE_SUFFIXES = frozenset([".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".avif"])
MD5_PATTERN = re.compile(r"[0-9a-f]{32}")


class ManifestError(ValueError):
    """Published metadata is invalid or no longer matches the source files."""


def valid_media_path(path: object, pack: str) -> bool:
    if not isinstance(path, str) or not path or "\\" in path or ":" in path:
        return False
    parts = path.split("/")
    if any(
        not part
        or part.startswith((".", "~"))
        or part.endswith((".", " "))
        or any(ord(char) < 32 or char in '<>"|?*' for char in part)
        or part.split(".")[0].upper()
        in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{n}" for n in range(1, 10)),
            *(f"LPT{n}" for n in range(1, 10)),
        }
        for part in parts
    ):
        return False
    suffix = Path(parts[-1]).suffix.lower()
    return (
        pack in PACKS
        and parts[-1].lower() != "manifest.json"
        and (
            suffix in MEDIA_SUFFIXES
            or (
                pack == "animation"
                and parts[0] == "scripts"
                and len(parts) > 1
                and suffix == ".json"
            )
        )
    )


def files_version(files: list[dict]) -> str:
    canonical = json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.md5(canonical, usedforsecurity=False).hexdigest()


def validate_manifest(value: object, pack: str) -> dict:
    if (
        not isinstance(value, dict)
        or set(value) != {"pack", "version", "total_size", "files"}
        or value["pack"] != pack
        or pack not in PACKS
        or not isinstance(value["version"], str)
        or not MD5_PATTERN.fullmatch(value["version"])
        or type(value["total_size"]) is not int
        or value["total_size"] < 0
        or not isinstance(value["files"], list)
    ):
        raise ManifestError("Invalid resource manifest header; regenerate the manifest")
    seen = set()
    parents = set()
    previous = None
    total = 0
    for entry in value["files"]:
        if (
            not isinstance(entry, dict)
            or set(entry) != {"path", "size", "md5"}
            or not valid_media_path(entry["path"], pack)
            or type(entry["size"]) is not int
            or entry["size"] < 0
            or not isinstance(entry["md5"], str)
            or not MD5_PATTERN.fullmatch(entry["md5"])
        ):
            raise ManifestError("Invalid resource file entry; regenerate the manifest")
        path = entry["path"]
        folded = path.casefold()
        ancestors = {
            "/".join(folded.split("/")[:index]) for index in range(1, len(path.split("/")))
        }
        if (
            folded in seen
            or folded in parents
            or seen.intersection(ancestors)
            or (previous is not None and path <= previous)
        ):
            raise ManifestError("Resource paths conflict or are unsorted; regenerate the manifest")
        seen.add(folded)
        parents.update(ancestors)
        previous = path
        total += entry["size"]
    if total != value["total_size"] or files_version(value["files"]) != value["version"]:
        raise ManifestError("Resource manifest fingerprint mismatch; regenerate the manifest")
    return value


def is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def pack_directory(resources_dir: Path, pack: str) -> Path:
    if pack not in PACKS:
        raise FileNotFoundError("Unknown resource pack")
    root = Path(resources_dir)
    directory = root / pack
    if is_link(root) or is_link(directory) or not directory.is_dir():
        raise FileNotFoundError("Resource pack is not available")
    return directory


def media_file(directory: Path, path: str, pack: str) -> Path:
    if not valid_media_path(path, pack):
        raise FileNotFoundError("Invalid resource path")
    target = directory
    for part in path.split("/"):
        target = target / part
        if is_link(target):
            raise FileNotFoundError("Linked resources are not published")
    if not target.resolve().is_relative_to(directory.resolve()) or not target.is_file():
        raise FileNotFoundError("Resource file is not available")
    return target


def validate_animation_scripts(directory: Path, manifest: dict) -> None:
    if manifest["pack"] != "animation":
        return
    published = {entry["path"]: entry for entry in manifest["files"]}
    for path, entry in published.items():
        if Path(path).suffix.lower() != ".json":
            continue
        try:
            raw = media_file(directory, path, "animation").read_bytes()
            if (
                len(raw) != entry["size"]
                or hashlib.md5(raw, usedforsecurity=False).hexdigest() != entry["md5"]
            ):
                raise ManifestError("Animation script changed; regenerate the manifest")
            animation = json.loads(raw)
            if not isinstance(animation, dict):
                raise ManifestError("Animation script must be a Lottie object")
            for dimension in ("w", "h"):
                if (
                    type(animation.get(dimension)) is not int
                    or not 1 <= animation[dimension] <= 8192
                ):
                    raise ManifestError("Invalid animation dimensions")
            for field in ("fr", "ip", "op"):
                if type(animation.get(field)) not in (int, float) or not math.isfinite(
                    animation[field]
                ):
                    raise ManifestError("Invalid animation timing")
            rate, start, end = (animation[field] for field in ("fr", "ip", "op"))
            if not 1 <= rate <= 120 or start < 0 or end <= start or (end - start) / rate > 60:
                raise ManifestError("Animation timing exceeds playback limits")
            if not isinstance(animation.get("layers"), list) or not isinstance(
                animation.get("assets"), list
            ):
                raise ManifestError("Animation layers and assets must be lists")
            pending = [animation]
            while pending:
                value = pending.pop()
                if isinstance(value, dict):
                    if isinstance(value.get("x"), str) or value.get("fPath"):
                        raise ManifestError("Expressions and external fonts are not published")
                    if "layers" in value:
                        layers = value["layers"]
                        if not isinstance(layers, list) or any(
                            not isinstance(layer, dict)
                            or type(layer.get("ty")) is not int
                            or layer["ty"] not in (0, 1, 2, 3, 4, 5)
                            for layer in layers
                        ):
                            raise ManifestError("Unsupported animation layer")
                    pending.extend(value.values())
                elif isinstance(value, list):
                    pending.extend(value)
                elif type(value) in (int, float) and not math.isfinite(value):
                    raise ManifestError("Animation numbers must be finite")
            image_ids = set()
            for asset in animation["assets"]:
                if not isinstance(asset, dict):
                    raise ManifestError("Invalid animation asset")
                if type(asset.get("e", 0)) is not int or asset.get("e", 0) != 0:
                    raise ManifestError("Embedded animation images are not published")
                if "p" not in asset and "u" not in asset:
                    continue
                image_id = asset.get("id")
                if not isinstance(image_id, str) or not image_id or image_id in image_ids:
                    raise ManifestError("Animation image IDs must be nonempty and unique")
                image_ids.add(image_id)
                folder, image = asset.get("u", ""), asset.get("p")
                if not isinstance(folder, str) or (folder and not folder.endswith("/")):
                    raise ManifestError("Invalid animation image directory")
                if (
                    not valid_media_path(image, "animation")
                    or Path(image).suffix.lower() not in IMAGE_SUFFIXES
                ):
                    raise ManifestError("Invalid animation image path")
                relative = f"{path.rsplit('/', 1)[0]}/{folder}{image}"
                if not valid_media_path(relative, "animation") or relative not in published:
                    raise ManifestError("Animation image is not published in this pack")
                target = media_file(directory, relative, "animation")
                if target.stat().st_size != published[relative]["size"]:
                    raise ManifestError("Animation image changed; regenerate the manifest")
        except (OSError, ValueError, UnicodeError, RecursionError, OverflowError) as error:
            raise ManifestError(f"Invalid animation script {path}: {error}") from error


def load_manifest(resources_dir: Path, pack: str) -> dict:
    directory = pack_directory(resources_dir, pack)
    path = directory / "manifest.json"
    if is_link(path):
        raise ManifestError("Resource manifest must not be a link")
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise
    except (OSError, UnicodeError) as error:
        raise ManifestError("Cannot read resource manifest") from error
    try:
        manifest = validate_manifest(json.loads(raw), pack)
        validate_animation_scripts(directory, manifest)
        return manifest
    except (ValueError, RecursionError) as error:
        raise ManifestError("Invalid resource manifest; regenerate the manifest") from error


def download_file(resources_dir: Path, pack: str, path: str) -> Path:
    if not valid_media_path(path, pack):
        raise FileNotFoundError("Invalid resource path")
    manifest = load_manifest(resources_dir, pack)
    entry = next((item for item in manifest["files"] if item["path"] == path), None)
    if entry is None:
        raise FileNotFoundError("Resource file is not published")
    target = media_file(pack_directory(resources_dir, pack), path, pack)
    if target.stat().st_size != entry["size"]:
        raise ManifestError("Resource size changed; regenerate the manifest")
    return target


def load_upload_log(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (ValueError, RecursionError) as error:
        raise ManifestError("Resource upload log is invalid") from error
    if not isinstance(value, dict) or any(
        not isinstance(url, str)
        or not isinstance(entry, dict)
        or not isinstance(entry.get("path"), str)
        or type(entry.get("size")) is not int
        or entry["size"] < 0
        or not isinstance(entry.get("md5"), str)
        or not MD5_PATTERN.fullmatch(entry["md5"])
        for url, entry in value.items()
    ):
        raise ManifestError("Resource upload log is invalid")
    return value


def build_archive(resources_dir: Path, pack: str, archive_dir: Path) -> dict:
    manifest = load_manifest(resources_dir, pack)
    directory = pack_directory(resources_dir, pack)
    archive_dir.mkdir(parents=True, exist_ok=True)
    temporary = None
    metadata_temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=archive_dir, suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            manifest_info = zipfile.ZipInfo("manifest.json")
            manifest_info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(
                manifest_info,
                json.dumps(manifest, ensure_ascii=False, sort_keys=True).encode("utf-8"),
            )
            for entry in manifest["files"]:
                file = media_file(directory, entry["path"], pack)
                info = zipfile.ZipInfo(entry["path"])
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                digest = hashlib.md5(usedforsecurity=False)
                size = 0
                with file.open("rb") as source, archive.open(info, "w") as target:
                    while block := source.read(1024 * 1024):
                        target.write(block)
                        digest.update(block)
                        size += len(block)
                if size != entry["size"] or digest.hexdigest() != entry["md5"]:
                    raise ManifestError(f"Resource changed while packing: {pack}/{entry['path']}")
        with temporary.open("rb") as stream:
            digest = hashlib.file_digest(
                stream, lambda: hashlib.md5(usedforsecurity=False)
            ).hexdigest()
        metadata = {
            "pack": pack,
            "version": manifest["version"],
            "size": temporary.stat().st_size,
            "md5": digest,
        }
        temporary.replace(archive_dir / f"{digest}.zip")
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=archive_dir, suffix=".tmp", delete=False
        ) as stream:
            metadata_temporary = Path(stream.name)
            json.dump(metadata, stream, sort_keys=True)
            stream.write("\n")
        metadata_temporary.replace(archive_dir / f"{pack}.json")
        return metadata
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        if metadata_temporary is not None:
            metadata_temporary.unlink(missing_ok=True)


def load_archive(archive_dir: Path, pack: str) -> dict:
    if pack not in PACKS:
        raise FileNotFoundError("Unknown resource pack")
    metadata_path = archive_dir / f"{pack}.json"
    if is_link(metadata_path):
        raise ManifestError("Resource archive metadata must not be a link")
    try:
        value = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (ValueError, RecursionError) as error:
        raise ManifestError("Invalid resource archive metadata") from error
    if (
        not isinstance(value, dict)
        or set(value) != {"pack", "version", "size", "md5"}
        or value["pack"] != pack
        or type(value["size"]) is not int
        or value["size"] <= 0
        or any(
            not isinstance(value[key], str) or not MD5_PATTERN.fullmatch(value[key])
            for key in ("version", "md5")
        )
    ):
        raise ManifestError("Invalid resource archive metadata")
    file = archive_dir / f"{value['md5']}.zip"
    if is_link(file) or file.stat().st_size != value["size"]:
        raise ManifestError("Resource archive changed; rebuild the archive")
    return value


def update_manifest(resources_dir: Path, pack: str) -> dict:
    directory = pack_directory(resources_dir, pack)
    files = []

    def scan_error(error: OSError):
        raise error

    for parent, directories, names in directory.walk(follow_symlinks=False, on_error=scan_error):
        directories[:] = [
            name
            for name in directories
            if not name.startswith((".", "~")) and not is_link(parent / name)
        ]
        for name in names:
            file = parent / name
            relative = file.relative_to(directory).as_posix()
            if not valid_media_path(relative, pack) or is_link(file):
                continue
            file = media_file(directory, relative, pack)
            with file.open("rb") as stream:
                digest = hashlib.file_digest(
                    stream, lambda: hashlib.md5(usedforsecurity=False)
                ).hexdigest()
            files.append({"path": relative, "size": file.stat().st_size, "md5": digest})
    files.sort(key=lambda entry: entry["path"])
    manifest = validate_manifest(
        {
            "pack": pack,
            "version": files_version(files),
            "total_size": sum(entry["size"] for entry in files),
            "files": files,
        },
        pack,
    )
    validate_animation_scripts(directory, manifest)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=directory,
            prefix=".manifest-",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(manifest, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        temporary.replace(directory / "manifest.json")
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return manifest
