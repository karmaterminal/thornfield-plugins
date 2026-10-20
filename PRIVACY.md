# Privacy policy

This policy covers the plugins in this repository. It says what each one reads, what it writes
and where, what leaves your machine and to whom, and how to delete what it keeps. The plugins have
no servers of their own and collect nothing for us: we, the maintainers, receive no data from
any of them.

Using Claude Code itself sends your conversation to Anthropic (or to the provider you have set
Claude Code up to use) under your own account. That is covered by your agreement with that
provider, not by this policy. This policy covers only what the plugins add.

## causal-bug-proof

causal-bug-proof is instructions only: one skill and two reference pages, all Markdown. It has no
hooks, no scripts, no MCP servers and no binaries, so the plugin itself reads nothing, stores
nothing and sends nothing anywhere.

When Claude follows the skill in a session that can run commands, Claude runs your project's own
tools in your workspace through your usual permission settings: `git log`, `git blame`,
`git bisect`, `git diff`, `git apply`, `git worktree` and your test command. The skill's
templates may create:

- a git worktree beside your checkout (`../bisect-worktree`), which the template removes when the
  bisect ends;
- a temporary patch file (from `mktemp`) holding the diff of the fix, in your system's temporary
  directory, which the template removes at the end;
- the test, fix and report you ask for, in your project.

Nothing else is written, and nothing leaves your machine except as part of your normal Claude Code
session. To remove it, uninstall the plugin; delete any leftover worktree with
`git worktree remove`, and any temporary patch file left by an interrupted run by hand.

## learned-skills

learned-skills is **off by default**. In a project without `.claude/learned-skills.json` (or a
config named by the `LEARNED_SKILLS_CONFIG` environment variable), its two hooks and its commands
check for that file and exit, reading, writing and sending nothing else.

### What it reads

Once a project opts in:

- **Session transcripts, locally.** After each turn, Claude Code's `Stop` hook gives the plugin the
  path of the current session's transcript, the file Claude Code already keeps on your machine.
  The plugin remembers up to 50 such paths per project. When a review is due (by default every 8
  turns, and at most once every 20 minutes), it reads each remembered transcript of that project
  from where the last completed review stopped (a review that fails reads the same text again
  next time). It never reads a transcript of another project. It reads only the user and
  assistant messages of the main session, including tool calls and their results, each cut to a
  fixed length; subagent turns are skipped. Transcripts are
  opened read-only and never changed.
- **The project's skills directory** (`.claude/skills` by default): full copies of the
  `learned-*` skills, and only the name and description of every other skill. The bodies of other
  skills are never read.
- **Files you list in `context_files`**, if any (none by default).
- **Its own config file** and its own state, described below.

### What it writes, and where

All of the plugin's own state lives in `~/.local/state/learned-skills/<project>-<hash>/` (under
`$XDG_STATE_HOME` instead, when that is set). The plugin sets that directory and its parent to
mode `0700`, so other users on the machine can't read anything in it. Files inside are created
with your usual umask; the digest is created with mode `0600`. The state directory holds:

- `state.json`: turn counts, review times, the remembered transcript paths, the current session
  id, how far each transcript has been read, a fingerprint of each transcript (device, inode and a
  SHA-256 hash of its first 4 KB), and whether a private-key guard is open for it. No message text.
- `reviewer/digest.md`: the text of the last review's input (see below). It is overwritten by the
  next review.
- `reviewer/context/`, `reviewer/work/`, `before/`: copies of your `context_files` and learned
  skills from the last review.
- `undo/`: copies of a learned skill from before and after an uncommitted change, kept until you
  undo it or a later review commits or replaces it.
- `review.log`: a log of each review, including the last part of the reviewer's reply (credential
  shapes removed). It is never trimmed.
- `notices.jsonl`: the notices of the last review, removed once your next prompt shows them.
- With a sink only: `sink-pending/` (items waiting for the sink, at most 200 by default) and
  `sink-clone/` (the plugin's own clone of the sink repository, or the `clone_dir` you set).

In your project, a review may create, change or remove directories named `learned-*` in the
skills directory, and nothing else. By default it doesn't commit; with `"commit": true` it makes
one local commit per skill. It never pushes your project.

### What leaves your machine, and to whom

- **To Anthropic, under your own account.** Each review starts a second Claude Code run
  (`claude -p`) on your machine, with the `sonnet` model by default. That run sends Anthropic the
  review instructions, a digest of the transcript text since the last review (at most 200 KB by
  default), the learned skills, the names and descriptions of the other skills, and any
  `context_files`. It is billed to your account and quota like any other Claude Code run, and
  Anthropic handles it under your agreement with Anthropic. If your shell environment points
  `claude` at another provider (a gateway, Bedrock or Vertex), the review goes there instead.
  The run is started with session persistence off, so it leaves no transcript of its own.
- **Credentials are removed first, by pattern.** Before the digest is written, the plugin replaces
  known credential shapes (private keys, GitHub, Anthropic, OpenAI, Slack, AWS, Google and Discord
  tokens, JWTs, SSH key blobs and padded base64) with a placeholder. A secret with no recognizable
  shape, such as a plain password, is not detected and reaches the review run. `context_files`
  are copied as they are, without redaction.
- **To a git remote, only if you configure a `sink`.** The skills and learning records a review
  writes, and a small JSON event for each skill change, go to the repository and branch you name.
  Each event and record carries the plugin version, the model, a timestamp, the ids of the
  reviewed sessions and, unless you set `"host": false`, this machine's hostname. The transcript
  and digest are never written there. The plugin pushes only when the sink sets `"push": true`.
- **To your own `filter_command`, only if you configure one.** It receives each item before it is
  kept, as files on your machine.

Nothing else is sent anywhere. The plugin has no telemetry and contacts no service of ours.

### How to delete it

- Stop collection in a project: delete `.claude/learned-skills.json`. Or uninstall:
  `/plugin uninstall learned-skills@thornfield-plugins`.
- Delete the local state: `rm -rf ~/.local/state/learned-skills/` (or the same path under
  `$XDG_STATE_HOME`). This removes the digest, the log, undo copies, pending sink items and the
  sink clone.
- Delete learned skills: remove the `learned-*` directories you don't want from the project's
  skills directory, or use `/learned-skills:learned-undo learned-NAME`.
- Data already sent to Anthropic in a review run is governed by your agreement with Anthropic.
  Data already pushed to a sink is in that repository's history; remove it there.

## Changes and contact

Changes to this policy are made in this file, and its history is the repository's git history.
Questions: open an issue at <https://github.com/karmaterminal/thornfield-plugins/issues>. Security
issues: see [SECURITY.md](SECURITY.md).
