#!/usr/bin/env python3
"""Stop hook: count finished turns and, when a review is due, start one detached.

Never blocks or changes the turn: every path exits 0 with no output.
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402


def main():
    if os.environ.get("LEARNED_SKILLS_REVIEW"):  # common.GUARD_ENV, spelled out
        return  # the review's own claude finished a turn
    try:
        hook = json.load(sys.stdin)
    except ValueError:
        return
    proj = common.project_dir(hook)
    cfg = common.load_config(proj)
    transcript = hook.get("transcript_path")
    if cfg is None or not transcript:
        return
    sdir = common.state_dir(proj)
    now = time.time()
    with common.locked_state(sdir) as state:
        state["turns"] += 1
        state["transcript"] = transcript
        state["session_id"] = hook.get("session_id")
        if transcript not in state["transcripts"]:
            state["transcripts"] = (state["transcripts"] + [transcript])[-50:]
        # The review resets turns and last_review only when it really runs; a review that finds
        # too little text keeps the count, so the next due Stop tries again (at most once a minute).
        due = (state["turns"] >= cfg["every_turns"]
               and now - state["last_review"] >= cfg["min_interval_minutes"] * 60
               and now - state["last_attempt"] >= 60)
        if due:
            state["last_attempt"] = now
    if due:
        spawn(proj, sdir)


def spawn(proj, sdir):
    review = os.path.join(os.path.dirname(os.path.abspath(__file__)), "review.py")
    with open(os.path.join(sdir, "review.log"), "a") as log:
        subprocess.Popen([sys.executable, review, proj], stdin=subprocess.DEVNULL,
                         stdout=log, stderr=log, cwd=sdir, start_new_session=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # a hook must never fail the turn
        print(f"learned-skills: {e}", file=sys.stderr)
    sys.exit(0)
