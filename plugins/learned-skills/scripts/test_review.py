#!/usr/bin/env python3
"""Regression tests for the review's fail-closed apply step. No claude needed: the review run is
replaced by a fake that writes into the staging copy the way a steered review could.
Run: python3 scripts/test_review.py
"""
import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

sys.dont_write_bytecode = True  # a cached .pyc would hold the folded fake token
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import review  # noqa: E402

GOOD = "---\nname: {n}\ndescription: Use when testing the learned-skills apply step.\n---\n\n# t\n\n1. step\n"
# Built at run time so this file holds no credential shape itself (validate.sh scans the tree).
FAKE_TOKEN = "gh" + "p_" + "A1b2C3d4" * 5


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


class Transcripts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "session.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def events(self, *events):
        write(self.path, "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n")
        return self.path

    def test_claude_format(self):
        self.events({"type": "user", "message": {"content": "hello"}},
                    {"type": "assistant", "isSidechain": True, "message": {"content": "CHILD"}},
                    {"type": "summary", "summary": "NOT A TURN"},
                    {"type": "assistant", "message": {"content": [
                        {"type": "tool_use", "name": "Read", "input": {"file_path": "FILE"}},
                        {"type": "tool_result", "is_error": True, "content": "failure"}]}})
        text, end = review.digest(self.path, 0, 200_000)
        self.assertEqual(text, 'USER: hello\nTOOL Read: {"file_path": "FILE"}\nRESULT (error): failure')
        self.assertEqual(end, os.path.getsize(self.path))

    def test_clipping_offsets_and_partial_utf8_line(self):
        self.events({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Read", "input": {"path": "x" * 900}},
            {"type": "tool_result", "content": "x" * 1200}]}})
        text, end = review.digest(self.path, 0, 200_000)
        self.assertIn(review.clip(json.dumps({"path": "x" * 900}), review.TOOL_CAP), text)
        self.assertIn(review.clip("x" * 1200, review.RESULT_CAP), text)
        event = json.dumps({"type": "assistant", "message": {"content": "caf\u00e9"}},
                           ensure_ascii=False).encode()
        with open(self.path, "ab") as fh:
            fh.write(event[:-1])
        self.assertEqual(review.digest(self.path, end, 200_000), ("", end))
        with open(self.path, "ab") as fh:
            fh.write(event[-1:] + b"\n")
        text, new_end = review.digest(self.path, end, 200_000)
        self.assertEqual(text, "ASSISTANT: caf\u00e9")
        self.assertEqual(new_end, os.path.getsize(self.path))
        capped, _ = review.digest(self.path, 0, 40)
        self.assertEqual(capped, "[earlier turns cut]\n" + review.digest(self.path, 0, 200_000)[0][-40:])

    def test_a_cut_through_a_key_never_leaves_its_body(self):
        """The digest keeps its tail; redacted only after the cut, a cut that dropped a key's
        BEGIN line would leave the body with nothing for the header-dependent rule to match.
        At each cap the cut lands mid-body: digest's own cut, and gather's final cut across two
        transcripts (at 500 the older transcript's own digest cut comes first)."""
        body = "".join(f"K{i:03d}q7Xr2Lm9" for i in range(150))  # 1800 chars, under TEXT_CAP
        key = f"-----BEGIN RSA {'PRIVATE'} KEY-----\n{body}\n-----END RSA {'PRIVATE'} KEY-----"
        older = os.path.join(self.tmp.name, "older.jsonl")

        def user(text):
            return json.dumps({"type": "user", "message": {"content": text}}) + "\n"

        def build(via, cap, x):
            """The key, then filler: whole 2000-char turns short of the cap, and one of x chars."""
            fill = "".join(user("f" * 2000) for _ in range(max(0, cap // 2008 - 1))) + user("f" * x)
            if via == "digest":
                write(self.path, user(f"the key: {key}\nafter-key") + fill)
                return lambda c: review.digest(self.path, 0, c)[0]
            write(older, user(f"the key: {key}\nafter-key"))
            os.utime(older, (1, 1))
            write(self.path, fill)
            return lambda c: review.gather({"transcripts": [older, self.path], "offsets": {}}, c)[0]

        for cap in (500, 200_000):
            for via in ("digest", "gather"):
                with self.subTest(cap=cap, via=via):
                    plain = review.clip
                    with mock.patch.object(review, "shown", lambda t, n, guard=None, source=None: plain(t, n)):  # layout only
                        full = build(via, cap, 1)(10**9)
                        # The filler length that puts the cut on a chunk well inside the body.
                        x, chunk = next((1 + cap - (len(full) - full.index(f"K{i:03d}")), i)
                                        for i in range(140, 10, -1)
                                        if 1 <= 1 + cap - (len(full) - full.index(f"K{i:03d}")) < 2000)
                        full = build(via, cap, x)(10**9)
                        self.assertEqual(len(full) - cap, full.index(f"K{chunk:03d}"))
                    # Unredacted, this cut lands on that chunk. Redacted per block first, the
                    # whole body is gone before any cut, and the text after the block survives.
                    text = review.redact(build(via, cap, x)(cap))  # as main() redacts it after
                    survived = re.findall(r"K\d{3}q7Xr2Lm9", text)
                    self.assertEqual(survived, [], f"{len(survived)} key-body chunks survived the cut")
                    self.assertIn("[withheld: private-key] after-key", text)

    SPLIT_BODY = "MIIEowSPLIT" + "q7Xr2Lm9" * 8
    SPLIT_BEGIN = "-----BEGIN RSA " + "PRIVATE KEY-----"
    SPLIT_END = "-----END RSA " + "PRIVATE KEY-----"

    def split_events(self, *texts):
        """One user turn per text. An END only closes a key opened in the same kind of block
        (test_an_end_from_another_kind_of_block_closes_nothing covers the other case)."""
        return self.events(*({"type": "user", "message": {"content": t}} for t in texts))

    def test_a_key_split_across_two_messages_never_leaves_its_body(self):
        """BEGIN in one block and the body and END in the next left the body visible."""
        path = self.split_events(f"here is the key {self.SPLIT_BEGIN}",
                                 f"{self.SPLIT_BODY}\n{self.SPLIT_BODY}\n{self.SPLIT_END}\nafter-end",
                                 "the next message survives")
        text = review.digest(path, 0, 200_000)[0]
        self.assertNotIn(self.SPLIT_BODY, text)
        self.assertIn("here is the key [withheld: private-key]", text)
        self.assertIn("[withheld: private-key] after-end", text)
        self.assertIn("the next message survives", text)

    def test_a_key_whose_end_never_arrives_withholds_to_the_end_of_the_digest(self):
        path = self.split_events(f"key: {self.SPLIT_BEGIN}", self.SPLIT_BODY,
                                 f"{self.SPLIT_BODY} and then some prose")
        text = review.digest(path, 0, 200_000)[0]
        self.assertNotIn(self.SPLIT_BODY, text)
        self.assertNotIn("prose", text)  # inside an open key, everything is withheld
        self.assertEqual(text.count("[withheld: private-key]"), 3)

    @staticmethod
    def marker(kind, label):  # built here, so this file holds no key header itself
        return f"-----{kind} {label} {'PRIVATE'} KEY{' BLOCK' if label == 'PGP' else ''}-----"

    def mismatched(self):
        """(name, messages) where only the END with the opener's label may close the key: any
        END closed it, in a later block or in the opening block itself."""
        m, b = self.marker, self.SPLIT_BODY
        return {
            "wrong END in a later block": [f"key {m('BEGIN', 'RSA')}", m("END", "PGP"),
                                           b, f"{m('END', 'RSA')}\nafter-end"],
            "wrong END in the opening block": [f"key {m('BEGIN', 'RSA')} {b} {m('END', 'PGP')}",
                                               b, f"{m('END', 'RSA')}\nafter-end"],
            "all in one block": [f"key {m('BEGIN', 'RSA')} {b} {m('END', 'PGP')} {b} {m('END', 'RSA')}\nafter-end"],
            "nested, across blocks": [f"key {m('BEGIN', 'RSA')}", f"{m('BEGIN', 'PGP')} {b}",
                                      f"{m('END', 'PGP')} {b}", f"{m('END', 'RSA')}\nafter-end"],
            "nested, one block": [f"key {m('BEGIN', 'RSA')} {m('BEGIN', 'PGP')} {b} {m('END', 'PGP')} "
                                  f"{b} {m('END', 'RSA')}\nafter-end"],
        }

    def test_a_mismatched_or_nested_end_never_exposes_the_body(self):
        for name, texts in self.mismatched().items():
            with self.subTest(case=name):
                text = review.digest(self.split_events(*texts), 0, 10**6)[0]
                self.assertNotIn(self.SPLIT_BODY, text)
                # In one block the markers are space-joined: no END is a whole line, so the
                # key stays open and the text after it is withheld too (fail closed).
                if "one block" in name:
                    self.assertNotIn("after-end", text)
                else:
                    self.assertIn("[withheld: private-key] after-end", text)

    DECOYS = ("NOT_AN_END_LINE", "x", ", more", " prose")

    def test_a_malformed_end_with_the_right_label_closes_nothing(self):
        """An END marker anywhere closed the key, so a decoy such as END ...-----NOT_AN_END_LINE
        exposed the body after it. Only a complete END line closes."""
        m, b = self.marker, self.SPLIT_BODY
        for decoy in self.DECOYS:
            fake = m("END", "RSA") + decoy
            for where, texts in (
                    ("same block", [f"key {m('BEGIN', 'RSA')}\n{fake}\n{b}\n{m('END', 'RSA')}\nafter-end"]),
                    ("later block", [f"key {m('BEGIN', 'RSA')}", f"{fake}\n{b}", f"{m('END', 'RSA')}\nafter-end"])):
                with self.subTest(decoy=decoy, where=where):
                    text = review.digest(self.split_events(*texts), 0, 10**6)[0]
                    self.assertNotIn(b, text)
                    self.assertIn("[withheld: private-key] after-end", text)
            with self.subTest(decoy=decoy, where="redact() alone"):
                text = review.redact(f"key {m('BEGIN', 'RSA')}\n{fake}\n{b}\n{m('END', 'RSA')}\nafter-end")
                self.assertEqual(text, "key [withheld: private-key]\nafter-end")

    def test_a_json_escaped_end_line_still_closes(self):
        """A JSON-escaped key has no real newline: its END is followed by a literal \\n or a quote."""
        m, b = self.marker, self.SPLIT_BODY
        # The JSON parser decides what is a line break: \\n is one, but \\\\n is an
        # escaped backslash and then the letter n, so that END is not a whole line.
        for tail, closes in (("\\n", True), ("\\r\\n", True), ("\\\\n", False),
                             # the END then more of the same line is not a whole END line: the
                             # rest of that block is withheld too (fail closed), never the body shown
                             ('"', False),
                             # an escaped quote, then the string's end: JSON structure is not a
                             # line break, so the rest stays withheld (fail closed)
                             ('\\"', False)):
            with self.subTest(tail=tail):
                text = review.redact(f'{{"k": "{m("BEGIN", "RSA")}\\n{b}\\n{m("END", "RSA")}{tail}", "after": "yes"}}')
                self.assertNotIn(b, text)
                self.assertEqual("after" in text, closes)

    def test_the_single_block_rule_pairs_begin_with_its_own_end(self):
        """redact() alone (logs, summaries, check_skill's scan): BEGIN X runs to END X."""
        for name in ("all in one block", "nested, one block"):
            with self.subTest(case=name):
                text = review.redact(self.mismatched()[name][0])
                self.assertNotIn(self.SPLIT_BODY, text)
                # space-joined: no END is a whole line, so the key runs to the end of the block
                self.assertEqual(text, "key [withheld: private-key]")

    def test_a_mismatched_end_across_two_reviews_never_exposes_the_body(self):
        """The label is saved with the guard: review 2 still closes only on review 1's label."""
        for name in ("wrong END in a later block", "wrong END in the opening block"):
            with self.subTest(case=name):
                texts = self.mismatched()[name]
                self.events({"type": "user", "message": {"content": texts[0]}})
                state = {"transcripts": [self.path], "offsets": {}, "key_guard": {}}
                guards = {}
                first, offsets = review.gather(state, 10**6, guards)
                self.assertEqual(guards[self.path]["label"], "RSA PRIVATE KEY")
                with open(self.path, "a") as fh:
                    for t in texts[1:]:
                        fh.write(json.dumps({"type": "user", "message": {"content": t}}) + "\n")
                state = {"transcripts": [self.path], "offsets": offsets,
                         "key_guard": json.loads(json.dumps(guards))}  # as state.json keeps it
                second = review.gather(state, 10**6, {})[0]
                for text in (first, second):
                    self.assertNotIn(self.SPLIT_BODY, text)
                self.assertIn("[withheld: private-key] after-end", second)

    def prose(self, i):
        """One 2000-byte user turn, marked m00, m01, ..."""
        return {"type": "user", "message": {"content": f"m{i:02d} " + "w" * 1996}}

    def test_a_stray_begin_withholds_the_rest_until_reset_guard(self):
        """A BEGIN in prose with no END keeps its transcript withheld from reviews, in later
        reviews too, until `cli.py reset-guard` clears it, which is logged. Fail closed."""
        self.events({"type": "user", "message": {"content": f"the format starts {self.SPLIT_BEGIN}"}},
                    *({"type": "user", "message": {"content": f"m{i:02d} the ordinary words of turn {i}"}}
                      for i in range(5)))
        state = {"transcripts": [self.path], "offsets": {}}
        guards = {}
        text, offsets = review.gather(state, 10**6, guards)
        self.assertNotIn("m00", text)
        self.assertNotIn("m04", text)
        self.assertEqual(guards, {self.path: {"open": True, "label": "RSA PRIVATE KEY", "source": "user"}})
        with open(self.path, "a") as fh:
            fh.write(json.dumps({"type": "user", "message": {"content": "m05 the next review"}}) + "\n")
        state = {"transcripts": [self.path], "offsets": offsets, "key_guard": guards,
                 "ident": {self.path: review.identity(self.path, offsets[self.path])}}
        self.assertNotIn("m05", review.gather(dict(state), 10**6, {})[0])
        other = os.path.join(os.path.dirname(self.path), "other.jsonl")
        state["key_guard"][other] = {"open": True, "label": "RSA PRIVATE KEY", "source": "user"}
        with mock.patch.object(review, "log") as logged:
            self.assertEqual(review.reset_guards(state, "nope"), [])
            cleared = review.reset_guards(state, review.label(self.path))
        self.assertEqual(cleared, [self.path])
        logged.assert_called_once()
        # resetting one stray BEGIN never releases another transcript's real key
        self.assertIn(other, state["key_guard"])
        self.assertIn("m05 the next review", review.gather(state, 10**6, {})[0])

    def test_an_end_from_another_kind_of_block_closes_nothing(self):
        """A tool result (a fetched page, a file read) must not end a key pasted in a user turn."""
        b = self.SPLIT_BODY
        self.events({"type": "user", "message": {"content": f"key {self.SPLIT_BEGIN}"}},
                    {"type": "user", "message": {"content": [{"type": "tool_result", "content": f"{self.SPLIT_END}"}]}},
                    {"type": "user", "message": {"content": f"{b}\n{self.SPLIT_END}\nafter-end"}})
        text = review.digest(self.path, 0, 10**6)[0]
        self.assertNotIn(b, text)
        self.assertIn("[withheld: private-key] after-end", text)

    def test_a_literal_escaped_end_in_later_prose_closes_nothing(self):
        """A plain-text block's literal \\n is not decoded unless the block opens a key itself
        or is JSON, so it cannot fake an END line for a key opened earlier."""
        b = self.SPLIT_BODY
        self.events({"type": "user", "message": {"content": f"key {self.SPLIT_BEGIN}"}},
                    {"type": "user", "message": {"content": f"see \\n{self.SPLIT_END}\\n then {b}"}},
                    {"type": "user", "message": {"content": f"{self.SPLIT_END}\nafter-end"}})
        text = review.digest(self.path, 0, 10**6)[0]
        self.assertNotIn(b, text)
        self.assertIn("[withheld: private-key] after-end", text)

    def test_a_short_wrapped_pem_never_shows_a_line(self):
        """A valid PEM rewrapped at 16 columns leaked every alphabetic
        line. Inside an open key everything is withheld, whatever its shape."""
        body = "".join(chr(65 + (i * 7) % 26) + chr(97 + (i * 11) % 26) for i in range(64))  # letters only
        lines = [body[i:i + 16] for i in range(0, len(body), 16)]
        self.events({"type": "user", "message": {"content": "\n".join(
            [f"key {self.SPLIT_BEGIN}", *lines, self.SPLIT_END, "after-end"])}})
        text = review.digest(self.path, 0, 10**6)[0]
        for line in lines:
            self.assertNotIn(line, text)
        self.assertIn("[withheld: private-key] after-end", text)

    def test_an_escaped_backslash_n_never_forges_an_end_line(self):
        """In JSON, \\\\n (an escaped backslash, then n) was taken for a line break,
        so a same-source user block could forge the whole END line; a later AQ== reached the
        digest across review calls. JSON text is now decoded by the JSON parser."""
        forged = json.dumps({"note": f"x\\n{self.SPLIT_END}\\n"})  # literal backslash-n, not a newline
        self.events({"type": "user", "message": {"content": f"key {self.SPLIT_BEGIN}"}},
                    {"type": "user", "message": {"content": forged}})
        state = {"transcripts": [self.path], "offsets": {}}
        guards = {}
        text1, offsets = review.gather(state, 10**6, guards)
        self.assertTrue(guards[self.path]["open"])
        with open(self.path, "a") as fh:
            fh.write(json.dumps({"type": "user", "message": {"content": "AQ=="}}) + "\n")
            fh.write(json.dumps({"type": "user", "message": {"content": f"{self.SPLIT_END}\nafter-end"}}) + "\n")
        state = {"transcripts": [self.path], "offsets": offsets, "key_guard": guards,
                 "ident": {self.path: review.identity(self.path, offsets[self.path])}}
        text2 = review.gather(state, 10**6, {})[0]
        self.assertNotIn("AQ==", text1 + text2)
        self.assertIn("after-end", text2)

    def decoys(self):
        """JSON keys, values and brackets were joined by line breaks, so these
        made a whole END line; each is followed in the same block, or the next, by AQ==."""
        e = self.SPLIT_END
        return {"object": json.dumps({"note": e}),
                "object, AQ== after": json.dumps({"note": e, "b": "AQ=="}),
                "array": json.dumps(["x", e]),
                "array, AQ== after": json.dumps([e, "AQ=="]),
                "nested JSON": json.dumps({"a": json.dumps({"note": e})}),
                "in prose": f"see {json.dumps({'note': e})} and AQ==",
                "string end": json.dumps({"note": f"x\n{e}", "b": "AQ=="})}

    def test_json_structure_never_makes_an_end_line(self):
        for engine in ("claude", "copilot"):
            for name, decoy in self.decoys().items():
                with self.subTest(engine=engine, decoy=name):
                    path = self.split_events(engine, f"key {self.SPLIT_BEGIN}", decoy, "AQ==",
                                             f"{self.SPLIT_END}\nafter-end")
                    text = review.digest(path, 0, 10**6)[0]
                    self.assertNotIn("AQ==", text)
                    self.assertIn("[withheld: private-key] after-end", text)

    def test_json_structure_never_makes_an_end_line_across_reviews(self):
        for name, decoy in self.decoys().items():
            with self.subTest(decoy=name):
                self.events({"type": "user", "message": {"content": f"key {self.SPLIT_BEGIN}"}},
                            {"type": "user", "message": {"content": decoy}})
                guards = {}
                text1, offsets = review.gather({"transcripts": [self.path], "offsets": {}}, 10**6, guards)
                self.assertTrue(guards[self.path]["open"])
                with open(self.path, "a") as fh:
                    fh.write(json.dumps({"type": "user", "message": {"content": "AQ=="}}) + "\n")
                    fh.write(json.dumps({"type": "user", "message": {"content": f"{self.SPLIT_END}\nafter-end"}}) + "\n")
                state = {"transcripts": [self.path], "offsets": offsets,
                         "key_guard": json.loads(json.dumps(guards)),
                         "ident": {self.path: review.identity(self.path, offsets[self.path])}}
                text2 = review.gather(state, 10**6, {})[0]
                self.assertNotIn("AQ==", text1 + text2)
                self.assertIn("after-end", text2)

    def test_a_json_pasted_key_with_its_own_line_breaks_still_closes(self):
        """The fix keeps line breaks inside a string: a service-account file closes as before."""
        b = self.SPLIT_BODY
        doc = json.dumps({"type": "service_account",
                          "private_key": f"{self.SPLIT_BEGIN}\n{b}\n{self.SPLIT_END}\n", "after": "yes"})
        self.events({"type": "user", "message": {"content": doc}})
        text = review.digest(self.path, 0, 10**6)[0]
        self.assertNotIn(b, text)
        self.assertIn("after", text.split("[withheld: private-key]")[-1])

    def test_one_tool_result_cannot_close_another_results_key(self):
        """Tool result B closed the guard tool result A opened (both were just
        "tool_result"), and A's later body leaked. The guard keeps the very tool call's id."""
        b = self.SPLIT_BODY
        res = lambda cid, c: {"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": cid, "content": c}]}}
        self.events(res("A1", f"key {self.SPLIT_BEGIN}"), res("B2", self.SPLIT_END),
                    {"type": "user", "message": {"content": b}}, res("A1", f"{self.SPLIT_END}\nafter-end"))
        text = review.digest(self.path, 0, 10**6)[0]
        self.assertNotIn(b, text)
        self.assertIn("[withheld: private-key] after-end", text)

    def test_an_id_less_tool_block_source_never_repeats_across_runs(self):
        """An ID-less tool block got tool_result:?1 from a per-process counter, so the next
        review process's first ID-less result matched a saved guard and closed it."""
        code = ("import sys; sys.path.insert(0, %r); import review; "
                "print(review.tool_source('tool_result', None))" % os.path.dirname(os.path.abspath(review.__file__)))
        runs = {subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                               env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1")).stdout.strip() for _ in range(3)}
        self.assertEqual(len(runs), 3)
        for src in runs:
            self.assertRegex(src, r"^tool_result:\?[0-9a-f]{32}$")
            self.assertIsNotNone(review.KeyGuard({"open": True, "label": "RSA PRIVATE KEY", "source": src}).source)

    def test_plain_text_escapes_are_never_read_as_line_breaks(self):
        """Outside JSON nothing is unescaped, not even in the block that opens the key, so a
        literal \\n there cannot manufacture an END line."""
        b = self.SPLIT_BODY
        self.events({"type": "user", "message": {"content": f"k {self.SPLIT_BEGIN}\\n{self.SPLIT_END}\\n {b}"}},
                    {"type": "user", "message": {"content": f"{self.SPLIT_END}\nafter-end"}})
        text = review.digest(self.path, 0, 10**6)[0]
        self.assertNotIn(b, text)
        self.assertIn("after-end", text)

    def test_json_escaped_marker_characters_never_hide_a_key(self):
        """Valid JSON spelling the delimiters with
        \\u002d slipped past the raw BEGIN check; json.loads turns it back into the key."""
        b = self.SPLIT_BODY
        key = f"{self.SPLIT_BEGIN}\n{b}\n{self.SPLIT_END}\n"
        value = json.dumps(key)[1:-1]  # the JSON string's inside: escapes only in the value
        esc = lambda chars: '{"private_key": "' + "".join(
            f"\\u{ord(c):04x}" if c in chars else c for c in value) + '"}'
        shapes = {"hyphens": esc("-"), "every delimiter char": esc("-BEGINENDRSAPRIVATEKY "),
                  "label only": esc("RSAPRIVATEKY"), "mixed": esc("-EGKY")}
        contents = []
        for name, enc in shapes.items():
            self.assertEqual(json.loads(enc)["private_key"], key, name)
            contents += [enc, f"pasted: {enc} thanks"]
            # a top-level JSON string, alone and inside prose
            lit = enc[len('{"private_key": '):-1]
            self.assertEqual(json.loads(lit), key, name)
            contents += [lit, f"the key was {lit} ok"]
        for content in contents:
            with self.subTest(content=content[:20]):
                self.events({"type": "user", "message": {"content": content}})
                text = review.digest(self.path, 0, 10**6)[0]
                self.assertNotIn(b, text)
                self.assertNotIn(b, review.redact(text))
                self.assertNotIn(b, review.redact(content))

    def test_a_block_too_costly_to_decode_fails_closed(self):
        """Past DECODE_TRIES candidate JSON starts, a block is not parsed: its \\u escapes alone
        are read, and if a marker or rule shows there the whole block is withheld, the guard
        tracking what it held. A plain pathological block is shown as it is, quickly."""
        b = self.SPLIT_BODY
        noise = '{"a": [' * (review.DECODE_TRIES + 50)
        lit = json.dumps(f"{self.SPLIT_BEGIN}\n{b}").replace("-", "\\u002d")
        g = review.KeyGuard()
        t0 = time.time()
        out = review.shown(noise + lit, 10**6, g, "user")
        self.assertLess(time.time() - t0, 5)
        self.assertNotIn(b, out)
        self.assertTrue(g.open)
        self.assertNotIn(b, review.redact(noise + lit))
        plain = review.shown(noise, 10**6, review.KeyGuard(), "user")
        self.assertIn('{"a": [', plain)

    def test_a_u_escape_left_undecoded_withholds_the_block(self):
        """A quoted word, then an escape, then the escaped key literal: the string decode pairs
        the wrong quotes, so the key literal stays escaped and its body showed. A \\u escape
        whose reading adds a marker or rule match withholds the block; an undecodable block
        never closes a key opened before it."""
        b = self.SPLIT_BODY
        lit = json.dumps(f"{self.SPLIT_BEGIN}\n{b}\n{self.SPLIT_END}\n").replace("-", "\\u002d")
        for content in (f'see "x" \\u0020 {lit} ok', f'see "x" \\u0020 {lit} and {{"t": 1}}',
                        lit.strip('"').replace("\\n", "\n")):  # no JSON at all, real line breaks
            with self.subTest(content=content[:20]):
                g = review.KeyGuard()
                self.assertEqual(review.shown(content, 10**6, g, "user"), "[withheld: undecodable block]")
                self.assertNotIn(b, review.redact(content))
        # past DECODE_TRIES with a key open, an END spelled with \\u escapes closes nothing
        g = review.KeyGuard({"open": True, "label": "RSA PRIVATE KEY", "source": "user"})
        forged = '{"a": [' * (review.DECODE_TRIES + 50) + "\n" + self.SPLIT_END.replace("-", "\\u002d") + "\n"
        self.assertEqual(review.shown(forged, 10**6, g, "user"), "[withheld: undecodable block]")
        self.assertTrue(g.open)
        self.assertEqual(review.shown(f"{b}\n", 10**6, g, "user").count(b), 0)
        # an ordinary escape in prose changes nothing
        self.assertEqual(review.shown('say "caf\\u00e9" twice', 10**6, review.KeyGuard(), "user"),
                         'say "caf\\u00e9" twice')

    def test_an_undecodable_block_never_synthesizes_an_end(self):
        """An undecodable block opened a fresh guard and closed it on a \\u-spelled END in the
        same block, so the next block's body showed."""
        begin, end = self.SPLIT_BEGIN, self.SPLIT_END
        esc_end = end.replace("-", "\\u002d")
        noise = '{"x": [' * (review.DECODE_TRIES + 50)
        for name, opener in (("plain BEGIN", begin), ("escaped BEGIN", begin.replace("-", "\\u002d"))):
            with self.subTest(case=name):
                g = review.KeyGuard()
                blk = f"{opener}\n{noise}\n{esc_end}\n"
                self.assertEqual(review.shown(blk, 10**6, g, "user"), "[withheld: undecodable block]")
                self.assertTrue(g.open)
                self.assertNotIn("CONTINUATION", review.shown("PRIVATE-BODY-CONTINUATION", 10**6, g, "user"))
                out = review.shown(f"{end}\nafter-end", 10**6, g, "user")
                self.assertIn("after-end", out)
                self.assertFalse(g.open)

    def test_reset_guard_needs_one_transcript_when_basenames_collide(self):
        """Two transcript paths with one basename were both cleared by reset-guard ID."""
        d = os.path.dirname(self.path)
        a, b = os.path.join(d, "x", "same.jsonl"), os.path.join(d, "y", "same.jsonl")
        g = {"open": True, "label": "RSA PRIVATE KEY", "source": "user"}
        state = {"key_guard": {a: dict(g), b: dict(g)}}
        with mock.patch.object(review, "log"):
            self.assertEqual(review.reset_guards(state, "same"), [])
            self.assertEqual(set(state["key_guard"]), {a, b})
            self.assertEqual(review.reset_guards(state, a), [a])
        self.assertEqual(set(state["key_guard"]), {b})

    def test_four_character_fragments_never_show(self):
        """4-character body fragments (AQ== included) survived, across
        review calls too. Inside an open key nothing shows, in this review or the next."""
        chunks = ["MIIE", "owIB", "AAKC", "AQEA", "q7Xr", "AQ=="]
        self.events({"type": "user", "message": {"content": f"key {self.SPLIT_BEGIN}\n" + "\n".join(chunks[:3])}})
        state = {"transcripts": [self.path], "offsets": {}}
        guards = {}
        text1, offsets = review.gather(state, 10**6, guards)
        with open(self.path, "a") as fh:
            fh.write(json.dumps({"type": "user", "message": {"content": " ".join(chunks[3:])}}) + "\n")
            fh.write(json.dumps({"type": "user", "message": {"content": f"{self.SPLIT_END}\nafter-end"}}) + "\n")
        state = {"transcripts": [self.path], "offsets": offsets, "key_guard": guards,
                 "ident": {self.path: review.identity(self.path, offsets[self.path])}}
        text2 = review.gather(state, 10**6, {})[0]
        for chunk in chunks:
            self.assertNotIn(chunk, text1 + text2)
        self.assertIn("after-end", text2)

    def test_no_size_bound_a_long_body_stays_withheld_across_messages_and_reviews(self):
        """A 32 KB bound once closed the guard, and the next
        block's body (no BEGIN marker) reached the digest. Now nothing but the whole END line
        with the opener's label closes it, however long the body and however many reviews."""
        body = "\n".join(f"MIIEow{i:05d}" + "q7Xr2Lm9" * 7 for i in range(700))  # ~44 KB
        half = len(body) // 2
        self.events({"type": "user", "message": {"content": f"key {self.SPLIT_BEGIN}\n{body[:half]}"}})
        state = {"transcripts": [self.path], "offsets": {}}
        guards = {}
        text1, offsets = review.gather(state, 10**7, guards)
        self.assertEqual(guards, {self.path: {"open": True, "label": "RSA PRIVATE KEY", "source": "user"}})
        with open(self.path, "a") as fh:
            fh.write(json.dumps({"type": "user", "message": {"content": "here is the rest, sorry:"}}) + "\n")
            fh.write(json.dumps({"type": "user", "message": {"content": body[half:]}}) + "\n")
            fh.write(json.dumps({"type": "user", "message": {"content": f"{self.SPLIT_END}\nafter-end"}}) + "\n")
        state = {"transcripts": [self.path], "offsets": offsets, "key_guard": guards,
                 "ident": {self.path: review.identity(self.path, offsets[self.path])}}
        guards2 = {}
        text2 = review.gather(state, 10**7, guards2)[0]
        for text in (text1, text2):
            self.assertNotIn("MIIEow", text)
            self.assertNotIn("q7Xr2Lm9", text)
        self.assertNotIn("here is the rest", text2)  # commentary inside a key neither shows
        self.assertIn("after-end", text2)            # nor ends it
        self.assertEqual(guards2, {self.path: None})

    BOUNDARY = ("x{END}", "{END}x", "a {END} b", "{END}NOT_AN_END_LINE", "  {END}, more")

    def test_only_a_whole_end_line_closes_in_both_paths(self):
        """One table for the guard and for redact(): an END closes a key only
        as a line of its own. Each decoy here leaves the key open, so the body after it stays hidden."""
        m, b = self.marker, self.SPLIT_BODY
        for decoy in self.BOUNDARY:
            fake = decoy.format(END=m("END", "RSA"))
            with self.subTest(decoy=decoy, path="guard"):
                g = review.KeyGuard()
                out = " ".join(review.shown(x, 10**6, g, "user") for x in (f"k {m('BEGIN', 'RSA')}", fake, b))
                self.assertNotIn(b, out)
                self.assertTrue(g.open)
            with self.subTest(decoy=decoy, path="redact"):
                self.assertNotIn(b, review.redact(f"k {m('BEGIN', 'RSA')}\n{fake}\n{b}\n"))

    def read(self, state):
        """One review's gather, then its saves, as main() keeps them."""
        guards, idents = {}, {}
        text, offsets = review.gather(state, 10**6, guards, idents)
        state["offsets"].update(offsets)
        state.setdefault("ident", {}).update(idents)
        state["key_guard"] = {t: g for t, g in guards.items() if g}
        return text

    def first_read(self):
        """m00 and m01 read, with the guard saved open: a replaced file must reset both."""
        self.events(self.prose(0), self.prose(1))
        state = {"transcripts": [self.path], "offsets": {}}
        self.assertIn("m01 ", self.read(state))
        state["key_guard"] = {self.path: {"open": True, "label": "RSA PRIVATE KEY", "source": "user"}}
        return state

    def test_a_transcript_recreated_larger_is_read_from_the_start(self):
        """Only a shrink was seen as a replacement. Here the old file is kept alive (renamed),
        so the new one is another inode, with the same first bytes and more after."""
        state = self.first_read()
        os.rename(self.path, self.path + ".old")
        self.events(self.prose(0), self.prose(1), self.prose(2), self.prose(3))
        text = self.read(state)
        self.assertIn("m00 ", text)  # from offset 0, with a fresh guard
        self.assertIn("m03 ", text)
        self.assertEqual(state["key_guard"], {})

    def test_a_transcript_rewritten_in_place_at_equal_size_is_read_from_the_start(self):
        state = self.first_read()
        size, ino = os.path.getsize(self.path), os.stat(self.path).st_ino
        with open(self.path, "r+b") as fh:  # same inode, same size, a different first turn
            fh.write(json.dumps(self.prose(7)).encode())
        self.assertEqual((os.path.getsize(self.path), os.stat(self.path).st_ino), (size, ino))
        text = self.read(state)
        self.assertIn("m07 ", text)
        self.assertEqual(state["key_guard"], {})

    def test_an_append_keeps_the_offset_and_the_guard(self):
        state = self.first_read()
        with open(self.path, "a") as fh:
            fh.write(json.dumps({"type": "user", "message": {"content": f"{self.SPLIT_BODY}\n{self.SPLIT_END}\nafter"}}) + "\n")
        text = self.read(state)
        self.assertNotIn("m00 ", text)  # only the new turn
        self.assertNotIn(self.SPLIT_BODY, text)  # under the guard saved open
        self.assertIn("after", text)

    def test_state_without_an_identity_is_adopted(self):
        """State saved before identities existed keeps its offset, and gains an identity."""
        self.events(self.prose(0))
        size = os.path.getsize(self.path)
        with open(self.path, "a") as fh:
            fh.write(json.dumps(self.prose(1)) + "\n")
        state = {"transcripts": [self.path], "offsets": {self.path: size}}
        text = self.read(state)
        self.assertNotIn("m00 ", text)
        self.assertIn("m01 ", text)
        self.assertEqual(state["ident"][self.path]["n"], min(os.path.getsize(self.path), 4096))

    def test_a_replaced_transcript_resets_its_guard(self):
        self.events(self.prose(0))
        state = {"transcripts": [self.path], "offsets": {self.path: 10**6},  # past its size
                 "key_guard": {self.path: {"open": True, "withheld": 0}}}
        guards = {}
        text = review.gather(state, 10**6, guards)[0]
        self.assertIn("m00 ", text)
        self.assertEqual(guards, {self.path: None})

    def test_a_saved_guard_withholds_the_body_and_garbage_state_opens_nothing(self):
        # "after" as prose: a line that is a single base64-shaped word is withheld inside a key
        self.events({"type": "user", "message": {"content": f"{self.SPLIT_BODY}\n{self.SPLIT_END}\nafter the end."}})
        rsa = "RSA PRIVATE KEY"
        # (saved, body hidden, text after the END shown)
        for saved, hidden, after in (({"open": True, "label": rsa, "source": "user"}, True, True),
                                     # a 0.3.2 state ("withheld", no source): unknown provenance,
                                     # so nothing but reset-guard closes it
                                     ({"open": True, "label": rsa}, True, False),
                                     ({"open": True, "withheld": 5, "label": rsa}, True, False),
                                     ("junk", False, True), ({"open": "yes", "label": rsa}, False, True),
                                     # an unreadable or other label: open until reset-guard, as
                                     # only its own END could close it: everything stays hidden
                                     ({"open": True, "withheld": 5}, True, False),
                                     ({"open": True, "label": "x]-----"}, True, False),
                                     ({"open": True, "label": "PGP PRIVATE KEY BLOCK"}, True, False),
                                     # opened in a tool result: a user turn's END closes nothing
                                     ({"open": True, "label": rsa, "source": "tool_result"}, True, False)):
            with self.subTest(saved=saved):
                state = {"transcripts": [self.path], "offsets": {}, "key_guard": {self.path: saved}}
                text = review.gather(state, 10**6, {})[0]
                self.assertEqual(self.SPLIT_BODY not in text, hidden)
                self.assertEqual("after" in text, after)

    def test_session_labels(self):
        paths = [f"{self.tmp.name}/{name}.jsonl" for name in ("SESSION_A", "SESSION_B")]
        for path in paths:
            write(path, '{"type":"user","message":{"content":"hello"}}\n')
        text, offsets = review.gather({"transcripts": paths, "offsets": {}}, 200_000)
        for name in ("SESSION_A", "SESSION_B"):
            self.assertIn(f"## session {name}\n", text)
        self.assertEqual(sorted(review.label(t) for t in offsets), ["SESSION_A", "SESSION_B"])


class CheckSkill(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, n):
        return review.check_skill(self.d, n, 40_000)

    def test_good_skill_passes(self):
        write(f"{self.d}/learned-ok/SKILL.md", GOOD.format(n="learned-ok"))
        self.assertIsNone(self.check("learned-ok"))

    def test_injected_allowed_tools_refused(self):
        write(f"{self.d}/learned-x/SKILL.md", GOOD.format(n="learned-x").replace(
            "description:", "allowed-tools: Bash(*)\ndescription:"))
        self.assertIn("frontmatter keys not allowed", self.check("learned-x"))

    def test_injected_hooks_refused(self):
        write(f"{self.d}/learned-x/SKILL.md", GOOD.format(n="learned-x").replace(
            "description:", "hooks:\n  Stop: []\ndescription:"))
        self.assertIn("frontmatter keys not allowed", self.check("learned-x"))

    def test_planted_secret_refused_without_quoting_it(self):
        write(f"{self.d}/learned-x/SKILL.md", GOOD.format(n="learned-x") + f"\ntoken {FAKE_TOKEN}\n")
        why = self.check("learned-x")
        self.assertIn("credential shape github-token", why)
        self.assertNotIn(FAKE_TOKEN, why)

    def test_planted_private_key_in_reference_refused(self):
        write(f"{self.d}/learned-x/SKILL.md", GOOD.format(n="learned-x"))
        write(f"{self.d}/learned-x/references/k.md", "-----BEGIN OPENSSH " + "PRIVATE KEY-----\n")
        self.assertIn("credential shape private-key", self.check("learned-x"))

    def test_symlinked_subdir_refused(self):
        write(f"{self.d}/learned-x/SKILL.md", GOOD.format(n="learned-x"))
        os.symlink(os.path.expanduser("~"), f"{self.d}/learned-x/ref")
        self.assertIn("contains a symlink (ref)", self.check("learned-x"))

    def test_symlinked_file_refused(self):
        write(f"{self.d}/learned-x/SKILL.md", GOOD.format(n="learned-x"))
        os.symlink("/etc/hostname", f"{self.d}/learned-x/h.md")
        self.assertIn("contains a symlink", self.check("learned-x"))

    def test_symlinked_skill_dir_refused(self):
        write(f"{self.d}/real/SKILL.md", GOOD.format(n="learned-x"))
        os.symlink(f"{self.d}/real", f"{self.d}/learned-x")
        self.assertEqual(self.check("learned-x"), "is a symlink")

    def test_bad_name_refused(self):
        self.assertIn("directory name", self.check("learned-../x"))

    def test_redteam_frontmatter_keys_refused(self):
        """Every key a transcript asked for, one at a time, with PyYAML."""
        for extra in ("allowed-tools: Bash(*)", "model: opus", "disable-model-invocation: false",
                      "hooks:\n  PreToolUse: []"):
            with self.subTest(extra=extra.split(":")[0]):
                write(f"{self.d}/learned-x/SKILL.md", GOOD.format(n="learned-x").replace(
                    "description:", extra + "\ndescription:"))
                self.assertIn("frontmatter keys not allowed", self.check("learned-x"))

    def test_redteam_names_refused(self):
        """The names a transcript asked for."""
        for n in ("../escape", "learned-../../x", "learned-Docs-Build", "learned-" + "a" * 200):
            with self.subTest(n=n[:20]):
                self.assertIn("directory name", self.check(n))

    def test_name_mismatch_refused(self):
        write(f"{self.d}/learned-x/SKILL.md", GOOD.format(n="learned-y"))
        self.assertIn("!= directory", self.check("learned-x"))


class Apply(unittest.TestCase):
    """main() end to end with a fake review: only good learned-* dirs reach the project."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.proj = f"{t}/proj"
        self.skills = f"{self.proj}/.claude/skills"
        write(f"{self.skills}/hand-made/SKILL.md", GOOD.format(n="hand-made"))
        write(f"{self.proj}/.claude/learned-skills.json", json.dumps({"idle_seconds": 0, "commit": True}))
        for c in (["init", "-q"], ["add", "-A"],
                  ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"]):
            subprocess.run(["git", "-C", self.proj, *c], check=True)
        subprocess.run(["git", "-C", self.proj, "config", "user.name", "t"], check=True)
        subprocess.run(["git", "-C", self.proj, "config", "user.email", "t@t"], check=True)
        self.transcript = f"{t}/t.jsonl"
        with open(self.transcript, "w") as fh:
            for i in range(20):
                fh.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
                    {"type": "text", "text": f"step {i}: " + "worked it out " * 20}]}}) + "\n")
        os.environ["XDG_STATE_HOME"] = f"{t}/state"
        self.orig = review.run_claude

    def tearDown(self):
        review.run_claude = self.orig
        self.tmp.cleanup()

    def register(self, *transcripts, proj=None):
        with common.locked_state(common.state_dir(proj or self.proj)) as st:
            st["transcripts"] += [t for t in transcripts if t not in st["transcripts"]]

    def run_review(self, fake, rc=0, proj=None):
        self.register(self.transcript, proj=proj)
        seen = {}

        def run_claude(cfg, sdir, prompt):
            seen["digest"] = open(os.path.join(sdir, "digest.md")).read()
            seen["prompt"], seen["rdir"] = prompt, sdir
            seen["staged"] = sorted(os.listdir(os.path.join(sdir, "work")))
            seen["files"] = {os.path.relpath(os.path.join(r, f), sdir): open(os.path.join(r, f), errors="replace").read()
                             for r, _, fs in os.walk(sdir) for f in fs}
            fake(os.path.join(sdir, "work"))
            return types.SimpleNamespace(returncode=rc, stdout="LEARNED created learned-good: ok", stderr="")
        review.run_claude = run_claude
        sys.argv = ["review.py", proj or self.proj, "--now"]
        review.main()
        return seen

    def git(self, *a):
        return subprocess.run(["git", "-C", self.proj, *a], capture_output=True, text=True).stdout

    def good(self, work):
        write(f"{work}/learned-good/SKILL.md", GOOD.format(n="learned-good"))

    def test_only_valid_learned_skills_apply(self):
        def fake(work):
            write(f"{work}/learned-good/SKILL.md", GOOD.format(n="learned-good"))
            write(f"{work}/learned-bad/SKILL.md", GOOD.format(n="learned-bad").replace(
                "description:", "allowed-tools: Bash(*)\ndescription:"))
            write(f"{work}/learned-leak/SKILL.md", GOOD.format(n="learned-leak") + FAKE_TOKEN)
            os.makedirs(f"{work}/learned-link")
            write(f"{work}/learned-link/SKILL.md", GOOD.format(n="learned-link"))
            os.symlink(os.path.expanduser("~"), f"{work}/learned-link/home")
            write(f"{work}/hand-made/SKILL.md", "---\nname: hand-made\ndescription: rewritten\n---\n")
        self.run_review(fake)
        self.assertEqual(sorted(os.listdir(self.skills)), ["hand-made", "learned-good"])
        with open(f"{self.skills}/hand-made/SKILL.md") as fh:
            self.assertEqual(fh.read(), GOOD.format(n="hand-made"))
        log = subprocess.run(["git", "-C", self.proj, "log", "--format=%s"], capture_output=True,
                             text=True).stdout.split("\n")
        self.assertEqual(log[0], "learned: created learned-good")
        status = subprocess.run(["git", "-C", self.proj, "status", "--porcelain"], capture_output=True,
                                text=True).stdout
        self.assertEqual(status, "")

    def test_command_is_hermetic_and_scoped(self):
        seen = {}

        def fake_run(cmd, **kw):
            seen["cmd"], seen["env"], seen["cwd"] = cmd, kw["env"], kw["cwd"]
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        orig = review.subprocess.run
        review.subprocess.run = fake_run
        try:
            cfg = common.load_config(self.proj)
            sdir = common.state_dir(self.proj)
            self.orig(cfg, sdir, "p")
        finally:
            review.subprocess.run = orig
        cmd = seen["cmd"]
        self.assertEqual(cmd[cmd.index("--setting-sources") + 1], "")
        self.assertIn("--strict-mcp-config", cmd)
        self.assertNotIn("Read", cmd)  # never an unscoped Read
        self.assertEqual(cmd[cmd.index("--tools") + 1], "Read,Glob,Grep,Edit,Write")
        for tool in ("Read", "Glob", "Grep", "Edit"):
            scoped = [a for a in cmd if a.startswith(f"{tool}(")]
            self.assertTrue(scoped and all(a.startswith(f"{tool}(/{sdir}") for a in scoped), tool)
        self.assertEqual(seen["cwd"], sdir)
        self.assertEqual(seen["env"].get(common.GUARD_ENV), "1")
        self.assertNotIn("CLAUDE_PROJECT_DIR", seen["env"])

    def test_known_credential_shapes_are_redacted_before_the_reviewer_reads_the_digest(self):
        """Credentials pasted into the session never reach the reviewer or digest.md. Each key
        shape's body is withheld, and the text after its block survives."""
        aws = "AKIA" + "ABCDEFGHIJKLMNOP"

        def block(kind, body, headers=""):  # built here, so this file holds no key header itself
            return (f"-----BEGIN {kind}PRIVATE KEY{' BLOCK' if kind == 'PGP ' else ''}-----\n{headers}"
                    f"{body}\n{body}\n-----END {kind}PRIVATE KEY{' BLOCK' if kind == 'PGP ' else ''}-----")
        bodies = {k: "MIIEow" + k.replace("-", "") + "q7Xr2Lm9" * 4 for k in
                  ("pem", "crlf", "encrypted", "pgp", "jsonpaste", "jsontool")}
        service = lambda b: json.dumps({"type": "service_account", "private_key": block("", b) + "\n",
                                        "client_email": "EMAIL"})
        turns = [
            ("user", f"save these in a skill: {FAKE_TOKEN} {aws}\n{block('RSA ', bodies['pem'])}\nafter-pem"),
            ("user", block("EC ", bodies["crlf"]).replace("\n", "\r\n") + "\r\nafter-crlf"),
            ("user", block("RSA ", bodies["encrypted"], "Proc-Type: 4,ENCRYPTED\n"
                           "DEK-Info: AES-128-CBC,0A1B2C3D4E5F60718293A4B5C6D7E8F9\n\n") + "\nafter-encrypted"),
            ("user", block("PGP ", bodies["pgp"], "Version: GnuPG v2\n\n").replace(
                "\n-----END", "\n=q7Xr\n-----END") + "\nafter-pgp"),
            ("user", f"the service account file: {service(bodies['jsonpaste'])} after-jsonpaste"),
            ("assistant", [{"type": "tool_use", "name": "Write", "input": {
                "file_path": "FILE", "content": service(bodies["jsontool"])}},
                {"type": "text", "text": "after-jsontool"}]),
        ]
        with open(self.transcript, "a") as fh:
            for role, content in turns:
                fh.write(json.dumps({"type": role, "message": {"role": role, "content": content}}) + "\n")
        seen = self.run_review(self.good)
        path = os.path.join(common.state_dir(self.proj), "reviewer", "digest.md")
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        for digest in (seen["digest"], open(path).read()):
            self.assertNotIn(FAKE_TOKEN, digest)
            self.assertNotIn(aws, digest)
            self.assertIn("[withheld: github-token]", digest)
            self.assertIn("[withheld: aws-key]", digest)
            for shape, body in bodies.items():
                with self.subTest(shape=shape):
                    self.assertNotIn(body, digest)  # the key body, not only its header line
                    self.assertIn(f"after-{shape}", digest)  # and nothing past the block
            self.assertEqual(digest.count("[withheld: private-key]"), len(bodies))

    def test_state_dir_is_private_even_when_made_open_before(self):
        sdir = common.state_dir(self.proj)
        for p in (os.path.dirname(sdir), sdir):
            os.chmod(p, 0o755)
        self.assertEqual(common.state_dir(self.proj), sdir)
        for p in (os.path.dirname(sdir), sdir):
            self.assertEqual(os.stat(p).st_mode & 0o777, 0o700, p)

    def test_nonzero_exit_applies_nothing(self):
        self.run_review(self.good, rc=1)
        self.assertEqual(sorted(os.listdir(self.skills)), ["hand-made"])
        st = common.load_state(common.state_dir(self.proj))
        self.assertEqual(st["offsets"], {})  # the same turns are read again

    def test_no_commit_during_merge_and_nothing_left_staged(self):
        gitdir = self.git("rev-parse", "--absolute-git-dir").strip()
        write(f"{gitdir}/MERGE_HEAD", self.git("rev-parse", "HEAD"))
        self.run_review(self.good)
        self.assertTrue(os.path.isdir(f"{self.skills}/learned-good"))  # applied to the tree
        self.assertEqual(self.git("log", "-1", "--format=%s").strip(), "init")  # but not committed
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "")  # and not staged

    def test_no_commit_on_detached_head(self):
        subprocess.run(["git", "-C", self.proj, "checkout", "-q", "--detach"], check=True)
        self.run_review(self.good)
        self.assertEqual(self.git("log", "-1", "--format=%s").strip(), "init")

    def test_commit_branch_respected(self):
        cfgp = f"{self.proj}/.claude/learned-skills.json"
        write(cfgp, json.dumps({"idle_seconds": 0, "commit": True, "commit_branch": "learned"}))
        self.run_review(self.good)
        self.assertEqual(self.git("log", "-1", "--format=%s").strip(), "init")

    def test_project_reached_through_a_symlink_still_commits(self):
        link = f"{self.tmp.name}/link"
        os.symlink(self.proj, link)
        self.run_review(self.good, proj=link)
        self.assertEqual(self.git("log", "-1", "--format=%s").strip(), "learned: created learned-good")

    def test_every_known_transcript_is_read(self):
        other = f"{self.tmp.name}/older.jsonl"
        with open(other, "w") as fh:
            fh.write(json.dumps({"type": "user", "message": {"role": "user", "content": "OLDER-SESSION " * 200}}) + "\n")
        os.utime(other, (1, 1))
        self.register(other)
        seen = self.run_review(self.good)
        self.assertIn("OLDER-SESSION", seen["digest"])
        self.assertIn("worked it out", seen["digest"])
        self.assertLess(seen["digest"].index("OLDER-SESSION"), seen["digest"].index("worked it out"))

    def test_skip_keeps_the_turn_count(self):
        small = f"{self.tmp.name}/small.jsonl"
        write(small, json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}}) + "\n")
        sdir = common.state_dir(self.proj)
        with common.locked_state(sdir) as st:
            st["transcripts"], st["turns"] = [small], 9
        sys.argv = ["review.py", self.proj, "--now"]
        review.main()
        self.assertEqual(common.load_state(sdir)["turns"], 9)

    def undo(self, name):
        cli = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cli.py")
        env = dict(os.environ, CLAUDE_PROJECT_DIR=self.proj)
        return subprocess.run([sys.executable, cli, "undo", name], capture_output=True, text=True, env=env)

    def test_undo_update_removes_added_files_and_never_undoes_an_undo(self):
        self.run_review(self.good)
        with open(self.transcript, "a") as fh:  # more turns, so the second review has text
            for i in range(20):
                fh.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
                    {"type": "text", "text": f"more {i}: " + "learned again " * 20}]}}) + "\n")

        def update(work):
            write(f"{work}/learned-good/SKILL.md", GOOD.format(n="learned-good") + "2. more\n")
            write(f"{work}/learned-good/references/extra.md", "added by the update\n")
        self.run_review(update)
        self.assertEqual(self.git("log", "-1", "--format=%s").strip(), "learned: updated learned-good")
        r = self.undo("learned-good")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(f"{self.skills}/learned-good/references/extra.md"))
        with open(f"{self.skills}/learned-good/SKILL.md") as fh:
            self.assertEqual(fh.read(), GOOD.format(n="learned-good"))
        r = self.undo("learned-good")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not a learned change", r.stderr)
        self.assertNotEqual(self.undo("hand-made").returncode, 0)

    def test_reset_guard_clears_one_session_and_is_on_record(self):
        sdir = common.state_dir(self.proj)
        other = os.path.join(os.path.dirname(self.transcript), "other.jsonl")
        guard = {"open": True, "label": "RSA PRIVATE KEY", "source": "user"}
        with common.locked_state(sdir) as st:
            st["key_guard"] = {self.transcript: dict(guard), other: dict(guard)}
        cli = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cli.py")
        env = dict(os.environ, CLAUDE_PROJECT_DIR=self.proj)
        run = lambda *a: subprocess.run([sys.executable, cli, *a], capture_output=True, text=True, env=env)
        self.assertIn("key guard open in t (RSA PRIVATE KEY)", run("status").stdout)
        listed = run("reset-guard")  # no session: lists, clears nothing
        self.assertIn("open: t (RSA PRIVATE KEY)", listed.stdout)
        self.assertIn("open: other (RSA PRIVATE KEY)", listed.stdout)
        for bad in (("t", "other"), ("t; rm -rf ~",), ("",)):
            with self.subTest(bad=bad):
                self.assertNotEqual(run("reset-guard", *bad).returncode, 0)
        self.assertEqual(len(common.load_state(sdir)["key_guard"]), 2)
        self.assertIn("nothing cleared: no single open key guard for nope", run("reset-guard", "nope").stdout)
        r = run("reset-guard", "t")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("cleared the key guard of t", r.stdout)
        # one session only: another transcript's guard (maybe a real key) stays
        self.assertEqual(list(common.load_state(sdir)["key_guard"]), [other])
        with open(os.path.join(sdir, "review.log")) as fh:
            log = fh.read()
        self.assertIn("key guard reset for t by cli.py reset-guard", log)
        self.assertNotIn("for other", log)
        with common.locked_state(sdir) as st:
            st["key_guard"] = {}
        status = subprocess.run([sys.executable, cli, "status"], capture_output=True, text=True, env=env)
        self.assertNotIn("key guard open", status.stdout)

    def test_review_now_output_also_lands_in_the_log(self):
        self.register(self.transcript)
        fake = f"{self.tmp.name}/bin/claude"
        write(fake, "#!/bin/sh\ncat >/dev/null\necho 'LEARNED nothing'\n")
        os.chmod(fake, 0o755)
        cli = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cli.py")
        env = dict(os.environ, CLAUDE_PROJECT_DIR=self.proj,
                   PATH=f"{os.path.dirname(fake)}:{os.environ['PATH']}")
        r = subprocess.run([sys.executable, cli, "review-now"], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("review end: nothing learned", r.stdout)
        with open(os.path.join(common.state_dir(self.proj), "review.log")) as fh:
            self.assertIn("review end: nothing learned", fh.read())

    def state_text(self):
        """Every file under the state dir, path and content, symlinks not followed."""
        out = []
        for r, ds, fs in os.walk(common.state_dir(self.proj)):
            for x in ds + fs:
                p = os.path.join(r, x)
                out.append(p)
                if x in fs and not os.path.islink(p):
                    out.append(open(p, errors="replace").read())
        return "\n".join(out)

    def test_a_hand_written_skill_body_never_reaches_the_state_dir(self):
        write(f"{self.skills}/hand-made/SKILL.md", "---\nname: hand-made\ndescription: Use when "
              "deploying the HAND-DESC service.\n---\n\n# t\n\nHAND-BODY-PRIVATE-CONTEXT\n")
        write(f"{self.skills}/hand-made/references/notes.md", "HAND-REFERENCE-PRIVATE\n")
        write(f"{self.skills}/learned-old/SKILL.md", GOOD.format(n="learned-old"))
        self.git("add", "-A")
        self.git("commit", "-qm", "skills")
        seen = self.run_review(self.good)
        self.assertEqual(seen["staged"], ["learned-old"])  # only what the review may change
        self.assertIn("- hand-made: Use when deploying the HAND-DESC service.", seen["prompt"])
        self.assertIn("contents are not copied here", seen["prompt"])
        for secret in ("HAND-BODY-PRIVATE-CONTEXT", "HAND-REFERENCE-PRIVATE"):
            self.assertNotIn(secret, seen["prompt"])
            self.assertFalse(any(secret in t for t in seen["files"].values()), secret)
            self.assertNotIn(secret, self.state_text())
        self.assertEqual(sorted(seen["files"]), ["digest.md", "work/learned-old/SKILL.md"])
        self.assertTrue(os.path.isdir(f"{self.skills}/learned-good"))  # the review still works

    def test_symlinks_at_every_level_are_refused_and_nothing_outside_is_staged(self):
        outside = f"{self.tmp.name}/outside"
        write(f"{outside}/linked-skill/SKILL.md", GOOD.format(n="learned-linkdir") + "OUTSIDE-DIR\n")
        write(f"{outside}/notes.md", "OUTSIDE-FILE\n")
        write(f"{outside}/home/.ssh/id_fake", "OUTSIDE-SSH-KEY\n")  # a stand-in for ~/.ssh
        write(f"{outside}/hand/SKILL.md", "---\nname: shared\ndescription: OUTSIDE-DESC\n---\nOUTSIDE-HAND\n")
        os.symlink(f"{outside}/linked-skill", f"{self.skills}/learned-linkdir")
        write(f"{self.skills}/learned-linkfile/SKILL.md", GOOD.format(n="learned-linkfile"))
        os.symlink(f"{outside}/notes.md", f"{self.skills}/learned-linkfile/references-notes.md")
        write(f"{self.skills}/learned-ssh/SKILL.md", GOOD.format(n="learned-ssh"))
        os.makedirs(f"{self.skills}/learned-ssh/deep/er")
        os.symlink(f"{outside}/home/.ssh", f"{self.skills}/learned-ssh/deep/er/ssh")
        os.symlink(f"{outside}/missing", f"{self.skills}/learned-broken")
        os.symlink(f"{outside}/hand", f"{self.skills}/shared")
        write(f"{self.skills}/learned-fifo/SKILL.md", GOOD.format(n="learned-fifo"))
        os.mkfifo(f"{self.skills}/learned-fifo/pipe")
        write(f"{self.skills}/learned-plain/SKILL.md", GOOD.format(n="learned-plain"))

        def fake(work):  # same-named rewrites of skills it was never shown
            for name in ("learned-linkdir", "learned-linkfile", "learned-ssh", "learned-fifo"):
                write(f"{work}/{name}/SKILL.md", GOOD.format(n=name) + "REWRITTEN\n")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            seen = self.run_review(fake)
        self.assertEqual(seen["staged"], ["learned-plain"])
        log = out.getvalue()
        for name, why in (("learned-linkdir", "learned-linkdir is a symlink"),
                          ("learned-linkfile", "learned-linkfile/references-notes.md is a symlink"),
                          ("learned-ssh", "learned-ssh/deep/er/ssh is a symlink"),
                          ("learned-broken", "learned-broken is a symlink"),
                          ("learned-fifo", "learned-fifo/pipe is not a regular file")):
            self.assertIn(f"not staged {name}: {why}", log)
        self.assertIn("- shared\n", seen["prompt"] + "\n")  # a symlinked skill: its name only
        text = self.state_text()
        for secret in ("OUTSIDE-DIR", "OUTSIDE-FILE", "OUTSIDE-SSH-KEY", "OUTSIDE-DESC", "OUTSIDE-HAND"):
            self.assertNotIn(secret, seen["prompt"])
            self.assertNotIn(secret, text)
        self.assertFalse(any(os.path.islink(os.path.join(common.state_dir(self.proj), r, x))
                             for r, ds, fs in os.walk(common.state_dir(self.proj)) for x in ds + fs))
        # A review that writes over a skill it was never shown can't replace it.
        for name in ("learned-linkdir", "learned-linkfile", "learned-ssh", "learned-fifo"):
            self.assertIn(f"not applied {name}: left out of staging", log)
        self.assertTrue(os.path.islink(f"{self.skills}/learned-linkdir"))
        self.assertTrue(os.path.islink(f"{self.skills}/learned-ssh/deep/er/ssh"))
        for p in (f"{outside}/linked-skill/SKILL.md", f"{self.skills}/learned-linkfile/SKILL.md",
                  f"{self.skills}/learned-ssh/SKILL.md", f"{self.skills}/learned-fifo/SKILL.md"):
            with open(p) as fh:
                self.assertNotIn("REWRITTEN", fh.read(), p)

    def test_a_link_in_the_reviewer_dir_refuses_the_review(self):
        build = review.build_prompt

        def planting(cfg, sdir, *a):
            prompt = build(cfg, sdir, *a)
            os.symlink(os.path.expanduser("~"), os.path.join(sdir, "context", "home"))
            return prompt
        out = io.StringIO()
        with mock.patch.object(review, "build_prompt", planting), contextlib.redirect_stdout(out):
            self.run_review(lambda work: self.fail("the reviewer must not run"))
        self.assertIn("review refused: 1 symlink(s) or special file(s) in the reviewer dir", out.getvalue())
        self.assertEqual(common.load_state(common.state_dir(self.proj))["offsets"], {})

    def test_a_name_left_out_of_staging_is_never_applied(self):
        """A learned dir snapshot left out is invisible to the review; a dir the review writes
        under that name must not replace it: live, nor in the sink with live: false, where the
        changed-in-the-project check does not run."""
        t = self.tmp.name
        sink_skills = f"{t}/sink-skills"
        for root in (self.skills, sink_skills):
            write(f"{root}/learned-hidden/SKILL.md", GOOD.format(n="learned-hidden"))
            os.symlink(f"{t}/elsewhere", f"{root}/learned-hidden/ref")

        def fake(work):
            write(f"{work}/learned-hidden/SKILL.md", GOOD.format(n="learned-hidden") + "REPLACED\n")
        for live in (True, False):
            with self.subTest(live=live):
                write(f"{self.proj}/.claude/learned-skills.json", json.dumps({
                    "idle_seconds": 0, "live": live, "sink": {"url": f"{t}/unused.git", "branch": "b"}}))
                landed = []
                with common.locked_state(common.state_dir(self.proj)) as st:
                    st["offsets"] = {}  # the same turns again
                out = io.StringIO()
                with mock.patch.object(review.sink, "sink_skills", return_value=sink_skills), \
                        mock.patch.object(review.sink, "write_sink",
                                          side_effect=lambda cfg, sdir, items, log: landed.extend(items)), \
                        contextlib.redirect_stdout(out):
                    self.run_review(fake)
                self.assertEqual([i["name"] for i in landed], [])
                for root in (self.skills, sink_skills):
                    with open(f"{root}/learned-hidden/SKILL.md") as fh:
                        self.assertEqual(fh.read(), GOOD.format(n="learned-hidden"))
                    self.assertTrue(os.path.islink(f"{root}/learned-hidden/ref"))
                self.assertIn("not applied learned-hidden: left out of staging", out.getvalue())
        self.assertEqual(self.git("log", "-1", "--format=%s").strip(), "init")

    def test_reviewer_stderr_is_redacted_before_it_is_clipped(self):
        """The 400-char clip cut a token in two, and log()'s own redaction no longer matched the
        half that survived."""
        def run_claude(cfg, sdir, prompt):
            return types.SimpleNamespace(returncode=0, stdout="LEARNED nothing",
                                         stderr="x" * 380 + " " + FAKE_TOKEN)
        self.register(self.transcript)
        review.run_claude = run_claude
        sys.argv = ["review.py", self.proj, "--now"]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            review.main()
        line = next(x for x in out.getvalue().splitlines() if "stderr:" in x)
        self.assertNotIn(FAKE_TOKEN[:12], line)
        self.assertIn("[withheld:", line)  # the marker itself may be clipped

    def test_a_begin_read_by_one_review_withholds_the_body_in_the_next(self):
        """The guard is saved with the offset, in the same state update, and cleared at END."""
        body = Transcripts.SPLIT_BODY
        with open(self.transcript, "a") as fh:
            fh.write(json.dumps({"type": "user", "message": {"content": f"key: {Transcripts.SPLIT_BEGIN}"}}) + "\n")
        self.run_review(lambda work: None)
        st = common.load_state(common.state_dir(self.proj))
        self.assertEqual(st["key_guard"], {self.transcript: {"open": True, "label": "RSA PRIVATE KEY",
                                                             "source": "user"}})
        self.assertEqual(st["offsets"], {self.transcript: os.path.getsize(self.transcript)})
        self.assertEqual(st["ident"], {self.transcript: review.identity(self.transcript,
                                                                      os.path.getsize(self.transcript))})
        with open(self.transcript, "a") as fh:
            fh.write(json.dumps({"type": "user", "message": {"content":
                                 f"{body}\n{Transcripts.SPLIT_END}\nafter-end"}}) + "\n")
            for i in range(20):
                fh.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
                    {"type": "text", "text": f"later {i}: " + "worked it out " * 20}]}}) + "\n")
        seen = self.run_review(lambda work: None)
        self.assertNotIn(body, seen["files"]["digest.md"])
        self.assertIn("[withheld: private-key] after-end", seen["files"]["digest.md"])
        self.assertEqual(common.load_state(common.state_dir(self.proj))["key_guard"], {})

    def more_turns(self, word):
        with open(self.transcript, "a") as fh:
            for i in range(20):
                fh.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
                    {"type": "text", "text": f"{word} {i}: " + "learned again " * 20}]}}) + "\n")

    def uncommitted(self):
        write(f"{self.proj}/.claude/learned-skills.json", json.dumps({"idle_seconds": 0}))
        self.git("commit", "-qam", "default config")

    def test_default_leaves_the_change_uncommitted_and_the_notice_says_how_to_keep_it(self):
        self.uncommitted()
        self.run_review(self.good)
        self.assertTrue(os.path.isfile(f"{self.skills}/learned-good/SKILL.md"))
        self.assertEqual(self.git("log", "-1", "--format=%s").strip(), "default config")
        self.assertEqual(self.git("diff", "--cached", "--name-only"), "")
        hook = os.path.join(os.path.dirname(os.path.abspath(__file__)), "on_prompt.py")
        r = subprocess.run([sys.executable, hook], input="{}", capture_output=True, text=True,
                           env=dict(os.environ, CLAUDE_PROJECT_DIR=self.proj))
        self.assertIn("💾 Learned: created learned-good", r.stdout)
        self.assertIn("not committed (commit: false)", r.stdout)
        self.assertIn("commit `.claude/skills/NAME`", r.stdout)
        self.assertIn("/learned-skills:learned-undo NAME", r.stdout)

    def test_undo_of_uncommitted_create_and_update(self):
        self.uncommitted()
        self.run_review(self.good)
        self.git("add", "-A")
        self.git("commit", "-qm", "kept by hand")
        self.more_turns("more")

        def update(work):
            write(f"{work}/learned-good/SKILL.md", GOOD.format(n="learned-good") + "2. more\n")
            write(f"{work}/learned-good/references/extra.md", "added by the update\n")
        self.run_review(update)
        r = self.undo("learned-good")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("uncommitted", r.stdout)
        self.assertEqual(self.git("status", "--porcelain"), "")  # back to the kept version
        self.more_turns("again")

        def create(work):
            write(f"{work}/learned-new/SKILL.md", GOOD.format(n="learned-new"))
        self.run_review(create)
        self.assertEqual(self.undo("learned-new").returncode, 0)
        self.assertFalse(os.path.exists(f"{self.skills}/learned-new"))
        self.assertNotEqual(self.undo("learned-new").returncode, 0)  # nothing left to undo

    def test_undo_of_uncommitted_change_refuses_after_a_hand_edit(self):
        self.uncommitted()
        self.run_review(self.good)
        with open(f"{self.skills}/learned-good/SKILL.md", "a") as fh:
            fh.write("3. my own step\n")
        r = self.undo("learned-good")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("changed after its last learned change", r.stderr)
        with open(f"{self.skills}/learned-good/SKILL.md") as fh:
            self.assertIn("my own step", fh.read())


class Commands(unittest.TestCase):
    """Slash-command text is substituted into `!` lines before any shell parses them, so no
    quoting can make $ARGUMENTS safe there: no `!` line may carry user text at all."""

    def test_no_arguments_in_shell_lines(self):
        d = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "commands")
        for f in sorted(os.listdir(d)):
            with open(os.path.join(d, f)) as fh:
                for n, line in enumerate(fh, 1):
                    if line.lstrip().startswith("!`"):
                        for bad in ("$ARGUMENTS", "$1", "$2", "${ARGUMENTS"):
                            self.assertNotIn(bad, line, f"{f}:{n}")

    def test_cli_refuses_unknown_verbs_and_names(self):
        cli = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cli.py")
        for args in (["status;", "touch", "/tmp/x"], ["undo", "learned-x'; touch /tmp/x; '"],
                     ["undo", "learned-$(touch /tmp/x)"], ["rm"]):
            r = subprocess.run([sys.executable, cli, *args], capture_output=True, text=True,
                               env=dict(os.environ, CLAUDE_PROJECT_DIR=tempfile.gettempdir()))
            self.assertNotEqual(r.returncode, 0, args)


class NoYaml(unittest.TestCase):
    """Without PyYAML the frontmatter checks fail closed."""

    def setUp(self):
        self.saved = sys.modules.get("yaml")
        sys.modules["yaml"] = None  # `import yaml` now raises ImportError
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        if self.saved is not None:
            sys.modules["yaml"] = self.saved
        else:
            sys.modules.pop("yaml", None)
        self.tmp.cleanup()

    def check(self, fm_lines):
        d = self.tmp.name
        write(f"{d}/learned-x/SKILL.md", "---\nname: learned-x\n" + fm_lines + "\n---\n\n# x\n")
        return review.check_skill(d, "learned-x", 40_000)

    def test_folded_description_parses(self):
        self.assertIsNone(self.check("description: >-\n  Use when testing\n  the fallback."))
        _, desc = common.frontmatter(f"{self.tmp.name}/learned-x/SKILL.md")
        self.assertEqual(desc, "Use when testing the fallback.")

    def test_quoted_key_refused(self):
        self.assertIsNotNone(self.check("description: ok\n\"allowed-tools\": Bash(*)"))

    def test_single_quoted_key_refused(self):
        self.assertIsNotNone(self.check("description: ok\n'hooks': x"))

    def test_explicit_key_refused(self):
        self.assertIsNotNone(self.check("description: ok\n? allowed-tools\n: Bash(*)"))

    def test_flow_mapping_refused(self):
        self.assertIsNotNone(self.check("description: ok\nx: {allowed-tools: Bash}"))

    def test_bare_extra_key_refused(self):
        self.assertIn("not allowed", self.check("description: ok\nmodel: opus"))


class Secrets(unittest.TestCase):
    def scan(self, text):
        return [rule for rule, rx in review.SECRET_RULES if rx.search(text)]

    def test_shas_paths_urls_and_identifiers_pass(self):
        text = ("git show 7d8a1a91c6724367e5cd6f6d6ca0248af59c8ac0 -- "
                "/home/someone/src/WORKTREES/composite-23e9/src/infra/sqlite "
                "https://github.com/example/project/blob/main/plugins/learned "
                "createAccountScopedConversationBindingManagerV2 NODE_OPTIONS=--max-old-space-size=6144 "
                "bak-host-a-20260930T173944Z sha256:" + "ab12" * 16)
        self.assertEqual(self.scan(text), [])

    def test_padded_base64_refused(self):
        import base64
        blob = base64.b64encode(bytes(range(7, 38))).decode()
        self.assertTrue(blob.endswith("="))
        self.assertEqual(self.scan(f"KEY={blob}"), ["padded-base64"])

    def test_pgp_private_key_block_refused(self):
        self.assertEqual(self.scan("-----BEGIN PGP PRIVATE " + "KEY BLOCK-----"), ["private-key"])

    def test_private_key_rule_is_linear_on_a_long_run(self):
        """An unbounded header-name branch rescanned the run at every position: 22 s for 200 KB."""
        start = time.time()
        review.redact("-----BEGIN PRIVATE " + "KEY-----" + "A" * 200_000)
        self.assertLess(time.time() - start, 2)

    def test_token_shapes_refused(self):
        self.assertIn("github-token", self.scan(FAKE_TOKEN))
        self.assertIn("aws-key", self.scan("AKIA" + "ABCDEFGHIJKLMNOP"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
