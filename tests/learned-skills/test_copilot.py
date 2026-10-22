#!/usr/bin/env python3
"""Offline engine, hook, transcript and hostile-tool regressions. No model calls."""
import contextlib
import io
import json
import os
import shlex
import subprocess
import time
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
PLUGIN = os.path.realpath(os.path.join(os.path.dirname(__file__), "../../plugins/learned-skills"))
SCRIPTS = os.path.join(PLUGIN, "scripts")
sys.path.insert(0, SCRIPTS)
import cli
import common
import on_prompt
import on_stop
import review
import reviewer_permissions

GOOD = "---\nname: learned-fixture\ndescription: Use when verifying a synthetic cache migration.\n---\n\n1. Verify the cache.\n"
RECORD = ("---\nsymptom: fixture command not found\nstage: setup\ncause: harness\n"
          "resolution: install the fixture tool\nrecurs: yes\n---\n\nCheck the tool before starting.\n")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


class Copilot(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        self.proj = os.path.join(self.root, "project")
        self.rdir = os.path.join(self.root, "reviewer")
        for side in ("work", "work-records"):
            os.makedirs(os.path.join(self.rdir, side))
        self.env = mock.patch.dict(os.environ, {
            "XDG_STATE_HOME": os.path.join(self.root, "state"), "COPILOT_GITHUB_TOKEN": "test-only",
        })
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.tmp.cleanup)
        self.fake = os.path.join(self.root, "bin", "copilot")
        write(self.fake, "#!" + sys.executable + "\n" + (
            "import json, os, subprocess, sys\nsys.dont_write_bytecode = True\n"
            f"sys.path.insert(0, {SCRIPTS!r})\n"
            "import review\n"
            "if '--help' in sys.argv:\n"
            "    print('\\n'.join(review.COPILOT_FLAGS)); sys.exit(0)\n"
            "if '--version' in sys.argv:\n"
            "    print('GitHub Copilot CLI 1.0.102.'); sys.exit(0)\n"
            "home = os.environ['COPILOT_HOME']\n"
            "with open(os.path.join(home, 'settings.json')) as f: settings = json.load(f)\n"
            "with open(os.path.join(home, 'capture.json'), 'w') as f:\n"
            "    json.dump({'argv': sys.argv[1:], 'env': dict(os.environ), 'cwd': os.getcwd(), "
            "'settings': settings}, f)\n"
            "prompt = sys.argv[sys.argv.index('-p') + 1]\n"
            "if prompt == 'nonzero': sys.exit(7)\n"
            "if prompt == 'timeout':\n"
            "    import time; time.sleep(10)\n"
            f"files = {{'work/learned-fixture/SKILL.md': {GOOD!r}, 'work-records/fixture.md': {RECORD!r}}}\n"
            "hook = settings['hooks']['preToolUse'][0]\n"
            "for path, text in files.items():\n"
            "    patch = '*** Begin Patch\\n*** Add File: ' + path + '\\n+text\\n*** End Patch\\n'\n"
            "    event = {'toolName': 'apply_patch', 'toolArgs': {'input': patch}}\n"
            "    result = subprocess.run([hook['exec'], *hook['args']], input=json.dumps(event), "
            "capture_output=True, text=True)\n"
            "    assert result.returncode == 0, result.stderr\n"
            "    os.makedirs(os.path.dirname(path), exist_ok=True)\n"
            "    with open(path, 'w') as f: f.write(text)\n"
            "if sys.argv[sys.argv.index('--model') + 1] == 'fixture-nonzero': sys.exit(7)\n"
            "print('LEARNED created learned-fixture: synthetic repair\\nRECORDED fixture: check setup')\n"
        ))
        os.chmod(self.fake, 0o700)
        self.config()

    def config(self, **extra):
        write(os.path.join(self.proj, ".claude/learned-skills.json"), json.dumps(extra))
        return common.load_config(self.proj)

    def cfg(self, **extra):
        return self.config(engine="copilot", engine_command=[self.fake], model="fixture-model", **extra)

    def test_default_follows_transcript_not_installed_executables(self):
        cfg = self.config()
        self.assertEqual((cfg["engine"], cfg["model"], cfg["commit"]), ("auto", None, False))
        for engine, event, model in (
                ("claude", {"type": "user", "message": {"content": "hello"}}, "sonnet"),
                ("copilot", {"type": "session.start", "data": {"producer": "copilot-agent"}}, "auto")):
            path = os.path.join(self.root, engine + ".jsonl")
            write(path, json.dumps(event) + "\n")
            chosen = review.select_engine(cfg, {"transcript": path, "transcripts": []})
            self.assertEqual((chosen["engine"], chosen["model"]), (engine, model))
            explicit = review.select_engine(dict(cfg, engine="claude", model="custom"), {})
            self.assertEqual((explicit["engine"], explicit["model"]), ("claude", "custom"))

    def test_auto_uses_current_session_then_newest_known_transcript(self):
        a, b = os.path.join(self.root, "a.jsonl"), os.path.join(self.root, "b.jsonl")
        write(a, '{"type":"user","message":{"content":"a"}}\n')
        write(b, '{"type":"user.message","data":{"content":"b"}}\n')
        os.utime(a, (1, 1))
        cfg = self.config()
        state = {"transcript": a, "transcripts": [a, b]}
        self.assertEqual(review.select_engine(cfg, state)["engine"], "claude")
        state["transcript"] = None
        self.assertEqual(review.select_engine(cfg, state)["engine"], "copilot")

    def test_unknown_or_incomplete_transcript_refuses_auto(self):
        path = os.path.join(self.root, "unknown.jsonl")
        for content in ('{"type":"session.start","data":{"producer":"unknown"}}\n',
                        '{"type":"user.message"', '{}\n'):
            write(path, content)
            with self.assertRaises(review.ReviewRefused):
                review.select_engine(self.config(), {"transcript": path, "transcripts": [path]})
        for cfg in (self.config(engine="unknown"), self.config(engine="copilot", kind="unknown")):
            with self.assertRaises(review.ReviewRefused):
                review.select_engine(cfg, {})

    def test_generic_wrapper_prefix_and_relative_executable(self):
        cfg = self.cfg()
        cfg["engine_command"] = ["launcher", "agent", "run"]
        self.assertEqual(review.copilot_command(cfg, self.rdir, "p")[:3], ["launcher", "agent", "run"])
        cfg = self.config(engine_command=["./wrapper", "agent"])
        self.assertEqual(cfg["engine_command"], [os.path.join(self.proj, ".claude/wrapper"), "agent"])
        for prefix in ("copilot", [], [""], ["x", "--allow-all"], [None], ["x\nbad"], ["x\0bad"]):
            with self.subTest(prefix=prefix), self.assertRaises(review.ReviewRefused):
                review.copilot_command(dict(cfg, engine_command=prefix), self.rdir, "p")
        with self.assertRaises(review.ReviewRefused):
            review.copilot_command(cfg, self.rdir + "(*)", "p")

    def test_wrapper_argv_prefix_is_executed_without_shell(self):
        cfg = self.config(engine="copilot", engine_command=[sys.executable, self.fake], model="fixture-model")
        result = review.run_copilot(cfg, self.rdir, "wrapper fixture")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(os.path.isfile(os.path.join(self.rdir, "work/learned-fixture/SKILL.md")))

    def test_fake_executable_argv_environment_and_settings_are_isolated(self):
        injected = {
            "COPILOT_ALLOW_ALL": "true", "COPILOT_ASSISTED_APPROVAL": "true",
            "COPILOT_CUSTOM_INSTRUCTIONS_DIRS": "/outside", "COPILOT_AGENT_SESSION_ID": "outer",
            "COPILOT_PROVIDERS_CONFIG": "/outside/providers.json", "COPILOT_PLUGIN_ROOT": "/outside",
            "CLAUDE_PROJECT_DIR": "/outside", "NODE_OPTIONS": "--require=/outside/loader.js",
            "BASH_ENV": "/outside/startup", "GIT_DIR": "/outside/.git", "SECRET_FIXTURE": "private",
            "COPILOT_PROVIDER_API_KEY_COMMAND": "unsafe shell command",
        }
        with mock.patch.dict(os.environ, injected):
            result = review.run_copilot(self.cfg(), self.rdir, "fixture")
        self.assertEqual(result.returncode, 0, result.stderr)
        home = os.path.join(self.root, "copilot-home", ".copilot")
        with open(os.path.join(home, "capture.json")) as fh:
            captured = json.load(fh)
        argv, env = captured["argv"], captured["env"]
        self.assertEqual(argv[:4], ["-p", "fixture", "--model", "fixture-model"])
        for flag in review.COPILOT_FLAGS:
            self.assertTrue(any(arg == flag or arg.startswith(flag + "=") for arg in argv), flag)
        self.assertIn("--available-tools=view,glob,rg,apply_patch", argv)
        self.assertIn("--deny-tool=shell", argv)
        self.assertIn("--deny-tool=url", argv)
        for side in ("work", "work-records"):
            self.assertIn(f"--allow-tool=write({self.rdir}/{side})", argv)
        self.assertFalse(any(arg.startswith("--allow-all") for arg in argv))
        self.assertEqual(env["COPILOT_ALLOW_ALL"], "false")
        self.assertEqual(env[common.GUARD_ENV], "1")
        for key in injected.keys() - {"COPILOT_ALLOW_ALL"}:
            self.assertNotIn(key, env)
        self.assertEqual(env["HOME"], os.path.dirname(home))
        for key in ("COPILOT_HOME", "TMPDIR", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
            self.assertTrue(env[key].startswith(env["HOME"] + "/"), key)
        self.assertEqual(captured["cwd"], self.rdir)
        hook = captured["settings"]["hooks"]["preToolUse"][0]
        self.assertEqual(hook["exec"], sys.executable)
        self.assertEqual(hook["args"], [os.path.join(SCRIPTS, "reviewer_permissions.py"), self.rdir, "copilot"])
        self.assertNotIn("disableAllHooks", captured["settings"])
        self.assertEqual(os.stat(os.path.dirname(home)).st_mode & 0o777, 0o700)

    def test_unavailable_flags_and_old_hook_runtime_refuse(self):
        for text in ("print('--model')", "print(' '.join(review.COPILOT_FLAGS))"):
            write(self.fake, "#!" + sys.executable + f"\nimport sys\nsys.path.insert(0, {SCRIPTS!r})\nimport review\n"
                  + "if '--help' in sys.argv:\n    " + text + "\nelse: print('GitHub Copilot CLI 1.0.1.')\n")
            with self.assertRaises(review.ReviewRefused):
                review.run_copilot(self.cfg(), self.rdir, "fixture")
        self.assertFalse(os.path.exists(os.path.join(self.rdir, "work/learned-fixture")))

    def test_repo_configuration_and_policy_refuse(self):
        write(os.path.join(self.rdir, ".github/hooks/hostile.json"), "{}")
        with self.assertRaisesRegex(review.ReviewRefused, "project configuration"):
            review.run_copilot(self.cfg(), self.rdir, "fixture")
        os.remove(os.path.join(self.rdir, ".github/hooks/hostile.json"))
        os.rmdir(os.path.join(self.rdir, ".github/hooks"))
        os.rmdir(os.path.join(self.rdir, ".github"))
        os.mkdir(os.path.join(self.root, ".git"))
        with self.assertRaisesRegex(review.ReviewRefused, "git repository"):
            review.run_copilot(self.cfg(), self.rdir, "fixture")
        os.rmdir(os.path.join(self.root, ".git"))
        exists = os.path.exists
        with mock.patch.object(os.path, "exists", side_effect=lambda p: p == "/etc/github-copilot/policy.d" or exists(p)):
            with mock.patch.object(os, "listdir", return_value=["policy.json"]):
                with self.assertRaisesRegex(review.ReviewRefused, "machine policy"):
                    review.check_copilot_root(self.rdir)

    def test_missing_auth_does_not_fall_back_to_claude(self):
        original = subprocess.run

        def run(argv, **kwargs):
            if argv[:3] == ["gh", "auth", "token"]:
                return subprocess.CompletedProcess(argv, 1, "", "")
            return original(argv, **kwargs)

        with mock.patch.dict(os.environ, {"PATH": os.environ["PATH"]}, clear=True):
            with mock.patch.object(subprocess, "run", side_effect=run):
                with self.assertRaisesRegex(review.ReviewRefused, "gh auth login"):
                    review.run_copilot(self.cfg(), self.rdir, "fixture")

    def forker(self, name, then):
        """A fake engine that forks a sleeping child (pid to a file), then runs `then`."""
        pidfile = os.path.join(self.root, name + ".pid")
        path = os.path.join(self.root, "bin", name)
        write(path, "#!" + sys.executable + "\nimport subprocess, sys, time\n"
              f"child = subprocess.Popen(['sleep', '300'])\nopen({pidfile!r}, 'w').write(str(child.pid))\n"
              + then + "\n")
        os.chmod(path, 0o700)
        return path, pidfile

    def assert_gone(self, pidfile):
        with open(pidfile) as fh:
            pid = int(fh.read())
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            with open(f"/proc/{pid}/stat") as fh:  # reparented zombies count as gone
                if fh.read().rsplit(")", 1)[1].split()[0] == "Z":
                    return
            time.sleep(0.05)
        os.kill(pid, 9)
        self.fail(f"descendant {pid} outlived the engine call")

    def test_timeout_kills_every_descendant(self):
        path, pidfile = self.forker("hang", "time.sleep(300)")
        with self.assertRaises(subprocess.TimeoutExpired):
            review.run_group([path], timeout=1)
        self.assert_gone(pidfile)

    def test_normal_exit_reaps_forked_descendants(self):
        path, pidfile = self.forker("leaver", "sys.exit(0)")
        self.assertEqual(review.run_group([path], timeout=30).returncode, 0)
        self.assert_gone(pidfile)

    def test_gh_copilot_shim_is_refused_before_any_launch(self):
        shim = os.path.join(self.root, "bin", "copilot-shim")
        write(shim, '#!/bin/sh\nPATH=$(echo "$PATH" | sed "s|$HOME/.local/bin:||")\nexec gh copilot "$@"\n')
        os.chmod(shim, 0o700)
        with mock.patch.object(review, "run_group", side_effect=AssertionError("launched")):
            with self.assertRaisesRegex(review.ReviewRefused, "gh copilot"):
                review.run_copilot(self.config(engine="copilot", engine_command=[shim]), self.rdir, "p")

    def test_classic_pat_is_refused_from_env_and_gh(self):
        with mock.patch.dict(os.environ, {"COPILOT_GITHUB_TOKEN": "ghp_" + "x" * 36}):
            with self.assertRaisesRegex(review.ReviewRefused, "classic"):
                review.run_copilot(self.cfg(), self.rdir, "fixture")
        original = subprocess.run

        def run(argv, **kwargs):
            if argv[:3] == ["gh", "auth", "token"]:
                return subprocess.CompletedProcess(argv, 0, "ghp_" + "y" * 36 + "\n", "")
            return original(argv, **kwargs)

        with mock.patch.dict(os.environ, {"PATH": os.environ["PATH"]}, clear=True):
            with mock.patch.object(subprocess, "run", side_effect=run):
                with self.assertRaisesRegex(review.ReviewRefused, "classic"):
                    review.run_copilot(self.cfg(), self.rdir, "fixture")

    def test_cli_1_0_103_retired_remote_flags_are_adapted(self):
        # 1.0.103: --no-remote removed, --no-remote-export renamed to --sync-session off.
        new_help = [f for f in review.COPILOT_FLAGS if f not in review.REMOTE_FLAGS] + ["--sync-session"]
        script = open(self.fake).read().replace(
            "print('\\n'.join(review.COPILOT_FLAGS)); sys.exit(0)",
            f"print('\\n'.join({new_help!r})); sys.exit(0)")
        self.assertNotEqual(script, open(self.fake).read())
        write(self.fake, script)
        result = review.run_copilot(self.cfg(), self.rdir, "fixture")
        self.assertEqual(result.returncode, 0, result.stderr)
        with open(os.path.join(os.path.dirname(self.rdir), "copilot-home", ".copilot", "capture.json")) as fh:
            argv = json.load(fh)["argv"]
        self.assertIn("--sync-session=off", argv)
        self.assertNotIn("--no-remote", argv)
        self.assertNotIn("--no-remote-export", argv)

    def test_remote_flags_missing_without_the_new_shape_still_refuse(self):
        old_help = [f for f in review.COPILOT_FLAGS if f != "--no-remote"]
        script = open(self.fake).read().replace(
            "print('\\n'.join(review.COPILOT_FLAGS)); sys.exit(0)",
            f"print('\\n'.join({old_help!r})); sys.exit(0)")
        write(self.fake, script)
        with self.assertRaisesRegex(review.ReviewRefused, "--no-remote"):
            review.run_copilot(self.cfg(), self.rdir, "fixture")

    def test_nonzero_and_timeout_are_not_success(self):
        result = review.run_copilot(self.cfg(), self.rdir, "nonzero")
        self.assertEqual(result.returncode, 7)
        with self.assertRaises(subprocess.TimeoutExpired):
            review.run_copilot(self.cfg(timeout_seconds=0.1), self.rdir, "timeout")

    def test_refusal_and_partial_nonzero_keep_offsets_and_apply_nothing(self):
        transcript = os.path.join(self.root, "events.jsonl")
        write(transcript, json.dumps({"type": "user.message", "data": {"content": "synthetic work " * 180}}) + "\n")
        cfg = self.config(engine="copilot", engine_command=[self.fake], model="fixture-nonzero")
        sdir = common.state_dir(self.proj)
        with common.locked_state(sdir) as state:
            state["transcripts"] = [transcript]
        for mode in ("nonzero", "refusal"):
            if mode == "refusal":
                write(self.fake, "#!" + sys.executable + "\nprint('--model')\n")
            output = io.StringIO()
            with mock.patch.object(sys, "argv", ["review.py", self.proj, "--now"]):
                with contextlib.redirect_stdout(output):
                    review.main()
            self.assertIn("nothing applied", output.getvalue())
            self.assertEqual(common.load_state(sdir)["offsets"], {})
            self.assertEqual(common.learned_skills(cfg["skills_dir"]), [])
        self.assertFalse(os.path.exists(os.path.join(sdir, "notices.jsonl")))

    def test_both_review_kinds_apply_through_fake_executable_and_undo(self):
        transcript = os.path.join(self.root, "events.jsonl")
        write(transcript, json.dumps({"type": "user.message", "data": {"content": "synthetic work " * 180}}) + "\n")
        for kind in ("skill", "record", "both"):
            cfg = self.cfg(kind=kind)
            sdir = common.state_dir(self.proj)
            with common.locked_state(sdir) as state:
                state["transcripts"] = [transcript]
                state["offsets"] = {}
            output = io.StringIO()
            with mock.patch.object(sys, "argv", ["review.py", self.proj, "--now"]):
                with mock.patch.object(review, "run_claude", side_effect=AssertionError("unexpected fallback")):
                    with contextlib.redirect_stdout(output):
                        review.main()
            self.assertIn("copilot exit 0", output.getvalue())
            self.assertEqual(bool(common.learned_skills(cfg["skills_dir"])), kind != "record")
            self.assertEqual("recorded fixture" in output.getvalue(), kind != "skill")
            if kind != "record":
                with contextlib.redirect_stdout(io.StringIO()):
                    cli.undo(self.proj, "learned-fixture")
            self.assertTrue(common.load_state(sdir)["offsets"])

    def hook(self, module, event, *args):
        output = io.StringIO()
        with mock.patch.object(sys, "argv", [module.__file__, *args]):
            with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(event))):
                with contextlib.redirect_stdout(output):
                    module.main()
        return output.getvalue()

    def test_native_hooks_and_session_end_transport_without_double_count(self):
        with open(os.path.join(PLUGIN, "com.github.copilot/hooks/hooks.json")) as fh:
            hooks = json.load(fh)
        self.assertEqual(hooks["version"], 1)
        self.assertEqual(set(hooks["hooks"]), {"agentStop", "sessionEnd", "sessionStart", "postToolUse"})
        self.config(every_turns=2, min_interval_minutes=0)
        event = {"cwd": self.proj, "sessionId": "12345678-1234-1234-1234-123456789abc",
                 "transcriptPath": os.path.join(self.root, "events.jsonl")}
        with mock.patch.object(on_stop, "spawn") as spawn:
            self.hook(on_stop, dict(event, agentId="child"), "--copilot")
            self.hook(on_stop, dict(event, stop_hook_active=True), "--copilot")
            self.hook(on_stop, event, "--copilot")
            self.hook(on_stop, event, "--copilot")
            self.hook(on_stop, event, "--copilot", "--session-end")
            self.assertEqual(spawn.call_count, 1)
        st = common.load_state(common.state_dir(self.proj))
        self.assertEqual(st["turns"], 2)
        self.assertEqual(st["transcripts"], [event["transcriptPath"]])
        self.assertEqual(st["session_id"], event["sessionId"])
        with mock.patch.dict(os.environ, {"COPILOT_HOME": os.path.join(self.root, "host-home")}):
            event.pop("transcriptPath")
            expected = os.path.join(self.root, "host-home/session-state", event["sessionId"], "events.jsonl")
            self.assertEqual(common.transcript_path(event), expected)
        event["sessionId"] = "../../outside"
        self.assertIsNone(common.transcript_path(event))

    def test_session_end_retries_due_review_and_hooks_fail_open_when_disabled(self):
        self.config(every_turns=1, min_interval_minutes=0)
        event = {"cwd": self.proj, "sessionId": "12345678-1234-1234-1234-123456789abc"}
        sdir = common.state_dir(self.proj)
        with common.locked_state(sdir) as state:
            state["turns"] = 1
        with mock.patch.object(on_stop, "spawn") as spawn:
            self.hook(on_stop, event, "--copilot", "--session-end")
            spawn.assert_called_once()
            with mock.patch.dict(os.environ, {common.GUARD_ENV: "1"}):
                self.hook(on_stop, event, "--copilot")
            os.remove(os.path.join(self.proj, common.CONFIG_NAME))
            self.hook(on_stop, event, "--copilot")
            spawn.assert_called_once()

    def test_notice_is_context_delivered_once_not_lost_at_prompt(self):
        path = os.path.join(common.state_dir(self.proj), "notices.jsonl")
        write(path, json.dumps({"verb": "created", "skill": "learned-fixture", "ref": "not committed"}) + "\n")
        event = {"cwd": self.proj, "sessionId": "fixture"}
        with mock.patch.dict(os.environ, {"COPILOT_CLI": "1", "CLAUDE_PROJECT_DIR": "/wrong"}):
            self.assertEqual(self.hook(on_prompt, dict(event, hook_event_name="UserPromptSubmit")), "")
            self.assertTrue(os.path.exists(path))
            self.assertEqual(self.hook(on_prompt, dict(event, agentId="child"), "--copilot"), "")
            output = self.hook(on_prompt, event, "--copilot")
        text = json.loads(output)["additionalContext"]
        self.assertIn("learned-fixture", text)
        self.assertIn('cli.py" undo NAME', text)
        self.assertEqual(self.hook(on_prompt, event, "--copilot"), "")

    def test_copilot_transcript_offsets_redaction_children_and_tool_sources(self):
        token = "gh" + "p_" + "A1b2C3d4" * 5
        begin, end = (f"-----{edge} RSA {'PRIVATE'} KEY-----" for edge in ("BEGIN", "END"))
        events = [
            {"type": "user.message", "data": {"content": "hello " + token}},
            {"type": "assistant.message", "data": {"content": "investigating"}},
            {"type": "assistant.message", "data": {"content": "CHILD", "parentToolCallId": "parent"}},
            {"type": "assistant.message", "agentId": "child", "data": {"content": "CHILD"}},
            {"type": "tool.execution_start", "data": {"toolName": "view", "toolCallId": "t1",
                                                     "arguments": {"path": "example"}}},
            {"type": "tool.execution_complete", "data": {"toolCallId": "t1", "success": False,
                                                        "error": {"message": token}}},
            {"type": "tool.execution_complete", "data": {"toolCallId": "key", "success": True,
                                                        "result": {"content": begin + "\nBODY"}}},
            {"type": "tool.execution_complete", "data": {"toolCallId": "decoy", "success": True,
                                                        "result": {"content": end}}},
            {"type": "tool.execution_complete", "data": {"toolCallId": "key", "success": True,
                                                        "result": {"content": "BODY\n" + end + "\nafter-end"}}},
            {"type": "hook.start", "data": {"input": "DUPLICATE"}},
        ]
        path = os.path.join(self.root, "events.jsonl")
        write(path, "\n".join(json.dumps(e) for e in events) + "\n")
        text, offset = review.digest(path, 0, 200_000)
        for wanted in ("USER: hello", "ASSISTANT: investigating", "TOOL view:", "RESULT (error)", "after-end"):
            self.assertIn(wanted, text)
        for unwanted in (token, "CHILD", "DUPLICATE", "BODY"):
            self.assertNotIn(unwanted, text)
        self.assertEqual(offset, os.path.getsize(path))
        with open(path, "a") as fh:
            fh.write('{"type":"user.message"')
        self.assertEqual(review.digest(path, offset, 200_000), ("", offset))

    def test_copilot_session_labels_are_ids_not_events(self):
        session = "12345678-1234-1234-1234-123456789abc"
        self.assertEqual(review.label(f"/home/session-state/{session}/events.jsonl"), session)
        self.assertEqual(review.label("/home/claude-session.jsonl"), "claude-session")

    def guard(self, engine, tool, args):
        event = ({"toolName": tool, "toolArgs": args} if engine == "copilot"
                 else {"tool_name": tool, "tool_input": args})
        argv = [sys.executable, os.path.join(SCRIPTS, "reviewer_permissions.py"), self.rdir]
        if engine == "copilot":
            argv.append(engine)
        return subprocess.run(argv, input=json.dumps(event), capture_output=True, text=True)

    def test_hostile_read_search_write_move_shell_network_and_agent_probes(self):
        patch = "*** Begin Patch\n*** Add File: work/learned-fixture/SKILL.md\n+text\n*** End Patch\n"
        probes = [
            ("view", {"path": "../outside"}), ("view", {"path": "/etc/passwd"}),
            ("view", {"path": self.rdir + "-sibling/file"}), ("view", {"path": None}),
            ("rg", {"pattern": "secret", "paths": [".", ".."]}),
            ("glob", {"pattern": "../**/*"}), ("glob", {"pattern": "{.,../outside}/**"}),
            ("rg", {"pattern": "secret", "glob": "/etc/*"}),
            ("rg", {"pattern": "secret", "paths": "--pre=touch outside"}),
            ("rg", {"pattern": "secret", "type": "--pre=touch outside"}),
            ("rg", {"pattern": "secret", "extra_args": ["--pre=touch outside"]}),
            ("view", {"path": "digest.md", "command": "cat ../outside"}),
            ("apply_patch", {"input": patch.replace("work/", "../")}),
            ("apply_patch", {"input": patch.replace("work/learned-fixture/SKILL.md", "digest.md")}),
            ("apply_patch", {"input": patch.replace("*** End Patch",
                "*** Update File: work/x\n*** Move to: ../outside\n*** End Patch")}),
            ("bash", {"command": "touch ../outside"}), ("powershell", {"command": "Get-Content ../outside"}),
            ("web_fetch", {"url": "https://example.invalid"}), ("web_search", {"query": "private"}),
            ("task", {"prompt": "escape"}), ("skill", {"skill": "outside"}),
            ("read_agent", {"agent_id": "outside"}), ("unknown", {}),
        ]
        for tool, args in probes:
            with self.subTest(tool=tool, args=args):
                result = self.guard("copilot", tool, args)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(json.loads(result.stdout)["permissionDecision"], "deny")
        for tool, args in (
                ("view", {"path": "digest.md"}), ("rg", {"pattern": "x"}),
                ("glob", {"pattern": "**/*.md"}), ("apply_patch", {"input": patch}),
                ("apply_patch", patch)):
            result = self.guard("copilot", tool, args)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["permissionDecision"], "allow")

    def test_both_guards_refuse_symlinks_hardlinks_and_special_files(self):
        write(os.path.join(self.root, "outside"), "sentinel")
        for entry in ("symlink", "hardlink", "fifo"):
            path = os.path.join(self.rdir, entry)
            if entry == "symlink":
                os.symlink(self.root, path)
            elif entry == "hardlink":
                os.link(os.path.join(self.root, "outside"), path)
            else:
                os.mkfifo(path)
            for engine, tool, args in (("copilot", "glob", {"pattern": "**/*"}),
                                       ("claude", "Glob", {"pattern": "**/*"})):
                self.assertEqual(self.guard(engine, tool, args).returncode, 2)
            os.remove(path)

    def test_claude_guard_equivalence_and_launcher_registration(self):
        for tool, args, allowed in (
                ("Read", {"file_path": "digest.md"}, True),
                ("Read", {"file_path": "../outside"}, False),
                ("Edit", {"file_path": "work/learned-fixture/SKILL.md"}, True),
                ("Write", {"file_path": "work-records/fixture.md"}, True),
                ("Write", {"file_path": "digest.md"}, False),
                ("Grep", {"pattern": "secret", "path": ".."}, False),
                ("Glob", {"pattern": "../**/*"}, False), ("Bash", {"command": "true"}, False)):
            self.assertEqual(self.guard("claude", tool, args).returncode == 0, allowed)
        with mock.patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")) as run:
            review.run_claude(self.config(), self.rdir, "fixture")
        argv = run.call_args.args[0]
        self.assertEqual(argv[argv.index("--setting-sources") + 1], "")
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "dontAsk")
        self.assertEqual(argv[argv.index("--tools") + 1], "Read,Glob,Grep,Edit,Write")
        settings = json.loads(argv[argv.index("--settings") + 1])
        hook = settings["hooks"]["PreToolUse"][0]
        self.assertEqual(hook["matcher"], "*")
        command = shlex.split(hook["hooks"][0]["command"])
        self.assertEqual(command, [sys.executable, os.path.join(SCRIPTS, "reviewer_permissions.py"), self.rdir])

    def test_guard_budget_and_malformed_input_deny_instead_of_timing_out(self):
        event = {"toolName": "view", "toolArgs": {"path": "digest.md"}}
        output = io.StringIO()
        with mock.patch.object(sys, "argv", ["guard", self.rdir, "copilot"]):
            with mock.patch.object(sys, "stdin", io.StringIO(json.dumps(event))):
                with mock.patch.object(reviewer_permissions, "plain_tree", side_effect=TimeoutError):
                    with contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
                        self.assertEqual(reviewer_permissions.main(), 2)
        self.assertEqual(json.loads(output.getvalue())["permissionDecision"], "deny")
        for raw in ("{", "null", "[]"):
            result = subprocess.run(
                [sys.executable, os.path.join(SCRIPTS, "reviewer_permissions.py"), self.rdir, "copilot"],
                input=raw, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(json.loads(result.stdout)["permissionDecision"], "deny")


if __name__ == "__main__":
    unittest.main()
