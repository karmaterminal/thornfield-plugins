# Validation receipt — 2026-11-24

Local parent execution, Python3.14, offline prototype only:

- `python3 tests/capsule-import/test_import.py -v`:18/18 pass, zero skipped. Both original and extended Winter Register fixtures consumed.
- `python3 scripts/validate.py`:0 errors.
- `bash scripts/validate.sh`:exit0; capsule18, Copilot-live1, Copilot27, review85, sink45, summon54 tests reported by wrapper. The wrapper does not expose skip counts for inherited suites; do not infer live Copilot access from that one-test row.
- Duplicate-scene guard removed temporarily, with tests unchanged: targeted duplicate-scene test fails exit1 (CapsuleError not raised). Restored guard: full focused suite18/18 pass exit0. Only the isolated candidate was faulted; original source restored before handoff.
- `git diff --check`:clean.

Not performed: full authoring-schema validation, canonical memvid2 roundtrip, inference, cadence/timeline/plot performance, playback/replay/recording, Canticle/Discord output, recipient encounter, installed plugin proof or Project-57 writes. Independent review is tracked separately and is not implied by these parent results.
