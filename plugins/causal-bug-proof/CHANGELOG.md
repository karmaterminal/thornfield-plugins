# Changelog

## 0.2.0 (2026-11-10)

Three habits from using the skill on a regression that blocked a release:

- **Keep the fossil.** After the fix, revert, reapply cycle, the fossil lands in the project's suite as
  the regression test, unchanged, with its inverse beside it: the case the fix must still refuse. A fix
  that is too loose then fails as well as one that is too narrow. The evidence ladder says what a kept
  fossil passing later does and doesn't establish, and the report template has a row for it.
- **Test the seam.** "Why the tests stayed green" now covers two owners that are each tested correctly
  but disagree: the fossil runs one owner's real output through the other owner's real check.
- **Look for earlier sightings.** Freezing the symptom now includes transcripts, earlier runs' logs,
  issue history and learning-tool records, and checking that a remembered case is the same mechanism
  before it is counted.

## 0.1.1 (2026-10-20)

- **An icon** for the plugin directory, `.claude-plugin/icon.png` (1024 px square). No change to the skill.

## 0.1.0 (2026-10-19): first public release

A fresh, standalone version of a method first written for a private plugin catalog. Changes from
that version:

- **Works from git, the project's own tests and the source alone.** A code-graph tool is used only
  when the session already has one. The graph export step, and the private package it needed, are
  gone.
- **Nothing specific to one project.** No test-runner rules, pointers to internal skills or internal
  schema names.
- **New:** a rule to walk history in a separate git worktree and never discard uncommitted changes,
  a check of the other ways into the broken code, a `git bisect run` template with its exit codes,
  a `git apply` template for the revert step, a Markdown report template, and a path for sessions
  without a shell.
