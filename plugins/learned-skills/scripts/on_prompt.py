#!/usr/bin/env python3
"""UserPromptSubmit hook: hand the session any 💾 Learned notices from background reviews.

Prints them as added context (once each) so the agent can tell its people and they can say undo.
Never blocks the prompt.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402


def main():
    if os.environ.get("LEARNED_SKILLS_REVIEW"):  # common.GUARD_ENV, spelled out
        return
    try:
        hook = json.load(sys.stdin)
    except ValueError:
        hook = {}
    proj = common.project_dir(hook)
    cfg = common.load_config(proj)
    if cfg is None:
        return
    path = os.path.join(common.state_dir(proj), "notices.jsonl")
    try:
        os.rename(path, path + ".reading")  # take them atomically; a review may append meanwhile
    except OSError:
        return
    with open(path + ".reading") as fh:
        notices = [json.loads(line) for line in fh if line.strip()]
    os.remove(path + ".reading")
    if not notices:
        return
    def short(v, n):
        v = " ".join(str(v).split())
        return v if len(v) <= n else v[:n] + "…"
    # Capped: a summary is written by the review, which read untrusted text.
    lines = [f"💾 Learned: {short(n.get('verb'), 10)} {short(n.get('skill'), 64)}"
             + (f" ({short(n['summary'], 200)})" if n.get("summary") else "")
             + f" [{short(n.get('ref'), 60)}]" for n in notices[-10:]]
    if len(notices) > 10:
        lines.insert(0, f"({len(notices) - 10} older notices not shown; see `/learned-skills:learned-log`)")
    print("Background skill review since your last turn (learned-skills plugin):\n"
          + "\n".join(lines)
          + "\nTell the people you work with, in one line each, where you would normally report work. "
            "Review: read the skill's SKILL.md. Undo: `/learned-skills:learned-undo NAME`."
          + (f" Keep: a change marked not committed is only in the working tree; commit "
             f"`{os.path.relpath(cfg['skills_dir'], proj)}/NAME` to keep it, or set \"commit\": true "
             "in .claude/learned-skills.json to have reviews commit."
             if any("not committed" in str(n.get("ref")) for n in notices[-10:]) else ""))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"learned-skills: {e}", file=sys.stderr)
    sys.exit(0)
