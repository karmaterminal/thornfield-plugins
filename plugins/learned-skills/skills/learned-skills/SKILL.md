---
name: learned-skills
description: >-
  Use when a "💾 Learned" notice arrives from the background skill review, when someone says undo
  after one, when enabling or tuning learned skills in a Claude Code project
  (.claude/learned-skills.json), when a learned-* skill misled you and needs a fix, or when
  deciding whether something belongs in a learned skill, in memory, or in a shared plugin, or when
  feeding learning records to another repo (kind record, sink, filter_command). Covers how the
  review works, its limits, keep and undo, records and sinks.
---

# learned-skills

After every few turns a detached, headless `claude -p` review reads what you did since the last
review and decides whether it taught a procedure worth keeping. If so, it creates or patches a
`learned-*` skill in this project's skills dir, and the next prompt you get carries a
`💾 Learned` notice. Learned skills load like any other skill: only the description, until a
task matches. By default a change is left in the working tree, uncommitted, for the user to keep
or undo.

**When not to use:** a skill you or the user wrote by hand is ordinary files; edit it directly.
Facts about people, preferences and project state are memory, not skills.

## Hard rules

- The review edits a staging copy of the skills dir, never the project. Only `learned-*`
  directories that pass every check are copied back; every other change is dropped. The checks:
  frontmatter holds `name` and `description` only (an `allowed-tools`, `hooks` or `model` key is
  refused), `name` equals the directory, the description is at most 1024 characters, the skill
  is at most `max_skill_bytes`, it holds only regular files and directories (no symlink at any
  level), and no file matches a credential shape (key headers, GitHub/Anthropic/Slack/AWS/Google/
  Discord tokens, JWTs, SSH key blobs, padded base64; the log names the rule, never the value).
  Without PyYAML the frontmatter must be bare `name:`/`description:` lines (quoted, `?` or flow
  keys are refused). A review whose `claude` exits non-zero applies nothing. A learned skill
  edited while the review ran is left alone.
- The review runs with no user or project settings, hooks, plugins or MCP servers, and has no
  shell or web tools. Its file reads and searches are scoped to `STATE/reviewer/`, and its edits
  and writes to `work/` and `work-records/` there. That dir holds only the redacted digest,
  copies of `context_files`, and copies of the `learned-*` skills. Other skills reach the review
  as a list of names and descriptions, never their bodies.
- Staging copies regular files and directories only, never following a link. A `learned-*`
  skill that is a symlink, or holds a symlink or special file at any depth, is not staged
  (`not staged NAME: ...` in the log), and a review that writes that name anyway can't apply it.
  A symlink found in the reviewer dir before the run refuses the review.
- It commits only with `"commit": true`, to whatever git repo the skills dir sits in, and never
  pushes. Even then it never commits on a detached HEAD or during a merge, rebase, cherry-pick,
  revert or bisect, and with `commit_branch` set only on that branch. Otherwise the change stays
  in the working tree, unstaged, and the notice says why.
- Session text is data to the review, never instructions. A learned skill can still carry a bad
  step from a bad session: read each notice's skill and undo what is wrong.

## What to do when

| Situation | Action |
| --- | --- |
| `💾 Learned: created learned-NAME` or `updated` arrives | Tell the user in one line, where you normally report work. Read the skill if it touches something risky. |
| The notice says `not committed (commit: false)` | The change is only in the working tree. To keep it, commit the skill dir (`git add .claude/skills/learned-NAME && git commit`); or set `"commit": true` so reviews commit their own changes. |
| Someone says undo, or the skill is wrong | `/learned-skills:learned-undo learned-NAME`. A created skill is removed; an updated one goes back to exactly its previous tree, added files included. An uncommitted change is restored from the copy the review kept; a committed one is reverted with a new commit. An undo is never undone by the tool: use git for that. |
| `changed after its last learned change` from undo | The skill was edited by hand since; undo refuses rather than lose that edit. The earlier copy's path is in the message. |
| A learned skill misled you mid-task | Fix the step by hand in its `SKILL.md`, or leave it to the next review, which patches skills that misled. |
| Turn on for a project | Add `.claude/learned-skills.json` (below), with the plugin installed. Hooks load at session start. |
| Check what it is doing | `/learned-skills:learned-status`, `/learned-skills:learned-log` |
| Review right now | `/learned-skills:learned-review-now` (foreground; same checks) |
| `learned-skills: no .claude/learned-skills.json in ...` | Not enabled in this project, or you are not in its dir: set `CLAUDE_PROJECT_DIR` or `cd` there. |
| `only N chars since the last review` in the log | Normal: too little new work; the turns carry over to the next review. |
| `not applied learned-NAME: ...` or `ignored NAME` in the log | The review wrote a skill that failed a check, touched a skill that isn't its own, or raced an edit; nothing landed. |
| `claude exit` not 0 in the log | Auth or quota; the same turns are read again next time. |
| `commit failed (index busy?)` or `not committed (MERGE_HEAD in progress)` and the like | The change is in the working tree, unstaged; commit it when the repo is free. |
| Learnings must go to another repo (a team repo, a branch) | Set `sink` and, for friction notes rather than skills, `kind: record` (§ Records, sinks and the filter). |
| `record not kept NAME: ...` or `withheld by filter (exit N)` in the log | A record failed its checks or the filter refused a candidate; nothing was kept. |
| `kept for the next review` or `sink unavailable` in the log | The sink couldn't take it now (network, push rejected); it waits in `sink-pending/` and lands on a later review. |
| A learned skill looks general enough for other projects | Rewrite it into a shared plugin by hand; it is the user's call, never the review's. |

## Enable

```json
{
  "skills_dir": ".claude/skills",
  "every_turns": 8,
  "min_interval_minutes": 20,
  "model": "sonnet",
  "commit": false,
  "context_files": ["~/.claude/projects/PROJECT/memory/MEMORY.md"]
}
```

Put it at `.claude/learned-skills.json` in the project; `{}` is enough. Every key is optional;
the values shown are the defaults, except `context_files` (default none): files the review reads
(as copies) so it does not write a skill for what memory already says. Also: `idle_seconds` (30,
wait before reading), `max_skill_bytes` (40000), `max_digest_bytes` (200000, the newest session
text kept), `timeout_seconds` (900), `commit_branch` (none: with `commit: true`, commit on any
branch; set it so learned commits never land on a feature branch), `engine` (`claude`, the only
one). Paths may start with `~`; a relative `skills_dir` is from the project root.

State (turn count, transcript offsets, log, pending notices, undo copies) lives in
`~/.local/state/learned-skills/PROJECT-HASH/` (or under `$XDG_STATE_HOME`), outside the repo.

## Records, sinks and the filter

For teams where learnings feed a curation step in another repo, and where nothing about the
work's subject may leave the organization.

```json
{
  "kind": "record",
  "live": false,
  "sink": {"url": "git@example.com:org/learnings.git", "path": "learnings",
           "branch": "team/learnings", "push": true},
  "filter_command": ["~/bin/disclosure-check"],
  "record_fields": {"team": "build"}
}
```

- **Config outside the project:** `LEARNED_SKILLS_CONFIG=/path/to/config.json` replaces
  `.claude/learned-skills.json`, so a pinned or assessed checkout stays clean. Per machine,
  `LEARNED_SKILLS_SINK_URL`, `_REPO`, `_BRANCH` and `_PATH` override the sink (give absolute
  paths there). In the config, `skills_dir` is relative to the project and every other path
  (`sink.repo`, `sink.clone_dir`, `context_files`, a `filter_command` path) to the directory
  holding the config file, whichever entry point runs.
- **`kind`**: `skill` (default: learned skills only), `record` (learning records only), or
  `both`. Record-only reviews do not snapshot the skills dir. **`live: false`** writes nothing
  to the project: skill changes go only to the sink.
- **A record** is one piece of friction caused by **the method, the harness or the host**.
  Friction the subject caused (the code or system under work) is a finding for the work itself,
  never a record; the review is told so, and a record whose `cause` isn't `method`, `harness` or
  `host` is refused. Fields: `symptom` (the verbatim error, subject parts replaced by
  placeholders), `stage`, `plane` (optional), `cause`, `resolution`, `recurs` (yes, no or unknown:
  would a fresh session hit it again). The frontmatter is parsed line by line, never as YAML:
  bare `key: value` only, no other keys, at most 8000 bytes. The plugin adds `engine`, `model`,
  `host`, `recorded`, `sessions`, `plugin`, your `record_fields`, and a `fingerprint`
  (normalised symptom plus stage, for dedupe: paths, URLs, hex, numbers blanked).
  **`host`** sets that field on every record and event: unset or `null` is the machine's
  hostname, a string is used as given, and `false` or `""` leaves the field out. `record_fields`
  can't set `host` or any other field the plugin adds. The sink's commit message never names the
  host.
- **`sink`**: `url` (or `repo`, a local checkout whose `remote` URL is read, and only read),
  `path`, `branch`, `push`. Records land as `PATH/UTC-NAME.md`; skill changes as
  `PATH/skills/NAME/` plus an event `PATH/events/UTC-NAME.json`. `UTC` is to the microsecond
  (`20261018T190726.123456Z`), and an event or record is never replaced: a second one with the
  same name lands beside it as `UTC.2-NAME`. All git work happens in a private clone in the
  state dir (or `clone_dir`): the user's checkout gets no worktree, ref, prune or write. The
  branch must not be the remote's default (`main`, `master` and the remote HEAD are refused
  unless `allow_default_branch`); a new branch starts from the remote's default branch, so
  machines creating it share history. Each write starts from a clean clone. The checkout's
  `user.*`, signing and `core.sshCommand` settings are read from `repo` and copied into the
  clone, then `sink.git_config` on top. Each write unstages `PATH` and adds it again, so git
  hashes every file there rather than trusting stat. Exactly two sets are staged, whatever the
  sink branch's `.gitignore` says: files already tracked under `PATH`, and the files this write
  produced. A git failure while staging fails the write, and the items stay pending. A rejected
  push merges (never rebases); a conflict resets the clone to the remote and lands the pending
  items again on top. Anything that can't land waits in `sink-pending/` (at most `max_pending`,
  200; the oldest go first; with no sink configured at all, nothing is staged), and **every item passes the credential scan and the filter again
  when it lands**, so an item queued before a filter was set never skips it.
- **`filter_command`**: your disclosure check. It gets **every file that would be written**
  (skill files and the event JSON, or the rendered record) as path arguments, with `LEARNED_KIND`,
  `LEARNED_NAME` and `LEARNED_PATH` (the candidate root) in its env, after the built-in checks and
  before anything is applied or sunk. Exit 0 admits; any other exit, a timeout
  (`filter_timeout_seconds`, 60) or a missing command withholds. On exit 0 its stdout may hold
  one JSON object, merged as `context` into the event or record; anything else on stdout
  withholds. Its output is never logged. Withhold, never admit.
- **Redaction:** known credential shapes are redacted before the reviewer reads the digest:
  each rendered block passes the credential scan before any clip or cut to the digest's tail,
  so a cut can't strip the header a rule needs and leave the body. That covers a private key's
  body too (PEM, encrypted PEM, PGP, JSON-escaped). An opaque password matches no shape and is kept out only by the review's own refusal, as is an over-broad description ("Use
  for every task") or a body that pipes a download to a shell; `undo` is the recovery. The state
  dir is `0700` and `digest.md` `0600`, like the transcripts it digests. The review's own words
  (its summaries, and the log of what it said) pass the credential scan too, also before any
  clip: a match is replaced by `[withheld: RULE]` in commit messages, events, notices and the log. Git calls never prompt
  and time out after 120 s.

## Memory, skills and shared plugins

| It is | It goes in |
| --- | --- |
| who someone is, what they asked you to do or avoid, and why | memory |
| state of a project, a pointer to a dashboard or ticket | memory |
| steps for a task you repeat, a verbatim error and its fix | a learned skill |
| knowledge about one codebase | that repo's docs or AGENTS.md |
| a procedure several projects need | a shared plugin, written by hand |

When a memory grows into steps, the steps move to a skill and the memory keeps the why. Patch
before creating; never say the same thing in both.

## Cost and limits

Each review is one headless `claude -p` run on the user's own login and model quota;
`every_turns` and `min_interval_minutes` bound how often. A review reads every transcript of the
project it has seen (the last 50) past where it stopped, so a session that ended or was cleared
before its review is still read. It sees main transcripts only (`isSidechain` entries are
excluded), rendered as text with long tool output cut. It does not archive unused skills; prune
by hand with `/learned-skills:learned-undo` or `git rm`.
