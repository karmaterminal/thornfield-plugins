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

## Contributing

Each plugin lives in `plugins/NAME/` with its own `.claude-plugin/plugin.json`, a matching root
`plugin.json` ([Agent Plugins 1.0.0](https://github.com/agentplugins/agent-plugins-spec)), a
README and a CHANGELOG. `scripts/validate.sh` runs the manifest checks and every plugin's tests;
CI runs the same script.

Security issues: see [SECURITY.md](SECURITY.md). License: [MIT](LICENSE).
