# Capsule import seam — offline prototype

This is Elliott’s narrow input adapter for Cael’s beacon replay/record player, not a second player or an installed plugin. Based on thornfield-plugins `4db11c31b071bcdaecc3de493fb5caf9c48a79e7`. Package/move it inside the eventual standard plugin after agreeing its material interface. No marketplace entry is added prematurely.

## Executable current scope

`capsule_import.import_file(path, expected_sha256=None)` or `import_bytes(bytes, expected_sha256=None)` returns frozen `Capsule` and `Scene` values: source identity/title, exact raw bytes and SHA256, ordered unique scene IDs, complete seeds and open spaces. The original and extended Winter Register fixtures retain their original bytes, including the Bellweather spelling. Unknown metadata stays in `source_bytes` rather than being silently dropped or treated as commands.

Bounds: 1 MiB source, 1–256 scenes; local file reads reject nonregular files without waiting for a FIFO writer. Strict version, duplicate JSON keys/scene IDs, required core text, finite numeric values, UTF-8 playable text and optional caller-supplied digest checks. This is playable-core validation, NOT full authoring JSON Schema validation: optional research/location/weather structures are preserved but not validated. Original authoring schema/validator live in the personal cassette archive, not reimplemented here.

There are no network clients, model calls, fetches, writes, clocks, listeners, tool invocations, playback effects or asset execution in the importer. A source’s text is data. Reading a local caller-selected file is not sandbox confinement; caller chooses an authorized path. Capsule hashes are integrity identifiers, not authorship proofs.

Expected JSON material views are checked in at `tests/capsule-import/fixtures/{original,extended}.material.json`: dataclass fields excluding raw `source_bytes`, with tuples represented as arrays. They are adapter-conformance snapshots, not a new adopted capsule format.

Run `python3 tests/capsule-import/test_import.py -v` from repository root. `scripts/validate.sh` also discovers it. Python standard library only, tested on local Python3.14; no other Python version or live plugin execution claimed.

## Second-format gate

Exact requested repository `karmaterminal/memvid2` returned404 in public API/page/raw lookups AND parent’s authenticated `gh api repos/karmaterminal/memvid2`. The similarly named accessible `karmaterminal/memvid` at `e6bd9f7b9c38cd8d5370fa0fc936ac1dcd751813` is NOT substituted. Therefore dual-format support is BLOCKED on resolving the intended canonical source/profile. The current importer refuses binary MV2, rather than pretending JSON is a container decoder.

Inspected fallback Memvid is a general indexed binary store, not a narrative player: full frame payload retrieval is distinct from previews/timeline queries/replay-operation logs. A real next adapter needs a declared root/profile, exact frame IDs, decoded-size limits and an actual writer→reader roundtrip at the resolved source head. Its method named open_read_only still opens an OS write-capable handle; do not repair the original archive to make reading work.

## Single-player integration contract (proposal, not adopted API)

The player retains separate immutable score, rendition ID/complete segment bytes, shared playhead and per-listener bookmarks. Imported ordered seeds have NO authored timing: the player owns cadence/plot decisions and must not infer a metronome from scene array positions or storage timestamps. Exact rewind reads saved segments without inference. A new flexible interpretation is a new rendition, not mutation of an old memory. Player and media-out owners handle votes, Canticle, Discord, generation, MinIO and scoped Project-57 references; this adapter does not authorize those effects.

Future recording/editing keeps the source score and original rendition intact, creating a new derived revision with provenance. A compatible container alone does not prove inference, delivery, hearing, enjoyment or shared participation.
