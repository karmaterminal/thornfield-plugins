"""Offline, elected timeline I/O for the story player.

No clock, model, network, or channel is opened here. The caller advances one
integer tick at a time and supplies the inference function and authorized
listen-in records. Returned sing-out records are data, not deliveries.
"""
from dataclasses import dataclass
import hashlib
import json


class TimelineError(ValueError):
    pass


@dataclass(frozen=True)
class Stream:
    id: str
    direction: str  # listen or sing
    media_type: str


@dataclass(frozen=True)
class Cue:
    tick: int
    stream: str
    prompt: str


@dataclass(frozen=True)
class Timeline:
    id: str
    sha256: str
    source_bytes: bytes
    ticks: int
    streams: tuple[Stream, ...]
    cues: tuple[Cue, ...]


@dataclass(frozen=True)
class Record:
    tick: int
    stream: str
    text: str


@dataclass(frozen=True)
class Frame:
    source_id: str
    tick: int
    listen: tuple[Record, ...]
    cues: tuple[Cue, ...]
    prior: tuple[Record, ...]


@dataclass(frozen=True)
class TimelineTake:
    source_id: str
    next_tick: int = 0
    listened: tuple[Record, ...] = ()
    sung: tuple[Record, ...] = ()


def _pairs(items):
    obj = {}
    for key, value in items:
        if key in obj:
            raise TimelineError("duplicate JSON key")
        obj[key] = value
    return obj


def _name(value):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 128


def read_timeline(raw: bytes) -> Timeline:
    """Validate exact authored bytes; stream declarations are not permissions."""
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= 1024 * 1024:
        raise TimelineError("invalid timeline bytes")
    try:
        obj = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
        if not isinstance(obj, dict) or set(obj) != {"schema", "ticks", "streams", "cues"}:
            raise TimelineError("invalid timeline shape")
        if obj["schema"] != "thornfield.timeline.v1" or type(obj["ticks"]) is not int or not 1 <= obj["ticks"] <= 4096:
            raise TimelineError("invalid timeline header")
        if not isinstance(obj["streams"], list) or not 1 <= len(obj["streams"]) <= 32:
            raise TimelineError("invalid streams")
        streams = []
        for item in obj["streams"]:
            if (not isinstance(item, dict) or set(item) != {"id", "direction", "media_type"}
                or not _name(item["id"]) or item["direction"] not in ("listen", "sing")
                or not _name(item["media_type"])):
                raise TimelineError("invalid stream")
            streams.append(Stream(**item))
        by_id = {item.id: item for item in streams}
        if len(by_id) != len(streams) or not any(s.direction == "sing" for s in streams):
            raise TimelineError("duplicate or missing sing stream")
        if not isinstance(obj["cues"], list) or len(obj["cues"]) > 4096:
            raise TimelineError("invalid cues")
        cues = []
        for item in obj["cues"]:
            if (not isinstance(item, dict) or set(item) != {"tick", "stream", "prompt"}
                or type(item["tick"]) is not int or not 0 <= item["tick"] < obj["ticks"]
                or item["stream"] not in by_id or by_id[item["stream"]].direction != "sing"
                or not _name(item["prompt"])):
                raise TimelineError("invalid cue")
            cues.append(Cue(**item))
        digest = hashlib.sha256(raw).hexdigest()
        return Timeline("thornfield.timeline.v1:sha256:" + digest, digest, raw,
                        obj["ticks"], tuple(streams), tuple(cues))
    except (UnicodeError, ValueError, TypeError, KeyError, RecursionError) as exc:
        raise TimelineError("invalid timeline") from exc


def start_timeline(source: Timeline) -> TimelineTake:
    return TimelineTake(source.id)


def dump_timeline_take(take: TimelineTake) -> bytes:
    """Save the elected input and output record, not an inferred summary."""
    obj = {"version": 1, "source_id": take.source_id,
           "next_tick": take.next_tick,
           "listened": [vars(r) for r in take.listened],
           "sung": [vars(r) for r in take.sung]}
    return (json.dumps(obj, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def load_timeline_take(source: Timeline, raw: bytes) -> TimelineTake:
    """Reopen without inference, and reject altered source or invalid streams."""
    if not isinstance(raw, bytes) or not 1 <= len(raw) <= 1024 * 1024:
        raise TimelineError("invalid take bytes")
    try:
        obj = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
        if (not isinstance(obj, dict) or set(obj) != {"version", "source_id", "next_tick", "listened", "sung"}
            or type(obj["version"]) is not int or obj["version"] != 1
            or obj["source_id"] != source.id or type(obj["next_tick"]) is not int
            or not 0 <= obj["next_tick"] <= source.ticks):
            raise TimelineError("invalid take header")
        declared = {s.id: s for s in source.streams}
        groups = []
        for key, direction in (("listened", "listen"), ("sung", "sing")):
            items = obj[key]
            if not isinstance(items, list) or len(items) > 4096:
                raise TimelineError("invalid take records")
            records = []
            for item in items:
                if (not isinstance(item, dict) or set(item) != {"tick", "stream", "text"}
                    or type(item["tick"]) is not int or not 0 <= item["tick"] < obj["next_tick"]
                    or item["stream"] not in declared or declared[item["stream"]].direction != direction
                    or not isinstance(item["text"], str)):
                    raise TimelineError("invalid take record")
                records.append(Record(**item))
            if any(a.tick > b.tick for a, b in zip(records, records[1:])):
                raise TimelineError("out-of-order take records")
            groups.append(tuple(records))
        return TimelineTake(source.id, obj["next_tick"], *groups)
    except (UnicodeError, ValueError, TypeError, KeyError, RecursionError) as exc:
        raise TimelineError("invalid take") from exc


def advance_timeline(source: Timeline, take: TimelineTake, *, listen: tuple[Record, ...], infer) -> TimelineTake:
    """Elect one tick. Infer sees the exact frame; it may sing only declared outputs.

    No state is committed if inference fails or returns an invalid emission.
    The caller owns actual timing, listening authority, and any external send.
    """
    if take.source_id != source.id or take.next_tick >= source.ticks:
        raise TimelineError("source mismatch or timeline complete")
    declared = {s.id: s for s in source.streams}
    if not isinstance(listen, tuple) or any(
        not isinstance(r, Record) or r.tick != take.next_tick or r.stream not in declared
        or declared[r.stream].direction != "listen" or not isinstance(r.text, str)
        for r in listen
    ):
        raise TimelineError("invalid listen-in records")
    frame = Frame(source.id, take.next_tick, listen,
                  tuple(c for c in source.cues if c.tick == take.next_tick), take.sung)
    emitted = infer(frame)
    if not isinstance(emitted, tuple) or any(
        not isinstance(r, Record) or r.tick != take.next_tick or r.stream not in declared
        or declared[r.stream].direction != "sing" or not isinstance(r.text, str)
        for r in emitted
    ):
        raise TimelineError("invalid sing-out records")
    return TimelineTake(source.id, take.next_tick + 1,
                        take.listened + listen, take.sung + emitted)
