#!/usr/bin/env python3
"""learned-skills: look after the skills the background review learns.

In a session: /learned-skills:learned-status, -log, -undo NAME, -review-now, -reset-guard.
Directly: python3 PLUGIN/scripts/cli.py ARGS.
(No bin/ entry: claude.ai-hosted plugins may not ship PATH executables.)

  status            config, learned skills, turns until the next review
  log [N]           last N lines of the review log (default 40)
  undo NAME         restore NAME to before its last learned change (removes it if created),
                    from the review's saved copy if uncommitted, else from git
  review-now        run a review now, in the foreground, of every known transcript
  reset-guard [SESSION]  list open private-key guards, or clear SESSION's (logged): after a
                    BEGIN with no END, that transcript's text is withheld from reviews until
                    its END or this. Only the named transcript's guard is cleared, and its
                    unread text is then reviewed as ordinary text, so a real key body still
                    in it would reach the review: clear only when no real key was pasted.

Run from the project (or set CLAUDE_PROJECT_DIR). Nothing happens until the project has
.claude/learned-skills.json.
"""
import os
import re
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import common  # noqa: E402
import review  # noqa: E402


def git(top, *args):
    return review.git(top, *args)  # no prompts, a timeout


def need_config(proj):
    cfg = common.load_config(proj)
    if cfg is None:
        sys.exit(f"learned-skills: no {common.CONFIG_NAME} in {proj}: not enabled here")
    return cfg


def status(proj):
    cfg = need_config(proj)
    sdir = common.state_dir(proj)
    st = common.load_state(sdir)
    print(f"project     {proj}\nskills dir  {cfg['skills_dir']}\nstate dir   {sdir}")
    last = st.get("last_review") or 0
    print(f"next review after {max(cfg['every_turns'] - st.get('turns', 0), 0)} more turn(s)"
          f" and not before {time.strftime('%H:%M', time.localtime(last + cfg['min_interval_minutes'] * 60))}"
          if last else f"next review after {max(cfg['every_turns'] - st.get('turns', 0), 0)} more turn(s)")
    guards = st.get("key_guard") if isinstance(st.get("key_guard"), dict) else {}
    for t, g in guards.items():
        print(f"key guard open in {review.label(t)} ({(g or {}).get('label')}): its text is withheld"
              " from reviews until the matching END line; clear with reset-guard")
    skills = common.learned_skills(cfg["skills_dir"])
    print(f"{len(skills)} learned skill(s)")
    for d, _, desc in skills:
        print(f"  {d}: {(desc or '').strip()[:120]}")


def undo(proj, name):
    cfg = need_config(proj)
    if not re.fullmatch(r"learned-[a-z0-9-]{1,56}", name):
        sys.exit(f"learned-skills: only {common.PREFIX}* skills are undone here")
    saved = os.path.join(common.state_dir(proj), "undo", name)
    if os.path.isdir(saved):
        return undo_saved(cfg, name, saved)
    top = git(cfg["skills_dir"], "rev-parse", "--show-toplevel")
    if top.returncode:
        sys.exit("learned-skills: the skills dir is not in a git repo; restore by hand")
    top = os.path.realpath(top.stdout.strip())
    busy = review.git_busy(top)
    if busy:
        sys.exit(f"learned-skills: not now ({busy})")
    path = os.path.relpath(os.path.join(cfg["skills_dir"], name), top)
    if git(top, "status", "--porcelain", "--", path).stdout.strip():
        sys.exit(f"learned-skills: {path} has uncommitted changes; commit or discard them first")
    h = git(top, "log", "-1", "--format=%H %s", "--", path).stdout.strip()
    sha, _, subject = h.partition(" ")
    if not subject.startswith("learned: ") or subject.startswith("learned: undo "):
        # An undo is never undone here: that would put the bad version back. Use git for that.
        sys.exit(f"learned-skills: the last commit on {path} is not a learned change: {h or 'none'}")
    # Replace the dir with its state before that commit: files the commit added go too.
    if os.path.exists(os.path.join(top, path)):
        r = git(top, "rm", "-r", "-q", "--", path)
        if r.returncode:
            sys.exit(r.stderr)
    if not git(top, "cat-file", "-e", f"{sha}^:{path}").returncode:
        r = git(top, "checkout", f"{sha}^", "--", path)
        if r.returncode:
            sys.exit(r.stderr)
    c = git(top, "commit", "-q", "-m", f"learned: undo {name}\n\nReverts {sha[:10]} ({subject}).", "--", path)
    if c.returncode:
        sys.exit(c.stderr.strip() or c.stdout.strip())
    print(f"undone: {name} (was {sha[:10]} {subject})")


def undo_saved(cfg, name, saved):
    """Undo a learned change that was left uncommitted, from the copies the review kept."""
    if review.changed_dirs_one(os.path.join(saved, "after"), cfg["skills_dir"], name):
        sys.exit(f"learned-skills: {name} changed after its last learned change; restore it by hand "
                 f"(the copy from before that change is in {os.path.join(saved, 'before')})")
    review.restore(name, os.path.join(saved, "before"), cfg["skills_dir"])
    shutil.rmtree(saved)
    print(f"undone: {name} (an uncommitted learned change; the working tree is as before it)")


def review_now(proj):
    """Runs the review in the foreground, its output both here and in review.log (where the Stop
    hook's detached reviews write), so /learned-skills:learned-log shows it too."""
    p = subprocess.Popen([sys.executable, os.path.join(HERE, "review.py"), proj, "--now"],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    with open(os.path.join(common.state_dir(proj), "review.log"), "a") as log:
        for line in p.stdout:
            sys.stdout.write(line)
            log.write(line)
            log.flush()
    return p.wait()


def main():
    args = sys.argv[1:]
    proj = common.project_dir()
    if not args or args[0] in ("-h", "--help"):
        print(__doc__.strip())
    elif args[0] == "status":
        status(proj)
    elif args[0] == "log":
        need_config(proj)
        n = int(args[1]) if len(args) > 1 else 40
        p = os.path.join(common.state_dir(proj), "review.log")
        if os.path.exists(p):
            with open(p) as fh:
                print("".join(fh.readlines()[-n:]), end="")
    elif args[0] == "undo" and len(args) == 2:
        undo(proj, args[1])
    elif args[0] == "reset-guard" and len(args) in (1, 2):
        need_config(proj)
        sdir = common.state_dir(proj)
        if len(args) == 1:
            guards = common.load_state(sdir).get("key_guard") or {}
            print("\n".join(f"open: {review.label(t)} ({(g or {}).get('label')}) {t}" for t, g in guards.items())
                  or "no open key guard")
            return
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}|/[A-Za-z0-9._/-]{1,4000}\.jsonl", args[1]):
            sys.exit("learned-skills: reset-guard takes one session id, as status shows it, or its full path")
        with common.locked_state(sdir) as st:
            cleared = review.reset_guards(st, args[1])
        msg = (f"cleared the key guard of {args[1]}. Its text after the saved offset, unread so far,"
               " is now reviewed as ordinary text: a real key body still in it would reach the"
               " review with no BEGIN to hide it" if cleared else
               f"nothing cleared: no single open key guard for {args[1]} (an id two transcripts share needs the full path)")
        if cleared:  # in the review log too, where `log` shows it
            with open(os.path.join(sdir, "review.log"), "a") as fh:
                fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} key guard reset for {args[1]} "
                         "by cli.py reset-guard; its text is reviewed again from the saved offset\n")
        print(msg)
    elif args[0] == "review-now":
        need_config(proj)
        if not common.load_state(common.state_dir(proj))["transcripts"]:
            sys.exit("learned-skills: no transcript seen yet (the Stop hook records it after a turn)")
        sys.exit(review_now(proj))
    else:
        sys.exit(__doc__.strip())


if __name__ == "__main__":
    main()
