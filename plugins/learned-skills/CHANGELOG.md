# Changelog

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
