#!/usr/bin/env python3
"""Tests for learning records, the disclosure filter and the sink. No claude needed.
Run: python3 scripts/test_sink.py
"""
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import review  # noqa: E402
import sink  # noqa: E402

GOOD = "---\nname: {n}\ndescription: Use when testing the learned-skills sink.\n---\n\n# t\n\n1. step\n"
RECORD = ("---\nsymptom: {s}\nstage: build\ncause: harness\nresolution: reinstalled the SDK\n"
          "recurs: yes\n---\n\nThe build step could not find the SDK; installing it fixed it.\n")
FAKE_TOKEN = "gh" + "p_" + "A1b2C3d4" * 5


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def sh(*cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True).stdout


class Records(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.p = f"{self.tmp.name}/r.md"

    def tearDown(self):
        self.tmp.cleanup()

    def parse(self, text):
        write(self.p, text)
        return sink.parse_record(self.p)

    def test_valid_record(self):
        fields, body = self.parse(RECORD.format(s="dotnet: command not found"))
        self.assertEqual(fields["cause"], "harness")
        self.assertIn("SDK", body)

    def test_extra_key_refused(self):
        fields, why = self.parse(RECORD.format(s="x").replace("stage:", "subject_repo: acme\nstage:"))
        self.assertIsNone(fields)
        self.assertIn("keys not allowed", why)

    def test_subject_cause_refused(self):
        fields, why = self.parse(RECORD.format(s="x").replace("cause: harness", "cause: repo"))
        self.assertIsNone(fields)
        self.assertIn("cause must be", why)

    def test_missing_field_refused(self):
        fields, why = self.parse(RECORD.format(s="x").replace("resolution: reinstalled the SDK\n", ""))
        self.assertIsNone(fields)

    def test_no_yaml_fails_closed(self):
        saved = sys.modules.get("yaml")
        sys.modules["yaml"] = None
        try:
            fields, _ = self.parse(RECORD.format(s="x").replace("stage:", "'hooks': x\nstage:"))
            self.assertIsNone(fields)
            fields, _ = self.parse(RECORD.format(s="dotnet: command not found"))
            self.assertIsNotNone(fields)
        finally:
            if saved is not None:
                sys.modules["yaml"] = saved
            else:
                sys.modules.pop("yaml", None)

    def test_fingerprint_ignores_run_specific_parts(self):
        a = sink.fingerprint("error at /home/a/x/y.cs:12 in 3f2a9c1d (attempt 4)", "build")
        b = sink.fingerprint("Error at /srv/b/q/z.cs:98 in 77aa0b12 (attempt 9)", "Build")
        c = sink.fingerprint("error at /home/a/x/y.cs:12 in 3f2a9c1d (attempt 4)", "test")
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)


class Flow(unittest.TestCase):
    """review.main() with a fake review, a filter, and a sink repo with a bare remote."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.proj, self.skills = f"{t}/proj", f"{t}/proj/.claude/skills"
        write(f"{self.skills}/hand-made/SKILL.md", GOOD.format(n="hand-made"))
        self.remote = f"{t}/state-repo.git"
        self.sinkrepo = f"{t}/state-repo"
        sh("git", "init", "-q", "--bare", self.remote)
        sh("git", "clone", "-q", self.remote, self.sinkrepo)
        for repo in (self.proj, self.sinkrepo):
            if not os.path.isdir(f"{repo}/.git"):
                sh("git", "init", "-q", repo)
            sh("git", "-C", repo, "config", "user.name", "t")
            sh("git", "-C", repo, "config", "user.email", "t@t")
            write(f"{repo}/README.md", "x\n")
            sh("git", "-C", repo, "add", "-A")
            sh("git", "-C", repo, "commit", "-qm", "init")
        sh("git", "-C", self.sinkrepo, "push", "-q", "origin", "HEAD:refs/heads/main")
        sh("git", "--git-dir", self.remote, "symbolic-ref", "HEAD", "refs/heads/main")  # as on a real host
        self.transcript = f"{t}/t.jsonl"
        with open(self.transcript, "w") as fh:
            for i in range(20):
                fh.write(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": [
                    {"type": "text", "text": f"step {i}: " + "worked it out " * 20}]}}) + "\n")
        os.environ["XDG_STATE_HOME"] = f"{t}/state"
        self.orig = review.run_claude
        self.filter = f"{t}/filter.sh"

    def tearDown(self):
        review.run_claude = self.orig
        for k in [k for k in os.environ if k.startswith("LEARNED_SKILLS_")]:
            del os.environ[k]
        self.tmp.cleanup()

    def owner_state(self):
        """Everything about the owner's sink checkout the plugin must never change."""
        g = lambda *a: sh("git", "-C", self.sinkrepo, *a)  # noqa: E731
        return (g("for-each-ref"), g("status", "--porcelain"), g("rev-parse", "--abbrev-ref", "HEAD"),
                os.path.exists(f"{self.sinkrepo}/.git/worktrees"))

    def config(self, **kw):
        cfg = {"idle_seconds": 0}
        cfg.update(kw)
        write(f"{self.proj}/.claude/learned-skills.json", json.dumps(cfg))

    def sink_cfg(self, push=True):
        return {"repo": self.sinkrepo, "path": "learnings", "branch": "team/learnings", "push": push}

    def run_review(self, fake, stdout=""):
        with common.locked_state(common.state_dir(self.proj)) as st:
            if self.transcript not in st["transcripts"]:
                st["transcripts"].append(self.transcript)
        with open(self.transcript, "a") as fh:  # fresh text for every review
            fh.write(json.dumps({"type": "user", "message": {"role": "user", "content": "more " * 500}}) + "\n")

        def run_claude(cfg, sdir, prompt):
            self.prompt = prompt
            state = common.state_dir(self.proj)
            fake(os.path.join(state, "work"), os.path.join(sdir, "work-records"))
            return types.SimpleNamespace(returncode=0, stdout=stdout, stderr="")
        review.run_claude = run_claude
        sys.argv = ["review.py", self.proj, "--now"]
        review.main()

    def show(self, branch, path):
        return sh("git", "--git-dir", self.remote, "show", f"{branch}:{path}")

    def remote_files(self, branch="team/learnings"):
        r = subprocess.run(["git", "--git-dir", self.remote, "ls-tree", "-r", "--name-only", branch],
                           capture_output=True, text=True)
        return r.stdout.split()

    def test_records_go_to_the_sink_only_and_are_pushed(self):
        self.config(kind="record", sink=self.sink_cfg(), record_fields={"lane": "3", "method_pin": "r110"})
        owner_before = self.owner_state()

        def fake(work, records):
            write(f"{records}/sdk-missing.md", RECORD.format(s="dotnet: command not found"))
            write(f"{work}/learned-sneaky/SKILL.md", GOOD.format(n="learned-sneaky"))
        self.run_review(fake)
        self.assertEqual(sorted(os.listdir(self.skills)), ["hand-made"])  # nothing live in record mode
        files = self.remote_files()
        recs = [f for f in files if f.startswith("learnings/") and f.endswith("-sdk-missing.md")]
        self.assertEqual(len(recs), 1, files)
        text = subprocess.run(["git", "--git-dir", self.remote, "show", f"team/learnings:{recs[0]}"],
                              capture_output=True, text=True).stdout
        for field in ('engine: "claude"', 'lane: "3"', 'method_pin: "r110"', "fingerprint:", "host:"):
            self.assertIn(field, text)
        # the owner's checkout is untouched: refs, tree, branch, and no worktree registered
        self.assertEqual(self.owner_state(), owner_before)
        self.assertFalse(owner_before[3])
        self.assertFalse(os.path.exists(f"{self.sinkrepo}/learnings"))

    def test_record_stamps_engine_model_and_session_label(self):
        self.config(kind="record", live=False, sink=self.sink_cfg(),
                    record_fields={"engine": "not-the-reviewer"})
        self.run_review(lambda w, r: write(f"{r}/model.md", RECORD.format(s="fixture friction")),
                        stdout="RECORDED model: resolved")
        record = next(f for f in self.remote_files() if f.endswith("-model.md"))
        text = self.show("team/learnings", record)
        self.assertIn('engine: "claude"', text)
        self.assertIn('model: "sonnet"', text)
        self.assertIn(f'sessions: "{review.label(self.transcript)}"', text)
        self.assertNotIn("not-the-reviewer", text)
        self.assertEqual(sorted(os.listdir(self.skills)), ["hand-made"])

    def test_record_only_does_not_snapshot_symlinked_source_skills(self):
        self.config(kind="record", sink=self.sink_cfg())
        os.symlink(f"{self.skills}/hand-made", f"{self.skills}/shared")

        def fake(work, records):
            self.assertEqual(os.listdir(work), [])
            self.assertEqual(os.listdir(os.path.join(os.path.dirname(work), "before")), [])
            write(f"{records}/clean.md", RECORD.format(s="synthetic method friction"))
        self.run_review(fake)
        self.assertTrue(any(f.endswith("-clean.md") for f in self.remote_files()))

    def test_filter_withholds_records_and_skills(self):
        write(self.filter, "#!/bin/sh\nprintf '%s\\n' \"$@\" >> " + self.tmp.name + "/seen\n"
              "grep -qi acme \"$@\" && exit 1\nexit 0\n")
        os.chmod(self.filter, 0o755)
        self.config(kind="both", sink=self.sink_cfg(), filter_command=[self.filter])

        def fake(work, records):
            write(f"{records}/leaky.md", RECORD.format(s="ACME build failed"))
            write(f"{records}/clean.md", RECORD.format(s="dotnet: command not found"))
            write(f"{work}/learned-leaky/SKILL.md", GOOD.format(n="learned-leaky") + "ACME\n")
            write(f"{work}/learned-clean/SKILL.md", GOOD.format(n="learned-clean"))
        self.run_review(fake)
        self.assertEqual(sorted(os.listdir(self.skills)), ["hand-made", "learned-clean"])
        files = self.remote_files()
        self.assertTrue(any(f.endswith("-clean.md") for f in files), files)
        self.assertFalse(any("leaky" in f for f in files), files)
        self.assertIn("learnings/skills/learned-clean/SKILL.md", files)
        self.assertTrue(any(f.startswith("learnings/events/") and f.endswith("-learned-clean.json")
                            for f in files), files)
        seen = open(f"{self.tmp.name}/seen").read()
        self.assertIn("SKILL.md", seen)  # the filter saw the skill files
        self.assertRegex(seen, r"events/\S+-learned-clean\.json")  # and the event JSON

    def test_filter_context_is_merged_and_bad_json_withholds(self):
        write(self.filter, "#!/bin/sh\ngrep -q withhold-me \"$@\" && { echo not-json; exit 0; }\n"
              "echo '{\"owner\": \"lane3\", \"fp\": \"abc\"}'\n")
        os.chmod(self.filter, 0o755)
        self.config(kind="both", sink=self.sink_cfg(), filter_command=[self.filter])

        def fake(work, records):
            write(f"{records}/ctx.md", RECORD.format(s="dotnet: command not found"))
            write(f"{records}/bad.md", RECORD.format(s="withhold-me"))
            write(f"{work}/learned-clean/SKILL.md", GOOD.format(n="learned-clean"))
        self.run_review(fake)
        files = self.remote_files()
        self.assertFalse(any(f.endswith("-bad.md") for f in files), files)
        rec = next(f for f in files if f.endswith("-ctx.md"))
        text = sh("git", "--git-dir", self.remote, "show", f"team/learnings:{rec}")
        self.assertIn('context: {"owner": "team", "fp": "abc"}', text)
        ev = next(f for f in files if f.startswith("learnings/events/"))
        self.assertEqual(json.loads(sh("git", "--git-dir", self.remote, "show", f"team/learnings:{ev}"))["context"],
                         {"owner": "team", "fp": "abc"})

    def test_live_false_writes_nothing_to_the_project(self):
        outside = f"{self.tmp.name}/cfg.json"
        write(outside, json.dumps({"idle_seconds": 0, "kind": "both", "live": False, "sink": self.sink_cfg()}))
        os.environ["LEARNED_SKILLS_CONFIG"] = outside
        os.remove(f"{self.proj}/.claude/skills/hand-made/SKILL.md")
        sh("git", "-C", self.proj, "add", "-A")
        before = sh("git", "-C", self.proj, "status", "--porcelain")

        def fake(work, records):
            write(f"{work}/learned-clean/SKILL.md", GOOD.format(n="learned-clean"))
            write(f"{records}/r.md", RECORD.format(s="dotnet: command not found"))
        self.run_review(fake)
        self.assertEqual(sh("git", "-C", self.proj, "status", "--porcelain"), before)
        self.assertFalse(os.path.exists(f"{self.skills}/learned-clean"))
        files = self.remote_files()
        self.assertIn("learnings/skills/learned-clean/SKILL.md", files)
        self.assertTrue(any(f.endswith("-r.md") for f in files), files)

    def test_default_branch_refused_and_env_override(self):
        self.config(kind="record", sink=dict(self.sink_cfg(), branch="main"))
        self.run_review(lambda w, r: write(f"{r}/x.md", RECORD.format(s="first")))
        self.assertNotIn("learnings", " ".join(self.remote_files("main")))
        os.environ["LEARNED_SKILLS_SINK_BRANCH"] = "lane7/learnings"
        self.run_review(lambda w, r: write(f"{r}/y.md", RECORD.format(s="second")))
        files = self.remote_files("lane7/learnings")
        self.assertTrue(any(f.endswith("-x.md") for f in files), files)  # the pending one too
        self.assertTrue(any(f.endswith("-y.md") for f in files), files)

    def test_missing_filter_withholds_everything(self):
        self.config(kind="both", sink=self.sink_cfg(), filter_command=[f"{self.tmp.name}/nope"])

        def fake(work, records):
            write(f"{records}/clean.md", RECORD.format(s="dotnet: command not found"))
            write(f"{work}/learned-clean/SKILL.md", GOOD.format(n="learned-clean"))
        self.run_review(fake)
        self.assertEqual(sorted(os.listdir(self.skills)), ["hand-made"])
        self.assertEqual(self.remote_files(), [])

    def test_record_with_a_credential_is_not_kept(self):
        self.config(kind="record", sink=self.sink_cfg())

        def fake(work, records):
            write(f"{records}/tok.md", RECORD.format(s="auth failed for " + FAKE_TOKEN))
        self.run_review(fake)
        self.assertEqual(self.remote_files(), [])

    def test_push_rejected_then_merged(self):
        self.config(kind="record", sink=self.sink_cfg())
        self.run_review(lambda w, r: write(f"{r}/one.md", RECORD.format(s="first")))
        other = f"{self.tmp.name}/other"
        sh("git", "clone", "-q", "-b", "team/learnings", self.remote, other)
        sh("git", "-C", other, "config", "user.name", "o")
        sh("git", "-C", other, "config", "user.email", "o@o")
        write(f"{other}/learnings/from-other-lane.md", "x\n")
        sh("git", "-C", other, "add", "-A")
        sh("git", "-C", other, "commit", "-qm", "other")
        sh("git", "-C", other, "push", "-q", "origin", "team/learnings")
        self.run_review(lambda w, r: write(f"{r}/two.md", RECORD.format(s="second")))
        files = self.remote_files()
        self.assertIn("learnings/from-other-lane.md", files)
        self.assertTrue(any(f.endswith("-two.md") for f in files), files)

    def test_no_sink_keeps_records_pending_until_one_is_set(self):
        self.config(kind="record")
        self.run_review(lambda w, r: write(f"{r}/early.md", RECORD.format(s="early")))
        pend = os.path.join(common.state_dir(self.proj), "sink-pending")
        self.assertTrue(os.listdir(pend))
        self.config(kind="record", sink=self.sink_cfg())
        self.run_review(lambda w, r: write(f"{r}/late.md", RECORD.format(s="late")))
        files = self.remote_files()
        self.assertTrue(any(f.endswith("-early.md") for f in files), files)
        self.assertTrue(any(f.endswith("-late.md") for f in files), files)

    def test_record_prompt_keeps_the_ownership_split(self):
        self.config(kind="record", sink=self.sink_cfg())
        self.run_review(lambda w, r: None)
        self.assertIn("Split ownership first", self.prompt)
        self.assertNotIn("{{", self.prompt)

    def test_foreign_clone_dir_is_never_removed(self):
        precious = f"{self.tmp.name}/precious"
        write(f"{precious}/keep.txt", "mine\n")
        wt_like = f"{self.tmp.name}/worktree-like"
        write(f"{wt_like}/.git", "gitdir: /elsewhere\n")
        for d in (precious, wt_like):
            self.config(kind="record", sink=dict(self.sink_cfg(), clone_dir=d))
            self.run_review(lambda w, r: write(f"{r}/x.md", RECORD.format(s="first")))
        self.assertEqual(open(f"{precious}/keep.txt").read(), "mine\n")
        self.assertEqual(sorted(os.listdir(precious)), ["keep.txt"])
        self.assertEqual(open(f"{wt_like}/.git").read(), "gitdir: /elsewhere\n")
        self.assertEqual(self.remote_files(), [])  # nothing landed; the records wait
        empty = f"{self.tmp.name}/empty"
        os.makedirs(empty)
        self.config(kind="record", sink=dict(self.sink_cfg(), clone_dir=empty))
        self.run_review(lambda w, r: None)
        self.assertTrue(any(f.endswith("-x.md") for f in self.remote_files()))
        self.assertTrue(os.path.isfile(f"{empty}/.git/{sink.CLONE_MARKER}"))

    # ---- review follow-ups ----

    def test_u1_summary_with_a_token_is_redacted_everywhere(self):
        import contextlib
        import io
        self.config(kind="skill", commit=True, sink=self.sink_cfg())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):  # the review log
            self.run_review(lambda w, r: write(f"{w}/learned-good/SKILL.md", GOOD.format(n="learned-good")),
                            stdout=f"LEARNED created learned-good: uses {FAKE_TOKEN} to log in")
        self.assertNotIn(FAKE_TOKEN, out.getvalue())
        msg = sh("git", "-C", self.proj, "log", "-1", "--format=%B")
        self.assertNotIn(FAKE_TOKEN, msg)
        self.assertIn("[withheld: github-token]", msg)
        ev = next(f for f in self.remote_files() if f.startswith("learnings/events/"))
        self.assertNotIn(FAKE_TOKEN, self.show("team/learnings", ev))
        sdir = common.state_dir(self.proj)
        self.assertNotIn(FAKE_TOKEN, open(os.path.join(sdir, "notices.jsonl")).read())

    def test_u2_queued_items_pass_the_gate_at_push_time(self):
        self.config(kind="record")  # no sink, no filter: items queue
        self.run_review(lambda w, r: write(f"{r}/acme.md", RECORD.format(s="ACME broke")))
        write(self.filter, "#!/bin/sh\ngrep -qi acme \"$@\" && exit 1\nexit 0\n")
        os.chmod(self.filter, 0o755)
        self.config(kind="record", sink=self.sink_cfg(), filter_command=[self.filter])
        self.run_review(lambda w, r: write(f"{r}/clean.md", RECORD.format(s="dotnet: command not found")))
        files = self.remote_files()
        self.assertTrue(any(f.endswith("-clean.md") for f in files), files)
        self.assertFalse(any("acme" in f for f in files), files)  # queued before the filter existed
        self.assertEqual(os.listdir(os.path.join(common.state_dir(self.proj), "sink-pending")) if
                         os.path.isdir(os.path.join(common.state_dir(self.proj), "sink-pending")) else [], [])

    def test_u2_pending_is_bounded(self):
        self.config(kind="record", max_pending=3)
        for i in range(5):
            self.run_review(lambda w, r, i=i: write(f"{r}/n{i}.md", RECORD.format(s=f"err {i}")))
        pend = os.path.join(common.state_dir(self.proj), "sink-pending")
        self.assertEqual(len(os.listdir(pend)), 3)

    def test_u3_switching_branch_carries_nothing_over(self):
        self.config(kind="record", sink=self.sink_cfg())
        self.run_review(lambda w, r: write(f"{r}/a.md", RECORD.format(s="first")))
        os.environ["LEARNED_SKILLS_SINK_BRANCH"] = "lane7/learnings"
        self.run_review(lambda w, r: write(f"{r}/b.md", RECORD.format(s="second")))
        lane7 = self.remote_files("lane7/learnings")
        self.assertTrue(any(f.endswith("-b.md") for f in lane7), lane7)
        self.assertFalse(any(f.endswith("-a.md") for f in lane7), lane7)

    def test_u3_orphan_branch_on_a_headless_remote_carries_nothing_over(self):
        sh("git", "--git-dir", self.remote, "symbolic-ref", "HEAD", "refs/heads/none")  # no default
        self.config(kind="record", sink=self.sink_cfg())
        self.run_review(lambda w, r: write(f"{r}/a.md", RECORD.format(s="first")))
        os.environ["LEARNED_SKILLS_SINK_BRANCH"] = "lane7/learnings"
        self.run_review(lambda w, r: write(f"{r}/b.md", RECORD.format(s="second")))
        lane7 = self.remote_files("lane7/learnings")
        self.assertEqual(len(lane7), 1, lane7)
        self.assertTrue(lane7[0].endswith("-b.md"), lane7)

    def test_u4_conflict_after_a_rejected_push_recovers(self):
        self.config(kind="skill", live=False, sink=self.sink_cfg())
        self.run_review(lambda w, r: write(f"{w}/learned-good/SKILL.md", GOOD.format(n="learned-good")))
        other = f"{self.tmp.name}/other"
        sh("git", "clone", "-q", "-b", "team/learnings", self.remote, other)
        sh("git", "-C", other, "config", "user.name", "o")
        sh("git", "-C", other, "config", "user.email", "o@o")
        write(f"{other}/learnings/skills/learned-good/SKILL.md", GOOD.format(n="learned-good") + "theirs\n")
        sh("git", "-C", other, "commit", "-qam", "theirs")
        sh("git", "-C", other, "push", "-q", "origin", "team/learnings")
        # ours edits the same file while theirs lands: the review's clone must not stay stuck
        self.run_review(lambda w, r: write(f"{w}/learned-good/SKILL.md", GOOD.format(n="learned-good") + "ours\n"))
        clone = os.path.join(common.state_dir(self.proj), "sink-clone")
        self.assertFalse(os.path.exists(f"{clone}/.git/MERGE_HEAD"))
        self.run_review(lambda w, r: write(f"{r}/later.md", RECORD.format(s="later")))
        self.assertIn("ours", self.show("team/learnings", "learnings/skills/learned-good/SKILL.md"))

    def test_u5_two_hosts_creating_one_branch_share_history(self):
        self.config(kind="record", sink=self.sink_cfg(), )
        self.run_review(lambda w, r: write(f"{r}/host1.md", RECORD.format(s="one")))
        os.environ["XDG_STATE_HOME"] = f"{self.tmp.name}/state-host2"  # a second host's state
        self.run_review(lambda w, r: write(f"{r}/host2.md", RECORD.format(s="two")))
        files = self.remote_files()
        self.assertTrue(any(f.endswith("-host1.md") for f in files) and any(f.endswith("-host2.md") for f in files), files)
        base = sh("git", "--git-dir", self.remote, "merge-base", "team/learnings", "main").strip()
        self.assertEqual(base, sh("git", "--git-dir", self.remote, "rev-parse", "main").strip())

    def test_u6_owner_git_identity_reaches_the_clone(self):
        sh("git", "-C", self.sinkrepo, "config", "user.email", "owner@example.org")
        self.config(kind="record", sink=dict(self.sink_cfg(), git_config={"commit.gpgsign": "false"}))
        self.run_review(lambda w, r: write(f"{r}/x.md", RECORD.format(s="x")))
        clone = os.path.join(common.state_dir(self.proj), "sink-clone")
        self.assertEqual(sh("git", "-C", clone, "config", "--local", "user.email").strip(), "owner@example.org")
        self.assertEqual(sh("git", "-C", clone, "config", "--local", "commit.gpgsign").strip(), "false")

    def test_u7_a_sink_crash_keeps_offsets_and_notices(self):
        self.config(kind="record", sink=self.sink_cfg())
        orig = sink.write_sink

        def boom(*a, **k):
            raise review.subprocess.TimeoutExpired("git", 1)
        sink.write_sink = boom
        try:
            self.run_review(lambda w, r: write(f"{r}/x.md", RECORD.format(s="x")))
        finally:
            sink.write_sink = orig
        sdir = common.state_dir(self.proj)
        self.assertTrue(common.load_state(sdir)["offsets"])
        self.assertIn("recorded", open(os.path.join(sdir, "notices.jsonl")).read())

    def test_u8_live_false_skills_build_up(self):
        self.config(kind="skill", live=False, sink=self.sink_cfg())
        self.run_review(lambda w, r: write(f"{w}/learned-good/SKILL.md", GOOD.format(n="learned-good")))
        seen = {}

        def second(w, r):
            seen["had"] = os.path.exists(f"{w}/learned-good/SKILL.md")
            write(f"{w}/learned-good/SKILL.md", GOOD.format(n="learned-good") + "2. more\n")
        self.run_review(second)
        self.assertTrue(seen["had"])  # the review saw the sink's earlier skill
        evs = sorted(f for f in self.remote_files() if f.startswith("learnings/events/"))
        self.assertEqual(json.loads(self.show("team/learnings", evs[-1]))["verb"], "updated")

    # ---- same-second names ----

    def test_u11_same_stamp_events_and_records_all_land(self):
        self.config(kind="both", live=False, sink=self.sink_cfg())
        with mock.patch.object(sink, "stamp", return_value="20261018T190726.000000Z"):
            self.run_review(lambda w, r: (write(f"{w}/learned-good/SKILL.md", GOOD.format(n="learned-good")),
                                          write(f"{r}/same.md", RECORD.format(s="first"))))
            self.run_review(lambda w, r: (write(f"{w}/learned-good/SKILL.md", GOOD.format(n="learned-good") + "2. more\n"),
                                          write(f"{r}/same.md", RECORD.format(s="second"))))
        files = self.remote_files()
        evs = sorted(f for f in files if f.startswith("learnings/events/"))
        self.assertEqual([json.loads(self.show("team/learnings", e))["verb"] for e in evs], ["created", "updated"])
        recs = sorted(f for f in files if f.startswith("learnings/") and f.endswith("-same.md"))
        self.assertEqual(len(recs), 2, files)
        self.assertIn('"first"', self.show("team/learnings", recs[0]))
        self.assertIn('"second"', self.show("team/learnings", recs[1]))

    def test_u11_stamps_are_sub_second_and_sort_by_time(self):
        a, b = sink.stamp(), sink.stamp()
        self.assertRegex(a, r"^\d{8}T\d{6}\.\d{6}Z$")
        self.assertLessEqual(a, b)

    def test_u11_a_landed_file_is_kept_once_and_a_new_one_beside_it(self):
        d = self.tmp.name
        write(f"{d}/sink/events/S-n.json", "a\n")
        write(f"{d}/same", "a\n")
        write(f"{d}/other", "b\n")
        self.assertIsNone(sink.unique_path(f"{d}/sink/events/S-n.json", f"{d}/same"))  # a re-land
        self.assertEqual(sink.unique_path(f"{d}/sink/events/S-n.json", f"{d}/other"), f"{d}/sink/events/S.2-n.json")
        write(f"{d}/sink/events/S.2-n.json", "b\n")
        self.assertIsNone(sink.unique_path(f"{d}/sink/events/S-n.json", f"{d}/other"))

    def test_u14_tracked_files_a_sink_gitignore_matches_survive(self):
        self.config(kind="skill", live=False, sink=self.sink_cfg())
        self.run_review(lambda w, r: write(f"{w}/learned-good/SKILL.md", GOOD.format(n="learned-good")))
        first_ev = next(f for f in self.remote_files() if f.startswith("learnings/events/"))
        other = f"{self.tmp.name}/other"  # someone ignores what the sink already tracks
        sh("git", "clone", "-q", "-b", "team/learnings", self.remote, other)
        sh("git", "-C", other, "config", "user.name", "o")
        sh("git", "-C", other, "config", "user.email", "o@o")
        write(f"{other}/.gitignore", "learnings/events/\nlearnings/skills/learned-good/\n")
        sh("git", "-C", other, "add", ".gitignore")
        sh("git", "-C", other, "commit", "-qm", "ignore")
        sh("git", "-C", other, "push", "-q", "origin", "team/learnings")
        self.run_review(lambda w, r: write(f"{w}/learned-good/SKILL.md", GOOD.format(n="learned-good") + "2. more\n"))
        files = self.remote_files()
        clone = os.path.join(common.state_dir(self.proj), "sink-clone")
        self.assertEqual(sh("git", "-C", clone, "ls-tree", "-r", "--name-only", "HEAD").split(), files)
        self.assertIn(first_ev, files)  # tracked and ignored: kept
        self.assertIn("2. more", self.show("team/learnings", "learnings/skills/learned-good/SKILL.md"))
        evs = sorted(f for f in files if f.startswith("learnings/events/"))
        self.assertEqual(len(evs), 2, files)  # our own new event lands, ignored or not
        self.assertEqual(json.loads(self.show("team/learnings", evs[-1]))["verb"], "updated")
        import shutil
        self.run_review(lambda w, r: shutil.rmtree(f"{w}/learned-good"))
        self.assertFalse(any(f.startswith("learnings/skills/learned-good/") for f in self.remote_files()))
        self.assertIn(first_ev, self.remote_files())

    def test_u14_a_failed_force_add_fails_the_write(self):
        self.config(kind="record", sink=self.sink_cfg())
        self.run_review(lambda w, r: write(f"{r}/a.md", RECORD.format(s="first")))
        orig, logs = review.git, []

        def git(top, *args, **kw):
            if "-f" in args and "add" in args:
                return subprocess.CompletedProcess(args, 128, "", "fatal: boom")
            return orig(top, *args, **kw)
        with mock.patch.object(review, "git", git):
            ref = sink.write_sink({"sink": self.sink_cfg()}, common.state_dir(self.proj),
                                  [{"kind": "record", "name": "b", "verb": "recorded",
                                    "writes": [{"rel": "S-b.md", "text": "b\n"}]}], logs.append)
        self.assertIn("staging failed", ref)
        self.assertTrue(any("fatal: boom" in l for l in logs), logs)
        self.assertTrue(os.listdir(os.path.join(common.state_dir(self.proj), "sink-pending")))  # kept

    def test_u15_a_sink_gitignore_on_the_whole_path_still_lands_and_pushes(self):
        self.config(kind="both", live=False, sink=self.sink_cfg())
        self.run_review(lambda w, r: (write(f"{w}/learned-good/SKILL.md", GOOD.format(n="learned-good")),
                                      write(f"{r}/a.md", RECORD.format(s="first"))))
        before = self.remote_files()
        other = f"{self.tmp.name}/other"
        sh("git", "clone", "-q", "-b", "team/learnings", self.remote, other)
        sh("git", "-C", other, "config", "user.name", "o")
        sh("git", "-C", other, "config", "user.email", "o@o")
        write(f"{other}/.gitignore", "learnings/\n")
        sh("git", "-C", other, "add", ".gitignore")
        sh("git", "-C", other, "commit", "-qm", "ignore the sink path")
        sh("git", "-C", other, "push", "-q", "origin", "team/learnings")
        orig = sink.restage

        def stray_then_restage(clone, path, *rest):  # an ignored file that isn't ours
            write(os.path.join(clone, path, "stray.txt"), "not ours\n")
            return orig(clone, path, *rest)
        with mock.patch.object(sink, "restage", stray_then_restage):
            self.run_review(lambda w, r: (write(f"{w}/learned-good/SKILL.md", GOOD.format(n="learned-good") + "2. more\n"),
                                          write(f"{r}/b.md", RECORD.format(s="second"))))
        files = self.remote_files()
        self.assertTrue(set(before) <= set(files), (before, files))  # tracked: all kept
        self.assertTrue(any(f.endswith("-b.md") for f in files), files)  # ours: landed and pushed
        self.assertEqual(len([f for f in files if f.startswith("learnings/events/")]), 2, files)
        self.assertIn("2. more", self.show("team/learnings", "learnings/skills/learned-good/SKILL.md"))
        self.assertNotIn("learnings/stray.txt", files)  # never another ignored file
        self.assertFalse(os.path.isdir(os.path.join(common.state_dir(self.proj), "sink-pending"))
                         and os.listdir(os.path.join(common.state_dir(self.proj), "sink-pending")))

    def test_u12_stat_blind_git_still_commits_a_same_size_rewrite(self):
        # As in a container whose ~/.gitconfig sets these: git compares only size and mtime seconds.
        gconf = f"{self.tmp.name}/gitconfig"
        write(gconf, "[core]\n\tcheckStat = minimal\n\ttrustctime = false\n")
        sdir = f"{self.tmp.name}/sdir"
        os.makedirs(sdir)
        cfg = {"sink": self.sink_cfg()}

        def land(text):
            src = f"{self.tmp.name}/src-{text}/learned-x"
            write(f"{src}/SKILL.md", text)
            os.utime(f"{src}/SKILL.md", (1_000_000_000, 1_000_000_000))  # copy2 keeps it: same mtime
            return sink.write_sink(cfg, sdir, [{"kind": "skill", "name": "learned-x", "verb": "updated",
                                                "writes": [{"rel": "skills/learned-x", "tree": src}]}], print)
        with mock.patch.dict(review.GIT_ENV, GIT_CONFIG_GLOBAL=gconf):
            land("created\n")
            clone = os.path.join(sdir, "sink-clone")
            sh("git", "-C", clone, "config", "core.checkStat", "minimal")
            sh("git", "-C", clone, "config", "core.trustctime", "false")
            land("updated\n")
        self.assertEqual(self.show("team/learnings", "learnings/skills/learned-x/SKILL.md"), "updated\n")

    # ---- the host field and the commit message ----------------------------------------------

    def landed(self, **kw):
        """Record and event text from one review with these config keys, and the sink commit."""
        self.config(kind="both", live=False, sink=self.sink_cfg(), **kw)
        self.run_review(lambda w, r: (write(f"{w}/learned-good/SKILL.md", GOOD.format(n="learned-good")),
                                      write(f"{r}/h.md", RECORD.format(s="dotnet: command not found"))))
        files = self.remote_files()
        rec = sorted(f for f in files if f.endswith("-h.md"))[-1]  # the newest
        ev = sorted(f for f in files if f.startswith("learnings/events/"))[-1]
        msg = sh("git", "--git-dir", self.remote, "log", "-1", "--format=%B", "team/learnings")
        return self.show("team/learnings", rec), json.loads(self.show("team/learnings", ev)), msg

    def test_u13_host_defaults_to_the_hostname(self):
        import socket
        rec, ev, _ = self.landed()
        self.assertIn(f"host: {json.dumps(socket.gethostname())}", rec)
        self.assertEqual(ev["host"], socket.gethostname())
        rec, ev, _ = self.landed(host=None)
        self.assertEqual(ev["host"], socket.gethostname())

    def test_u13_host_set_to_a_string(self):
        rec, ev, _ = self.landed(host="lane-3")
        self.assertIn('host: "lane-3"', rec)
        self.assertEqual(ev["host"], "lane-3")

    def test_u13_host_omitted_and_record_fields_cannot_bring_it_back(self):
        import socket
        for off in (False, ""):
            with self.subTest(host=off):
                self.tearDown()
                self.setUp()
                rec, ev, msg = self.landed(host=off, record_fields={"host": "sneaky", "lane": "3"})
                self.assertNotIn("host:", rec)
                self.assertIn('lane: "3"', rec)  # the rest of record_fields still lands
                self.assertNotIn("host", ev)
                for text in (rec, json.dumps(ev), msg):
                    self.assertNotIn(socket.gethostname(), text)
                    self.assertNotIn("sneaky", text)

    def test_u13_sink_commit_message_has_no_hostname(self):
        import socket
        _, _, msg = self.landed()
        self.assertTrue(msg.startswith("learned: 2 item(s)\n"), msg)
        self.assertNotIn(socket.gethostname(), msg)

    def test_u9_relative_paths_resolve_against_the_config_file(self):
        cfgdir = f"{self.tmp.name}/conf"
        write(f"{cfgdir}/c.json", json.dumps({"sink": {"repo": "../state-repo", "branch": "team/learnings"},
                                             "filter_command": ["./f.sh"], "context_files": ["m.md"]}))
        os.environ["LEARNED_SKILLS_CONFIG"] = f"{cfgdir}/c.json"
        here = os.getcwd()
        try:
            for cwd in (self.tmp.name, "/"):
                os.chdir(cwd)
                cfg = common.load_config(self.proj)
                self.assertEqual(cfg["sink"]["repo"], os.path.realpath(self.sinkrepo))
                self.assertEqual(cfg["filter_command"][0], os.path.realpath(f"{cfgdir}/f.sh"))
                self.assertEqual(cfg["context_files"][0], os.path.realpath(f"{cfgdir}/m.md"))
        finally:
            os.chdir(here)

    def test_u10_git_never_hangs(self):
        import time as _t
        t0 = _t.time()
        r = review.git(self.proj, "-c", "alias.slow=!sleep 5", "slow", timeout=1)
        self.assertEqual(r.returncode, 124)
        self.assertLess(_t.time() - t0, 4)

    def test_sink_path_cannot_escape(self):
        bad = dict(self.sink_cfg(), path="../outside")
        self.assertIsNone(sink.sink_config({"sink": bad}))


if __name__ == "__main__":
    unittest.main(verbosity=1)
