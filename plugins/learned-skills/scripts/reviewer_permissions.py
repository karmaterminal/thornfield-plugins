"""Fail-closed file-tool boundary for the staged reviewer, independent of allow rules."""
import json
import os
import re
import signal
import stat
import sys


def contained(root, value):
    if (not isinstance(value, str) or not value or value.startswith("-")
            or any(c in value for c in "\0\r\n")):
        return False
    target = os.path.realpath(os.path.join(root, os.path.expanduser(value)))
    return os.path.commonpath((root, target)) == root


def plain_pattern(value):
    return (isinstance(value, str) and not os.path.isabs(value)
            and not any(part in value for part in ("..", "{", "}", "~", "\0")))


def plain_tree(target):
    def check(path):
        info = os.lstat(path)
        return (stat.S_ISDIR(info.st_mode)
                or (stat.S_ISREG(info.st_mode) and info.st_nlink == 1))

    def failed(error):
        raise error

    if os.path.lexists(target) and not check(target):
        return False
    for directory, dirs, files in os.walk(target, followlinks=False, onerror=failed):
        if not all(check(os.path.join(directory, name)) for name in dirs + files):
            return False
    return True


def writable(root, target):
    if not contained(root, target):
        return False
    path = os.path.realpath(os.path.join(root, os.path.expanduser(target)))
    return any(path != os.path.join(root, side) and contained(os.path.join(root, side), path)
               for side in ("work", "work-records"))


def copilot_permitted(root, event):
    tool, args = event.get("toolName"), event.get("toolArgs")
    if tool == "apply_patch" and isinstance(args, str):
        args = {"input": args}
    if not isinstance(args, dict):
        return False
    if tool == "apply_patch":
        if set(args) - {"input", "patch"}:
            return False
        patch = args.get("input") or args.get("patch")
        if not isinstance(patch, str):
            return False
        paths = re.findall(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$",
                           patch, re.MULTILINE)
        return bool(paths) and all(writable(root, target.strip()) for target in paths)
    if tool == "view":
        if set(args) - {"path", "view_range", "forceReadLargeFiles"}:
            return False
        paths = [args.get("path")]
    elif tool in ("glob", "rg"):
        keys = ({"pattern", "paths"} if tool == "glob" else {
            "pattern", "paths", "output_mode", "glob", "type", "-i", "-A", "-B", "-C", "-n",
            "head_limit", "multiline",
        })
        if set(args) - keys:
            return False
        if "type" in args and (not isinstance(args["type"], str)
                               or not re.fullmatch(r"[A-Za-z0-9_+-]+", args["type"])):
            return False
        if not plain_pattern(args.get("pattern") if tool == "glob" else args.get("glob", "*")):
            return False
        paths = args.get("paths", ".")
        paths = paths if isinstance(paths, list) else [paths]
    else:
        return False
    return bool(paths) and all(contained(root, path) for path in paths)


def permitted(root, event):
    tool, args = event.get("tool_name"), event.get("tool_input")
    if not isinstance(args, dict):
        return False
    if tool in ("Read", "Edit", "Write"):
        target = args.get("file_path")
        return contained(root, target) and (tool == "Read" or writable(root, target))
    if tool not in ("Glob", "Grep") or not contained(root, args.get("path", root)):
        return False
    return plain_pattern(args.get("pattern") if tool == "Glob" else args.get("glob", "*"))


def expired(signum, frame):
    raise TimeoutError("reviewer guard budget exceeded")


def main():
    copilot = sys.argv[2:] == ["copilot"]
    allowed = False
    try:
        # CLI hook timeouts fall through to normal permissions. Exit with a denial first.
        signal.signal(signal.SIGALRM, expired)
        signal.alarm(2)
        root = os.path.realpath(sys.argv[1])
        event = json.load(sys.stdin)
        check = copilot_permitted if copilot else permitted
        allowed = isinstance(event, dict) and check(root, event) and plain_tree(root)
    except (OSError, ValueError, TypeError, IndexError):
        allowed = False
    finally:
        signal.alarm(0)
    reason = ("Reviewer staged file access." if allowed else
              "Reviewer tool access refused: outside the staged file boundary or unsupported input.")
    if copilot:
        print(json.dumps({"permissionDecision": "allow" if allowed else "deny",
                          "permissionDecisionReason": reason}))
    if not allowed:
        print(reason, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
