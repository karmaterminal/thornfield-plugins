"""Workload boundary: dispatch identity, election, inference, save, delivery."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "prototypes/story-player"))
from timeline import Record, TimelineError, read_timeline, start_timeline
from workload import Binding, Invocation, play_one_tick


def fixture():
    source = read_timeline(json.dumps({
        "schema": "thornfield.timeline.v1", "ticks": 2,
        "streams": [
            {"id": "vote", "direction": "listen", "media_type": "text/plain"},
            {"id": "action", "direction": "sing", "media_type": "text/plain"},
            {"id": "smoke", "direction": "sing", "media_type": "text/plain"},
        ],
        "cues": [{"tick": tick, "stream": stream, "prompt": "Use window fact"}
                 for tick in range(2) for stream in ("action", "smoke")],
        "facts": {"window": "closed"},
        "junctures": [{"tick": 0, "stream": "vote", "options": ["open", "leave"],
                       "default": "leave", "fact": "window",
                       "values": {"open": "open", "leave": "closed"}}],
    }).encode())
    invocation = Invocation("show-1", source.id, 0,
                            (Binding("vote", "canticle:controller"),),
                            (Binding("action", "canticle:actor"),
                             Binding("smoke", "canticle:air")))
    return source, invocation


class WorkloadTests(unittest.TestCase):
    def run_case(self, answer):
        source, invocation = fixture()
        events = []

        def receive(binding, tick):
            events.append(("receive", binding.channel, tick))
            return () if answer is None else (Record(tick, binding.stream, answer),)

        def infer(frame):
            events.append(("infer", frame.facts["window"], frame.choices))
            return tuple(Record(frame.tick, cue.stream,
                                f"window={frame.facts['window']};{cue.stream}")
                         for cue in frame.cues)

        def save(take):
            events.append(("save", take.next_tick))

        def send(delivery):
            events.append(("send", delivery.key, delivery.channel, delivery.record.text))

        take = play_one_tick(source, start_timeline(source), invocation,
                             receive=receive, infer=infer, save=save, send=send)
        return take, events

    def test_vote_and_silence_share_fact_across_two_outputs(self):
        for answer, expected in (("open", "open"), (None, "closed")):
            with self.subTest(answer=answer):
                take, events = self.run_case(answer)
                self.assertEqual([record.text for record in take.sung],
                                 [f"window={expected};action", f"window={expected};smoke"])
                self.assertEqual([event[0] for event in events],
                                 ["receive", "infer", "save", "send", "send"])
                self.assertEqual([event[1] for event in events[-2:]],
                                 ["show-1:0:0", "show-1:0:1"])

    def test_wrong_source_or_unbound_output_refuses_before_receive(self):
        source, invocation = fixture()
        for bad in (Invocation("show-1", "wrong", 0, invocation.listen, invocation.sing),
                    Invocation("show-1", source.id, 0, invocation.listen,
                               (Binding("action", "canticle:actor"),))):
            with self.assertRaises(TimelineError):
                play_one_tick(source, start_timeline(source), bad,
                              receive=lambda *_: self.fail("received"),
                              infer=lambda _: (), save=lambda _: self.fail("saved"),
                              send=lambda _: self.fail("sent"))

    def test_save_failure_never_sends(self):
        source, invocation = fixture()
        def fail(_):
            raise OSError("storage unavailable")
        with self.assertRaises(OSError):
            play_one_tick(source, start_timeline(source), invocation,
                          receive=lambda *_: (), infer=lambda _: (),
                          save=fail, send=lambda _: self.fail("sent before save"))

    def test_receiver_cannot_cross_bound_stream(self):
        source, invocation = fixture()
        with self.assertRaises(TimelineError):
            play_one_tick(source, start_timeline(source), invocation,
                          receive=lambda *_: (Record(0, "action", "forged"),),
                          infer=lambda _: self.fail("inferred"),
                          save=lambda _: self.fail("saved"),
                          send=lambda _: self.fail("sent"))


if __name__ == "__main__":
    unittest.main()
