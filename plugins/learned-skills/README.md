# learned-skills

learned-skills turns work in Claude Code or GitHub Copilot CLI into skills either can reuse. Every few turns,
a background review reads the session so far and asks one question: did this teach a procedure
worth keeping? If it did, the review writes or patches a `learned-*` skill in the project's
`.claude/skills/`, with a `💾 Learned` notice that names the skill.
You read it, then keep it or undo it. Nothing happens in a project until you opt it in.

> **What leaves your session, and what it costs.** Each review starts a second `claude -p` or
> `copilot -p` run under your own account and quota. By default the engine follows the current
> session's transcript, never which executable happens to be installed. Reviews run after every
> 8 turns, at most once every 20 minutes; the model defaults to `sonnet` for Claude and `auto`
> for Copilot. Copilot Auto can choose a billable model; set `model` to control this.
> The reviewer's file tools can read exactly these:
>
> - a digest of this project's transcripts (up to the 50 most recent sessions, so earlier sessions'
>   unreviewed turns too) since each one's last review, up to `max_digest_bytes` (200 KB by
>   default), with known credential shapes redacted (other secrets are not; see
>   [Privacy and limits](#privacy-and-limits));
> - copies of the project's `learned-*` skills, the only skills it may change;
> - the **name and description** of each other skill in the skills dir. Their bodies and files
>   are never copied;
> - copies of any `context_files` you list in the config (none by default), as they are.
>
> The review text goes to the selected engine's inference provider, under your agreement with
> that provider. The plugin has no telemetry or service of its own; Copilot client telemetry is
> disabled for reviews. If you configure a `sink`,
> the skills and learning records a review writes (not the transcript) go to that git remote too,
> with a change event per skill. Records and events name the reviewed session ids and, unless you
> set `"host": false`, this machine's hostname.
>
> The review run loads no user or project settings, so an `env` block in your `settings.json`
> doesn't apply to it. If you route Claude Code through a gateway, Bedrock or Vertex with
> settings, the review instead uses whatever your shell environment and login give `claude -p`.
> Set those variables in the environment Claude Code starts from, or don't enable the plugin.
> Copilot uses token environment variables or `gh auth token`, not your normal Copilot home.
> Direct provider credentials and proxy/CA variables are preserved; provider API-key shell
> commands and external provider config files are not.

## Install

In Claude Code:

```
/plugin marketplace add karmaterminal/thornfield-plugins
/plugin install learned-skills@thornfield-plugins
```

In GitHub Copilot CLI:

```sh
copilot plugin marketplace add karmaterminal/thornfield-plugins
copilot plugin install learned-skills@thornfield-plugins
```

It needs Python 3.9 or newer and `git` on your `PATH`. PyYAML is used when present; without it,
frontmatter checks are stricter, never looser. Copilot reviews require GitHub Copilot CLI
1.0.101 or newer, with the confinement flags checked at runtime. Only the selected engine
needs to be installed. Copilot's isolated reviewer needs `COPILOT_GITHUB_TOKEN`, `GH_TOKEN`,
`GITHUB_TOKEN`, a direct custom-provider environment, or a working `gh auth login`.

## Turn it on for a project

The plugin does nothing until a project has a config file. In the project root:

```sh
mkdir -p .claude && echo '{}' > .claude/learned-skills.json
```

Start a new session there: hooks load at session start. `{}` means every default below.
The config and default skills path keep their `.claude/` names for compatibility; Copilot
also discovers skills there. Nothing requires a Claude executable when using Copilot.

## Day to day

When a review changes something, your next prompt carries a notice like this:

```
💾 Learned: created learned-flaky-test-retry (how to rerun the one flaky suite) [not committed (commit: false)]
```

By default the change is only in your working tree. Then:

- **Look:** read `.claude/skills/learned-NAME/SKILL.md`.
- **Keep:** commit it, `git add .claude/skills/learned-NAME && git commit -m "keep learned-NAME"`.
  Or set `"commit": true` and reviews commit each change themselves, one commit per skill.
- **Undo:** `/learned-skills:learned-undo learned-NAME`. A new skill is removed; an updated one
  goes back to exactly what it was. Undo refuses if you have edited the skill since, rather than
  lose your edit.

| Command | What it does |
| --- | --- |
| `/learned-skills:learned-status` | Config, learned skills, and when the next review is due |
| `/learned-skills:learned-log` | The last 40 lines of the review log |
| `/learned-skills:learned-undo learned-NAME` | Undo the last learned change to one skill |
| `/learned-skills:learned-review-now` | Run a review now, in the foreground |
| `/learned-skills:learned-reset-guard [SESSION]` | List open private-key guards, or clear one session's (see [Privacy and limits](#privacy-and-limits)) |

Claude delivers notices on your next prompt. Copilot delivers them at the next session start
or successful tool call, once each; a tool-free turn may not show one. Copilot uses the
portable `learned-skills` skill rather than Claude's command namespace. From the project,
use the same commands directly (replace `PLUGIN` with the installed plugin directory):

```sh
python3 PLUGIN/scripts/cli.py status
python3 PLUGIN/scripts/cli.py log
python3 PLUGIN/scripts/cli.py review-now
python3 PLUGIN/scripts/cli.py undo learned-NAME
python3 PLUGIN/scripts/cli.py reset-guard SESSION
```

The plugin also ships a `learned-skills` skill, so either engine knows how to read a notice, when to
undo, and how a learned skill differs from memory.

## Try it

In a project you have opted in, ask your agent:

- "Is learned-skills on in this project? Tell me what a review would send, and when the next
  one runs."
- "Run a learned-skills review now and show me what it learned, if anything."
- "That last 💾 Learned notice: show me the skill it changed, and undo it if the steps don't
  match what we actually did."

## Configuration

All keys are optional, in `.claude/learned-skills.json`:

| Key | Default | Meaning |
| --- | --- | --- |
| `every_turns` | `8` | Turns between reviews |
| `min_interval_minutes` | `20` | Never review more often than this |
| `idle_seconds` | `30` | Wait after a turn before reading the transcript |
| `engine` | `"auto"` | `claude`, `copilot`, or follow the current session transcript; unknown producers refuse |
| `engine_command` | none | Copilot executable/subcommand argv prefix, e.g. `["wrapper", "agent"]`; not a shell string |
| `model` | engine default | `sonnet` for Claude, `auto` for Copilot; an explicit model must work with the selected engine |
| `max_digest_bytes` | `200000` | Most session text one review sees (the newest is kept) |
| `max_skill_bytes` | `40000` | Largest learned skill directory accepted |
| `timeout_seconds` | `900` | A review that runs longer applies nothing |
| `skills_dir` | `".claude/skills"` | Where learned skills live, relative to the project |
| `commit` | `false` | Commit each learned change (never pushes) |
| `commit_branch` | none | With `commit: true`, commit only on this branch |
| `context_files` | `[]` | Files the review reads (as copies) so it doesn't duplicate them, such as a memory file |
| `kind` | `"skill"` | `skill`, `record` (learning records only) or `both` |
| `live` | `true` | `false` writes nothing to the project; changes go only to the sink |
| `sink` | none | A git remote, path and branch that receives skills and records |
| `filter_command` | none | Your disclosure check; anything but exit 0 withholds an item |
| `record_fields` | `{}` | Extra fields stamped on every record and event |
| `host` | hostname | `host` field on records and events; `false` leaves it out |

`kind: record`, `sink` and `filter_command` are for teams that want friction notes collected in
a shared repo. The `learned-skills` skill (`skills/learned-skills/SKILL.md`) documents them in
full: the record format, how the sink's private clone works, and the filter contract.

`engine_command` applies only to Copilot. It must be a nonempty list of nonempty strings,
without NULs, newlines or option arguments starting with `-`. A relative executable path
resolves from the config's directory. No launcher name is special: the wrapper is trusted
operator code and must forward the appended flags, respect the isolated environment and not
inject settings, plugins, tools or MCP servers. The plugin never retries with weaker flags
or a different engine after a refusal or launch failure.

## How a review stays contained

- The review run gets no user or project settings, hooks, plugins or MCP servers, and no shell
  or web tools. It can read only its reviewer directory (`STATE/reviewer/`, holding the inputs
  listed above) and edit only the staged learned skills and its record staging there. The rest
  of the state directory (the log, undo copies, a sink's clone) is outside that directory.
- Staging copies regular files and directories only. A `learned-*` skill that is a symlink, or
  holds a symlink or special file at any depth, is not staged at all, and the log says so; a
  review can't replace it either, in the project or in a sink. A symlinked skill of yours
  contributes its name only. Before the run starts, the reviewer
  directory is checked again, and any symlink there refuses the review. The tool guard also
  refuses special files and multi-linked regular files.
- Only `learned-*` directories that pass every check are copied into the project: frontmatter
  with `name` and `description` only (no `allowed-tools`, `hooks` or `model`), no symlinks, a
  size cap, and no credential-shaped strings. Every other change is dropped. Skills you wrote
  are never touched.
- A review that fails, times out or exits non-zero applies nothing, and the same turns are read
  again next time.
- Transcript text is passed to the review as data, with an instruction never to follow it.

| Boundary | Claude Code | GitHub Copilot CLI |
| --- | --- | --- |
| File tools only | `--tools Read,Glob,Grep,Edit,Write` | `--available-tools=view,glob,rg,apply_patch`; shell and URL permissions also denied |
| Read root | Scoped `Read`, `Glob`, `Grep` approvals | Cwd is `STATE/reviewer/`; `--disallow-temp-dir`; no extra path grants |
| Write root | Scoped `Edit` approvals for `work/` and `work-records/` (also govern Write) | Absolute `write(...)` approvals for those two staging dirs only |
| Independent path guard | Explicit `--settings` PreToolUse command | Private `settings.json` native `preToolUse` executable hook |
| No MCP | Empty `--mcp-config` with `--strict-mcp-config` | Fresh config home, no project config, `--disable-builtin-mcps` |
| No user/project settings, hooks or plugins | `--setting-sources ""` | Fresh `HOME`, `COPILOT_HOME` and XDG roots; refuse a reviewer cwd inside a git repo or containing project config |
| No custom instructions | Reviewer cwd is outside the project | `--no-custom-instructions` |
| No prompts or privilege escalation | `--permission-mode dontAsk` | Noninteractive, `--no-ask-user`, no allow-all flags, inherited approvals removed |

Copilot has no `--setting-sources` switch. Its replacement is isolation, not a promise to
ignore configuration found in a repository: **all review kinds are refused** if the reviewer
directory is inside a git repository, contains project config, has permission-pattern
metacharacters, or known machine-policy files are present (the policy-hook directory,
managed-settings JSON on Linux/macOS, or the macOS managed-preferences plist). Those policies
cannot be excluded with a CLI switch. Unsupported versions or missing confinement flags also refuse all
kinds. Use an ordinary state directory outside a checkout; never weaken the boundary to fix a
launch failure. No review kind is refused on the supported, isolated Copilot path.

Both engines run the trusted `reviewer_permissions.py` guard, not hooks from the session.
It checks every tool name and path, patch moves included, and rejects recursive search
patterns that could escape. A malformed invocation, crash or nonzero exit denies the call.
**Copilot's CLI-level hook timeout is fail-open** (normal native permissions then apply);
the guard has its own two-second fail-closed budget, below the ten-second CLI timeout.
Native path checks, scoped write approvals and the tool allowlist remain independent barriers.
These are agent tool boundaries, not an OS sandbox against malicious executables, a modified
CLI, administrator policy or another process running as your user.
Server-managed administrative settings remain part of the trusted CLI/provider environment;
this plugin does not override or bypass them.

The Copilot hook file is `com.github.copilot/hooks/hooks.json`, version 1, using documented
camelCase events. `agentStop` records the transcript and counts turns; `sessionEnd` checks
whether a review is due without counting twice (it resolves the session's `events.jsonl`
when no transcript path is supplied). `sessionStart` and `postToolUse` inject notice context.
All entry hooks remain opt-in and fail-open to the main session. See the official
[hook reference](https://docs.github.com/en/copilot/reference/hooks-reference) and
[plugin reference](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference).

## Privacy and limits

- **Redaction is pattern-based.** Known credential shapes are redacted before the reviewer
  reads the digest: private keys (the whole block), GitHub, Anthropic, OpenAI, Slack, AWS,
  Google and Discord tokens, JWTs, SSH key blobs and padded base64. Each piece of the session is
  redacted before it is shortened, so a cut can never leave half a key behind. A key pasted
  across several messages, or across two reviews, stays withheld until its own `END` line,
  however long it is: everything in between is withheld. The same scan
  runs again on every file, log line, notice and commit the plugin writes, including the
  review's own output. An opaque secret, such as a plain password, matches no pattern. It
  reaches the review run, and only the review's own instructions keep it out of a skill.
- **A stray `BEGIN … PRIVATE KEY` line pauses reviews of that session.** If one appears with no
  matching `END` line (in a note about key formats, say), the rest of that session is withheld
  from reviews, because it can't be told apart from a key. `/learned-skills:learned-status` says
  so; `/learned-skills:learned-reset-guard SESSION` clears that one session's guard (give the
  full path it lists if two sessions share an id), and the review log records it. The session's
  text not yet reviewed is then read as ordinary text, so a real key body still in it would
  reach the review. Only clear it when no real key is in that session.
- **A skill can still be wrong.** A review can learn a bad step from a bad session, or be steered
  by hostile text in the transcript. The safeguards are the checks above, the notice, and undo.
  Read what it writes.
- **Local state.** Turn counts, transcript offsets, the review log, the last digest, undo copies
  and, only when a sink is configured, items waiting for it live in `~/.local/state/learned-skills/` (or `$XDG_STATE_HOME`),
  in `0700` directories; the digest file is `0600`, other files take your umask. The review log is
  never trimmed and keeps the last 1,500 characters of each (redacted) reviewer reply.
- **Reviewer transcripts.** Claude uses `--no-session-persistence`. Copilot has no equivalent
  switch: its own transcript, logs, session store and usage receipt live in a private
  `STATE/copilot-home/`, outside the model's file-tool read root. That home is replaced before
  each Copilot review. Delete it with the rest of the state to remove the retained review.
- **Main session only.** Subagent transcripts aren't read. Long tool output is cut.
- **No pruning.** Unused learned skills stay until you undo or delete them.
- Claude Code or GitHub Copilot CLI, on Linux and macOS (the hooks use `fcntl` and POSIX signals).

## Privacy

What the plugin reads, writes and sends, and how to delete it, is in the repository's
[privacy policy](../../PRIVACY.md#learned-skills).

## Support

Report problems and ideas in the repository's
[issues](https://github.com/karmaterminal/thornfield-plugins/issues). Report security issues
privately, as its [security policy](https://github.com/karmaterminal/thornfield-plugins/security/policy)
describes.

## Uninstall

```
/plugin uninstall learned-skills@thornfield-plugins
```

For Copilot, run `copilot plugin uninstall learned-skills`.

Then, if you like, remove `.claude/learned-skills.json` from each project, any `learned-*`
skills you don't want, and the state directory `~/.local/state/learned-skills/`.

## Credits

The idea follows the skill workshop in [OpenClaw](https://github.com/openclaw/openclaw).
MIT licensed; see [LICENSE](LICENSE).
