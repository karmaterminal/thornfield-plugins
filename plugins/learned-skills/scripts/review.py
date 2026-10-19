#!/usr/bin/env python3
"""Background experience review: read the turns since the last review and let a headless
reviewer create or patch learned-* skills. Runs detached from the Stop hook; also `learned-skills
review-now`. Usage: review.py PROJECT_DIR [--now]. Reads every known transcript of the project
(state.json `transcripts`) past its saved offset, so turns from an ended or replaced session are
not lost.

Fail-closed: the reviewer gets no MCP servers, no shell, no web. Claude runs in this project's
state dir and edits staged skills. After it exits, only learned-* skill dirs that pass the
checks below are copied into the project; every other change is dropped.
"""
import fcntl
import filecmp
import json
import os
import re
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import sink  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TEXT_CAP, TOOL_CAP, RESULT_CAP = 3000, 400, 600


def log(msg):
    print(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {redact(str(msg))}", flush=True)


def redact(text):
    """Credential shapes replaced by their rule name. Applied to everything the plugin writes
    from the review's own words: log lines, summaries, commit messages, notices, events."""
    for rule, rx in SECRET_RULES:
        text = rx.sub(f"[withheld: {rule}]", text)
    return text


def clip(s, n):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n] + f" …[{len(s) - n} more chars]"


def render_blocks(role, content):
    if isinstance(content, str):
        return [f"{role.upper()}: {clip(content, TEXT_CAP)}"]
    out = []
    for b in content or []:
        t = b.get("type") if isinstance(b, dict) else None
        if t == "text":
            out.append(f"{role.upper()}: {clip(b.get('text', ''), TEXT_CAP)}")
        elif t == "tool_use":
            out.append(f"TOOL {b.get('name')}: {clip(json.dumps(b.get('input'), ensure_ascii=False), TOOL_CAP)}")
        elif t == "tool_result":
            c = b.get("content")
            if isinstance(c, list):
                c = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
            tag = "RESULT (error)" if b.get("is_error") else "RESULT"
            out.append(f"{tag}: {clip(c, RESULT_CAP)}")
    return out


def digest(transcript, offset, cap):
    """Renders the transcript from byte `offset` to its end. Returns (text, new_offset)."""
    lines = []
    with open(transcript, "rb") as fh:
        fh.seek(offset)
        data = fh.read()
    end = offset + data.rfind(b"\n") + 1  # only whole lines; a partial last line waits
    for raw in data[: end - offset].splitlines():
        try:
            e = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        if e.get("isSidechain") or e.get("type") not in ("user", "assistant"):
            continue
        msg = e.get("message") or {}
        lines.extend(render_blocks(msg.get("role", e["type"]), msg.get("content")))
    text = "\n".join(lines)
    if len(text) > cap:
        text = "[earlier turns cut]\n" + text[-cap:]
    return text, end


def snapshot(src, dst):
    if os.path.exists(dst):
        shutil.rmtree(dst)
    if src and os.path.isdir(src):
        shutil.copytree(src, dst, symlinks=True)
    else:
        os.makedirs(dst)


def changed_dirs(before, after):
    """Top-level entries of the skills dir that differ between two trees."""
    names = set(os.listdir(before)) | (set(os.listdir(after)) if os.path.isdir(after) else set())
    return [n for n in sorted(names) if changed_dirs_one(before, after, n)]


def same_tree(a, b):
    c = filecmp.dircmp(a, b)
    if c.left_only or c.right_only or c.funny_files:
        return False
    _, mismatch, errs = filecmp.cmpfiles(a, b, c.common_files, shallow=False)
    return not mismatch and not errs and all(same_tree(os.path.join(a, d), os.path.join(b, d))
                                             for d in c.common_dirs)


def changed_dirs_one(a, b, name):
    """[name] when entry `name` differs between trees a and b, else []."""
    pa, pb = os.path.join(a, name), os.path.join(b, name)
    if os.path.exists(pa) != os.path.exists(pb):
        return [name]
    if os.path.isdir(pa) and os.path.isdir(pb):
        return [] if same_tree(pa, pb) else [name]
    return [] if not os.path.exists(pa) or filecmp.cmp(pa, pb, shallow=False) else [name]


def restore(name, before, skills_dir):
    live, old = os.path.join(skills_dir, name), os.path.join(before, name)
    if os.path.isdir(live) and not os.path.islink(live):
        shutil.rmtree(live)
    elif os.path.lexists(live):
        os.remove(live)
    if os.path.isdir(old):
        shutil.copytree(old, live, symlinks=True)
    elif os.path.exists(old):
        shutil.copy2(old, live)


# Credential shapes refused in any learned file. Only the rule name is logged.
SECRET_RULES = [
    # The block through its END line, so redact() withholds the key body, not just the header:
    # PEM (LF or CRLF), encrypted PEM headers (Proc-Type, DEK-Info), PGP armor, and a body whose
    # newlines are JSON-escaped once (a pasted service-account file) or more (one in a tool input).
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY(?: BLOCK)?-----"
                               r"(?:[A-Za-z][A-Za-z-]{0,31}: [!-~]+|\\+[rn]|[A-Za-z0-9+/=\s])*"
                               r"(?:-----END [A-Z ]*PRIVATE KEY(?: BLOCK)?-----)?")),
    ("github-token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})")),
    ("anthropic/openai-key", re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}")),
    ("slack-token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    ("aws-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("discord-token", re.compile(r"\b[MNO][A-Za-z0-9_-]{23,27}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}\b")),
    ("discord-webhook", re.compile(r"(?:discord|discordapp)\.com/api/(?:v\d+/)?webhooks/\d+/[A-Za-z0-9_-]{20,}")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")),
    ("ssh-public-key-blob", re.compile(r"\bAAAA[BC][0-9A-Za-z+/]{60,}")),
    # Padded base64 only: an unpadded run can't be told from a path, an identifier or a SHA
    # The review reads only the digest, which is redacted with these same rules; this is the
    # second guard. An opaque password matches no rule: only the review's own refusal keeps it out.
    ("padded-base64", re.compile(r"(?<![A-Za-z0-9+/])(?=[A-Za-z0-9+/]*[0-9])(?=[A-Za-z0-9+/]*[A-Z])"
                                 r"[A-Za-z0-9+/]{38,}={1,2}(?![A-Za-z0-9+/=])")),
]
# A learned skill's frontmatter may hold these keys only: anything else (allowed-tools, hooks,
# model, ...) would let a steered review grant itself more than a procedure.
FRONTMATTER_KEYS = {"name", "description"}


def frontmatter_keys(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None
    try:
        import yaml
        fm = yaml.safe_load(m.group(1))
        return set(fm) if isinstance(fm, dict) else None
    except ImportError:
        return strict_keys(m.group(1))
    except Exception:
        return None


def strict_keys(block):
    """Without PyYAML, fail closed: every line must be a bare `key:` at column 0 or an indented
    continuation. Quoted keys, `? key`, flow mappings, anchors or tags make it unparseable."""
    keys = set()
    for line in block.split("\n"):
        if not line.strip():
            continue
        if line[0] in " \t":
            if not keys:
                return None
            continue
        k = re.fullmatch(r"([a-z][a-z0-9_-]*):(?:[ \t]+(.*))?", line)
        if not k or (k.group(2) or "").lstrip()[:1] in ("&", "*", "!", "{", "["):
            return None
        keys.add(k.group(1))
    return keys


def check_skill(skills_dir, name, max_bytes):
    """None when the learned skill is acceptable, else why not (never quoting file content)."""
    if not re.fullmatch(r"learned-[a-z0-9-]{1,56}", name):
        return "directory name is not learned- plus lowercase letters, digits and hyphens"
    d = os.path.join(skills_dir, name)
    if os.path.islink(d):
        return "is a symlink"
    if not os.path.exists(d):
        return None  # removed: allowed (the review may merge two skills into one)
    if not os.path.isdir(d):
        return "not a directory"
    sk = os.path.join(d, "SKILL.md")
    size = 0
    for r, dirs, fs in os.walk(d):
        for x in dirs + fs:
            p = os.path.join(r, x)
            if os.path.islink(p):
                return f"contains a symlink ({os.path.relpath(p, d)})"
            if x in fs and not os.path.isfile(p):
                return f"not a regular file ({os.path.relpath(p, d)})"
        for f in fs:
            p = os.path.join(r, f)
            size += os.path.getsize(p)
            with open(p, errors="replace") as fh:
                text = fh.read()
            for rule, rx in SECRET_RULES:
                if rx.search(text):
                    return f"credential shape {rule} in {os.path.relpath(p, d)}"
    if size > max_bytes:
        return f"{size} bytes > max_skill_bytes {max_bytes}"
    if not os.path.isfile(sk):
        return "no SKILL.md"
    with open(sk, errors="replace") as fh:
        keys = frontmatter_keys(fh.read())
    if keys is None:
        return "no parseable frontmatter"
    if keys - FRONTMATTER_KEYS:
        return f"frontmatter keys not allowed: {sorted(keys - FRONTMATTER_KEYS)}"
    fm_name, desc = common.frontmatter(sk)
    if fm_name != name:
        return f"frontmatter name {fm_name!r} != directory {name!r}"
    if not isinstance(desc, str) or not desc.strip() or len(desc) > 1024:
        return "description missing or over 1024 chars"
    return None


GIT_ENV = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_EDITOR="true", GIT_ASKPASS="true")


def git(top, *args, timeout=120):
    """Never waits on a prompt (terminal, editor, askpass) and never hangs: a hook or signer that
    doesn't return within the timeout is a failed call, not a stuck review holding review.lock."""
    try:
        return subprocess.run(["git", "-C", top, *args], capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, env=GIT_ENV, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(["git", *args], 124, "", f"git {args[0]} timed out after {timeout}s")


def git_busy(top):
    """Why committing now would land somewhere it shouldn't, or None."""
    if git(top, "symbolic-ref", "-q", "HEAD").returncode:
        return "detached HEAD"
    gitdir = git(top, "rev-parse", "--absolute-git-dir").stdout.strip()
    for marker in ("MERGE_HEAD", "REBASE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG",
                   "rebase-merge", "rebase-apply"):
        if os.path.exists(os.path.join(gitdir, marker)):
            return f"{marker} in progress"
    return None


def commit(skills_dir, name, verb, summary, branch=None):
    """Commits one learned skill dir on its own. Returns a short ref or why it was not committed;
    an uncommitted change stays in the working tree, never staged."""
    top = git(skills_dir, "rev-parse", "--show-toplevel")
    if top.returncode:
        return "not in a git repo; not committed"
    top = os.path.realpath(top.stdout.strip())
    busy = git_busy(top)
    if busy:
        return f"not committed ({busy}); change left in the working tree"
    if branch:
        cur = git(top, "symbolic-ref", "-q", "--short", "HEAD").stdout.strip()
        if cur != branch:
            return f"not committed (on {cur}, commit_branch is {branch}); change left in the working tree"
    path = os.path.relpath(os.path.join(os.path.realpath(skills_dir), name), top)
    msg = f"learned: {verb} {name}\n\n{summary}\n\nWritten by the learned-skills background review."
    for _ in range(5):  # the session may hold index.lock for a moment
        add = git(top, "add", "-A", "--", path)
        if add.returncode == 0:
            c = git(top, "commit", "-q", "-m", msg, "--", path)
            if c.returncode == 0:
                return git(top, "rev-parse", "--short", "HEAD").stdout.strip()
            if "nothing to commit" in c.stdout + c.stderr:
                return "nothing to commit"
        time.sleep(2)
    git(top, "reset", "-q", "--", path)
    return "commit failed (index busy?); change left in the working tree, unstaged"


def keep_undo(sdir, name, before, work, committed):
    """For a change left in the working tree, copies of the skill before and after it, so `undo`
    can put it back without git history. A committed change is undone from git: its copy goes."""
    d = os.path.join(sdir, "undo", name)
    if os.path.isdir(d):
        shutil.rmtree(d)
    if committed:
        return
    for side, tree in (("before", before), ("after", work)):
        os.makedirs(os.path.join(d, side))
        if os.path.isdir(os.path.join(tree, name)):
            shutil.copytree(os.path.join(tree, name), os.path.join(d, side, name), symlinks=True)


def parse_summaries(out):
    s = {}
    for line in out.splitlines():
        parts = line.strip().split(" ", 3)
        if len(parts) == 4 and parts[0] == "LEARNED" and parts[1] in ("created", "updated", "removed"):
            s[parts[2].rstrip(":")] = parts[3]
        rec = line.strip().split(" ", 2)
        if len(rec) == 3 and rec[0] == "RECORDED" and rec[1] != "nothing":
            s["record:" + rec[1].rstrip(":")] = rec[2]
    return s


def run_claude(cfg, sdir, prompt):
    """Hermetic: no MCP, no user/project settings or hooks, and tools scoped to the state dir."""
    mcp = os.path.join(sdir, "no-mcp.json")
    with open(mcp, "w") as fh:
        json.dump({"mcpServers": {}}, fh)
    here = "/" + sdir.rstrip("/")
    work, records = "/" + os.path.join(sdir, "work"), "/" + os.path.join(sdir, "work-records")
    cmd = ["claude", "-p", "--model", cfg["model"], "--strict-mcp-config", "--mcp-config", mcp,
           "--setting-sources", "", "--no-session-persistence", "--permission-mode", "default",
           # Only these five tools exist in the run (no Bash, web, agents, cron, messaging), and
           # each is scoped: Edit(...) rules also govern Write.
           "--tools", "Read,Glob,Grep,Edit,Write",
           "--allowedTools", f"Read({here}/**)", f"Glob({here}/**)", f"Grep({here}/**)",
           f"Edit({work}/**)", f"Edit({records}/**)"]
    env = dict(os.environ, **{common.GUARD_ENV: "1"})
    env.pop("CLAUDE_PROJECT_DIR", None)
    return subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=sdir, env=env,
                          timeout=cfg["timeout_seconds"])


def build_prompt(cfg, sdir, digest_path, work, records=None, source=None):
    parts = []
    if cfg["kind"] in ("skill", "both"):
        parts.append("review-prompt.md")
    if cfg["kind"] in ("record", "both"):
        parts.append("review-prompt-records.md")
    tmpl = ""
    for name in parts:
        with open(os.path.join(HERE, name)) as fh:
            tmpl += fh.read() + "\n\n"
    if cfg["kind"] == "record":
        tmpl = ("You review a finished stretch of an agent's work session and write learning "
                "records about it.\n\n" + tmpl + "End your reply with the RECORDED lines, or the "
                "single line `RECORDED nothing` when you wrote none.\n")
    source = source or cfg["skills_dir"]
    existing = common.learned_skills(source)
    listing = "\n".join(f"- {d}: {desc}" for d, _, desc in existing) or "(none yet)"
    others = sorted(d for d in os.listdir(source) if not d.startswith(common.PREFIX)) \
        if os.path.isdir(source) else []
    ctx_dir = os.path.join(sdir, "context")
    shutil.rmtree(ctx_dir, ignore_errors=True)
    os.makedirs(ctx_dir)
    ctx = []
    for i, p in enumerate(cfg["context_files"]):
        if os.path.isfile(p):
            dst = os.path.join(ctx_dir, f"{i}-{os.path.basename(p)}")
            shutil.copy2(p, dst)
            ctx.append(f"- {dst} (copy of {p})")
    return (tmpl.replace("{{SKILLS_DIR}}", work)
            .replace("{{RECORDS_DIR}}", records or os.path.join(sdir, "work-records"))
            .replace("{{DIGEST}}", digest_path)
            .replace("{{LEARNED}}", listing)
            .replace("{{OTHER_SKILLS}}", ", ".join(others) or "(none)")
            .replace("{{CONTEXT_FILES}}", "\n".join(ctx) or "- (none)")
            .replace("{{MAX_BYTES}}", str(cfg["max_skill_bytes"])))


def label(transcript):
    return os.path.splitext(os.path.basename(transcript))[0]


def gather(state, cap):
    """Digest of every known transcript past its offset, oldest first. Returns (text, offsets)."""
    parts, offsets = [], {}
    known = [t for t in state["transcripts"] if os.path.isfile(t)]
    for t in sorted(known, key=os.path.getmtime):
        off = state["offsets"].get(t, 0)
        if off > os.path.getsize(t):
            off = 0  # the transcript was replaced
        text, end = digest(t, off, cap)
        offsets[t] = end
        if text:
            parts.append(f"## session {label(t)}\n{text}")
    text = "\n\n".join(parts)
    if len(text) > cap:
        text = "[earlier turns cut]\n" + text[-cap:]
    return text, offsets


def main():
    proj = os.path.realpath(sys.argv[1])
    now = "--now" in sys.argv[2:]
    cfg = common.load_config(proj)
    if cfg is None:
        return
    sdir = common.state_dir(proj)
    lock = open(os.path.join(sdir, "review.lock"), "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("another review is running; skipped")
        return
    if not now:
        time.sleep(cfg["idle_seconds"])  # let the session settle before reading its turns
    if cfg["engine"] != "claude":
        log(f"review refused: engine must be claude, not {cfg['engine']!r}; nothing applied")
        return
    state = common.load_state(sdir)
    text, new_offsets = gather(state, cfg["max_digest_bytes"])
    # Credentials pasted into the session never reach the reviewer or digest.md.
    text = redact(text)
    if len(text) < 2000:
        log(f"only {len(text)} chars since the last review; nothing to learn from yet")
        return
    with common.locked_state(sdir) as state:  # a real review: the count starts again
        state["turns"] = 0
        state["last_review"] = time.time()
    digest_path = os.path.join(sdir, "digest.md")
    # 0600 itself, not by umask: the transcripts it digests are 0600 too.
    with os.fdopen(os.open(digest_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as fh:
        fh.write(text)
    os.chmod(digest_path, 0o600)  # O_CREAT's mode applies only to a new file
    # Claude edits staged skills inside its cwd, not a project's sensitive .claude/ tree.
    before, work = os.path.join(sdir, "before"), os.path.join(sdir, "work")
    records = os.path.join(sdir, "work-records")
    # The skills the review starts from: the project's, or with live: false the sink's own
    # PATH/skills, so skills build up there (and "updated" means updated) across reviews.
    source = cfg["skills_dir"]
    if not cfg["live"] and cfg["kind"] in ("skill", "both"):
        try:
            source = sink.sink_skills(cfg, sdir, log)
        except Exception as e:
            source = None
            log(f"sink: could not read its skills ({type(e).__name__})")
        if source is None:
            log("live: false and the sink's skills are unreadable; review skipped; the same turns are read next time")
            return
    snapshot(source if cfg["kind"] in ("skill", "both") else None, before)
    snapshot(source if cfg["kind"] in ("skill", "both") else None, work)
    snapshot(None, records)  # empty: each review writes only its own new records
    log(f"review start: {len(text)} chars from {len(new_offsets)} transcript(s)")
    try:
        res = run_claude(cfg, sdir, build_prompt(cfg, sdir, digest_path, work, records, source))
    except OSError as e:
        log(f"review refused: {e}; nothing applied; the same turns are read next time")
        return
    except subprocess.TimeoutExpired:
        log(f"{cfg['engine']} timed out; nothing applied")
        return
    out = res.stdout
    log(f"{cfg['engine']} exit {res.returncode}; stderr: {clip(res.stderr, 400)}")
    log(f"{cfg['engine']} said: {clip(out[-1500:], 1500)}")
    if res.returncode != 0:  # auth, quota, crash: a half-finished run applies nothing
        log(f"nothing applied ({cfg['engine']} exit not 0); the same turns are read again next time")
        return
    summaries = parse_summaries(out)
    notices, sink_items = [], []
    meta = {"ts": sink.utc_now(), "plugin": sink.plugin_version(),
            "sessions": sorted(label(t) for t in new_offsets),
            "model": cfg["model"]}
    st = sink.stamp()
    for n in (changed_dirs(before, work) if cfg["kind"] in ("skill", "both") else []):
        if not n.startswith(common.PREFIX):
            log(f"ignored {n}: outside {common.PREFIX}*")
            continue
        why = check_skill(work, n, cfg["max_skill_bytes"])
        if why:
            log(f"not applied {n}: {why}")
            continue
        if cfg["live"] and changed_dirs_one(before, cfg["skills_dir"], n):
            log(f"not applied {n}: it changed in the project while the review ran")
            continue
        verb = ("removed" if not os.path.exists(os.path.join(work, n))
                else "updated" if os.path.exists(os.path.join(before, n)) else "created")
        summary = redact(clip(summaries.get(n, ""), 200))
        event = dict(sink.plugin_fields(cfg, meta), kind="skill", skill=n, verb=verb, summary=summary)
        skill_write = ({"rel": f"skills/{n}", "delete": True} if verb == "removed"
                       else {"rel": f"skills/{n}", "tree": os.path.join(work, n)})
        item = {"kind": "skill", "name": n, "verb": verb, "writes": [
            skill_write,
            {"rel": f"events/{st}-{n}.json", "text": json.dumps(event, indent=2, ensure_ascii=False) + "\n"}]}
        why, ctx = sink.run_filter(cfg, sdir, item)
        if why:
            log(f"not applied {n}: {why}")
            continue
        item = sink.with_context(item, ctx)
        if cfg["live"]:
            os.makedirs(cfg["skills_dir"], exist_ok=True)
            restore(n, work, cfg["skills_dir"])  # live := work copy (or removed)
            ref = (commit(cfg["skills_dir"], n, verb, summary, cfg["commit_branch"]) if cfg["commit"]
                   else "not committed (commit: false)")
            keep_undo(sdir, n, before, work, committed=bool(re.fullmatch(r"[0-9a-f]{4,40}", ref)))
        else:
            ref = "sink only (live: false)"
        log(f"{verb} {n} ({ref}) {summary}")
        notices.append({"ts": time.time(), "verb": verb, "skill": n, "summary": summary, "ref": ref})
        sink_items.append(item)
    if cfg["kind"] in ("record", "both"):
        for f in sorted(os.listdir(records)):
            p = os.path.join(records, f)
            name = sink.record_name(f) if f.endswith(".md") else None
            if not name or os.path.islink(p) or not os.path.isfile(p):
                log(f"record not kept {f}: name or type")
                continue
            fields, body = sink.parse_record(p)
            if fields is None:
                log(f"record not kept {name}: {body}")
                continue
            text, fp = sink.render_record(fields, body, cfg, meta)
            hit = next((rule for rule, rx in SECRET_RULES if rx.search(text)), None)
            if hit:
                log(f"record not kept {name}: credential shape {hit}")
                continue
            item = {"kind": "record", "name": name, "verb": "recorded",
                    "writes": [{"rel": f"{st}-{name}.md", "text": text}]}
            why, ctx = sink.run_filter(cfg, sdir, item)
            if why:
                log(f"record not kept {name}: {why}")
                continue
            summary = redact(clip(summaries.get("record:" + name, fields["symptom"]), 200))
            log(f"recorded {name} ({fp}) {summary}")
            notices.append({"ts": time.time(), "verb": "recorded", "skill": name, "summary": summary,
                            "ref": fp})
            sink_items.append(sink.with_context(item, ctx))
    if sink_items or os.path.isdir(os.path.join(sdir, "sink-pending")):
        if not sink.sink_config(cfg) and sink_items:
            log("no sink is set (or it is unsafe); items kept in sink-pending/ only")
        try:
            sref = sink.write_sink(cfg, sdir, sink_items, log)
        except Exception as e:  # never lose the review's own state over the sink
            log(f"sink failed ({type(e).__name__}); items kept for the next review")
            sref = None
        if sref:
            log(f"sink: {sref}")
            for x in notices:
                x["ref"] = f"{x['ref']}; sink {sref}"
    if notices:
        with open(os.path.join(sdir, "notices.jsonl"), "a") as fh:
            for x in notices:
                fh.write(json.dumps(x) + "\n")
    else:
        log("review end: nothing learned")
    with common.locked_state(sdir) as state:
        state["offsets"].update(new_offsets)


if __name__ == "__main__":
    main()
