# Evidence ladder

What each kind of result lets you claim, and what it doesn't let you claim yet. Use it to word findings,
commit messages, pull request descriptions and incident reports.

| What you have | What you can claim | What you can't claim yet |
| --- | --- | --- |
| A captured log, payload, database row or visible outcome | The symptom happened | Its cause |
| A fossil that fails | The fossil characterizes a defect | That you know the cause |
| `git log -S`, `-G` or `-L`, blame or diffs point at a change | A candidate introducing commit, found by archaeology | A first-bad commit |
| The fossil passes before a commit and fails after it | A first-bad commit, found by behaviour | That it is the only cause |
| A fix makes the unchanged fossil pass | The fix satisfies the fossil | That the incident is cured |
| Reverting only the fix makes the fossil fail, and reapplying it makes the fossil pass | The fix is load-bearing for the fossil | That it is the only or the smallest fix, or the incident's cause |
| An end-to-end or live run shaped like the incident changes with the fix and only with it | Strong support that the fix removes the incident's cause | Anything beyond the identities you froze |

Say "proves" only about a narrow statement whose whole chain of results is in front of you. Otherwise
use the specific wording in the middle column.

## History

- **Introducing commit:** created the mechanism already in its broken state. This is the right term
  for code that was born broken.
- **First-bad commit:** a change from good to bad, shown by running the same fossil on both sides of
  it, usually with `git bisect run`.
- **Refactor that preserves the defect:** moved or extracted the mechanism without changing what it
  does.
- **Archaeology:** conclusions from `git log -S`, `-G` or `-L`, blame, reading the source, or graph
  paths, without running the fossil across revisions.

Don't say a test was "run back through history" when only its symbols or lines were traced.

## The revert step

Call the revert in the fix, revert, reapply cycle a **patch-only revert**. It isn't mutation testing,
which generates many small changes to measure how sensitive a test suite is.

A revert that restores the failure shows that a fix is load-bearing. It doesn't show that the fix is
minimal or unique. To claim the smallest fix, list the candidate fixes and say how you ranked them.

## Keep mechanisms apart

Give each mechanism its own row, even when several produce the same visible symptom:

| Symptom | Mechanism | Fossil or other evidence | Status |
| --- | --- | --- | --- |
| What a person or a system observed | The narrow mechanism, in the code that owns it | The exact test, payload, log line or row | open, candidate, fixed on a branch, or released |

A mechanism you fixed lends no authority to a neighbouring one you didn't.

## Observed and inferred

Mark every link you worked out rather than saw as inferred: a graph path, a ranked cut, a call you
expect but didn't trace. Keep it apart from what you observed. When graph arithmetic shaped a decision,
record the relation filter and the algorithm, such as "calls only, minimum node cut".

## Titles

Before the fix, revert, reapply cycle has run, title the work as an investigation or a failing-test
report. After it, say exactly what was established:

- the fix is load-bearing for the fossil;
- the owner boundary;
- support for the incident's cause from an end-to-end or live run, if you have one;
- what remains uncertain.

No result carries over when the code, the test, the inputs or the fix change.
