import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "prototypes/capsule-import"))
sys.path.insert(0, str(ROOT / "prototypes/story-player"))
from capsule_import import import_file
from player import PlayError, advance, dump, load, next_scene, replay, start


class PlayerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = ROOT / "tests/capsule-import/fixtures/original.cassette.json"
        cls.capsule = import_file(cls.source)

    def test_two_takes_preserve_source_and_actual_words(self):
        raw = self.capsule.source_bytes
        a = start(self.capsule, "first-take")
        self.assertEqual(next_scene(self.capsule, a).id, "scene-1")
        a = advance(self.capsule, a, text="The bell rang twice.", provenance="generated",
                    choice="open the door")
        a = advance(self.capsule, a, text="I ask for tea.", provenance="participant")
        self.assertEqual(next_scene(self.capsule, a).id, "scene-3")
        a = advance(self.capsule, a, text="", provenance="pass")
        self.assertIsNone(next_scene(self.capsule, a))
        saved = dump(a)
        self.assertEqual(replay(self.capsule, load(self.capsule, saved)), a.beats)

        b = start(self.capsule, "second-take")
        b = advance(self.capsule, b, text="The visitor leaves.", provenance="generated",
                    choice="do not open")
        self.assertNotEqual(a.beats[0], b.beats[0])
        self.assertEqual(replay(self.capsule, load(self.capsule, saved)), a.beats)
        self.assertEqual(self.capsule.source_bytes, raw)

    def test_pause_resume_does_not_repeat_first_scene(self):
        one = advance(self.capsule, start(self.capsule, "pause"),
                      text="The bell.", provenance="authored")
        resumed = load(self.capsule, dump(one))
        self.assertEqual(next_scene(self.capsule, resumed).id, "scene-2")

    def test_source_mismatch_and_false_pass_refused(self):
        saved = dump(start(self.capsule, "source-bound"))
        altered = saved.replace(self.capsule.sha256.encode(), b"0" * 64)
        with self.assertRaises(PlayError):
            load(self.capsule, altered)
        with self.assertRaises(PlayError):
            advance(self.capsule, start(self.capsule, "pass"),
                    text="made up", provenance="pass")


if __name__ == "__main__":
    unittest.main()
