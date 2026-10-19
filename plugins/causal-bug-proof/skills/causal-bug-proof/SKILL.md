---
name: causal-bug-proof
description: >-
  Use when a bug needs stronger evidence than an ordinary regression test: a regression after a
  release, upgrade, refactor or merge; a cause that is unclear or disputed between your code, a
  dependency, the environment and a flaky test; a test suite that stays green while the bug is live;
  or a fix that works without anyone knowing why. Triggers include "find the root cause", "prove this
  fix", "which commit broke this", "why didn't the tests catch it" and "is this our bug or
  upstream's". Pins the wanted behaviour in a failing test whose assertions never change, traces the
  code path and the git history, applies the smallest fix, and shows that reverting only the fix
  brings the failure back. Prevents fixes that pass by coincidence, tests weakened to fit old code,
  and root-cause claims stronger than the evidence.
---

# Causal bug proof

Treat the bug as an experiment. Pin the behaviour you want in a test that fails today, find the code
and the change that broke it, make the smallest fix where the fault lives, and then show that the fix
is what turns the test green: take out only the fix and the test fails again, put it back and it
passes.

```text
symptom -> fossil fails (RED) -> smallest fix -> fossil passes (GREEN)
                                       |
                                       +-> revert only the fix -> RED -> reapply -> GREEN
```

A **fossil** is a test that states the behaviour you want, with realistic inputs. Its assertions stay
fixed for the whole investigation, at every commit you run it on.

## When to use it

- A regression appeared after a release, an upgrade, a refactor or a merge, and you need the change
  that caused it.
- The cause is disputed: your code, a dependency, configuration, the environment, or a flaky test.
- The test suite is green while the bug is live.
- Several symptoms may share one cause, or one symptom may have several.
- A fix turns the tests green but nobody can say why, or it has to convince a skeptical reviewer.
- An incident needs evidence that will hold up in a review or a postmortem.

Skip it for an obvious local mistake with an obvious fix. If the person wants a quick patch instead,
make it, and say which of the steps below you skipped.

## Rules

1. **Never change a fossil's assertions** to make it pass, at any commit. When code has moved, adapt
   only imports, fixtures or harness glue.
2. **Claim only what the evidence supports.** A failing test characterizes a defect; it doesn't prove
   a cause. [references/evidence-ladder.md](references/evidence-ladder.md) says what each kind of
   result lets you claim.
3. **Never report a result you didn't see.** If you couldn't run a step, say so, and mark everything
   that depends on it as inferred.
4. **Keep the evidence before you change anything:** the failing output, logs, inputs and versions.
5. **One mechanism per defect.** Similar symptoms can have different causes, and a proven mechanism
   doesn't vouch for its neighbours.
6. **Leave the person's working copy alone.** Walk history in a separate worktree, and never discard
   uncommitted changes.
7. **Don't add production logging, tracing or telemetry only to prove a bug is gone.** Proof
   scaffolding belongs in tests or a scratch harness.
8. **A result holds only for the exact code, test, inputs and fix it ran against.** Run it again when
   any of them changes.

## Where to start

| Situation | Start at |
| --- | --- |
| A bug report and nothing else | 1. Freeze the symptom |
| A reproduction, but no idea where the fault is | 3. Trace the code path |
| The tests pass but the bug is real | 5. Ask why the tests stayed green |
| "It worked in the last release" | 6. Walk back through history |
| A fix exists and you need to know whether it removes the cause | 8. Fix, revert, reapply |
| Several candidate fixes | 7. Model only the part you need |
| No shell in this session | When you can't run commands, at the end |

## Procedure

### 1. Freeze the symptom

Write down the exact identities before you change anything:

- the commit, tag or release that shows the bug, and its branch;
- the dependency versions that matter, or the lockfile at that commit;
- the runtime, operating system, configuration and feature flags;
- the input that triggers it;
- what was observed: the output or error, log lines with their timestamps, and any state that changed.

Copy the evidence somewhere it won't be overwritten. Reproduce the bug on those identities rather than
reasoning from old logs or someone's summary of them.

### 2. Separate the hypotheses

Write each candidate mechanism as its own entry, even when the symptoms look alike: a wrong field in a
payload, a retry that bypasses its policy, a lock or connection that is never released, a missing
timeout, correct code fed stale input. Keep a table and update it as you go:

| Symptom | Mechanism | Evidence | Status |
| --- | --- | --- | --- |
| What was observed | The narrow mechanism, in the code that owns it | The test, payload or log that shows it | open, candidate or fixed |

### 3. Trace the code path

Follow the behaviour from where it enters to where the wrong decision is made. Then follow that
decision's inputs back to where they come from, and find whoever owns cleanup, retries and policy on
that path. Search and read the source. If the session already has a code-graph or call-graph tool, use
it as well, and note which commit it indexed: an index of a different commit can send you to code
that no longer exists.

Name the **owner boundary**, the module or function whose contract is broken. It is often not where the
symptom shows.

### 4. Pin the behaviour in a fossil

Write a test that states the behaviour you want, and see it fail now.

- Use real-shaped inputs: captured payloads and realistic data, not values invented to fit the code.
- Assert the contract, not today's output.
- Tell a failure apart from work that never finishes. Give the test a timeout that turns a hang into a
  failure, and say that you did.
- Add a control case that should pass, so that a broken harness can't pass for the bug.
- Run it with the project's own test command, and keep the exact command and its output.

### 5. Ask why the tests stayed green

Run the existing tests nearest the bug at the bad commit. If they pass while the fossil fails, that is
a finding in its own right, not just missing coverage. Look for what those tests fake that the real
path depends on: a mocked registry or transport, a fixture that skips cleanup, a stub that always
succeeds. Put the fossil at the first real boundary above that blind spot, and mock only external I/O.
Report which fake hid the bug, so that a later change doesn't bring the same blind spot back.

### 6. Walk back through history

Find when the bad behaviour arrived, and whether the code was born broken or broke later.

- **Archaeology** finds candidate changes: `git log -S` for a string, `git log -G` for a regular
  expression, `git log -L` for a function or a range of lines, `git blame`, and parent diffs. It shows
  text changing, not behaviour.
- **Behaviour** is what the fossil does when you run it across commits, and only that can name a
  first-bad commit. `git bisect run` automates the search.

Run the walk in its own worktree, and keep the fossil outside it so that every commit runs the same
file. Copy it in at a path that no commit already uses. This is a template: replace the four values and
`YOUR_TEST_COMMAND` before you run it.

```bash
BAD=commit-that-shows-the-bug
GOOD=commit-believed-good
FOSSIL=/absolute/path/to/the/fossil/test/file
TARGET=path/inside/the/repo/for/the/fossil

git worktree add ../bisect-worktree "$BAD" || exit 1
cd ../bisect-worktree || exit 1
git bisect start "$BAD" "$GOOD" || exit 1
git bisect run sh -c 'cp "$1" "$2" || exit 125; YOUR_TEST_COMMAND "$2"; rc=$?; rm -f "$2"; exit $rc' _ "$FOSSIL" "$TARGET"
git bisect log
git bisect reset
cd - && git worktree remove ../bisect-worktree
```

The script must exit 0 when the fossil passes, and with a code from 1 to 127 other than 125 when it
fails. Make it exit 125 when a commit can't build or can't load the test, so that bisect skips that
commit instead of calling it bad. Check your test runner's own codes: some use a separate code for "no
tests found" or "usage error", and those mean skip, not bad. Any exit code above 127 stops the bisect.

Before you trust the good end of the range, check it:

- Did the same test, with the same assertions, run there?
- Did it exercise the path that fails now?
- Were the dependencies and configuration the same, or did two things change at once?
- Is there real output behind the "pass", rather than someone's summary?

A pass that fails any of these checks is comparison evidence. It can't bound a bisect, so it can't
support a first-bad claim.

When dependencies are involved, bracket on two axes. Walk your code's history with the dependencies
held fixed, then walk the dependency versions with your code held fixed. That separates "our change
broke it" from "the combination broke it".

If no good commit ever exercised the failing condition, call it a **latent defect exposed by a stricter
test** rather than naming a first-bad commit.

Words for the result:

- **introducing commit:** it created the code already in its broken state, so the code was born broken;
- **first-bad commit:** the fossil passes before it and fails after it;
- **refactor that preserves the defect:** it moved or extracted the code without changing its
  behaviour.

### 7. Model only the part you need

Sketch the causal chain: the code on the path, the commits that touched it, each defect, the tests, the
incident evidence and the fix. Label each link with what supports it (a call in the source, a diff, a
test result, a log line) and with whether you observed it or inferred it. A table or a small Mermaid
diagram is usually enough.

When the picture is tangled, a little graph arithmetic helps to rank fixes: the shortest path from the
entry point to the defect, the smallest set of nodes whose removal separates the incident from the
failing test, or the node that every path to the defect passes through. Python's networkx computes
these if it is installed (`shortest_path`, `minimum_node_cut`, `immediate_dominators`). Count only the
links that carry execution, such as calls, when you compute a cut. Treat paths and cuts as rankings,
not proof, and say which links and which algorithm you used.

Rank candidate fixes by:

- how many independent fossils the fix turns green;
- whether it sits at the owner boundary;
- how many production lines it changes;
- its blast radius, and any change of policy it makes;
- the cost of the controls and the live proof it needs.

Throw the sketch away once it has given you the owner boundary, the blind spot and the candidate fix.
Keep it only when a reviewer needs it.

### 8. Fix, revert, reapply

1. Make the smallest change at the owner boundary that cuts the path.
2. Run the unchanged fossil. It must pass.
3. Revert only the fix and keep the fossil. The fossil must fail again.
4. Reapply the fix. The fossil must pass again.
5. Run the surrounding suite and the controls. Check any failure against the base commit: one that
   fails there too isn't caused by the fix.

With the fix still uncommitted, steps 3 and 4 can look like this. Again, replace the placeholders first.

```bash
PATCH=$(mktemp) || exit 1
git diff HEAD -- PATHS_CHANGED_BY_THE_FIX > "$PATCH" || exit 1
git apply -R "$PATCH" || exit 1   # the fix is out and the fossil stays
FOSSIL_TEST_COMMAND               # expect a failure
git apply "$PATCH" || exit 1      # the fix is back
FOSSIL_TEST_COMMAND               # expect a pass
```

This shows that the fix is load-bearing for the fossil. It doesn't show that the fix is the only one or
the smallest one, and it doesn't show that the incident is cured. For the incident you need an
end-to-end or live run, shaped like the incident, whose outcome changes with the fix and only with the
fix.

"Fails on the base, passes on the branch" is good regression evidence, but it isn't this proof. Call a
fix revert-proven only when steps 3 and 4 ran.

### 9. Review and report

- Keep separate mechanisms in separate fixes and separate pull requests.
- Don't fix an unrelated failure that also fails on the base branch just to get a green run. Report it
  instead.
- Write up the result with [references/proof-report.md](references/proof-report.md). Title it by what
  you established: an investigation, a failing-test report, or a fix with revert proof.
- Keep the exact commits and versions, what's needed to reproduce the condition, the fossil and its
  failing output, the passing output with the fix, the revert and reapply outputs, any end-to-end or
  live evidence, and what remains uncertain.
- Delete scratch graphs, logs and worktrees once their findings are in the fix, the test or the report.

## When you can't run commands

Without a shell, as in a chat, do the reasoning steps yourself (1, 2, 3 and 7), and write the fossil
and the fix. Give the person the exact commands for steps 4, 5, 6 and 8, with what each result should
look like, and ask them to paste the output back. Mark every result you haven't seen as not yet run.
