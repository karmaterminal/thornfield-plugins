import hashlib
import json
import base64
from pathlib import Path
import sys
import tarfile
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

    def test_elliott_byte_corpus_at_reader_boundary(self):
        archive = ROOT / "tests/story-player/fixtures/elliott-story-conformance-20261125.tar.gz"
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(),
                         "f865e53f483b0a2e847cb7673559f0a0cc0755e7079008ef18751cd67dca386c")
        prefix = "story-conformance-20261125/"
        with tarfile.open(archive, "r:gz") as bundle:
            def member(path):
                stream = bundle.extractfile(prefix + path)
                self.assertIsNotNone(stream)
                return stream.read()

            manifest = json.loads(member("manifest.json"))
            self.assertEqual((len(manifest["specimens"]), len(manifest["cases"])), (18, 19))
            specimens = {item["id"]: item for item in manifest["specimens"]}
            accepted = {}
            for case in manifest["cases"]:
                with self.subTest(case=case["id"]):
                    specimen = specimens[case["specimen"]]
                    storage = specimen["storage"]
                    raw = member(storage["path"])
                    if storage["encoding"] == "base64":
                        raw = base64.b64decode(raw.strip(), validate=True)
                    self.assertEqual(len(raw), specimen["byteLength"])
                    self.assertEqual(hashlib.sha256(raw).hexdigest(), specimen["sha256"])
                    if case["expectedPolicyOutcome"] == "reject":
                        with self.assertRaises(StoryError):
                            read_story_bytes(raw, case["suppliedDigest"])
                    else:
                        source = read_story_bytes(raw, case["suppliedDigest"])
                        self.assertEqual(source.source_bytes, raw)
                        self.assertEqual(source.sha256, specimen["sha256"])
                        self.assertEqual(source.id, case["expectedCapsuleId"])
                        accepted[case["id"]] = source
            self.assertNotEqual(accepted["01-baseline"].id, accepted["02-reformatted"].id)
            self.assertEqual(accepted["01-baseline"].authored,
                             accepted["02-reformatted"].authored)


if __name__ == "__main__":
    unittest.main()
