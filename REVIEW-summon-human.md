# Review: summon-human 0.1.0

## Named refs and evidence identity

| Category | Ref | Full SHA / state |
|---|---|---|
| Product/base ref | `main` | `04b2cf90d62359eafc617e5cc1bea5a192ea5564` (server; local worktree base) |
| Under review | PR #13 head `claude/project-thread-c45vta` | `b5ccedb06259a3dba5ec6b80d8476556a2bb8ad3` |
| Safe lane ref | `codeagent/review-tp13` | local = tracking = server = `b5ccedb06259a3dba5ec6b80d8476556a2bb8ad3` before this review artifact; unchanged after publication |
| CI/workflow ref | N/A | Review-only lane; repository-specific pytest used instead of bootstrap Mode-B |
| Presentation ref | PR body/marketplace/plugin/README manifest | `b5ccedb06259a3dba5ec6b80d8476556a2bb8ad3` |
| Docs/proof ref | frond-alarm system | main `a048482db0a528d8d475db33673fd153a1d6911a` |

## Findings

### Low: the light-path wording and room mention are missing

**`plugins/summon-human/README.md:78-85` and `plugins/summon-human/skills/summon-human/SKILL.md:33-38, 103-115`**

The README offers natural-language examples, and the skill explains summon vs. chat policy, but it does not provide the requested exact one-step “I want figs here now” action. It also does not tell the caller to use the room @-mention as the light path before or instead of a call. The current text says “post in the room” / “Try the room” without a concrete room mention token or one-step imperative.

This is a documentation-contract miss, not an implementation or safety defect. It should be made explicit so operators do not jump directly to `summon.py submit`.

## Contract checks

- **frond-alarm body/title/label:** The implementation generates the marker, sorted JSON, title, label, `source=prince_manual`, and `from` mapping in the same form as the pinned `submit.sh`. The live cross-check passes.
- **Text/question/request-id validation:** Text and question limits and character sets are validated before issue creation; request IDs are 6–80 characters and the supported set is enforced; invalid input returns refusal and creates no issue.
- **Identity:** Submission uses `/user` login and maps it only through the alarm roster. It does not use `gh auth switch` or read `hosts.yml`. The credential fallback and header handling do not print a token in normal output.
- **Dispatch:** The `frond-call` event is sent only as an optional wake; the worker reads the issue, not the dispatch payload.
- **Outcome read-back:** Worker-authored labels and comments are mapped across answered, not-answered, outcome-unknown, uncertain, failed, dry-run, duplicate, rejected, and answer states. Unknown/untrusted label/comment sources are warned or ignored. `uncertain` is terminal and treated as possibly rung, never redialled. Polling is bounded and pending waits return honest status.
- **Real-call safety:** Real submission is distinct from `--dry-run`; the plugin posts an issue under the caller's own account and may wake the live alarm. The PR tests use a fake GitHub, and the live system cross-checks also use a fake `gh`; neither creates an issue or places a call.
- **Rate limits and left-open state:** The skill and script explain the 10-minute cooldown and 6/hour fleet cap, retain queued requests, and surface the “left open” reasons after 10 minutes.
- **Credentials and privacy:** Examples contain no credentials. Privacy documentation states what is read, written, and sent, and the script has no local persistence.

## Tests

```text
python3 -m pytest tests/summon-human -q
53 passed, 352 subtests passed in 0.82s
```

This run used `FROND_ALARM_DIR=/tmp/frond-alarm-review-tp13` at the exact frond-alarm main SHA above, enabling the submit.sh, validator, and answer-format live cross-checks. All tests use fake GitHub/provider surfaces and did not create a real issue or call.

## Verdict

**Approve with nits.**

The implementation is contract-fidelity strong and the review found no real-call, identity, validation, or outcome-handling defect. The one documentation issue should be corrected, but it does not block the plugin implementation.
