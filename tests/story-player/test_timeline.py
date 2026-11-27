"""Model-facing timeline I/O contract: no clock or network required."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "prototypes/story-player"))
from timeline import (Record, TimelineError, advance_timeline, dump_timeline_take,
                      load_timeline_take, read_timeline, start_timeline)


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
    def test_recorded_vote_or_declared_default_changes_shared_fact_for_both_outputs(self):
        obj = json.loads(source_bytes())
        obj["ticks"] = 3
        obj["facts"] = {"window": "closed", "smoke": "in_kitchen"}
        obj["junctures"] = [{"tick": 1, "stream": "controller",
                              "options": ["open_window", "leave_closed"],
                              "default": "leave_closed", "fact": "window",
                              "values": {"open_window": "open", "leave_closed": "closed"}}]
        source = read_timeline(json.dumps(obj).encode())

        def infer(frame):
            if frame.tick == 1:
                self.assertEqual(frame.choices[0][1],
                                 "open_window" if frame.facts["window"] == "open" else "leave_closed")
            return (Record(frame.tick, "action", "window=" + frame.facts["window"]),
                    Record(frame.tick, "smoke", "window=" + frame.facts["window"]))

        first = advance_timeline(source, start_timeline(source), listen=(), infer=infer)
        voted = advance_timeline(source, first,
                                 listen=(Record(1, "controller", "open_window"),), infer=infer)
        defaulted = advance_timeline(source, first, listen=(), infer=infer)
        self.assertEqual([r.text for r in voted.sung[-2:]], ["window=open", "window=open"])
        self.assertEqual([r.text for r in defaulted.sung[-2:]], ["window=closed", "window=closed"])
        reopened = load_timeline_take(source, dump_timeline_take(voted))
        continued = advance_timeline(source, reopened, listen=(), infer=infer)
        self.assertEqual([r.text for r in continued.sung[-2:]], ["window=open", "window=open"])
        for invalid in ((Record(1, "controller", "break_window"),),
                        (Record(1, "controller", "open_window"), Record(1, "controller", "leave_closed"))):
            with self.assertRaises(TimelineError):
                advance_timeline(source, first, listen=invalid, infer=infer)
        tampered = json.loads(dump_timeline_take(voted))
        tampered["listened"][0]["text"] = "break_window"
        with self.assertRaises(TimelineError):
            load_timeline_take(source, json.dumps(tampered).encode())

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
        self.assertEqual(load_timeline_take(source, dump_timeline_take(take)), take)
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

    def test_reopen_rejects_wrong_direction_and_out_of_order_records(self):
        source = read_timeline(source_bytes())
        take = advance_timeline(source, start_timeline(source), listen=(),
                                infer=lambda _: (Record(0, "smoke", "Above the stove"),))
        obj = json.loads(dump_timeline_take(take))
        obj["sung"][0]["stream"] = "controller"
        with self.assertRaises(TimelineError):
            load_timeline_take(source, json.dumps(obj).encode())
        obj["sung"] = [{"tick": 1, "stream": "smoke", "text": "future"}]
        with self.assertRaises(TimelineError):
            load_timeline_take(source, json.dumps(obj).encode())


if __name__ == "__main__":
    unittest.main()
