"""Private, bounded PNG/JPEG evidence stored in the game transaction."""

import base64
import binascii
import json
import secrets
import struct
import zlib

from fastapi import HTTPException

from . import storage
from .game import game_view

MAX_IMAGE = 2 * 1024 * 1024


def decode_image(data_url):
    if not isinstance(data_url, str) or len(data_url) > 2_800_000:
        raise HTTPException(422, "图片必须是2MB以内的PNG或JPEG")
    try:
        header, encoded = data_url.split(",", 1)
        if header not in ("data:image/png;base64", "data:image/jpeg;base64"):
            raise ValueError()
        image = base64.b64decode(encoded, validate=True)
        if not image or len(image) > MAX_IMAGE:
            raise ValueError()
        width = height = 0
        if header == "data:image/png;base64":
            if image[:8] != b"\x89PNG\r\n\x1a\n":
                raise ValueError()
            pos, found_data, ended = 8, False, False
            while pos + 12 <= len(image):
                size = struct.unpack_from(">I", image, pos)[0]
                tag = image[pos + 4 : pos + 8]
                end = pos + 8 + size
                if (
                    end + 4 > len(image)
                    or zlib.crc32(image[pos + 4 : end]) != struct.unpack_from(">I", image, end)[0]
                ):
                    raise ValueError()
                if pos == 8:
                    if tag != b"IHDR" or size != 13:
                        raise ValueError()
                    width, height = struct.unpack_from(">II", image, pos + 8)
                if tag == b"IDAT":
                    found_data = True
                pos = end + 4
                if tag == b"IEND":
                    ended = size == 0 and pos == len(image)
                    break
            if not found_data or not ended:
                raise ValueError()
            mime = "image/png"
        else:
            if not image.startswith(b"\xff\xd8") or not image.endswith(b"\xff\xd9"):
                raise ValueError()
            pos, scan = 2, False
            while pos + 4 <= len(image):
                if image[pos] != 255:
                    raise ValueError()
                while pos < len(image) and image[pos] == 255:
                    pos += 1
                marker = image[pos]
                pos += 1
                size = struct.unpack_from(">H", image, pos)[0]
                if size < 2 or pos + size > len(image):
                    raise ValueError()
                if marker in (0xC0, 0xC1, 0xC2):
                    if size < 8:
                        raise ValueError()
                    height, width = struct.unpack_from(">HH", image, pos + 3)
                if marker == 0xDA:
                    scan = True
                    break
                pos += size
            if not scan:
                raise ValueError()
            mime = "image/jpeg"
        if not (0 < width <= 4096 and 0 < height <= 4096 and width * height <= 4_194_304):
            raise ValueError()
        return mime, image
    except ValueError, IndexError, struct.error, binascii.Error:
        raise HTTPException(422, "图片无效，仅支持2MB以内、最大4096边长的PNG或JPEG") from None


def create(db, game_id, actor, text="", image=None):
    if not isinstance(text, str) or len(text) > 4000 or (not text.strip() and not image):
        raise HTTPException(422, "请填写证物文字或上传图片（文字最多4000字）")
    mime, blob = decode_image(image) if image else (None, None)
    evidence_id = secrets.token_urlsafe(18)
    db.execute(
        "INSERT INTO evidence(id,game_id,owner_id,text,mime,image,created_at) VALUES(?,?,?,?,?,?,?)",
        (evidence_id, game_id, actor["id"], text.strip(), mime, blob, storage.now_text()),
    )
    return evidence_id


def get_permitted(db, game, actor, evidence_id):
    row = db.execute(
        "SELECT * FROM evidence WHERE id=? AND game_id=?", (evidence_id, game["id"])
    ).fetchone()
    if not row:
        raise HTTPException(404, "证物不存在或你无权查看")
    if actor["kind"] == "host" or row["owner_id"] in actor["access_ids"]:
        return row
    if any(
        item.get("image_id") == evidence_id
        for item in game_view(game, actor).get("information", [])
    ):
        return row
    for message in db.execute(
        "SELECT audience FROM messages WHERE game_id=? AND image_id=?", (game["id"], evidence_id)
    ):
        if message["audience"] is None or set(actor["access_ids"]).intersection(
            json.loads(message["audience"])
        ):
            return row
    raise HTTPException(404, "证物不存在或你无权查看")


def validate_references(db, game, actor, payload):
    # All image references cross the same permission boundary, including nested action data.
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key == "image_id" and value is not None:
                if not isinstance(value, str):
                    raise HTTPException(422, "证物编号无效")
                get_permitted(db, game, actor, value)
            else:
                validate_references(db, game, actor, value)
    elif isinstance(payload, list):
        for value in payload:
            validate_references(db, game, actor, value)
