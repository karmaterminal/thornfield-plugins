# Validation receipt — 2026-11-24

Local parent execution, Python3.14, offline prototype only. Original18-test candidate98e9224 is superseded by the reviewed-finding repair and concrete expected-material snapshots below:

- Final `python3 tests/capsule-import/test_import.py -v`:20/20 pass, zero skipped. Both original and extended Winter Register fixtures consumed, with checked expected-material output snapshots.
- `python3 scripts/validate.py`:0 errors.
- `bash scripts/validate.sh`:exit0; final capsule20, Copilot-live1, Copilot27, review85, sink45, summon54 tests reported by wrapper. The wrapper does not expose skip counts for inherited suites; do not infer live Copilot access from that one-test row.
- Duplicate-scene guard removed temporarily, with tests unchanged: targeted duplicate-scene test fails exit1 (CapsuleError not raised). Restored guard: full focused suite18/18 pass exit0. Only the isolated candidate was faulted; original source restored before handoff.
- Independent source review found one P2: CPython large-integer decoder limits leaked raw ValueError. Parent reproduced a failing unchanged regression at98e9224; repair normalizes decoder ValueError while retaining CapsuleError details. Repair-only revert brings back RED/exit1; restored repair gives GREEN/19 tests before adding the material snapshot test. Reviewer did not execute tests; this closure is parent-verified, not a second independent approval.
- `git diff --check`:clean.

Not performed: full authoring-schema validation, canonical memvid2 roundtrip, inference, cadence/timeline/plot performance, playback/replay/recording, Canticle/Discord output, recipient encounter, installed plugin proof or Project-57 writes. Independent review is tracked separately and is not implied by these parent results.
