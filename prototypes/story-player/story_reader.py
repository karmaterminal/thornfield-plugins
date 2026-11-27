"""Bounded, read-only thornfield.story.v1 graph reader.

The source bytes are the authority for identity and authored metadata. Parsing
neither executes cues nor grants a caller permission to play or publish them.
"""
from dataclasses import dataclass
import hashlib
import json
import math
import re


MAX_BYTES = 1024 * 1024
MAX_SCENES = 256


class StoryError(ValueError):
    pass


@dataclass(frozen=True)
class Choice:
    label: str
    next: str


@dataclass(frozen=True)
class StoryScene:
    id: str
    seed: str
    choices: tuple[Choice, ...]
    next: str | None
    end: bool
    beat: int | None
    duration_beats: int
    open_space: str | None
    location_ref: str | None
    cues: tuple[dict, ...]
    authored: dict


@dataclass(frozen=True)
class StorySource:
    id: str
    sha256: str
    source_bytes: bytes
    start: str
    scenes: tuple[StoryScene, ...]
    title: str
    authored: dict


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise StoryError("duplicate JSON key: " + key)
        result[key] = value
    return result


def _constant(value):
    raise StoryError("non-JSON constant: " + value)


def _float(value):
    number = float(value)
    if not math.isfinite(number):
        raise StoryError("non-finite JSON number")
    return number


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise StoryError(name + " must be nonblank text")
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise StoryError("invalid Unicode in " + name) from exc
    return value


def _optional_text(value, name):
    if value is None:
        return None
    if not isinstance(value, str):
        raise StoryError(name + " must be text")
    return value


def _scene(item):
    if not isinstance(item, dict):
        raise StoryError("scene must be an object")
    sid = _text(item.get("id"), "scene id")
    seed = _text(item.get("seed"), "scene seed")
    if "default" in item or "default_choice" in item:
        raise StoryError("default route is not supported")
    duration = item.get("duration_beats")
    if type(duration) is not int or duration <= 0:
        raise StoryError("invalid duration_beats")
    beat = item.get("beat")
    if beat is not None and (type(beat) is not int or beat < 0):
        raise StoryError("invalid scene beat")
    has_choices, has_next, has_end = ("choices" in item, "next" in item,
                                      "end" in item)
    if sum((has_choices, has_next, has_end)) != 1:
        raise StoryError("scene needs exactly one route form")
    choices = ()
    next_id = None
    end = False
    if has_choices:
        raw = item["choices"]
        if not isinstance(raw, list) or not raw:
            raise StoryError("choices must be nonempty")
        seen = set()
        parsed = []
        for choice in raw:
            if not isinstance(choice, dict) or set(choice) != {"label", "next"}:
                raise StoryError("choice needs label and next")
            label = _text(choice["label"], "choice label")
            if label in seen:
                raise StoryError("duplicate choice label")
            seen.add(label)
            parsed.append(Choice(label, _text(choice["next"], "choice target")))
        choices = tuple(parsed)
    elif has_next:
        next_id = _text(item["next"], "next target")
    else:
        if item["end"] is not True:
            raise StoryError("terminal must be end:true")
        end = True
    raw_cues = item.get("cues", [])
    if not isinstance(raw_cues, list):
        raise StoryError("cues must be a list")
    cue_ids = set()
    for cue in raw_cues:
        if not isinstance(cue, dict):
            raise StoryError("cue must be an object")
        at = cue.get("at_beat")
        if type(at) is not int or at < 0 or at > duration:
            raise StoryError("invalid cue at_beat")
        cue_id = _text(cue.get("id"), "cue id")
        if cue_id in cue_ids:
            raise StoryError("duplicate cue ID")
        cue_ids.add(cue_id)
        _text(cue.get("type"), "cue type")
        _text(cue.get("prompt"), "cue prompt")
    return StoryScene(sid, seed, choices, next_id, end, beat, duration,
                      _optional_text(item.get("open_space"), "open_space"),
                      _optional_text(item.get("location_ref"), "location_ref"),
                      tuple(raw_cues), item)


def read_story_bytes(raw: bytes, expected_sha256: str | None = None) -> StorySource:
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_BYTES:
        raise StoryError("source must be 1..1048576 bytes")
    digest = hashlib.sha256(raw).hexdigest()
    if expected_sha256 is not None:
        if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            raise StoryError("expected digest must be lowercase SHA256")
        if digest != expected_sha256:
            raise StoryError("source digest mismatch")
    try:
        obj = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                         parse_constant=_constant, parse_float=_float)
    except StoryError:
        raise
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise StoryError("invalid UTF-8 JSON story") from exc
    if not isinstance(obj, dict) or obj.get("schema") != "thornfield.story.v1":
        raise StoryError("unsupported story schema")
    start = _text(obj.get("start"), "start")
    raw_scenes = obj.get("scenes")
    if not isinstance(raw_scenes, list) or not 1 <= len(raw_scenes) <= MAX_SCENES:
        raise StoryError("expected 1..256 scenes")
    scenes = tuple(_scene(item) for item in raw_scenes)
    by_id = {scene.id: scene for scene in scenes}
    if len(by_id) != len(scenes):
        raise StoryError("duplicate scene ID")
    if start not in by_id:
        raise StoryError("missing start scene")
    edges = {}
    for scene in scenes:
        targets = tuple(choice.next for choice in scene.choices) if scene.choices else (() if scene.end else (scene.next,))
        if any(target not in by_id for target in targets):
            raise StoryError("missing branch target")
        edges[scene.id] = targets
    visiting, visited = set(), set()

    def visit(sid):
        if sid in visiting:
            raise StoryError("cycle in story graph")
        if sid in visited:
            return
        visiting.add(sid)
        for target in edges[sid]:
            visit(target)
        visiting.remove(sid)
        visited.add(sid)

    visit(start)
    if len(visited) != len(scenes):
        raise StoryError("unreachable scene")
    return StorySource("thornfield.story.v1:sha256:" + digest, digest, raw,
                       start, scenes, _text(obj.get("title"), "title"), obj)
