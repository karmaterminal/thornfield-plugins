# learned-skills

learned-skills turns the work Claude does in a project into skills it can reuse. Every few turns,
a background review reads the session so far and asks one question: did this teach a procedure
worth keeping? If it did, the review writes or patches a `learned-*` skill in the project's
`.claude/skills/`, and your next prompt starts with a `💾 Learned` notice that names the skill.
You read it, then keep it or undo it. Nothing happens in a project until you opt it in.

> **What leaves your session, and what it costs.** Each review starts a second `claude -p` run.
> That run uses your own Claude account and quota, the same way any `claude -p` call you make
> does. At the default cadence a review runs after every 8 turns, at most once every 20 minutes,
> with the `sonnet` model. The reviewer can read exactly these, and nothing else:
>
> - a digest of the session transcript since the last review, up to `max_digest_bytes` (200 KB by
>   default), with known credential shapes redacted (other secrets are not; see
>   [Privacy and limits](#privacy-and-limits));
> - copies of the project's `learned-*` skills, the only skills it may change;
> - the **name and description** of each other skill in the skills dir. Their bodies and files
>   are never copied;
> - copies of any `context_files` you list in the config (none by default), as they are.
>
> The text goes nowhere else: no third-party service, no telemetry.

## Install

In Claude Code:

```
/plugin marketplace add karmaterminal/thornfield-plugins
/plugin install learned-skills@thornfield-plugins
```

It needs Python 3.9 or newer and `git` on your `PATH`. PyYAML is used when present; without it,
frontmatter checks are stricter, never looser.

## Turn it on for a project

The plugin does nothing until a project has a config file. In the project root:

```sh
mkdir -p .claude && echo '{}' > .claude/learned-skills.json
```

Start a new session there: hooks load at session start. `{}` means every default below.

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

The plugin also ships a `learned-skills` skill, so Claude knows how to read a notice, when to
undo, and how a learned skill differs from memory.

## Configuration

All keys are optional, in `.claude/learned-skills.json`:

| Key | Default | Meaning |
| --- | --- | --- |
| `every_turns` | `8` | Turns between reviews |
| `min_interval_minutes` | `20` | Never review more often than this |
| `idle_seconds` | `30` | Wait after a turn before reading the transcript |
| `model` | `"sonnet"` | Model for the review run |
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

## How a review stays contained

- The review run gets no user or project settings, hooks, plugins or MCP servers, and no shell
  or web tools. It can read only its reviewer directory (`STATE/reviewer/`, holding the inputs
  listed above) and edit only the staged learned skills and its record staging there. The rest
  of the state directory (the log, undo copies, a sink's clone) is outside that directory.
- Staging copies regular files and directories only. A `learned-*` skill that is a symlink, or
  holds a symlink or special file at any depth, is not staged at all, and the log says so; a
  review can't replace it either, in the project or in a sink. A symlinked skill of yours
  contributes its name only. Before the run starts, the reviewer
  directory is checked again, and any symlink there refuses the review.
- Only `learned-*` directories that pass every check are copied into the project: frontmatter
  with `name` and `description` only (no `allowed-tools`, `hooks` or `model`), no symlinks, a
  size cap, and no credential-shaped strings. Every other change is dropped. Skills you wrote
  are never touched.
- A review that fails, times out or exits non-zero applies nothing, and the same turns are read
  again next time.
- Transcript text is passed to the review as data, with an instruction never to follow it.

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
  so; `/learned-skills:learned-reset-guard SESSION` clears that one session's guard, and the
  review log records it. Only clear it when no real key is in that session.
- **A skill can still be wrong.** A review can learn a bad step from a bad session, or be steered
  by hostile text in the transcript. The safeguards are the checks above, the notice, and undo.
  Read what it writes.
- **Local state.** Turn counts, transcript offsets, the review log, the last digest, undo copies
  and, only when a sink is configured, items waiting for it live in `~/.local/state/learned-skills/` (or `$XDG_STATE_HOME`),
  with `0700` permissions; the digest file is `0600`.
- **Main session only.** Subagent transcripts aren't read. Long tool output is cut.
- **No pruning.** Unused learned skills stay until you undo or delete them.
- Claude Code only, on Linux and macOS (the hooks use `fcntl`).

## Uninstall

```
/plugin uninstall learned-skills@thornfield-plugins
```

Then, if you like, remove `.claude/learned-skills.json` from each project, any `learned-*`
skills you don't want, and the state directory `~/.local/state/learned-skills/`.

## Credits

The idea follows the skill workshop in [OpenClaw](https://github.com/openclaw/openclaw).
MIT licensed; see [LICENSE](../../LICENSE).
