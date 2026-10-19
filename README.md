# thornfield-plugins

A small, curated Claude Code plugin marketplace. Each plugin here is general-purpose,
self-contained, MIT licensed, and tested in CI on every change.

## Add the marketplace

In Claude Code:

```
/plugin marketplace add karmaterminal/thornfield-plugins
```

Then install a plugin by name, for example `/plugin install learned-skills@thornfield-plugins`.

## Plugins

| Plugin | What it does |
| --- | --- |
| [learned-skills](plugins/learned-skills/) | Turns repeated work into reviewable skills: a background review of the session writes or patches `learned-*` skills in the project, with a notice and one-command undo. Opt-in per project. Read its README for what it sends to a `claude -p` run. |
| [causal-bug-proof](plugins/causal-bug-proof/) | Proves a bug's cause instead of guessing it: a fossil test that fails today, a traced code path and history, the smallest fix, and a revert that brings the failure back. Instructions only: no hooks, servers or background runs. |

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
