# Changelog

## 0.1.0 (2026-10-19): first public release

A fresh, standalone version of a method first written for a private plugin catalog. Changes from
that version:

- **Works from git, the project's own tests and the source alone.** A code-graph tool is used only
  when the session already has one. The graph export step, and the private package it needed, are
  gone.
- **Nothing specific to one project.** No test-runner rules, pointers to internal skills or internal
  schema names.
- **New:** a rule to walk history in a separate git worktree and never discard uncommitted changes,
  a `git bisect run` template with its exit codes, a `git apply` template for the revert step, a
  Markdown report template, and a path for sessions without a shell.
