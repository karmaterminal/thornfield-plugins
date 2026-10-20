# causal-bug-proof

A skill that has Claude prove a bug's cause before anyone trusts the fix. Claude pins the behaviour you
want in a test that fails today and whose assertions never change. It traces the code path and the git
history, makes the smallest fix where the fault lives, and then shows that the fix is what turns the
test green: with only the fix reverted the test fails again, and with the fix reapplied it passes.

```text
symptom -> fossil fails (RED) -> smallest fix -> fossil passes (GREEN)
                                       |
                                       +-> revert only the fix -> RED -> reapply -> GREEN
```

It is for the bugs where an ordinary regression test isn't enough: a regression after a release or an
upgrade, a cause that is disputed between your code, a dependency and the environment, a test suite
that stays green while the bug is live, or a fix that works without anyone knowing why. Its evidence
ladder keeps Claude's wording honest, so a failing test is reported as a failing test, an archaeology
hit as a candidate commit, and a revert-proven fix as exactly that and no more.

## What it contains, runs and sends

The plugin is instructions only: one skill, `causal-bug-proof`, with two reference pages, an evidence
ladder and a report template. It has no hooks, no MCP servers, no scripts and no binaries. It sends
nothing anywhere and fetches nothing.

When Claude follows the skill in a session that can run commands, it runs your project's own tools in
your workspace: `git log`, `git blame`, `git worktree`, `git bisect`, `git diff` and `git apply`, and
your test command. Those commands go through your usual permission settings. The skill tells Claude to
walk history in a separate git worktree and never to discard your uncommitted changes.

## Install

In Claude Code:

```text
/plugin marketplace add karmaterminal/thornfield-plugins
/plugin install causal-bug-proof@thornfield-plugins
```

## Try it

Describe the bug. Claude loads the skill when the request fits, or you can ask for it by name. For
example:

- "Exports started dropping the last row after we upgraded the CSV library. Find the change that
  caused it and prove the fix before we ship it."
- "This test passes, but the bug still happens in production. Work out why the suite misses it."
- "Is this crash our bug or the library's? Show me the evidence either way."

## Where it works

It works best in Claude Code, or anywhere else Claude can run git and your tests. In a chat without a
shell, Claude does the reasoning, writes the test and the fix, and gives you the exact commands to run
and paste back. It marks every result it hasn't seen as not yet run.

## What it can't prove

A revert-proven fix is load-bearing for its test. That doesn't make it the only possible fix or the
smallest one, and it doesn't show that a production incident is cured: that takes an end-to-end or live
run shaped like the incident. The skill says so in its reports.

## Privacy

The plugin collects and sends nothing; see the repository's
[privacy policy](../../PRIVACY.md#causal-bug-proof).

## Support

Report problems and ideas in the repository's
[issues](https://github.com/karmaterminal/thornfield-plugins/issues). Report security issues privately, as its
[security policy](https://github.com/karmaterminal/thornfield-plugins/security/policy) describes.

## License

MIT. See [LICENSE](LICENSE).
