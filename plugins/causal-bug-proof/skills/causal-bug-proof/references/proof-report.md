# Proof report template

Copy this into the pull request, the issue or the incident record, and fill it in. Leave out a section
that doesn't apply, and say why in one line. Write "not run" next to any result you didn't see.

```markdown
# Investigation | Failing-test report | Fix with revert proof: ONE-LINE DEFECT

## Identities
- Code: REPOSITORY at COMMIT (BRANCH)
- Dependencies: the versions that matter, or the lockfile at that commit
- Runtime and environment: language version, operating system, configuration, flags
- Fossil: PATH/TO/TEST, run with `TEST COMMAND`

## Symptom
What was observed, with the exact output, error or log lines, and when.

## Mechanisms
| Symptom | Mechanism | Evidence | Status |
| --- | --- | --- | --- |
|  |  |  |  |

## Owner boundary and code path
Where the wrong decision is made, which module owns that contract, and the path from the entry point
to it. Mark inferred links.

## Why the existing tests missed it
Which tests stayed green at the bad commit, and what they fake that the real path depends on.

## History
- Method: archaeology (which commands) or behaviour (bisect range and script)
- Introducing or first-bad commit: COMMIT, and the method that found it
- Last good: COMMIT, and why it counts (same test, same path exercised, same dependencies)

## Fix, revert, reapply
| Step | Command | Result |
| --- | --- | --- |
| Fossil before the fix |  | fails |
| Fossil with the fix |  | passes |
| Fix reverted, fossil kept |  | fails |
| Fix reapplied |  | passes |
| Surrounding suite and controls |  | passes, or which failures also fail on the base |
| End-to-end or live run, if any |  |  |

## What this establishes
One line per claim, worded from the evidence ladder.

## What it doesn't establish
Remaining uncertainty, other candidate fixes and how they ranked, and anything not run.
```
