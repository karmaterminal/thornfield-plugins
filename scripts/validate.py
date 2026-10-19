#!/usr/bin/env python3
"""Manifest checks for every plugin in this marketplace. Run through scripts/validate.sh.

  - marketplace.json parses; every entry's source is ./plugins/NAME and every plugins/ dir has
    an entry (and the other way round)
  - each plugin has .claude-plugin/plugin.json and a root plugin.json (Agent Plugins 1.0.0):
    the same fields, plus $schema, from a closed set
  - names match the dir; versions agree between both manifests and the marketplace entry
  - every description (both manifests, the marketplace entry) is 500 characters or fewer
  - no plugin ships a top-level bin/ (file, dir or symlink)
  - each plugin has a README.md and CHANGELOG.md; every SKILL.md has name == dir, a description
    of 1024 characters or fewer
  - no credential-shaped string anywhere in the tracked tree
Exit 0 when clean, 1 otherwise.
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
ROOT_KEYS = {"$schema", "name", "version", "description", "author", "homepage", "repository",
             "license", "keywords", "extensions"}
MAX_DESC = 500
SECRET_RES = [
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{40,}"),
    re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY"),
]
errors = []


def err(msg):
    errors.append(msg)


def load(path):
    try:
        with open(os.path.join(ROOT, path)) as fh:
            return json.load(fh)
    except (OSError, ValueError) as e:
        err(f"{path}: {e}")
        return None


def desc_ok(where, desc):
    if not isinstance(desc, str) or not desc.strip():
        err(f"{where}: description missing")
    elif len(desc) > MAX_DESC:
        err(f"{where}: description is {len(desc)} chars (max {MAX_DESC})")


def frontmatter(text):
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return None
    try:
        import yaml
        fm = yaml.safe_load(m.group(1))
        return fm if isinstance(fm, dict) else None
    except ImportError:
        sys.path.insert(0, os.path.join(ROOT, "plugins", "learned-skills", "scripts"))
        import common
        return common.plain_frontmatter(m.group(1))
    except Exception:
        return None


def check_plugin(name, entry):
    base = os.path.join("plugins", name)
    if not NAME_RE.match(name):
        err(f"{base}: name must be lowercase letters, digits and hyphens")
    cc = load(os.path.join(base, ".claude-plugin", "plugin.json"))
    ap = load(os.path.join(base, "plugin.json"))
    if cc is None or ap is None:
        return
    if cc.get("name") != name:
        err(f"{base}/.claude-plugin/plugin.json: name {cc.get('name')!r} != dir {name!r}")
    if ap.get("$schema") != SCHEMA:
        err(f"{base}/plugin.json: $schema must be {SCHEMA}")
    if set(ap) - ROOT_KEYS:
        err(f"{base}/plugin.json: keys outside the Agent Plugins schema: {sorted(set(ap) - ROOT_KEYS)}")
    portable = {k: v for k, v in cc.items() if k in ROOT_KEYS}
    if portable != {k: v for k, v in ap.items() if k != "$schema"}:
        err(f"{base}: plugin.json and .claude-plugin/plugin.json differ")
    for where, d in ((f"{base}/.claude-plugin/plugin.json", cc.get("description")),
                     (f"{base}/plugin.json", ap.get("description")),
                     (f"marketplace entry {name}", entry.get("description"))):
        desc_ok(where, d)
    if entry.get("version") and entry["version"] != cc.get("version"):
        err(f"marketplace entry {name}: version {entry['version']} != plugin {cc.get('version')}")
    if os.path.lexists(os.path.join(ROOT, base, "bin")):
        err(f"{base}: a top-level bin/ is not allowed")
    for f in ("README.md", "CHANGELOG.md"):
        if not os.path.isfile(os.path.join(ROOT, base, f)):
            err(f"{base}: no {f}")
    skills = os.path.join(ROOT, base, "skills")
    for d in sorted(os.listdir(skills)) if os.path.isdir(skills) else []:
        p = os.path.join(skills, d, "SKILL.md")
        try:
            with open(p) as fh:
                fm = frontmatter(fh.read())
        except OSError:
            err(f"{base}/skills/{d}: no SKILL.md")
            continue
        if not fm:
            err(f"{base}/skills/{d}/SKILL.md: no parseable frontmatter")
            continue
        if fm.get("name") != d:
            err(f"{base}/skills/{d}/SKILL.md: name {fm.get('name')!r} != dir")
        desc = fm.get("description")
        if not isinstance(desc, str) or not desc.strip() or len(desc) > 1024:
            err(f"{base}/skills/{d}/SKILL.md: description missing or over 1024 chars")


def main():
    mk = load(os.path.join(".claude-plugin", "marketplace.json"))
    if mk is None:
        return
    if not NAME_RE.match(str(mk.get("name"))):
        err("marketplace.json: bad name")
    entries = {}
    for e in mk.get("plugins", []):
        n = e.get("name")
        if e.get("source") != f"./plugins/{n}":
            err(f"marketplace entry {n}: source must be ./plugins/{n}")
        entries[n] = e
    dirs = set(os.listdir(os.path.join(ROOT, "plugins"))) if os.path.isdir(os.path.join(ROOT, "plugins")) else set()
    for n in sorted(set(entries) - dirs):
        err(f"marketplace entry {n}: no plugins/{n}")
    for n in sorted(dirs - set(entries)):
        err(f"plugins/{n}: not listed in marketplace.json")
    for n in sorted(set(entries) & dirs):
        check_plugin(n, entries[n])
    files = subprocess.run(["git", "-C", ROOT, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                           capture_output=True, text=True).stdout.split("\0")
    for f in filter(None, files):
        p = os.path.join(ROOT, f)
        if not os.path.isfile(p):
            continue
        with open(p, errors="replace") as fh:
            text = fh.read()
        if any(rx.search(text) for rx in SECRET_RES):
            err(f"{f}: credential-shaped string")


main()
for e in errors:
    print(f"ERROR {e}")
print(f"validate: {len(errors)} error(s)")
sys.exit(1 if errors else 0)
