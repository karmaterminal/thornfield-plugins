---
description: Learned skills - undo the last learned change to one skill (learned-NAME)
argument-hint: "learned-NAME"
---

Undo the last learned change to the skill the user named: $ARGUMENTS

1. Take the skill name from the request. It must match `^learned-[a-z0-9-]{1,56}$` exactly. If it
   doesn't, or more than one name or anything else was given, stop and ask for one `learned-*`
   name. Never put anything else on the command line.
2. Run with the Bash tool, the name in single quotes:
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" undo 'learned-NAME'`
3. Report its output as it is.
