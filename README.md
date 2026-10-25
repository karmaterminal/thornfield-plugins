# thornfield-plugins

A small, curated plugin marketplace for Claude Code or GitHub Copilot CLI. Each plugin is general-purpose,
self-contained, MIT licensed, and tested in CI on every change.

## Add the marketplace

In Claude Code:

```
/plugin marketplace add karmaterminal/thornfield-plugins
```

Then install a plugin by name, for example `/plugin install learned-skills@thornfield-plugins`.

In GitHub Copilot CLI:

```sh
copilot plugin marketplace add karmaterminal/thornfield-plugins
copilot plugin install learned-skills@thornfield-plugins
```

## Plugins

| Plugin | What it does |
| --- | --- |
| [learned-skills](plugins/learned-skills/) | Turns repeated work into reviewable skills using Claude Code or GitHub Copilot CLI, with a confined background review, a notice and one-command undo. Opt-in per project. Read its README for data and cost disclosures. |
| [causal-bug-proof](plugins/causal-bug-proof/) | Proves a bug's cause instead of guessing it: a fossil test that fails today, a traced code path and history, the smallest fix, and a revert that brings the failure back. Instructions only: no hooks, servers or background runs. |
| [summon-human](plugins/summon-human/) | Lets an agent ask [frond-alarm](https://github.com/karmaterminal/frond-alarm) to phone figs, the Thornfield frond's human, and read what happened, using only the caller's GitHub token. For callers the alarm lists; a skill and a standard-library script, no hooks or servers. |

## Contributing

Each plugin lives in `plugins/NAME/` with its own `.claude-plugin/plugin.json`, a matching root
`plugin.json` ([Agent Plugins 1.0.0](https://github.com/agentplugins/agent-plugins-spec)), a
README and a CHANGELOG. `scripts/validate.sh` runs the manifest checks and every plugin's tests;
CI runs the same script.

## Privacy

What each plugin reads, writes and sends: [PRIVACY.md](PRIVACY.md).

## Support

Questions, bugs and ideas: [GitHub issues](https://github.com/karmaterminal/thornfield-plugins/issues).
Security issues: report them privately through GitHub's private vulnerability reporting, as
[SECURITY.md](SECURITY.md) describes. Please don't open a public issue for one.

License: [MIT](LICENSE).
