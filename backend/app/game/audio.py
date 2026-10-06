"""Public multi-track music state; trusted HANDLERS call play/change/stop directly."""

import json
import math
import re
import subprocess
from functools import lru_cache

from .. import resource_packs
from . import clock
from .state import GameError, require, uid

MIN_RATE = 0.25
MAX_RATE = 4.0
MAX_POSITION = 604800.0  # Seven days keeps native millisecond seek values within 32 bits.
TRACK_ID = re.compile(r"[A-Za-z0-9_-]{1,80}")


def songs():
    """Return only paths in the current validated audio manifest."""
    try:
        manifest = resource_packs.load_manifest(resource_packs.RESOURCES_DIR, "audio")
    except OSError, resource_packs.ManifestError:
        return []
    return [entry["path"] for entry in manifest["files"]]


def _number(value, label, minimum, maximum=None):
    require(type(value) in (int, float), f"{label}格式无效")
    try:
        value = float(value)
    except OverflowError as error:
        raise GameError(f"{label}超出允许范围") from error
    require(
        math.isfinite(value) and value >= minimum and (maximum is None or value <= maximum),
        f"{label}超出允许范围",
    )
    return float(value)


def _song(song):
    require(resource_packs.valid_media_path(song, "audio"), "歌曲路径无效")
    try:
        resource_packs.download_file(resource_packs.RESOURCES_DIR, "audio", song)
    except (OSError, resource_packs.ManifestError) as error:
        raise GameError("歌曲不在当前发布的音频资源包中") from error
    return song


@lru_cache(maxsize=128)
def _probe_duration(path, size, modified_ns):
    # Size/mtime invalidate the cached duration when the published file changes.
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-protocol_whitelist",
            "file",
            "-format_whitelist",
            "mp3,wav,ogg,flac",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=duration:format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    metadata = json.loads(result.stdout)
    stream = metadata["streams"][0]
    duration = float(stream.get("duration") or metadata["format"]["duration"])
    require(math.isfinite(duration) and 0 < duration <= MAX_POSITION, "歌曲时长无效")
    return duration


def _duration(song):
    try:
        path = resource_packs.download_file(resource_packs.RESOURCES_DIR, "audio", song)
        stat = path.stat()
        return _probe_duration(path, stat.st_size, stat.st_mtime_ns)
    except (
        OSError,
        subprocess.SubprocessError,
        ValueError,
        KeyError,
        IndexError,
        TypeError,
    ) as error:
        raise GameError(f"无法读取歌曲「{song}」的时长，请确认音频有效且 ffprobe 可用") from error


def _track(game, track_id):
    require(isinstance(track_id, str) and TRACK_ID.fullmatch(track_id), "音乐路标识无效")
    found = next(
        (track for track in game.get("audio", {}).get("tracks", []) if track["id"] == track_id),
        None,
    )
    if found is None:
        raise GameError("音乐路不存在")
    return found


def _position(track, now):
    return min(
        MAX_POSITION,
        track["position"]
        + (max(0.0, now - track["updated_at"]) * track["rate"] if track["playing"] else 0.0),
    )


def play(game, song, *, id=None, position=0, rate=1, playing=True):
    """Start a new route, or replace the same stable plugin id with another song.

    Mutates the supplied game and bumps its version so existing timer/command
    commits and state broadcasts also consume changes made by event HANDLERS.
    """
    require(game["status"] != "ended", "对局已结束，不能播放音乐")
    song = _song(song)
    track_id = uid() if id is None else id
    require(isinstance(track_id, str) and TRACK_ID.fullmatch(track_id), "音乐路标识无效")
    position = _number(position, "进度", 0, MAX_POSITION)
    rate = _number(rate, "倍速", MIN_RATE, MAX_RATE)
    require(type(playing) is bool, "播放状态无效")
    duration = _duration(song)
    game["version"] += 1
    track = {
        "id": track_id,
        "song": song,
        "position": position,
        "rate": rate,
        "playing": playing,
        "revision": game["version"],
        "updated_at": clock.now(),
        "duration": duration,
    }
    tracks = game.setdefault("audio", {"tracks": []})["tracks"]
    tracks[:] = [existing for existing in tracks if existing["id"] != track_id]
    tracks.append(track)
    return track_id


def change(game, id, *, song=None, position=None, rate=None, playing=None):
    """Seek/change speed/pause/resume a route, preserving progress when omitted."""
    require(game["status"] != "ended", "对局已结束，不能修改音乐")
    track = _track(game, id)
    song = track["song"] if song is None else _song(song)
    rate = track["rate"] if rate is None else _number(rate, "倍速", MIN_RATE, MAX_RATE)
    if playing is not None:
        require(type(playing) is bool, "播放状态无效")
    now = clock.now()
    position = (
        _position(track, now) if position is None else _number(position, "进度", 0, MAX_POSITION)
    )
    duration = (
        track["duration"] if song == track["song"] and "duration" in track else _duration(song)
    )
    game["version"] += 1
    track.update(
        song=song,
        position=position,
        rate=rate,
        playing=track["playing"] if playing is None else playing,
        updated_at=now,
        revision=game["version"],
        duration=duration,
    )


def stop(game, id):
    """Remove one route. Stop each named route to stop several independently."""
    track = _track(game, id)
    game["audio"]["tracks"].remove(track)
    game["version"] += 1


def expire_finished(game, now=None):
    """Remove only playing routes whose authoritative progress reached the end."""
    if game["status"] == "ended":
        return False
    now = clock.now() if now is None else now
    tracks = game.get("audio", {}).get("tracks", [])
    remaining = []
    changed = False
    for track in tracks:
        if "duration" not in track:
            track["duration"] = _duration(track["song"])
            changed = True
        if track["playing"] and _position(track, now) >= track["duration"]:
            changed = True
        else:
            remaining.append(track)
    if changed:
        tracks[:] = remaining
        game["version"] += 1
    return changed


def projection(game, now=None):
    now = clock.now() if now is None else now
    tracks = [] if game["status"] == "ended" else game.get("audio", {}).get("tracks", [])
    return {
        "server_time": now,
        "tracks": [
            {
                **{key: track[key] for key in ("id", "song", "rate", "playing", "revision")},
                "position": _position(track, now),
            }
            for track in tracks
        ],
    }


def snapshot(game):
    """Freeze progress at the mechanical snapshot, rather than an old play anchor."""
    now = clock.now()
    tracks = [] if game["status"] == "ended" else game.get("audio", {}).get("tracks", [])
    return {
        "tracks": [
            {**track, "position": _position(track, now), "updated_at": now} for track in tracks
        ]
    }


def restore(game):
    """Resume restored routes from snapshot progress at the current wall clock."""
    now = clock.now()
    for track in game.setdefault("audio", {"tracks": []})["tracks"]:
        track.update(updated_at=now, revision=game["version"] + 1)
