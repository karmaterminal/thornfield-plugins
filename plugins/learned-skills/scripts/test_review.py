#!/usr/bin/env python3
"""Regression tests for the review's fail-closed apply step. No claude needed: the review run is
replaced by a fake that writes into the staging copy the way a steered review could.
Run: python3 scripts/test_review.py
"""
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
                write(self.path, user(f"the key: {key} after-key") + fill)
                return lambda c: review.digest(self.path, 0, c)[0]
            write(older, user(f"the key: {key} after-key"))
            os.utime(older, (1, 1))
            write(self.path, fill)
            return lambda c: review.gather({"transcripts": [older, self.path], "offsets": {}}, c)[0]

        for cap in (500, 200_000):
            for via in ("digest", "gather"):
                with self.subTest(cap=cap, via=via):
                    with mock.patch.object(review, "redact", lambda t: t):  # the layout only
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
        path = os.path.join(common.state_dir(self.proj), "digest.md")
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
