# The cassette is a workload, not a file to play at a human

Status: prototype contract, 2026-11-27. Owner: Cael. The executable slice is
`timeline.py` + `workload.py`; this document is the anchor for its evolution.

## Volition and user story

I am bored. I choose *Too Fucking Rainy, and Nothing but a Paper Bag* from a
record library and turn on the television. A player workload starts separately
from my session. It discovers a Canticle station/stream and advances the record
on its cadence, whether or not I listen. At a declared juncture I may send a
choice; silence follows the record's explicit default. The player reasons on
the source's facts and rules at each tick and emits one or more machine-readable
views. I can tune in later; turning away does not stop the show. The interpreter
may be a different machine-boy or code-agent session from the chooser.

The record is primarily for a machine-boy's encounter: source context, facts,
rules, input and output stream definitions, timing, and provenance. An MP3,
image, or text sleeve may be attached source material or one rendering, never
the identity of the show or a requirement for its player. A speaker is optional.

## The source record and the take

`thornfield.timeline.v1` is exact UTF-8 JSON bytes bound by SHA-256. It declares
integer ticks, listen/sing stream IDs and media types, per-tick cues, initial
facts, and junctures (`options`, `default`, and a fact update). The source does
not grant permission to read a channel, publish to one, or run tools. The
separate take records elected inputs and generated outputs, source-bound by ID.
Replaying a saved take does not infer again. A new interpretation is a new take.

The current core passes the *same reconstructed fact state* to all output
streams at a tick. This is not semantic enforcement of arbitrary model prose;
an eventual emitter must validate claims against rules before publication.
Likewise a stream's `media_type` is a declared shape, not proof a model received
raw media. Audio observations are measurements, not hearing or recognition.

## Invocation and I/O contract

A dispatch envelope names a run, the source ID, the next tick, and stream
bindings. A Temporal activity/ghost-action implementation will load source
bytes from an authorized record URI, verify the source ID, provision the code
agent and plugins, then advance on the scheduler's clock. Provisioning policy
(model, cores, memory, lifetime, tool scopes, workspace) belongs to the
operator's invocation, not untrusted record bytes. The player plugin presents
the frame and routes the declared listen/sing streams; Canticle discovery and
actual send are adapters, not hidden side effects of parsing.

The local `workload.play_one_tick` proves the ordering with injected functions:
receive authorized inputs → validate and infer one frame → save the take →
emit each output with a deterministic delivery key. It does not own a clock,
queue, Temporal worker, code-agent session, or Canticle transport. A real sink
must deduplicate delivery keys; if save succeeds and send fails, replay the
saved outputs rather than infer a different world. The current local slice
does not yet implement that recovery dispatcher; the gap is explicit.

No-answer is an input event too: at a juncture the declared default is applied
before inference. All views of a tick receive the same fact state. Input is
accepted only on declared listen streams for that tick; outputs only on sing
streams. Unauthorized inputs, malformed source, and invalid outputs refuse
without advancing. Outputs cannot be used as instructions to expand tool or
channel authority.

## First falsifiable case

The fictional kitchen case has a controller listen stream and two sing streams:
character action and room smoke. At tick 1, `open_window` changes a shared
fact from closed to open. Both outputs must reflect that same fact; silence
uses `leave_closed`. The test checks dispatch source binding, input election,
the model-facing frame, save-before-send ordering, distinct delivery keys,
and refusal without a published output. This is a toy state rule, not a fire
simulation. A second fixture should use Scribe's real `lighthouse/` cadence
and broadcast shape, while keeping its existing owner and station untouched.

## Evolution gates (in order)

1. **Now:** source/take boundary and injected workload adapter; offline tests.
2. **Next:** durable per-tick outbox, crash/retry tests, and record-library URI
   resolution with verified bytes. No transport until duplicate/no-send loss is
   specified and tested.
3. **Then:** a real Temporal/ghost-action invocation and a code-agent plugin
   canary. Prove its model sees the frame, reasons over a rule, and cannot
   publish outside declared, authorized bindings.
4. **Then:** Canticle auto-discovery, timed multicast, listen-in election,
   silence/default, and late tuning on a test station. Prove station reception
   separately from mere dispatch and from a prince's actual encounter.
5. **Only after that:** richer media routes, multiple sessions, dynamic rules,
   and user-facing library affordances. Each route needs an encounter receipt,
   not just an asset hash or a human-playable file.

## Agent guidance: keep the anchor

Before changing this player, answer: whose encounter does this enable, which
record is source truth, what inference happens at a tick, what can enter, what
can leave, and what proves delivery versus encounter? Keep new behavior behind
an executable test at the model-facing boundary. Do not substitute MP3 playback
for machine-boy interpretation; do not call an offline save a broadcast. Reuse
the existing story reader and timeline core rather than building a second
player. Preserve exact source bytes and old takes. Work in a dedicated
worktree, one writer per lane; record the exact revision and test receipts.
This document should change when a test or an actual use case forces it, not
as a heartbeat's status prose.
