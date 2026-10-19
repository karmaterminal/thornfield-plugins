"""Learning records, the disclosure filter, and the configurable sink.

A record is one learning event (symptom, stage, cause, resolution), written by the review in
`kind: record` mode; records never become live skills. A sink is a git remote, path and branch.
All sink git work happens in a **private clone** in the state dir: the owner's checkout of that
repo is only read (`git remote get-url`), never written, and gets no worktree, ref or prune.
Every candidate passes the owner's `filter_command` first, seeing every file that would be
written; anything but exit 0 withholds it.
"""
import datetime
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import time

import common

RECORD_KEYS = {"symptom", "stage", "plane", "cause", "resolution", "recurs"}
RECORD_REQUIRED = {"symptom", "stage", "cause", "resolution", "recurs"}
RECORD_CAUSES = {"method", "harness", "host"}
RECORD_RECURS = {"yes", "no", "unknown"}
RECORD_MAX_BYTES = 8_000
PLUGIN_KEYS = {"engine", "model", "host", "recorded", "sessions", "plugin", "fingerprint", "context"}
NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")


def git(top, *args, timeout=120):
    import review  # one git wrapper: no prompts, a timeout instead of a hang
    return review.git(top, *args, timeout=timeout)


# ---- filter ---------------------------------------------------------------------------------

def materialize(item, root):
    """Writes an item's files under root, laid out as they would land under the sink PATH."""
    if os.path.exists(root):
        shutil.rmtree(root)
    os.makedirs(root)
    for w in item["writes"]:
        dst = os.path.join(root, w["rel"])
        if w.get("tree"):
            shutil.copytree(w["tree"], dst, symlinks=False)
        elif "text" in w:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, "w") as fh:
                fh.write(w["text"])
    return root


def run_filter(cfg, sdir, item, root=None):
    """(why, context). why is None when the owner's filter admits the item (or none is set).

    The filter gets every file that would be written, as path arguments, with LEARNED_KIND,
    LEARNED_NAME and LEARNED_PATH (the candidate root) in its env. Fail closed: a missing
    command, a timeout, any exit but 0, or stdout that isn't empty or one JSON object withholds.
    On admit, that object is the item's `context`. Nothing the filter prints is logged."""
    cmd = cfg.get("filter_command")
    if not cmd:
        return None, None
    if isinstance(cmd, str):
        cmd = [cmd]
    cmd = [os.path.expanduser(c) for c in cmd]
    own = root is None
    if own:
        root = materialize(item, os.path.join(sdir, "candidates", f"{item['kind']}-{item['name']}"))
    files = sorted(os.path.join(r, f) for r, _, fs in os.walk(root) for f in fs)
    env = dict(os.environ, LEARNED_KIND=item["kind"], LEARNED_NAME=item["name"], LEARNED_PATH=root)
    try:
        r = subprocess.run([*cmd, *files], cwd=sdir, env=env, stdin=subprocess.DEVNULL,
                           capture_output=True, timeout=cfg.get("filter_timeout_seconds", 60))
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"withheld by filter ({type(e).__name__})", None
    finally:
        if own:
            shutil.rmtree(root, ignore_errors=True)
    if r.returncode != 0:
        return f"withheld by filter (exit {r.returncode})", None
    raw = r.stdout.strip()
    if not raw:
        return None, None
    if len(raw) > 16_000:
        return "withheld by filter (context over 16000 bytes)", None
    try:
        ctx = json.loads(raw)
    except ValueError:
        return "withheld by filter (stdout is not one JSON object)", None
    if not isinstance(ctx, dict):
        return "withheld by filter (stdout is not one JSON object)", None
    return None, ctx


def with_context(item, ctx):
    """The item with the filter's context merged: under "context" in an event JSON, and as a
    `context:` line (JSON) in a record's frontmatter."""
    if not ctx:
        return item
    writes = []
    for w in item["writes"]:
        w = dict(w)
        if "text" in w and w["rel"].endswith(".json"):
            ev = json.loads(w["text"])
            ev["context"] = ctx
            w["text"] = json.dumps(ev, indent=2, ensure_ascii=False) + "\n"
        elif "text" in w and w["rel"].endswith(".md"):
            head, sep, rest = w["text"][4:].partition("\n---\n")
            ctx_line = "context: " + json.dumps(ctx, ensure_ascii=False)
            w["text"] = "---\n" + head + "\n" + ctx_line + sep + rest
        writes.append(w)
    return dict(item, writes=writes)


# ---- records --------------------------------------------------------------------------------

def normalize_symptom(s):
    """The symptom with run-specific parts blanked, so the same failure fingerprints the same."""
    s = s.strip().lower()
    s = re.sub(r"https?://\S+", "<url>", s)
    s = re.sub(r"(?:~|\.{0,2})?/[\w.@%+-]+(?:/[\w.@%+-]+)+", "<path>", s)
    s = re.sub(r"\b[0-9a-f]{7,64}\b", "<hex>", s)
    s = re.sub(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", "<uuid>", s)
    s = re.sub(r"\d+", "<n>", s)
    return re.sub(r"\s+", " ", s)


def fingerprint(symptom, stage):
    key = f"{normalize_symptom(symptom)}\x00{stage.strip().lower()}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def parse_record(path):
    """(fields, body) of a record file, or (None, why)."""
    try:
        with open(path, errors="replace") as fh:
            text = fh.read()
    except OSError as e:
        return None, f"unreadable ({type(e).__name__})"
    if len(text.encode()) > RECORD_MAX_BYTES:
        return None, f"over {RECORD_MAX_BYTES} bytes"
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        return None, "no frontmatter"
    # Always the strict line parser, never YAML: `recurs: yes` must stay text, `symptom:` lines
    # often hold `: `, and one parser everywhere means no install-dependent behavior.
    fm = plain_fields(m.group(1))
    if not isinstance(fm, dict):
        return None, "unparseable frontmatter"
    extra = set(fm) - RECORD_KEYS
    if extra:
        return None, f"keys not allowed: {sorted(map(str, extra))}"
    missing = RECORD_REQUIRED - {k for k, v in fm.items() if isinstance(v, str) and v.strip()}
    if missing:
        return None, f"missing or not text: {sorted(missing)}"
    if fm["cause"] not in RECORD_CAUSES:
        return None, f"cause must be one of {sorted(RECORD_CAUSES)}"
    if fm["recurs"] not in RECORD_RECURS:
        return None, f"recurs must be one of {sorted(RECORD_RECURS)}"
    if len(fm["symptom"]) > 500:
        return None, "symptom over 500 chars"
    return {k: str(v).strip() for k, v in fm.items()}, m.group(2).strip()


def plain_fields(block):
    """Bare `key: value` lines only; anything else (quoted keys, `?`, flow, block scalars,
    anchors, tags, continuation lines) makes the record unparseable."""
    out = {}
    for line in block.split("\n"):
        if not line.strip():
            continue
        m = re.fullmatch(r"([a-z][a-z_]*):[ \t]+(.*)", line)
        if not m:
            return None
        v = m.group(2).strip()
        if v[:1] in ("&", "*", "!", "{", "[", ">", "|"):
            return None
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        out[m.group(1)] = v
    return out


def host_field(cfg):
    """The `host` stamped on records and events: the hostname by default (`host` unset or null),
    the configured string, or None (`false` or "") to leave the field out."""
    h = cfg.get("host")
    if h is False or h == "":
        return None
    return h if isinstance(h, str) else socket.gethostname()


def plugin_fields(cfg, meta):
    """What the plugin adds to every record and event (never anything from the session).
    record_fields can't set the plugin's own keys, so an omitted host stays omitted."""
    out = {k: str(v) for k, v in (cfg.get("record_fields") or {}).items()
           if k not in RECORD_KEYS | PLUGIN_KEYS}
    out.update({"engine": cfg.get("engine", "claude"), "model": meta.get("model", cfg["model"])})
    host = host_field(cfg)
    if host is not None:
        out["host"] = host
    out.update({"recorded": meta["ts"], "sessions": ", ".join(meta["sessions"]), "plugin": meta["plugin"]})
    return out


def render_record(fields, body, cfg, meta):
    """The record as it lands in the sink: the review's fields, then the plugin's own."""
    full = dict(fields)
    full.update(plugin_fields(cfg, meta))
    full["fingerprint"] = fingerprint(fields["symptom"], fields["stage"])
    head = "\n".join(f"{k}: {json.dumps(v, ensure_ascii=False)}" for k, v in full.items())
    return f"---\n{head}\n---\n\n{body}\n", full["fingerprint"]


# ---- sink -----------------------------------------------------------------------------------

DEFAULT_BRANCHES = {"main", "master", "trunk", "default"}
CLONE_MARKER = "learned-skills-sink-clone"  # inside .git/, so it is never committed


def sink_config(cfg):
    """The sink, with LEARNED_SKILLS_SINK_{URL,REPO,BRANCH,PATH} overriding the config per host.
    None when no sink is set or it is unsafe (a path escaping the repo)."""
    s = dict(cfg.get("sink") or {})
    for key in ("url", "repo", "branch", "path"):
        v = os.environ.get(f"LEARNED_SKILLS_SINK_{key.upper()}")
        if v:
            s[key] = v
    if not (s.get("url") or s.get("repo")) or not s.get("branch"):
        return None
    out = {"url": s.get("url"), "repo": s.get("repo") and os.path.realpath(os.path.expanduser(s["repo"])),
           "branch": s["branch"], "path": (s.get("path") or "learnings").strip("/"),
           "remote": s.get("remote") or "origin", "push": bool(s.get("push")),
           "allow_default_branch": bool(s.get("allow_default_branch")),
           "clone_dir": s.get("clone_dir") and os.path.expanduser(s["clone_dir"]),
           "git_config": dict(s.get("git_config") or {})}
    if not out["path"] or out["path"].startswith("/") or ".." in out["path"].split("/"):
        return None
    return out


def sink_url(sk):
    """The remote to clone. From `url`, or read (only read) from the owner's checkout."""
    if sk["url"]:
        return sk["url"]
    r = git(sk["repo"], "remote", "get-url", sk["remote"])
    return r.stdout.strip() if r.returncode == 0 else None


GIT_CONFIG_KEYS = ("user.name", "user.email", "user.signingkey", "core.sshCommand",
                   "commit.gpgsign", "gpg.format", "gpg.program", "gpg.ssh.program")


def sink_clone(sk, sdir, log):
    """The private clone, clean and on the sink branch; None (logged) if unusable."""
    url = sink_url(sk)
    if not url:
        log("sink: no remote url (set sink.url, or a repo with that remote); sink skipped")
        return None
    clone = os.path.realpath(sk["clone_dir"] or os.path.join(sdir, "sink-clone"))
    marker = os.path.join(clone, ".git", CLONE_MARKER)
    if not os.path.isfile(marker):
        if os.path.lexists(clone) and not (os.path.isdir(clone) and not os.listdir(clone)):
            # Never remove what we didn't make: a mistyped clone_dir could be ~ or a project.
            log(f"sink: {clone} exists and is not this plugin's clone; refused (empty it or pick another clone_dir)")
            return None
        r = git(sdir, "clone", "-q", "--no-checkout", url, clone, timeout=600)
        if r.returncode:
            log(f"sink: clone failed: {r.stderr.strip()[:200]}")
            return None
        with open(marker, "w") as fh:
            fh.write("made by the learned-skills sink; safe to delete with this clone\n")
    elif git(clone, "remote", "get-url", "origin").stdout.strip() != url:
        log("sink: the private clone points at another remote; sink skipped")
        return None
    # The owner's identity, signing and ssh settings, read (only read) from their checkout, then
    # any sink.git_config: without them a commit or push from the clone can fail where theirs works.
    conf = {}
    if sk["repo"]:
        for key in GIT_CONFIG_KEYS:
            v = git(sk["repo"], "config", "--get", key)
            if v.returncode == 0 and v.stdout.strip():
                conf[key] = v.stdout.strip()
    conf.update(sk["git_config"])
    for key, v in conf.items():
        git(clone, "config", key, str(v))
    # The clone is ours alone: start every write from a clean tree, so nothing from an earlier
    # branch or a failed run is carried along.
    if os.path.exists(os.path.join(clone, ".git", "MERGE_HEAD")):
        git(clone, "merge", "--abort")
    git(clone, "reset", "-q", "--hard")
    git(clone, "clean", "-q", "-fdx")
    f = git(clone, "fetch", "-q", "--prune", "origin")
    if f.returncode:
        log(f"sink: fetch failed: {f.stderr.strip()[:200]}")
        return None
    default = remote_default(clone)
    if not sk["allow_default_branch"] and (sk["branch"] in DEFAULT_BRANCHES or sk["branch"] == default):
        log(f"sink: branch {sk['branch']} is a default branch; refused (allow_default_branch)")
        return None
    remote_ref = f"refs/remotes/origin/{sk['branch']}"
    if git(clone, "rev-parse", "-q", "--verify", f"refs/heads/{sk['branch']}").returncode == 0:
        r = git(clone, "checkout", "-q", "-f", sk["branch"])
    elif git(clone, "rev-parse", "-q", "--verify", remote_ref).returncode == 0:
        r = git(clone, "checkout", "-q", "-f", "-b", sk["branch"], f"origin/{sk['branch']}")
    elif default:
        # A new lane branch starts from the remote's default branch, so every host creating it
        # shares that history (no unrelated orphan roots to refuse merging later).
        r = git(clone, "checkout", "-q", "-f", "-b", sk["branch"], f"origin/{default}")
    else:  # an empty remote: an orphan, with nothing carried over
        r = git(clone, "checkout", "-q", "-f", "--orphan", sk["branch"])
        if r.returncode == 0:
            git(clone, "rm", "-r", "-q", "-f", "--ignore-unmatch", ".")
            git(clone, "clean", "-q", "-fdx")
    if r.returncode:
        log(f"sink: checkout failed: {r.stderr.strip()[:200]}")
        return None
    if git(clone, "rev-parse", "-q", "--verify", remote_ref).returncode == 0:
        m = git(clone, "merge", "-q", "--no-edit", f"origin/{sk['branch']}")  # never rebase
        if m.returncode:
            # A conflict with what another host pushed. Our own unpushed commits are rebuilt from
            # sink-pending/ (an item leaves it only once pushed), so take the remote as it is and
            # land the pending items on top of it: the clone never stays stuck.
            git(clone, "merge", "--abort")
            if not sk["push"]:  # local-only commits can't be rebuilt; keep them, skip this time
                log(f"sink: merge with the remote branch failed: {m.stderr.strip()[:200]}")
                return None
            git(clone, "reset", "-q", "--hard", f"origin/{sk['branch']}")
            log("sink: merge with the remote branch failed; reset to it and re-applying pending items")
    return clone


def remote_default(clone):
    r = git(clone, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD")
    if r.returncode == 0 and r.stdout.strip().startswith("origin/"):
        return r.stdout.strip()[len("origin/"):]
    git(clone, "remote", "set-head", "origin", "--auto")
    r = git(clone, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD")
    return r.stdout.strip()[len("origin/"):] if r.returncode == 0 and r.stdout.strip().startswith("origin/") else None


def sink_skills(cfg, sdir, log):
    """With live: false, the skills dir the review should see: the sink's PATH/skills, so skills
    build up across reviews instead of each one starting from nothing. None if unavailable."""
    sk = sink_config(cfg)
    if sk is None:
        return None
    clone = sink_clone(sk, sdir, log)
    return os.path.join(clone, sk["path"], "skills") if clone else None


def gate(cfg, sdir, it, log):
    """The disclosure gate at landing time, for fresh and queued items alike: the credential scan
    on every file, then the owner's filter. Returns the item (with any new context merged into
    its files) or None when withheld."""
    import review
    files = os.path.join(it["dir"], "files")
    for r, _, fs in os.walk(files):
        for f in fs:
            p = os.path.join(r, f)
            if os.path.islink(p):
                log(f"sink: withheld {it['kind']} {it['name']}: a symlink")
                return None
            with open(p, errors="replace") as fh:
                text = fh.read()
            hit = next((rule for rule, rx in review.SECRET_RULES if rx.search(text)), None)
            if hit:
                log(f"sink: withheld {it['kind']} {it['name']}: credential shape {hit}")
                return None
    why, ctx = run_filter_dir(cfg, sdir, it["kind"], it["name"], files)
    if why:
        log(f"sink: withheld {it['kind']} {it['name']}: {why}")
        return None
    if ctx:
        merge_context_files(files, ctx)
    return it


def run_filter_dir(cfg, sdir, kind, name, root):
    item = {"kind": kind, "name": name, "writes": []}
    return run_filter(cfg, sdir, item, root=root)


def merge_context_files(root, ctx):
    for r, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(r, f)
            if f.endswith(".json") and os.path.basename(r) == "events":
                with open(p) as fh:
                    ev = json.load(fh)
                ev["context"] = ctx
                with open(p, "w") as fh:
                    fh.write(json.dumps(ev, indent=2, ensure_ascii=False) + "\n")
            elif f.endswith(".md") and r == root:
                with open(p) as fh:
                    text = fh.read()
                head, sep, rest = text[4:].partition("\n---\n")
                head = "\n".join(l for l in head.split("\n") if not l.startswith("context: "))
                with open(p, "w") as fh:
                    fh.write("---\n" + head + "\ncontext: " + json.dumps(ctx, ensure_ascii=False) + sep + rest)


def write_sink(cfg, sdir, items, log):
    """Lands items (and earlier pending ones) in the sink. Every item passes the gate again here,
    at push time. Returns a short ref or why not; what can't land stays in sink-pending/."""
    sk = sink_config(cfg)
    pending = os.path.join(sdir, "sink-pending")
    for it in items:
        stage_item(pending, it)
    queue = load_pending(pending)
    cap = cfg.get("max_pending", 200)
    if len(queue) > cap:  # bounded: the oldest go first
        for it in queue[:len(queue) - cap]:
            shutil.rmtree(it["dir"], ignore_errors=True)
        log(f"sink: pending over {cap}; dropped the {len(queue) - cap} oldest")
        queue = queue[len(queue) - cap:]
    if sk is None or not queue:
        return None
    clone = sink_clone(sk, sdir, log)
    if clone is None:
        return "sink unavailable; kept for the next review"
    gated = []
    for it in queue:
        if gate(cfg, sdir, it, log) is None:
            shutil.rmtree(it["dir"], ignore_errors=True)  # withheld for good, never retried
        else:
            gated.append(it)
    if not gated:
        return None
    base = os.path.join(clone, sk["path"])
    written = []  # every file this write put under PATH, relative to the clone
    for it in gated:
        for w in it["writes"]:
            src = os.path.join(it["dir"], "files", w["rel"])
            if not w.get("delete") and os.path.isfile(src):  # an event or record: never replaced
                dst = unique_path(os.path.join(base, w["rel"]), src)
                if dst is None:
                    continue  # this very file already landed (committed, push failed)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                written.append(os.path.relpath(dst, clone))
                continue
            dst = os.path.join(base, w["rel"])
            if os.path.isdir(dst):
                shutil.rmtree(dst)
            elif os.path.lexists(dst):
                os.remove(dst)
            if w.get("delete"):
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copytree(src, dst)  # a skill dir, replaced whole
            written += [os.path.relpath(os.path.join(r, f), clone) for r, _, fs in os.walk(dst) for f in fs]
    names = ", ".join(f"{it['kind']} {it['name']}" for it in gated)
    msg = (f"learned: {len(gated)} item(s)\n\n{names}\n\n"
           "Written by the learned-skills background review.")
    if not restage(clone, sk["path"], written, log):
        return "sink staging failed; kept for the next review"
    c = git(clone, "commit", "-q", "-m", msg)
    if c.returncode and "nothing to commit" not in c.stdout + c.stderr:
        log(f"sink: commit failed: {c.stderr.strip()[:200]}")
        return "sink commit failed; kept for the next review"
    ref = git(clone, "rev-parse", "--short", "HEAD").stdout.strip()
    if sk["push"]:
        push = git(clone, "push", "-q", "origin", f"HEAD:refs/heads/{sk['branch']}")
        if push.returncode:  # rejected: merge the remote (never rebase), then try once more
            git(clone, "fetch", "-q", "origin")
            m = git(clone, "merge", "-q", "--no-edit", f"origin/{sk['branch']}")
            if m.returncode:
                git(clone, "merge", "--abort")
                log(f"sink: merge after a rejected push failed: {m.stderr.strip()[:200]}")
                return f"{sk['branch']}@{ref} committed in the private clone; push failed, kept for the next review"
            push = git(clone, "push", "-q", "origin", f"HEAD:refs/heads/{sk['branch']}")
        if push.returncode:
            log(f"sink: push failed: {push.stderr.strip()[:200]}")
            return f"{sk['branch']}@{ref} committed in the private clone; push failed, kept for the next review"
    for it in gated:
        shutil.rmtree(it["dir"], ignore_errors=True)
    return f"{sk['branch']}@{ref}" + ("" if sk["push"] else " (private clone; push: false)")


def restage(clone, path, written, log):
    """Stages PATH from the tree, hashing every file. Skill dirs are rewritten in place, and a
    same-size rewrite can match the index on every stat field (copy2 keeps the mtime, the inode
    is reused, ctime falls in the same second), so `git add` alone may stage nothing: PATH is
    unstaged first. Then exactly two sets are force-added: the files that were tracked and still
    exist, and the files this write produced. Both are ours whatever the sink's .gitignore says
    (it may ignore PATH itself); nothing else is added. False (logged) on any git failure, so
    nothing is reported landed that wasn't."""
    ls = git(clone, "ls-files", "-z", "--", path)
    if ls.returncode:
        log(f"sink: ls-files failed: {ls.stderr.strip()[:200]}")
        return False
    tracked = [p for p in ls.stdout.split("\0") if p]
    r = git(clone, "rm", "-r", "-q", "--cached", "--ignore-unmatch", "--", path)
    if r.returncode:
        log(f"sink: git rm failed: {r.stderr.strip()[:200]}")
        return False
    keep = [p for p in dict.fromkeys(tracked + written) if os.path.lexists(os.path.join(clone, p))]
    if keep:
        spec = os.path.join(clone, ".git", "learned-skills-stage")
        with open(spec, "w") as fh:
            fh.write("\0".join(keep) + "\0")
        r = git(clone, "--literal-pathspecs", "add", "-f", f"--pathspec-from-file={spec}", "--pathspec-file-nul")
        os.remove(spec)
        if r.returncode:
            log(f"sink: staging failed: {r.stderr.strip()[:200]}")
            return False
    return True


def unique_path(dst, src):
    """Where an append-only file lands: dst, or None when dst already holds these bytes, or else
    the first free STAMP.N-NAME beside it, so two items with one stamp both survive."""
    d, f = os.path.split(dst)
    head, sep, tail = f.partition("-")
    n = 1
    while os.path.lexists(dst):
        if os.path.isfile(dst) and not os.path.islink(dst):
            with open(dst, "rb") as a, open(src, "rb") as b:
                if a.read() == b.read():
                    return None
        n += 1
        dst = os.path.join(d, f"{head}.{n}{sep}{tail}" if sep else f"{f}.{n}")
    return dst


def stage_item(pending, it):
    """Copies an item into sink-pending/ so it survives until it lands."""
    d = os.path.join(pending, f"{time.time_ns()}-{it['kind']}-{it['name']}")
    materialize(it, os.path.join(d, "files"))
    with open(os.path.join(d, "item.json"), "w") as fh:
        json.dump({"kind": it["kind"], "name": it["name"], "verb": it["verb"],
                   "writes": [{"rel": w["rel"], "delete": bool(w.get("delete"))} for w in it["writes"]]}, fh)


def load_pending(pending):
    out = []
    for d in sorted(os.listdir(pending)) if os.path.isdir(pending) else []:
        try:
            with open(os.path.join(pending, d, "item.json")) as fh:
                out.append(dict(json.load(fh), dir=os.path.join(pending, d)))
        except (OSError, ValueError):
            continue
    return out


def stamp():
    """UTC to the microsecond: the name of an event or record file, so they sort by time and two
    reviews in one second don't share a name (write_sink still never replaces one)."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")


def record_name(path):
    n = os.path.splitext(os.path.basename(path))[0]
    return n if NAME_RE.fullmatch(n) else None


def plugin_version():
    try:
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                               ".claude-plugin", "plugin.json")) as fh:
            return "learned-skills@" + json.load(fh)["version"]
    except (OSError, ValueError, KeyError):
        return "learned-skills"


def utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
