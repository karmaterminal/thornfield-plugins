---
description: Learned skills - show status (config, learned skills, next review)
allowed-tools: Bash(python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py":*)
---

Report this output to the user as it is, then stop. If it says the plugin isn't enabled here, say
how to enable it (`.claude/learned-skills.json`, see the `learned-skills` skill).

!`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" status`
