"""Read-only cassette import; no inference, fetch, scheduling or playback effects.

This intentionally implements an import seam, NOT the beacon player. Unknown
fields are preserved in source_bytes. URLs and prose remain untrusted data.
"""
from dataclasses import dataclass
import hashlib
import json
import math
import os
import re
import stat

MAX_BYTES = 1024 * 1024
MAX_SCENES = 256

class CapsuleError(ValueError):
    pass

@dataclass(frozen=True)
class Scene:
    id: str
    title: str
    seed: str
    open_space: str

@dataclass(frozen=True)
class Capsule:
    id: str
    title: str
    sha256: str
    source_bytes: bytes
    scenes: tuple[Scene, ...]
    source_format: str = "canticle-cassette-authoring-draft/0"


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CapsuleError("duplicate JSON member: " + key)
        result[key] = value
    return result


def _invalid_constant(value):
    raise CapsuleError("non-JSON numeric constant: " + value)


def _float(value):
    parsed = float(value)
    if not math.isfinite(parsed):
        raise CapsuleError("non-finite JSON number")
    return parsed


def _text(obj, key, *, optional=False):
    value = obj.get(key, "" if optional else None)
    if not isinstance(value, str) or (not optional and not value.strip()):
        raise CapsuleError("expected " + key + " to be text")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise CapsuleError("invalid Unicode in " + key) from exc
    return value


def import_bytes(data: bytes, expected_sha256=None) -> Capsule:
    """Import exact UTF-8 source bytes. Deposit never resolves any asset/link.

    This validates the playable cassette core, not the full authoring JSON Schema
    (optional weather/location structures need the schema validator separately).
    """
    if not isinstance(data, bytes) or not data or len(data) > MAX_BYTES:
        raise CapsuleError("source must be 1..1048576 bytes")
    digest = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None:
        if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            raise CapsuleError("expected digest must be lowercase SHA256")
        if digest != expected_sha256:
            raise CapsuleError("source digest mismatch")
    try:
        obj = json.loads(data.decode("utf-8"), object_pairs_hook=_pairs,
                         parse_constant=_invalid_constant, parse_float=_float)
    except CapsuleError:
        raise
    except (ValueError, RecursionError) as exc:
        raise CapsuleError("invalid UTF-8 JSON source") from exc
    if not isinstance(obj, dict):
        raise CapsuleError("capsule must be an object")
    if obj.get("format") != "canticle-cassette-authoring-draft" or type(obj.get("version")) is not int or obj["version"] != 0:
        raise CapsuleError("unsupported capsule format/version; mv2 needs its own adapter")
    identity = _text(obj, "id")
    sleeve = obj.get("sleeve")
    if not isinstance(sleeve, dict):
        raise CapsuleError("missing sleeve")
    title = _text(sleeve, "title")
    scenes = obj.get("scenes")
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= MAX_SCENES:
        raise CapsuleError("expected 1..256 scenes")
    imported, ids = [], set()
    for scene in scenes:
        if not isinstance(scene, dict):
            raise CapsuleError("scene must be an object")
        sid = _text(scene, "id")
        if sid in ids:
            raise CapsuleError("duplicate scene ID")
        ids.add(sid)
        imported.append(Scene(sid, _text(scene, "title", optional=True),
                              _text(scene, "seed"), _text(scene, "openSpace", optional=True)))
    return Capsule(identity, title, digest, data, tuple(imported))


def import_file(path, expected_sha256=None) -> Capsule:
    """Bound the read before parsing; caller selects a local file, never a URI."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise CapsuleError("source must be a regular local file")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(MAX_BYTES + 1)
    finally:
        os.close(fd)
    return import_bytes(data, expected_sha256)
