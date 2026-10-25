# summon-human

A skill that lets an agent ask [frond-alarm](https://github.com/karmaterminal/frond-alarm) to phone
figs, the Thornfield frond's human, and then read what happened. frond-alarm turns one GitHub issue
into at most one phone call, placed off the fleet by its own GitHub Actions worker. This plugin
files that issue in the alarm's own format and reads back the outcome the worker records. It never
places a call itself and holds no provider keys.

```text
agent -> summon.py submit -> [call] issue + wake -> frond-alarm worker -> phone call to figs
agent <- summon.py status <- the worker's labels and comments (answered, not-answered, ..., figs's answers)
```

Summoning is the last rung: after the room, after the princes, for things that can't wait. The
skill says when a call is worth it, how to word the 240 characters the call speaks and up to 3
questions it asks figs, and how to read each outcome and answer without overclaiming it.

## What it contains, runs and sends

- One skill, `summon-human`, with one script, `skills/summon-human/scripts/summon.py`. The script
  needs Python 3 and uses only the standard library (tested on 3.11, 3.12 and 3.13). No hooks, MCP servers or binaries.
- `summon.py check` reads your GitHub login, the alarm's `princes.json` and your permissions on the
  alarm's repository. It files nothing.
- `summon.py submit "TEXT"` files one issue in the alarm's repository: the title
  `[call] REQUEST_ID`, the label `call-request`, and a body holding the `frond-call-v1` marker and
  JSON with your request, and with `--ask`, up to 3 questions for figs. The body is byte for byte
  what the alarm's own `submit.sh` writes. Then it sends a `frond-call` repository dispatch, which
  only wakes the worker sooner.
- `summon.py status` reads that issue, its comments and its label history, and reports the
  outcome, and figs's answers once the alarm posts them, from what the worker
  (`github-actions[bot]`) wrote. Comments from anyone else are counted but never shown or read as
  the outcome or as answers.

Everything goes to `api.github.com` under your own token, and nowhere else. Everyone with access
to the alarm's repository can read a request there, and the answers the alarm posts on it.

## Who can use it

The alarm accepts a request only from a GitHub login listed in its `princes.json`. It only sees
issues that carry its `call-request` label, and GitHub silently drops labels on a new issue from
an account without write access to the repository. `summon.py check` tells you whether both hold,
and `submit` checks the label again after filing. Text, questions, request ids and callers the
alarm would reject are refused before anything is filed; which line codes exist is left to the
alarm, which rejects a wrong one and says why. Requests always go in as `prince_manual`: the
alarm's `outage` source belongs to its own seat watcher.

## Install

In Claude Code:

```text
/plugin marketplace add karmaterminal/thornfield-plugins
/plugin install summon-human@thornfield-plugins
```

In GitHub Copilot CLI:

```sh
copilot plugin marketplace add karmaterminal/thornfield-plugins
copilot plugin install summon-human@thornfield-plugins
```

## Set up

The only credential is your own GitHub token. The script reads `FROND_ALARM_TOKEN`, then
`GH_TOKEN`, then `GITHUB_TOKEN`, then `gh auth token`. A fine-grained token scoped to the alarm's
repository needs Issues read and write; the wake also needs Contents read and write, and without
it pass `--no-wake` and the alarm's 5-minute schedule picks the request up. To check it, ask your
agent to run `summon.py check`, or run it yourself:

```sh
python3 PLUGIN_DIR/skills/summon-human/scripts/summon.py check
```

`--repo OWNER/NAME` (or `FROND_ALARM_REPO`) points it at another frond-alarm repository.

## Try it

Ask in your own words. The skill loads when the request fits, or you can name it. For example:

- "The build host is off the network and nothing we try brings it back. Summon figs to power cycle
  it."
- "Do a dry run of the summon-human setup, so we know the alarm would reach figs."
- "Phone figs and ask whether to restart the build host now or wait for the morning."
- "Did figs answer the call from request 42? Tell me exactly what the alarm recorded."

## Where it works

Anywhere Claude or Copilot can run Python and reach `api.github.com`: Claude Code, GitHub Copilot
CLI, or an OpenClaw seat. In a chat without a shell, Claude can still write the text and the exact
command for someone else to run.

## What it can't do

- It can't make the alarm call: the alarm's worker decides, rate-limits and dials, and a request
  can be held by its cooldown or hourly cap.
- It can't change a request once it is filed. The alarm rejects a request whose body was
  edited, so to change one, file a new one.
- It can't prove the phone rang. `answered` means a human turn, not a voicemail system, is in the
  call's transcript, which is the alarm's evidence, not the phone company's.
- Answers aren't a transcript. They are what the alarm's voice provider made of figs's words
  through speech recognition and its call analysis, which can arrive up to 24 hours late or never,
  and the alarm posts them on the issue, for everyone with access to its repository to read.

## Privacy

What it reads, writes and sends, and to whom: the repository's
[privacy policy](../../PRIVACY.md#summon-human).

## Support

Report problems and ideas in the repository's
[issues](https://github.com/karmaterminal/thornfield-plugins/issues). Report security issues
privately, as its [security policy](https://github.com/karmaterminal/thornfield-plugins/security/policy)
describes.

## License

MIT. See [LICENSE](LICENSE).
