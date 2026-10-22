"""Shared paths and config for the learned-skills hooks, review runner and CLI."""
import contextlib
import fcntl
import hashlib
import json
import os
import re

CONFIG_NAME = os.path.join(".claude", "learned-skills.json")
PREFIX = "learned-"
GUARD_ENV = "LEARNED_SKILLS_REVIEW"
SESSION_ID = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
DEFAULTS = {
    "skills_dir": os.path.join(".claude", "skills"),
    "every_turns": 8,
    "min_interval_minutes": 20,
    "idle_seconds": 30,
    "engine": "auto",
    "engine_command": None,
    "model": None,
    "max_skill_bytes": 40_000,
    "max_digest_bytes": 200_000,
    "timeout_seconds": 900,
    "commit": False,
    "commit_branch": None,
    "context_files": [],
    "kind": "skill",
    "live": True,
    "sink": None,
    "filter_command": None,
    "filter_timeout_seconds": 60,
    "max_pending": 200,
    "record_fields": {},
    "host": None,
}


def project_dir(hook_input=None):
    """The project root, symlinks resolved (git's toplevel is a real path, and so is the state key)."""
    if hook_input and copilot_hook(hook_input) and hook_input.get("cwd"):
        return os.path.realpath(hook_input["cwd"])
    if os.environ.get("CLAUDE_PROJECT_DIR"):
        return os.path.realpath(os.environ["CLAUDE_PROJECT_DIR"])
    if hook_input and hook_input.get("cwd"):
        return os.path.realpath(hook_input["cwd"])
    return os.path.realpath(os.getcwd())


def load_config(proj):
    """None when the project has not opted in (no config file, or LEARNED_SKILLS_CONFIG naming
    none): every entry point is then a no-op."""
    proj = os.path.realpath(proj)
    # LEARNED_SKILLS_CONFIG points at a config outside the project, for checkouts that must stay
    # clean (a method pinned to one commit, an assessed repo).
    path = os.path.expanduser(os.environ.get("LEARNED_SKILLS_CONFIG") or os.path.join(proj, CONFIG_NAME))
    if not os.path.isfile(path):
        return None
    with open(path) as fh:
        raw = json.load(fh)
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in raw.items() if k in DEFAULTS})
    # One rule for every entry point (the Stop hook runs from the state dir, review-now from
    # wherever the user is): skills_dir is relative to the project, every other path to the
    # directory holding the config file. Never to the process's working directory.
    base = os.path.dirname(os.path.realpath(path))

    def at(p, root):
        return os.path.realpath(os.path.join(root, os.path.expanduser(p)))
    cfg["skills_dir"] = at(cfg["skills_dir"], proj)
    cfg["context_files"] = [at(p, base) for p in cfg["context_files"]]
    ec = cfg.get("engine_command")
    if isinstance(ec, list) and ec and isinstance(ec[0], str) and ("/" in ec[0] or ec[0].startswith("~")):
        cfg["engine_command"] = [at(ec[0], base), *ec[1:]]
    fc = cfg.get("filter_command")
    if fc:
        fc = [fc] if isinstance(fc, str) else list(fc)
        if fc and ("/" in fc[0] or fc[0].startswith("~")):
            fc[0] = at(fc[0], base)
        cfg["filter_command"] = fc
    if isinstance(cfg.get("sink"), dict):
        sk = dict(cfg["sink"])
        for k in ("repo", "clone_dir"):
            if sk.get(k):
                sk[k] = at(sk[k], base)
        cfg["sink"] = sk
    cfg["config_path"] = path
    return cfg


def copilot_hook(hook):
    return hook.get("engine") == "copilot" or "sessionId" in hook


def transcript_path(hook):
    path = hook.get("transcript_path") or hook.get("transcriptPath")
    if path:
        return path
    session = hook.get("sessionId") or hook.get("session_id")
    if copilot_hook(hook) and isinstance(session, str) and SESSION_ID.fullmatch(session):
        home = os.environ.get("COPILOT_HOME") or os.path.expanduser("~/.copilot")
        return os.path.join(home, "session-state", session, "events.jsonl")
    return None


def state_dir(proj):
    proj = os.path.realpath(proj)
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    slug = re.sub(r"[^A-Za-z0-9]+", "-", os.path.basename(os.path.abspath(proj))).strip("-")
    digest = hashlib.sha256(os.path.abspath(proj).encode()).hexdigest()[:8]
    d = os.path.join(base, "learned-skills", f"{slug}-{digest}")
    os.makedirs(d, mode=0o700, exist_ok=True)
    # Private like the transcripts it digests (Claude Code keeps those 0600 under 0700), also
    # for state dirs made by earlier versions with the umask's 0755.
    for p in (os.path.dirname(d), d):
        os.chmod(p, 0o700)
    return d


def load_state(sdir):
    try:
        with open(os.path.join(sdir, "state.json")) as fh:
            st = json.load(fh)
    except (OSError, ValueError):
        st = {}
    for k, v in (("turns", 0), ("last_review", 0), ("last_attempt", 0), ("offsets", {}),
                 ("transcripts", []), ("transcript", None), ("key_guard", {}), ("ident", {})):
        st.setdefault(k, v)
    return st


@contextlib.contextmanager
def locked_state(sdir):
    """Read-modify-write of state.json under a lock: the Stop hook and a review both write it."""
    with open(os.path.join(sdir, "state.lock"), "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        st = load_state(sdir)
        yield st
        save_state(sdir, st)


def save_state(sdir, state):
    tmp = os.path.join(sdir, "state.json.tmp")
    with open(tmp, "w") as fh:
        json.dump(state, fh)
    os.replace(tmp, os.path.join(sdir, "state.json"))


def frontmatter(path):
    """Returns (name, description) from a SKILL.md, or (None, None) when it has no usable frontmatter."""
    try:
        with open(path) as fh:
            text = fh.read()
    except OSError:
        return None, None
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None, None
    try:
        import yaml
        fm = yaml.safe_load(m.group(1)) or {}
    except ImportError:
        fm = plain_frontmatter(m.group(1))
    except Exception:  # bad YAML
        return None, None
    if not isinstance(fm, dict):
        return None, None
    return fm.get("name"), fm.get("description")


def plain_frontmatter(block):
    """`name`/`description` without PyYAML: plain scalars and `>`/`|` block scalars (folded or kept)."""
    out, lines, i = {}, block.split("\n"), 0
    while i < len(lines):
        m = re.fullmatch(r"(name|description):[ \t]*(.*)", lines[i])
        i += 1
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val[:1] in (">", "|"):
            body = []
            while i < len(lines) and (not lines[i].strip() or lines[i][0] in " \t"):
                body.append(lines[i].strip())
                i += 1
            val = (" " if val[0] == ">" else "\n").join(body).strip()
        elif len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
            val = val[1:-1]
        out[key] = val
    return out


def learned_skills(skills_dir):
    out = []
    if os.path.isdir(skills_dir):
        for d in sorted(os.listdir(skills_dir)):
            if d.startswith(PREFIX):
                name, desc = frontmatter(os.path.join(skills_dir, d, "SKILL.md"))
                out.append((d, name, desc))
    return out
