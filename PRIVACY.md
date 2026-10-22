# Privacy policy

This policy covers the plugins in this repository. It says what each one reads, what it writes
and where, what leaves your machine and to whom, and how to delete what it keeps. The plugins have
no servers of their own and collect nothing for us: we, the maintainers, receive no data from
any of them.

Using Claude Code or GitHub Copilot CLI sends your conversation to the selected engine's
inference provider under your own account (including any custom provider you configure).
That is covered by your agreement with that
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
config named by the `LEARNED_SKILLS_CONFIG` environment variable), its hooks and commands
check for that file and exit, reading, writing and sending nothing else.

### What it reads

Once a project opts in:

- **Session transcripts, locally.** Claude Code's `Stop` or Copilot's `agentStop` hook gives the
  plugin the path of the current session's transcript, which the engine already keeps on your
  machine. Copilot's `sessionEnd` hook also checks for a due review, resolving
  `$COPILOT_HOME/session-state/SESSION/events.jsonl` (normally under `~/.copilot`) when its
  event has no transcript path. Session-end checks do not count an extra turn.
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
- `notices.jsonl`: notices awaiting delivery, removed once Claude's next prompt hook or
  Copilot's next session-start/successful-tool hook delivers them. Copilot discards prompt-hook
  output, so tool-free turns can leave a notice waiting.
- `copilot-home/`: an isolated reviewer home, including its Copilot transcript, logs, session
  database, settings and usage receipt. This is outside the reviewer's file-tool read root,
  mode `0700`, and replaced before each Copilot review. Copilot has no equivalent of Claude's
  `--no-session-persistence`; its retained reviewer transcript contains the review prompt and
  any staged material the reviewer read. Claude reviews disable session persistence.
- With a sink only: `sink-pending/` (items waiting for the sink, at most 200 by default) and
  `sink-clone/` (the plugin's own clone of the sink repository, or the `clone_dir` you set).

In your project, a review may create, change or remove directories named `learned-*` in the
skills directory, and nothing else. By default it doesn't commit; with `"commit": true` it makes
one local commit per skill. It never pushes your project.

### What leaves your machine, and to whom

- **To the selected inference provider, under your own account.** Each review starts a second
  Claude Code or GitHub Copilot CLI run (`claude -p` or `copilot -p`) on your machine.
  `engine: auto` (the default) follows the current transcript; explicit `claude` and `copilot`
  select that engine without fallback. The default model is `sonnet` for Claude or `auto`
  for Copilot; Copilot Auto may choose a billable model. That run sends the provider the
  review instructions, a digest of the transcript text since the last review (at most 200 KB by
  default), the learned skills, the names and descriptions of the other skills, and any
  `context_files`. It is billed to your account and quota like any other invocation of that engine, and
  the provider handles it under your agreement with that provider. If your shell environment points
  `claude` at another provider (a gateway, Bedrock or Vertex), the review goes there instead.
  Copilot token environment variables are preserved, or a token is obtained with `gh auth token`.
  Direct custom-provider settings and proxy/CA environment variables are preserved; external
  provider config files and API-key shell commands are not. The optional `engine_command` is
  trusted operator code launching Copilot and must honor the isolation and appended flags.
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

The plugin has no telemetry and contacts no service of ours. Copilot reviewer client telemetry,
remote control/export and automatic updates are disabled; engine/provider server-side processing
remains governed by that provider's agreement. The reviewer has no network or shell tools, but
the CLI itself must reach its inference/authentication services. An optional git sink and
disclosure filter run in the trusted plugin process, not as reviewer tools.

Both engines restrict reviewer reads to staged inputs in `reviewer/` and writes to `work/`
and `work-records/` there, using native tool restrictions and an explicit file-tool hook guard.
Copilot uses fresh HOME/config roots rather than loading user settings; reviews refuse
repository-scoped runtime directories, machine policy hooks that cannot be excluded, unsupported
versions or missing confinement flags. Its CLI hook timeout is fail-open to native permissions;
the guard exits with a denial on its own shorter budget. These are agent-tool boundaries, not
an OS sandbox against operator-controlled launchers or other same-user processes. See the
plugin's [confinement details](plugins/learned-skills/README.md#how-a-review-stays-contained).
Server-managed administrative settings remain part of the trusted CLI/provider environment;
the plugin does not override them.

### How to delete it

- Stop collection in a project: delete `.claude/learned-skills.json`. Or uninstall:
  `/plugin uninstall learned-skills@thornfield-plugins`.
  In Copilot: `copilot plugin uninstall learned-skills`.
- Delete the local state: `rm -rf ~/.local/state/learned-skills/` (or the same path under
  `$XDG_STATE_HOME`). This removes the digest, the log, undo copies, pending sink items and the
  sink clone.
- Delete learned skills: remove the `learned-*` directories you don't want from the project's
  skills directory, or use `/learned-skills:learned-undo learned-NAME`.
- Data already sent to the selected inference provider is governed by your agreement with it.
  Data already pushed to a sink is in that repository's history; remove it there.

## Changes and contact

Changes to this policy are made in this file, and its history is the repository's git history.
Questions: open an issue at <https://github.com/karmaterminal/thornfield-plugins/issues>. Security
issues: see [SECURITY.md](SECURITY.md).
