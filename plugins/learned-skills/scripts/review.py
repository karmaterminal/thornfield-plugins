#!/usr/bin/env python3
"""Background experience review: read the turns since the last review and let a headless
reviewer create or patch learned-* skills. Runs detached from the Stop hook; also `learned-skills
review-now`. Usage: review.py PROJECT_DIR [--now]. Reads every known transcript of the project
(state.json `transcripts`) past its saved offset, so turns from an ended or replaced session are
not lost.

Fail-closed: the reviewer gets no MCP servers, no shell, no web. Claude runs in STATE/reviewer/,
which holds the redacted digest, context copies and plain copies of the learned-* skills only,
and edits the staged skills there. After it exits, only learned-* skill dirs that pass the checks
below are copied into the project; every other change is dropped.
"""
import fcntl
import filecmp
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402
import sink  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
TEXT_CAP, TOOL_CAP, RESULT_CAP = 3000, 400, 600


def log(msg):
    print(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')} {redact(str(msg))}", flush=True)


def json_text(text):
    """The string values of a JSON document, decoded by the JSON parser and joined by line
    breaks; a value that is itself a JSON document (JSON inside JSON) is decoded the same way.
    So an escaped line break is one only when JSON says so, escaped backslashes included."""
    out = []

    def walk(v):
        if isinstance(v, str):
            inner = v.strip()
            if inner[:1] in ("{", "[") and is_json(inner):
                walk(json.loads(inner))
            else:
                out.append(v)
        elif isinstance(v, dict):
            for k, x in v.items():
                out.append(str(k))
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(json.loads(text))
    return "\n".join(out)


def decode_json(text):
    """`text` with each JSON document in it (the whole text, or an object or array inside prose,
    as a pasted service-account file) replaced by json_text(): line breaks are then what JSON
    says they are, and nothing else in the text is unescaped."""
    if is_json(text):
        return json_text(text)
    out, pos, dec = [], 0, json.JSONDecoder()
    for m in re.finditer(r"[{\[]", text):
        if m.start() < pos:
            continue
        try:
            value, end = dec.raw_decode(text, m.start())
        except ValueError:
            continue
        if isinstance(value, (dict, list)):
            out.append(text[pos:m.start()])
            out.append(json_text(json.dumps(value)))
            pos = end
    out.append(text[pos:])
    return "".join(out)


def is_json(text):
    """True for text that is one JSON document (where \\n is an escaped line break)."""
    try:
        json.loads(text)
        return True
    except ValueError:
        return False


def redact(text):
    """Credential shapes replaced by their rule name. Applied to everything the plugin writes
    from the review's own words: log lines, summaries, commit messages, notices, events."""
    if KEY_BEGIN.search(text):  # a JSON-escaped key's END as its own line, by the JSON parser
        text = decode_json(text)
    for rule, rx in SECRET_RULES:
        text = rx.sub(f"[withheld: {rule}]", text)
    return text


def clip(s, n):
    s = " ".join(str(s).split())
    return s if len(s) <= n else s[:n] + f" …[{len(s) - n} more chars]"


# The label is everything between BEGIN and the dashes ("RSA PRIVATE KEY", "PGP PRIVATE KEY
# BLOCK"). A key closes only at the END line with the same label: any other END is body.
KEY_LABEL = r"[A-Z ]*PRIVATE KEY(?: BLOCK)?"
KEY_BEGIN = re.compile(rf"-----BEGIN ({KEY_LABEL})-----")
# A BEGIN opens a key wherever it appears (fail closed). An END closes one only as a whole line:
# after JSON-escaped newlines are turned into real ones, a line that is exactly the END marker
# with the opener's label, give or take spaces, quotes, commas and closing brackets around it.
# No lookaround edges: "x-----END ...", "-----END ...-----x" and "a -----END ... b" are body.
END_EDGE = r"[ \t\r\"',}\]]*"


def key_end(label):
    return re.compile(rf"^{END_EDGE}-----END {re.escape(label)}-----{END_EDGE}$", re.M)


# Where a key was opened: the user's or the assistant's text, or one tool call's input or result,
# by its id. A tool block without an id gets a random one of its own (?UUID), so no other block,
# in this review or a later one, can close it (a per-process counter repeated across runs).
SOURCE_RE = re.compile(r"(?:user|assistant|(?:tool_use|tool_result):[A-Za-z0-9._?-]{1,128})")


def tool_source(kind, call_id):
    if isinstance(call_id, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,120}", call_id):
        return f"{kind}:{call_id}"
    return f"{kind}:?{uuid.uuid4().hex}"
WITHHELD_RUN = re.compile(r"\[withheld: private-key\](?:\s*\[withheld: private-key\])+")


class KeyGuard:
    """Across the blocks of a transcript: open, with the opening BEGIN's label, until the END
    line with that same label, so a key split over two messages never leaves its body visible
    and a mismatched END closes nothing. Saved with the transcript's offset (state.json
    `key_guard`), so a body read by the next review is withheld too. No size bound, and nothing
    but the matching whole END line, from the same kind of block, closes it: it fails closed.
    While open it withholds everything. A stray BEGIN in prose therefore hides the rest of that
    transcript from reviews until `cli.py reset-guard` (logged) clears it."""

    def __init__(self, saved=None):
        saved = saved if isinstance(saved, dict) else {}
        label, source = saved.get("label"), saved.get("source")
        self.open = saved.get("open") is True
        self.label = label if isinstance(label, str) and re.fullmatch(KEY_LABEL, label) else None
        # Where the key was opened (SOURCE_RE). Only an END from that same place closes it: the
        # user's text, the assistant's, or the very tool call, so one tool result (a fetched
        # page) cannot end a key that another result, or a user turn, opened. Unknown
        # (a 0.3.2 state, or unreadable): nothing closes it but reset-guard.
        self.source = source if isinstance(source, str) and SOURCE_RE.fullmatch(source) else None

    def saved(self):
        return {"open": True, "label": self.label, "source": self.source} if self.open else None

    @staticmethod
    def inside(text):
        """Everything inside an open key is withheld, whatever it looks like: any rule
        for "safe" text inside a key has a valid wrapping that defeats it."""
        return "[withheld: private-key]"


def shown(s, n, guard=None, source=None):
    """One rendered block for the digest: redacted whole, then clipped. A rule such as
    private-key needs its header, which a clip, or a later cut to the digest's tail, can drop.
    With a guard, the block is walked in order: text outside a key is redacted, and everything
    from a BEGIN to the whole END line with its label (in this block or a later one) is
    inside the key and withheld whole, nested or mismatched BEGIN and END markers included."""
    s = str(s)
    if guard is None:
        return clip(redact(s), n)
    # JSON in the block (the whole block, or a JSON document inside prose) is decoded by the
    # JSON parser, so a JSON-pasted key's END is a line of its own exactly when JSON says so.
    # Nothing outside JSON is unescaped: a literal \n in plain text cannot fake an END line.
    if guard.open or KEY_BEGIN.search(s):
        s = decode_json(s)  # the serialization layer, decoded once by the JSON parser
    out, pos = [], 0
    while pos <= len(s):
        if guard.open:
            m = (key_end(guard.label).search(s, pos)
                 if guard.label and guard.source is not None and guard.source == source else None)
            out.append(guard.inside(s[pos:m.start() if m else len(s)]))
            if not m:
                break
            guard.open, guard.label, guard.source, pos = False, None, None, m.end()
            continue
        m = KEY_BEGIN.search(s, pos)
        out.append(redact(s[pos:m.start() if m else len(s)]))
        if not m:
            break
        guard.open, guard.label, guard.source, pos = True, m.group(1), source, m.end()
    return clip(WITHHELD_RUN.sub("[withheld: private-key]", " ".join(out)), n)


def render_blocks(role, content, guard=None):
    if isinstance(content, str):
        return [f"{role.upper()}: {shown(content, TEXT_CAP, guard, role)}"]
    out = []
    for b in content or []:
        t = b.get("type") if isinstance(b, dict) else None
        if t == "text":
            out.append(f"{role.upper()}: {shown(b.get('text', ''), TEXT_CAP, guard, role)}")
        elif t == "tool_use":
            out.append(f"TOOL {b.get('name')}: {shown(json.dumps(b.get('input'), ensure_ascii=False), TOOL_CAP, guard, tool_source('tool_use', b.get('id')))}")
        elif t == "tool_result":
            c = b.get("content")
            if isinstance(c, list):
                c = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
            tag = "RESULT (error)" if b.get("is_error") else "RESULT"
            out.append(f"{tag}: {shown(c, RESULT_CAP, guard, tool_source('tool_result', b.get('tool_use_id')))}")
    return out


def digest(transcript, offset, cap, guard=None):
    """Renders the transcript from byte `offset` to its end. Returns (text, new_offset)."""
    lines, guard = [], guard if guard is not None else KeyGuard()
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
        lines.extend(render_blocks(msg.get("role", e["type"]), msg.get("content"), guard))
    text = "\n".join(lines)
    if len(text) > cap:
        text = "[earlier turns cut]\n" + text[-cap:]
    return text, end


def snapshot(src, dst):
    """Copies only the learned-* skills of src to dst, the trees the review may change. Other
    skills are never copied (the review sees their names and descriptions, nothing more). A
    learned skill that is a symlink, or holds a symlink or special file at any depth, is left out
    whole, so nothing from outside the skills dir is staged. Returns [(name, why)] left out."""
    if os.path.lexists(dst):
        shutil.rmtree(dst)
    os.makedirs(dst)
    skipped = []
    for name in sorted(os.listdir(src)) if src and os.path.isdir(src) else []:
        if not name.startswith(common.PREFIX):
            continue
        why = copy_plain(os.path.join(src, name), os.path.join(dst, name), name)
        if why:
            shutil.rmtree(os.path.join(dst, name), ignore_errors=True)
            skipped.append((name, why))
    return skipped


def copy_plain(src, dst, rel):
    """Copies regular files and directories only, never following a link. None, or why not."""
    st = os.lstat(src)
    if stat.S_ISLNK(st.st_mode):
        return f"{rel} is a symlink"
    if stat.S_ISDIR(st.st_mode):
        os.makedirs(dst)
        for name in sorted(os.listdir(src)):
            why = copy_plain(os.path.join(src, name), os.path.join(dst, name), f"{rel}/{name}")
            if why:
                return why
        return None
    if not stat.S_ISREG(st.st_mode):
        return f"{rel} is not a regular file"
    fd = os.open(src, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as a, open(dst, "wb") as b:
        shutil.copyfileobj(a, b)
    return None


def links_in(top):
    """Paths under top that are symlinks or special files: none may reach the reviewer."""
    bad = []
    for r, dirs, fs in os.walk(top):
        for x in dirs + fs:
            m = os.lstat(os.path.join(r, x)).st_mode
            if stat.S_ISLNK(m) or not (stat.S_ISDIR(m) or stat.S_ISREG(m)):
                bad.append(os.path.relpath(os.path.join(r, x), top))
    return bad


def other_skills(source):
    """`- name: description` for each skill in source that is not learned-*: what the review may
    know about skills it doesn't own, so it doesn't duplicate them. No body is read, and a
    symlinked skill or SKILL.md gives its name only."""
    out = []
    for d in sorted(os.listdir(source)) if source and os.path.isdir(source) else []:
        if d.startswith(common.PREFIX):
            continue
        p = os.path.join(source, d)
        sk = os.path.join(p, "SKILL.md")
        desc = None
        if not os.path.islink(p) and os.path.isdir(p) and not os.path.islink(sk) and os.path.isfile(sk):
            desc = common.frontmatter(sk)[1]
        out.append(f"- {d}: {clip(redact(desc), 300)}" if isinstance(desc, str) and desc.strip() else f"- {d}")
    return out


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
    if os.path.lexists(pa) != os.path.lexists(pb):  # a link, even a broken one, is not "absent"
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
    # BEGIN X through the complete END X line (a backreference; a whole END line, see key_end), or to the end
    # of the text: everything between, nested, mismatched or decoy END lines included, is
    # withheld, so PEM, encrypted PEM, PGP armor and JSON-escaped bodies need no shape of
    # their own. In the digest a block's BEGIN is already withheld by shown() first.
    ("private-key", re.compile(rf"-----BEGIN (?P<label>{KEY_LABEL})-----[\s\S]*?"
                               rf"(?:^{END_EDGE}-----END (?P=label)-----{END_EDGE}$|\Z)", re.M)),
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
    """Hermetic: no MCP, no user/project settings or hooks, and tools scoped to `sdir`, the
    reviewer dir (digest, context copies, staged learned skills, record staging) and no more."""
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


def build_prompt(cfg, sdir, digest_path, work, records=None, source=None, staged=None):
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
    existing = common.learned_skills(staged or work)  # the staged copies, never the project's
    listing = "\n".join(f"- {d}: {desc}" for d, _, desc in existing) or "(none yet)"
    others = other_skills(source)
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
            .replace("{{OTHER_SKILLS}}", "\n".join(others) or "- (none)")
            .replace("{{CONTEXT_FILES}}", "\n".join(ctx) or "- (none)")
            .replace("{{MAX_BYTES}}", str(cfg["max_skill_bytes"])))


def label(transcript):
    return os.path.splitext(os.path.basename(transcript))[0]


IDENT_PREFIX = 4096


def identity(path, offset):
    """What a saved offset belongs to: the file (dev, ino) and a hash of its first
    min(offset, 4096) bytes, which an append never changes."""
    n = min(offset, IDENT_PREFIX)
    with open(path, "rb") as fh:
        st = os.fstat(fh.fileno())
        head = fh.read(n)
    return {"dev": st.st_dev, "ino": st.st_ino, "n": n, "sha": hashlib.sha256(head).hexdigest()}


def replaced(path, offset, saved):
    """True when the transcript at `path` is not the one `offset` was read from: it shrank
    below the offset, or it is another file, or its start was rewritten. A saved state without
    an identity (from an earlier version) is adopted: only the size check applies to it."""
    if offset > os.path.getsize(path):
        return True
    if not (isinstance(saved, dict) and type(saved.get("n")) is int and saved["n"] == min(offset, IDENT_PREFIX)):
        return False
    return identity(path, offset) != {k: saved.get(k) for k in ("dev", "ino", "n", "sha")}


def gather(state, cap, guards=None, idents=None):
    """Digest of every known transcript past its offset, oldest first. Returns (text, offsets);
    fills `guards` with each transcript's KeyGuard state and `idents` with its identity, to
    save with its offset."""
    parts, offsets = [], {}
    saved = state.get("key_guard") if isinstance(state.get("key_guard"), dict) else {}
    known_ids = state.get("ident") if isinstance(state.get("ident"), dict) else {}
    known = [t for t in state["transcripts"] if os.path.isfile(t)]
    for t in sorted(known, key=os.path.getmtime):
        off, guard = state["offsets"].get(t, 0), KeyGuard(saved.get(t))
        if replaced(t, off, known_ids.get(t)):
            off, guard = 0, KeyGuard()  # the transcript was replaced: its guard goes with it
        text, end = digest(t, off, cap, guard)
        offsets[t] = end
        if guards is not None:
            guards[t] = guard.saved()
        if idents is not None:
            idents[t] = identity(t, end)
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
    new_guards, new_idents = {}, {}
    text, new_offsets = gather(state, cfg["max_digest_bytes"], new_guards, new_idents)
    # Each block was redacted before any clip or cut (shown); this pass catches a shape that
    # only the joined text forms.
    text = redact(text)
    if len(text) < 2000:
        log(f"only {len(text)} chars since the last review; nothing to learn from yet")
        return
    with common.locked_state(sdir) as state:  # a real review: the count starts again
        state["turns"] = 0
        state["last_review"] = time.time()
    # The reviewer reads only this dir: the digest, context copies, the staged learned skills
    # and its record staging. Never the log, undo copies, before/ or a sink clone beside it.
    rdir = os.path.join(sdir, "reviewer")
    os.makedirs(rdir, mode=0o700, exist_ok=True)
    digest_path = os.path.join(rdir, "digest.md")
    # 0600 itself, not by umask: the transcripts it digests are 0600 too.
    with os.fdopen(os.open(digest_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as fh:
        fh.write(text)
    os.chmod(digest_path, 0o600)  # O_CREAT's mode applies only to a new file
    # Claude edits staged skills inside its cwd, not a project's sensitive .claude/ tree.
    before, work = os.path.join(sdir, "before"), os.path.join(rdir, "work")
    records = os.path.join(rdir, "work-records")
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
    # Names left out of staging (a link or special file inside): apply skips them below, so a
    # review can't replace a skill it was never shown, in the project or (live: false) the sink.
    left_out = dict(snapshot(source if cfg["kind"] in ("skill", "both") else None, before))
    for name, why in left_out.items():
        log(f"not staged {name}: {why}; the review neither sees nor changes it")
    snapshot(before, work)  # before/ holds only plain learned-* trees by now
    snapshot(None, records)  # empty: each review writes only its own new records
    log(f"review start: {len(text)} chars from {len(new_offsets)} transcript(s)")
    try:
        prompt = build_prompt(cfg, rdir, digest_path, work, records, source, before)
        bad = links_in(rdir)
        if bad:  # never expected: the staging above copies plain files only
            log(f"review refused: {len(bad)} symlink(s) or special file(s) in the reviewer dir; nothing applied")
            return
        res = run_claude(cfg, rdir, prompt)
    except OSError as e:
        log(f"review refused: {e}; nothing applied; the same turns are read next time")
        return
    except subprocess.TimeoutExpired:
        log(f"{cfg['engine']} timed out; nothing applied")
        return
    out = res.stdout
    log(f"{cfg['engine']} exit {res.returncode}; stderr: {clip(redact(res.stderr), 400)}")
    log(f"{cfg['engine']} said: {clip(redact(out)[-1500:], 1500)}")
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
        if n in left_out:
            log(f"not applied {n}: left out of staging ({left_out[n]})")
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
        summary = clip(redact(summaries.get(n, "")), 200)
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
            summary = clip(redact(summaries.get("record:" + name, fields["symptom"])), 200)
            log(f"recorded {name} ({fp}) {summary}")
            notices.append({"ts": time.time(), "verb": "recorded", "skill": name, "summary": summary,
                            "ref": fp})
            sink_items.append(sink.with_context(item, ctx))
    # No sink configured: nothing is staged for one. A configured sink that is incomplete,
    # unsafe or unreachable keeps its items in sink-pending/ until it can take them.
    if sink.sink_set(cfg) and (sink_items or os.path.isdir(os.path.join(sdir, "sink-pending"))):
        if not sink.sink_config(cfg) and sink_items:
            log("the sink is incomplete or unsafe (it needs url or repo, a branch, and a path "
                "inside the repo); items kept in sink-pending/")
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
        if not isinstance(state.get("ident"), dict):
            state["ident"] = {}
        state["ident"].update(new_idents)  # the identity each new offset was read from
        if not isinstance(state.get("key_guard"), dict):
            state["key_guard"] = {}
        for t, g in new_guards.items():  # with the offset it belongs to, in the same update
            if g:
                state["key_guard"][t] = g
            else:
                state["key_guard"].pop(t, None)
        for t in state["key_guard"]:
            log(f"key guard open in {label(t)} ({state['key_guard'][t].get('label')}): its text is "
                "withheld from reviews until the matching END line, or cli.py reset-guard")


def reset_guards(state, session):
    """Clears one transcript's open key guard, logged: the recovery for a BEGIN that never gets
    its END, a format note in prose for example. `session` is the transcript's label as status
    shows it; no other transcript's guard is touched (a reset must not release an unrelated real
    key). Text after the guard is reviewed from the saved offset on, so nothing withheld is
    replayed. Returns the transcripts cleared (none for an unknown label)."""
    guards = state.get("key_guard") if isinstance(state.get("key_guard"), dict) else {}
    cleared = [t for t in list(guards) if label(t) == session]
    for t in cleared:
        del guards[t]
        log(f"key guard reset for {label(t)} by cli.py reset-guard")
    return cleared


if __name__ == "__main__":
    main()
