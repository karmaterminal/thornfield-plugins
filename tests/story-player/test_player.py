import sys
from pathlib import Path
import unittest
import hashlib
import re
from types import SimpleNamespace

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

    def test_silas_exact_score_resume_and_independent_receipt_ballots(self):
        # This is the author's unchanged Markdown score, not a claimed capsule import.
        raw = (ROOT / "tests/story-player/silas-seven-eleven-score.md").read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        self.assertEqual(len(raw), 7161)
        self.assertEqual(digest, "995f7e39b69c09d7647c28c52d78ddc07dae3437645efa05d91aca651ec5520e")
        lines = re.findall(r"(?m)^([1-8])\. (\d\d:\d\d) / .*?: ([A-Z ]+)\.", raw.decode("utf-8"))
        self.assertEqual([int(number) for number, _, _ in lines], list(range(1, 9)))
        self.assertIn("RETURNED / BORROWED / GIVEN", raw.decode("utf-8"))
        capsule = SimpleNamespace(id="silas-seven-eleven-score", sha256=digest,
                                  scenes=tuple(SimpleNamespace(id=f"beat-{number}")
                                               for number, _, _ in lines))

        first = start(capsule, "first-take")
        for number in range(1, 5):
            first = advance(capsule, first, text=lines[number - 1][2], provenance="authored")
        first = advance(capsule, first, text="RETURNED", provenance="participant",
                        choice="RETURNED")
        paused = dump(first)
        resumed = load(capsule, paused)
        self.assertEqual(next_scene(capsule, resumed).id, "beat-6")
        first = advance(capsule, resumed, text="the bell belonged to the house",
                        provenance="authored")
        for number in (7, 8):
            first = advance(capsule, first, text=lines[number - 1][2], provenance="authored")
        self.assertIsNone(next_scene(capsule, first))

        second = start(capsule, "fresh-take")
        for number in range(1, 5):
            second = advance(capsule, second, text=lines[number - 1][2], provenance="authored")
        second = advance(capsule, second, text="GIVEN", provenance="authored",
                         choice="GIVEN")
        second = advance(capsule, second, text="the shop has never received a present",
                         provenance="authored")
        self.assertEqual(replay(capsule, load(capsule, dump(first)))[4].choice, "RETURNED")
        self.assertEqual(replay(capsule, second)[4].choice, "GIVEN")
        self.assertEqual(replay(capsule, first)[5].text, "the bell belonged to the house")
        self.assertEqual(replay(capsule, second)[5].text,
                         "the shop has never received a present")


if __name__ == "__main__":
    unittest.main()
