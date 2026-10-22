# Changelog

## 0.5.0 (2026-10-22)

- **Claude Code or GitHub Copilot CLI.** `engine` accepts `claude`, `copilot` or `auto`
  (the default, following the current session transcript). Both engines support skills,
  learning records and combined reviews. Model defaults remain `sonnet` for Claude and
  `auto` for Copilot. Neither engine falls back to the other.
- **Native Copilot hooks and transcripts.** Turn and session-end hooks remember transcripts
  and start due reviews. Notices arrive at session start or after the next successful tool,
  because Copilot discards prompt-hook output. Claude's prompt notices are unchanged.
- **An explicit file-tool guard on both engines.** Copilot uses an isolated runtime home,
  no custom instructions or built-in MCP servers, a four-tool allowlist and scoped write
  approvals. Reviews refuse unsupported CLI versions/flags, repository-scoped runtime
  directories and machine policy that cannot be excluded. CLI hook timeouts and session
  persistence differences are documented.
- **Every Copilot process dies with the review.** Each Copilot call runs in its own process
  session; on a timeout, and after the engine exits, the whole process group is killed, so
  nothing it forked outlives the review. The launcher is resolved on the caller's PATH
  before the private HOME is set, and a `gh copilot` shim is refused (under a private HOME
  it re-execs itself without end); point `engine_command` at the Copilot binary. A classic
  personal access token (`ghp_`) is refused before launch, since Copilot CLI rejects it.
- **Optional wrapper argv.** `engine_command` is a generic executable/subcommand prefix
  for Copilot, validated without special-casing launcher names.
- Public defaults, opt-in commits, undo, redaction, staging, filters and optional sinks
  remain unchanged. New offline tests and an opt-in synthetic live proof cover the port.

## 0.4.2 (2026-10-20)

For the plugin directory's checks. No behaviour change.

- **An icon**, `.claude-plugin/icon.png` (1024 px square).
- **The tests no longer ship.** They moved from `scripts/` to the repository's
  `tests/learned-skills/`, so an installed plugin holds only what runs.
- **Every environment variable the plugin reads is named literally**: the review guard in both
  hooks, and the four `LEARNED_SKILLS_SINK_*` overrides. Before, those names were built at run time.

## 0.4.1 (2026-10-19)

- **JSON structure can no longer close a private-key guard.** Decoded JSON used to be joined
  with line breaks between keys, values and array items. So with a key open, a later message such
  as `{"note": "-----END RSA PRIVATE KEY-----"}` decoded to a whole END line, closed the guard,
  and showed what followed. Decoded JSON is now joined by a separator that is not a line break
  (`JSON_SEP`), at object and array edges too, so only a line break inside one string can bound
  an END. A JSON string that ends right after its END line, with no trailing `\n`, now leaves
  the guard open (fail closed); `/learned-skills:learned-reset-guard` clears it.

## 0.4.0 (2026-10-18): first public release

The first release outside the private catalog it grew up in. Changes from the last private
build (0.3.2):

- **Commits are opt-in.** `commit` now defaults to `false`: a review leaves its change in the
  working tree, and the `💾 Learned` notice says how to commit it or undo it.
- **Undo works without a commit.** For an uncommitted change, the review keeps copies of the
  skill from before and after it, and `/learned-skills:learned-undo` restores from those. It
  refuses if the skill was edited by hand since. Committed changes are still undone with a
  revert commit.
- `/learned-skills:learned-review-now` writes its output to the review log as well, so
  `/learned-skills:learned-log` shows it, as the command's text always said.
- **The reviewer sees only what the README lists.** Only `learned-*` skills are staged for the
  review; other skills reach it as names and descriptions, never their bodies. Its reads are
  scoped to a dedicated `STATE/reviewer/` dir, not the whole state dir. Staging refuses
  symlinks and special files at every level, so nothing from outside the skills dir is staged,
  and a learned skill left out that way can't be replaced by the review, in the project or, with
  `live: false`, in the sink.
- **No sink, no queue.** With no sink configured, a review stages nothing in `sink-pending/`
  and logs nothing about a sink. A sink that is configured but incomplete, unsafe or
  unreachable still keeps its items pending until it can take them.
- Each digest block is redacted before any clip or cut to the digest's tail, so a cut can't
  strip a private key's header and leave its body. A key split across messages or reviews is
  withheld too: everything from a `BEGIN` to the whole `END` line with the same label, from
  the same place (the user's text, Claude's, or the very tool call, by its id), is
  withheld; a nested, mismatched or malformed `END` is body, and a guard of unknown source
  closes at no `END`. JSON line breaks are decided by the JSON parser, also for JSON inside
  prose, and markers and credential shapes are matched on the decoded JSON (string literals included), so `\u`
  escapes can't hide a key, and a block that can't be decoded that way is withheld whole (it can open a key, never close
  one); nothing outside JSON is unescaped. That state is saved per transcript beside its offset.
  There is no size bound: only the matching `END` line closes a key, so it fails closed. A
  stray `BEGIN` keeps the rest of that session out of reviews; `learned-status` shows it, and
  the new `/learned-skills:learned-reset-guard SESSION` clears that one session's guard
  (the full path when two share an id; recorded in the review log). The reviewer's stdout, stderr and
  summaries are redacted before they are clipped.
- **Each saved offset is bound to its transcript file** (device, inode and a hash of its first
  4 KB). A transcript replaced at the same path is read again from the start with a fresh
  guard, even when the new file is the same size or larger.
- **Claude engine only.** The optional Copilot CLI engine (records only) is removed, with its
  transcript reader and the `engine_command` key. `engine` accepts only `claude`.
- Neutral wording throughout, a README with a data and cost disclosure, and a `license` field in
  both manifests.

## Private history

0.1.0 to 0.3.2 were built and used in a private plugin catalog on 2026-10-17 and 2026-10-18,
with several rounds of review. In brief:

- **0.3.2:** the digest is redacted before the review reads it (whole private-key blocks in PEM,
  encrypted PEM, PGP and JSON-escaped shapes); the state directory is `0700` and the digest
  `0600`. From a hostile-transcript red team.
- **0.3.1:** events and records written in the same second no longer collide; a `host` config
  key; the sink always rehashes and restages what it writes, whatever the sink's `.gitignore`.
- **0.3.0:** an optional Copilot CLI engine for records (removed again in 0.4.0) and the root
  Agent Plugins 1.0.0 manifest.
- **0.2.x:** learning records (`kind: record`), the git sink with its private clone, and the
  fail-closed `filter_command`; review fixes; no `bin/`, and no user text in any command's shell
  line.
- **0.1.0:** the Stop hook, detached headless review, `💾 Learned` notices and undo, with
  credential-shape checks, frontmatter limited to `name` and `description`, and no symlinks;
  after OpenClaw's skill workshop.
