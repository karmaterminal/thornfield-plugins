# One offline replay core, not a live Beacon

`player.py` takes Elliott's bounded JSON importer result and records a sequence of
scene outcomes as a separate rendition. `next_scene` resumes at the next scene;
`replay` returns the saved beats without inference. A new interpretation starts a
new rendition. `pass` records no invented text, and generated, authored and
participant words retain distinct provenance labels. The immutable source bytes
and SHA256 stay in the importer, never rewritten by playback.

This is a small executable contract, not a scheduler, metronome, model caller,
Canticle sender, Discord webhook, persistent store or installed plugin. The caller
must obtain authorized words and choose cadence/choices; untrusted seed text
cannot grant tools or publication. Serialized renditions are local bytes; the
caller owns any storage, authorization and integrity protection. The first runnable
fixture is Elliott's original *Winter Register* cassette. Silas's unchanged
eight-beat 7:11 authoring score is preserved at
`tests/story-player/silas-seven-eleven-score.md` (SHA256
`995f7e39b69c09d7647c28c52d78ddc07dae3437645efa05d91aca651ec5520e`).
The test binds a simulated take to those exact bytes, saves after the receipt,
resumes at beat 6, and proves a fresh GIVEN take does not change the saved
RETURNED take. This is **not** a Markdown capsule importer, a real audience
ballot, or a live Beacon/Canticle delivery proof.

Choice labels are source-bound only for `thornfield.story.v1` graph sources.
For ordered cassettes, a `choice` is a free-text annotation, not a validated
answer or evidence that the score's author offered that label.

Run `python3 tests/story-player/test_player.py -v` from repository root.

Rune's exact `thornfield.story.v1` JSON score is preserved separately at
`tests/story-player/rune-seven-eleven-score.json` (SHA256
`05a0666337e78fa4c9a369f71cb66442400a5fd887f421aaa2a69198970c2ceb`).
`story_reader.read_story_bytes(raw, expected_sha256=None)` validates this
bounded v1 graph and hands an immutable source-byte/digest identity to the
existing replay core. Its capsule ID is
`thornfield.story.v1:sha256:<SHA256 of original bytes>`; title is not identity.
It rejects duplicate JSON keys, ambiguous route forms, missing targets,
cycles, unreachable scenes, malformed durations/cues and digest mismatch. A
branch requires an explicit offered choice; there is no default/fallthrough.
Authored metadata remains inert in the original bytes and parsed `authored`
fields. This is **not** an MV2 reader or exact-frame provenance proof, ballot
receipt, metronome, cue executor, or live performance. Scene `beat` is data,
not an auto-advance clock. Duration, speed and effects remain explicit
integration gaps rather than silently executed from cue text.

Run `python3 tests/story-player/test_story_reader.py -v` for this boundary.

## Elected timeline I/O slice

`timeline.py` adds a separate, exact-byte `thornfield.timeline.v1` source with
named `listen` and `sing` streams and integer ticks. A caller explicitly
advances each tick, supplies authorized listen-in records, and provides the
inference function. That function receives one model-facing frame containing
current input, authored cues, and prior emissions; it returns records on any
declared sing-out streams. The same tick can emit several views of one event
(for example, a character's action and the changing smoke in a kitchen).
The source can also declare initial facts and choice junctures. Each juncture
names a listen-in stream, offered options, a default for no answer, and the
resulting fact value. A vote or default updates the shared facts *before* both
sing-out views at that tick; a saved take replays the elected input, and later
ticks reconstruct the same fact state. Invalid or duplicate votes refuse before
inference. The test exercises a kitchen-window vote, the no-answer default,
both outputs, and save/reopen continuation. The authored record is separate
from the input/output take, so a new take need not rewrite the source.
Takes save and reopen their exact elected input/output records without
inference. The test exercises two outputs, a later controller input, source
binding, wrong-direction refusal and save/reopen at this boundary. Run
`python3 tests/story-player/test_timeline.py -v`.

This is **not** a real-time clock, game-controller transport, model provider,
Canticle delivery, or evidence of model encounter. Stream declarations are
data, not permissions; a caller must authorize actual listening and sending.
Facts and choices reach the inference boundary as data; this prototype does
not prove that arbitrary model prose obeys them. The caller must validate or
constrain semantic outputs before external emission. MP3 is not part of this
timeline contract or required for native I/O.

`audio_observation.py` is a first bounded media path: decode exact MP3 bytes
with ffmpeg, measure four-second dynamics/spectral-centroid bins, and render
those measurements as a source-bound text record that a timeline may elect to
listen to. The model-facing test generates a real MP3, decodes it, and passes
the derived record into a timeline frame. This is **signal analysis**, not a
transcript, semantic sound recognition or raw-audio model input. It cannot tell
birds from rain; that limitation is explicit rather than filled by invention.
Run `python3 tests/story-player/test_audio_observation.py -v` (requires ffmpeg
and NumPy). A future audio-capable route could deliver the original bytes
instead, with a distinct encounter receipt.
The test includes Elliott's immutable 18-specimen/19-invocation byte corpus
(`tests/story-player/fixtures/elliott-story-conformance-20261125.tar.gz`,
SHA256 `f865e53f483b0a2e847cb7673559f0a0cc0755e7079008ef18751cd67dca386c`).
It checks the exact bytes and digest of every specimen, reader refusals, and
distinct content-addressed IDs for semantically equal but differently formatted
source. That is reader conformance, not MV2 extraction or live playback acceptance.
