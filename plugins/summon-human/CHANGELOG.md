# Changelog

## 0.1.0 (2026-10-25): first release

- **One skill, `summon-human`:** one command for "I want figs here now", since figs has said any
  seat may call, at any hour, for any reason (thornfield-plugins#16); the room @-mention as the
  light path for a question that can wait; how to word the 240 characters the call speaks and the
  questions it asks; and what each outcome and answer state means and what to do next.
- **`summon.py check`:** your login, the caller name the alarm lists for you and how the call
  announces you, and whether GitHub will keep the `call-request` label for you. It files nothing.
- **`summon.py submit`:** one issue in the alarm's issue-first format (karmaterminal/frond-alarm#9),
  byte for byte as the alarm's `submit.sh` writes it, then the optional wake. `--ask` adds up to 3
  questions for figs (karmaterminal/frond-alarm#31). It refuses before filing what the alarm would
  reject, a second open live request of yours, and a reused request id. It closes an issue again
  whose label GitHub dropped, and reports a create it can't confirm as unknown instead of retrying
  it.
- **`summon.py status`:** the outcome, and figs's answers once the alarm posts them, from the labels
  and comments the alarm's worker wrote, with `--wait` polling until both are in. Labels and
  comments from anyone else are named in a warning and never read as the outcome or as answers.
