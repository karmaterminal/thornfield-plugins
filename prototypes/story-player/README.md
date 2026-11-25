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
fixture is Elliott's original *Winter Register* cassette. Silas's eight-scene
7:11 score is the intended first new story fixture once its exact source is handed
off; this code does not claim to contain it yet.

Run `python3 tests/story-player/test_player.py -v` from repository root.
