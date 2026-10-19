---
description: Learned skills - clear open private-key guards (text after a BEGIN with no END is withheld from reviews)
allowed-tools: Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py":*)
---

Report this output to the user as it is, then stop. A private-key BEGIN with no matching END line
keeps the rest of its transcript out of reviews; this clears that, and the log records it. Only
run it when no real key is in that transcript.

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" reset-guard`
