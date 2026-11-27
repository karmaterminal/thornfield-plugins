"""One injected player workload step; no scheduler, network or channel authority."""

from dataclasses import dataclass
from typing import Callable

from timeline import Record, Timeline, TimelineError, TimelineTake, advance_timeline


@dataclass(frozen=True)
class Binding:
    stream: str
    channel: str


@dataclass(frozen=True)
class Invocation:
    run_id: str
    source_id: str
    tick: int
    listen: tuple[Binding, ...]
    sing: tuple[Binding, ...]


@dataclass(frozen=True)
class Delivery:
    key: str
    channel: str
    record: Record


def _valid_name(value: str) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= 128


def _validate(source: Timeline, take: TimelineTake, invocation: Invocation) -> None:
    if (not isinstance(invocation, Invocation) or not _valid_name(invocation.run_id)
        or invocation.source_id != source.id or invocation.tick != take.next_tick):
        raise TimelineError("invalid workload identity or tick")
    declared = {stream.id: stream.direction for stream in source.streams}
    for direction in ("listen", "sing"):
        bindings = getattr(invocation, direction)
        if (not isinstance(bindings, tuple)
            or len({b.stream for b in bindings if isinstance(b, Binding)}) != len(bindings)):
            raise TimelineError("invalid workload bindings")
        for binding in bindings:
            if (not isinstance(binding, Binding) or declared.get(binding.stream) != direction
                or not _valid_name(binding.channel)):
                raise TimelineError("invalid workload binding")
    if {b.stream for b in invocation.sing} != {s.id for s in source.streams if s.direction == "sing"}:
        raise TimelineError("every sing stream needs an explicit binding")


def play_one_tick(
    source: Timeline,
    take: TimelineTake,
    invocation: Invocation,
    *,
    receive: Callable[[Binding, int], tuple[Record, ...]],
    infer: Callable,
    save: Callable[[TimelineTake], None],
    send: Callable[[Delivery], None],
) -> TimelineTake:
    """Elect, infer, save, then send. The sink must deduplicate delivery keys.

    A failed save sends nothing. A failed send leaves a saved take and must be
    recovered from that take without re-inference by a future dispatcher.
    """
    _validate(source, take, invocation)
    inputs = []
    for binding in invocation.listen:
        received = receive(binding, invocation.tick)
        if not isinstance(received, tuple):
            raise TimelineError("receiver returned invalid records")
        if any(not isinstance(r, Record) or r.stream != binding.stream for r in received):
            raise TimelineError("receiver crossed a stream binding")
        inputs.extend(received)
    advanced = advance_timeline(source, take, listen=tuple(inputs), infer=infer)
    outputs = advanced.sung[len(take.sung):]
    channels = {binding.stream: binding.channel for binding in invocation.sing}
    deliveries = tuple(Delivery(f"{invocation.run_id}:{invocation.tick}:{index}",
                                channels[record.stream], record)
                       for index, record in enumerate(outputs))
    save(advanced)
    for delivery in deliveries:
        send(delivery)
    return advanced
