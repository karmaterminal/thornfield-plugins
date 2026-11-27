import json
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "prototypes/story-player"))
from audio_observation import observe_mp3, model_text, AudioError
from timeline import Record, advance_timeline, read_timeline, start_timeline


class AudioObservationTests(unittest.TestCase):
    def test_actual_mp3_decode_becomes_elected_model_facing_input(self):
        # Generate a tiny real MP3; no precomputed fixture or semantic guess.
        mp3 = subprocess.run(
            ["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
             "sine=frequency=440:duration=1", "-f", "mp3", "pipe:1"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True).stdout
        observation = observe_mp3(mp3)
        self.assertEqual(observation["schema"], "thornfield.audio-observation.v1")
        self.assertEqual(len(observation["bins"]), 1)
        self.assertGreater(observation["bins"][0]["rms"], 0)
        text = model_text(observation)
        self.assertIn(observation["source_sha256"], text)
        self.assertIn("not a transcript", text)

        source = read_timeline(json.dumps({
            "schema": "thornfield.timeline.v1", "ticks": 1,
            "streams": [{"id": "score", "direction": "listen", "media_type": "text/plain"},
                        {"id": "response", "direction": "sing", "media_type": "text/plain"}],
            "cues": [{"tick": 0, "stream": "response", "prompt": "Respond to the score"}],
        }).encode())
        seen = []
        take = advance_timeline(source, start_timeline(source),
                                listen=(Record(0, "score", text),),
                                infer=lambda frame: (seen.append(frame) or
                                                     (Record(0, "response", "A measured rise, not a source claim."),)))
        self.assertEqual(seen[0].listen[0].text, text)
        self.assertEqual(take.sung[0].stream, "response")

    def test_bad_audio_refuses(self):
        with self.assertRaises(AudioError):
            observe_mp3(b"not an mp3")


if __name__ == "__main__":
    unittest.main()
