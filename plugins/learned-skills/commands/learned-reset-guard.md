---
description: Learned skills - list open private-key guards, or clear one session's (logged)
argument-hint: "[SESSION-ID]"
---

List or clear the open private-key guards for: $ARGUMENTS

A private-key BEGIN with no matching END line keeps the rest of its transcript out of reviews.
Clearing one lets that transcript's new text be reviewed again; it never replays what was held.

1. With no session id in the request, run with the Bash tool
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" reset-guard`, report its output as it is, and stop.
2. Otherwise it must be one session id matching `^[A-Za-z0-9._-]{1,128}$`, or, when two
   transcripts share that id, one full path matching `^/[A-Za-z0-9._/-]{1,4000}\.jsonl$` as the
   listing shows it. Only one may be given. If not, stop and ask for one as the listing shows it. Never put anything else on the
   command line. Before clearing, say that it should only be done when no real key was pasted in
   that session.
3. Run, the id or path in single quotes: `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/cli.py" reset-guard 'ID'`
4. Report its output as it is.
