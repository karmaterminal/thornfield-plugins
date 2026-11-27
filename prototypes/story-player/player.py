"""Offline, deterministic replay core. No inference, clock, network or delivery.

The caller supplies authored text for each played scene. A saved rendition is a
record of that text and of explicit choices, never a replacement for the source.
"""
from dataclasses import dataclass, replace
import json
from typing import Literal


class PlayError(ValueError):
    pass


@dataclass(frozen=True)
class Beat:
    scene_id: str
    text: str
    provenance: Literal["authored", "generated", "participant", "pass"]
    choice: str | None = None


@dataclass(frozen=True)
class Rendition:
    rendition_id: str
    source_sha256: str
    source_id: str
    beats: tuple[Beat, ...] = ()


def start(capsule, rendition_id: str) -> Rendition:
    if not isinstance(rendition_id, str) or not rendition_id.strip():
        raise PlayError("rendition ID required")
    return Rendition(rendition_id, capsule.sha256, capsule.id)


def next_scene(capsule, rendition: Rendition):
    _check_source(capsule, rendition)
    if hasattr(capsule, "start"):
        return _graph_next(capsule, rendition)
    if len(rendition.beats) > len(capsule.scenes):
        raise PlayError("rendition exceeds source scenes")
    return capsule.scenes[len(rendition.beats)] if len(rendition.beats) < len(capsule.scenes) else None


def advance(capsule, rendition: Rendition, *, text: str, provenance: str,
            choice: str | None = None) -> Rendition:
    """Record one scene outcome; the caller chooses the cadence and content."""
    scene = next_scene(capsule, rendition)
    if scene is None:
        raise PlayError("rendition complete")
    if provenance not in ("authored", "generated", "participant", "pass"):
        raise PlayError("invalid provenance")
    if not isinstance(text, str) or (provenance != "pass" and not text.strip()):
        raise PlayError("scene text required")
    if provenance == "pass" and text:
        raise PlayError("pass must not invent text")
    if choice is not None and (not isinstance(choice, str) or not choice.strip()):
        raise PlayError("invalid choice")
    if hasattr(capsule, "start"):
        _graph_route(scene, choice)
    return replace(rendition, beats=rendition.beats +
                   (Beat(scene.id, text, provenance, choice),))


def replay(capsule, rendition: Rendition) -> tuple[Beat, ...]:
    """Return saved bytes, without invoking a generator or changing the source."""
    _check_source(capsule, rendition)
    if hasattr(capsule, "start"):
        _graph_next(capsule, rendition)
        return rendition.beats
    if len(rendition.beats) > len(capsule.scenes):
        raise PlayError("rendition exceeds source scenes")
    for beat, scene in zip(rendition.beats, capsule.scenes):
        if beat.scene_id != scene.id:
            raise PlayError("scene sequence mismatch")
    return rendition.beats


def dump(rendition: Rendition) -> bytes:
    payload = {"version": 0, "rendition_id": rendition.rendition_id,
               "source_sha256": rendition.source_sha256, "source_id": rendition.source_id,
               "beats": [vars(beat) for beat in rendition.beats]}
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def load(capsule, data: bytes) -> Rendition:
    if not isinstance(data, bytes) or len(data) > 1024 * 1024:
        raise PlayError("invalid rendition bytes")
    try:
        obj = json.loads(data.decode("utf-8"))
        if (not isinstance(obj, dict) or
            set(obj) != {"version", "rendition_id", "source_sha256", "source_id", "beats"} or
            type(obj["version"]) is not int or obj["version"] != 0 or
            not isinstance(obj["rendition_id"], str) or not obj["rendition_id"].strip() or
            not isinstance(obj["beats"], list)):
            raise ValueError("unsupported rendition")
        beats = []
        for item in obj["beats"]:
            if (not isinstance(item, dict) or
                set(item) != {"scene_id", "text", "provenance", "choice"} or
                not isinstance(item["scene_id"], str) or
                not isinstance(item["text"], str) or
                item["provenance"] not in ("authored", "generated", "participant", "pass") or
                (item["choice"] is not None and
                 (not isinstance(item["choice"], str) or not item["choice"].strip()))):
                raise ValueError("invalid beat")
            if item["provenance"] == "pass" and item["text"]:
                raise ValueError("pass with text")
            if item["provenance"] != "pass" and not item["text"].strip():
                raise ValueError("missing text")
            beats.append(Beat(**item))
        result = Rendition(obj["rendition_id"], obj["source_sha256"], obj["source_id"], tuple(beats))
        replay(capsule, result)
        return result
    except (UnicodeError, ValueError, TypeError, KeyError, AttributeError) as exc:
        raise PlayError("invalid rendition") from exc


def _check_source(capsule, rendition: Rendition):
    if rendition.source_sha256 != capsule.sha256 or rendition.source_id != capsule.id:
        raise PlayError("source identity mismatch")


def _graph_route(scene, choice: str | None) -> str | None:
    choices = getattr(scene, "choices", ())
    if choices:
        matches = [item.next for item in choices if item.label == choice]
        if len(matches) != 1:
            raise PlayError("choice must match one offered branch")
        return matches[0]
    if choice is not None:
        raise PlayError("choice on non-branching scene")
    return getattr(scene, "next", None)


def _graph_next(capsule, rendition: Rendition):
    scenes = {scene.id: scene for scene in capsule.scenes}
    if len(scenes) != len(capsule.scenes) or capsule.start not in scenes:
        raise PlayError("invalid source graph")
    scene_id = capsule.start
    for beat in rendition.beats:
        if scene_id is None or beat.scene_id != scene_id:
            raise PlayError("scene sequence mismatch")
        scene_id = _graph_route(scenes[scene_id], beat.choice)
        if scene_id is not None and scene_id not in scenes:
            raise PlayError("branch target missing")
    return scenes[scene_id] if scene_id is not None else None
