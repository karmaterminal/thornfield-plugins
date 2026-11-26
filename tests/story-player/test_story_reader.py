import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "prototypes/story-player"))
from story_reader import StoryError, read_story_bytes
from player import PlayError, advance, start


class StoryReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = (ROOT / "tests/story-player/rune-seven-eleven-score.json").read_bytes()

    def read_changed(self, change):
        obj = json.loads(self.raw)
        change(obj)
        return read_story_bytes(json.dumps(obj).encode())

    def test_exact_bytes_identity_metadata_and_player_choice_boundary(self):
        digest = hashlib.sha256(self.raw).hexdigest()
        source = read_story_bytes(self.raw, digest)
        self.assertEqual(source.source_bytes, self.raw)
        self.assertEqual(source.id, "thornfield.story.v1:sha256:" + digest)
        self.assertEqual(source.authored["reader_notes"]["authority"],
                         json.loads(self.raw)["reader_notes"]["authority"])
        self.assertEqual(source.scenes[0].cues[0]["id"], "porch-cue-1")
        with self.assertRaises(PlayError):
            advance(source, start(source, "unanswered"), text="At the porch",
                    provenance="authored")
        with self.assertRaisesRegex(StoryError, "digest mismatch"):
            read_story_bytes(self.raw, "0" * 64)

    def test_duplicate_nested_json_key_refused(self):
        raw = self.raw.replace(b'"fiction": true,',
                               b'"fiction": true, "fiction": false,', 1)
        with self.assertRaisesRegex(StoryError, "duplicate JSON key"):
            read_story_bytes(raw)

    def test_graph_requires_resolved_acyclic_reachable_explicit_routes(self):
        mutations = (
            lambda o: o["scenes"][0].update(next="road"),
            lambda o: o["scenes"][0]["choices"][0].update(next="missing"),
            lambda o: o["scenes"][0]["choices"][1].update(label="Read the list"),
            lambda o: o["scenes"][0]["choices"][1].update(label=" "),
            lambda o: o["scenes"][6].update(next="porch", end=False),
            lambda o: o["scenes"].append({"id": "island", "seed": "isolated",
                                           "duration_beats": 1, "end": True}),
            lambda o: o["scenes"][0].update(duration_beats=0),
            lambda o: o["scenes"][0]["cues"][0].update(at_beat=99),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate), self.assertRaises(StoryError):
                self.read_changed(mutate)


if __name__ == "__main__":
    unittest.main()
