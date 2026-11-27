"""Model-facing timeline I/O contract: no clock or network required."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "prototypes/story-player"))
from timeline import (Record, TimelineError, advance_timeline, read_timeline,
                      start_timeline)


def source_bytes():
    return json.dumps({
        "schema": "thornfield.timeline.v1", "ticks": 2,
        "streams": [
            {"id": "controller", "direction": "listen", "media_type": "text/plain"},
            {"id": "action", "direction": "sing", "media_type": "text/plain"},
            {"id": "smoke", "direction": "sing", "media_type": "text/plain"},
        ],
        "cues": [
            {"tick": 0, "stream": "action", "prompt": "Kitchen fire begins"},
            {"tick": 0, "stream": "smoke", "prompt": "Describe air quality"},
            {"tick": 1, "stream": "action", "prompt": "Continue from input"},
            {"tick": 1, "stream": "smoke", "prompt": "Update air quality"},
        ],
    }, sort_keys=True).encode()


class TimelineTests(unittest.TestCase):
    def test_two_sing_streams_and_one_listen_stream_reach_model_at_each_tick(self):
        source = read_timeline(source_bytes())
        seen = []

        def infer(frame):
            seen.append(frame)
            if frame.tick == 0:
                return (Record(0, "action", "I reach for the extinguisher."),
                        Record(0, "smoke", "Smoke gathers above the stove."))
            return (Record(1, "action", "I turn toward the exit."),
                    Record(1, "smoke", "The hallway remains clear."))

        take = start_timeline(source)
        take = advance_timeline(source, take, listen=(), infer=infer)
        take = advance_timeline(source, take,
                                listen=(Record(1, "controller", "Leave the kitchen"),),
                                infer=infer)
        self.assertEqual([f.tick for f in seen], [0, 1])
        self.assertEqual(seen[1].listen[0].text, "Leave the kitchen")
        self.assertEqual(len(seen[1].prior), 2)
        self.assertEqual([r.stream for r in take.sung], ["action", "smoke", "action", "smoke"])
        self.assertEqual(take.next_tick, 2)
        with self.assertRaises(TimelineError):
            advance_timeline(source, take, listen=(), infer=infer)

    def test_wrong_direction_and_tick_refuse_without_advancing(self):
        source = read_timeline(source_bytes())
        take = start_timeline(source)
        for invalid in ((Record(0, "smoke", "secret"),),
                        (Record(1, "controller", "too early"),)):
            with self.assertRaises(TimelineError):
                advance_timeline(source, take, listen=invalid, infer=lambda _: ())
        with self.assertRaises(TimelineError):
            advance_timeline(source, take, listen=(),
                             infer=lambda _: (Record(0, "controller", "wrong way"),))
        self.assertEqual(take.next_tick, 0)

    def test_source_bytes_bind_take_and_reject_undeclared_stream(self):
        source = read_timeline(source_bytes())
        other = read_timeline(source_bytes() + b" ")
        with self.assertRaises(TimelineError):
            advance_timeline(other, start_timeline(source), listen=(), infer=lambda _: ())
        obj = json.loads(source_bytes())
        obj["cues"][0]["stream"] = "undeclared"
        with self.assertRaises(TimelineError):
            read_timeline(json.dumps(obj).encode())


if __name__ == "__main__":
    unittest.main()
