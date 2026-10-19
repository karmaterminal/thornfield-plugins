# Anthropic plugin directory: submission checklist

Where each plugin stands against Anthropic's published requirements for the Claude plugin
directory, checked on 2026-10-19. **Met** means this repository meets it today, **unmet** means
it doesn't yet, and **unknown** means the official pages don't settle it or only Anthropic's
review can.

Sources (official pages only):

- [Policy]: Anthropic Software Directory Policy, updated 2026-04-15,
  <https://support.claude.com/en/articles/13145358-anthropic-software-directory-policy>
- [Terms]: Anthropic Software Directory Terms, updated 2026-03-16,
  <https://support.claude.com/en/articles/13145338-anthropic-software-directory-terms>
- [Checklist]: pre-submission checklist, <https://claude.com/docs/plugins/pre-submission-checklist>
- [Submit]: submitting a plugin, <https://claude.com/docs/plugins/submit>
- [Publish]: who can publish, <https://claude.com/docs/directory/publish>
- [CLI]: `claude plugin validate`, <https://code.claude.com/docs/en/plugins/cli-reference>

## Recommendation

**Submit causal-bug-proof first.** It is instructions only, with no hooks, scripts or network
access, so it meets every requirement below except the ones that depend on the repository going
public. learned-skills should wait for Anthropic's answer to the §1.F question at the end of this
page: its whole purpose is to read session transcripts, and the policy's wording could cover that.

## Before either submission

| Requirement | Status | Source |
| --- | --- | --- |
| Repository is public before the listing goes live | **unmet**: the repository is private | [Submit] |
| Private vulnerability reporting turned on (SECURITY.md points to it) | **unmet**: GitHub reports it unavailable while the repository is private; turn it on after going public | [Terms], [Policy] §3.B |
| A submitter on a Pro, Max, Team or Enterprise plan (on Team or Enterprise, an Owner or a member with the Directory permission), whose GitHub account can push to the repository | unknown: the owner's decision | [Publish], [Submit] |
| Verified contact email for the Compliance step | unknown: the owner's decision | [Submit], [Policy] §3.B |
| One plugin folder per submission | met: each plugin is its own folder | [Checklist] |
| Raise `version` on every release | met for now: both plugins have released versions; keep raising it | [Submit] |
| Agree to the Software Directory Terms | unknown: done by the submitter at submission | [Policy] §3.H, [Terms] |

## causal-bug-proof

| Requirement | Status | Source |
| --- | --- | --- |
| `.claude-plugin/plugin.json` in the plugin folder | met | [Checklist] |
| `name`: lowercase, digits, hyphens, at most 64 characters, not reserved or presented as official | met (whether the name is already taken: unknown until the portal checks) | [Checklist] |
| `description`, `author` and `version` set | met | [Checklist] |
| README of at least 40 words outside code blocks | met | [Checklist] |
| `LICENSE` file in the plugin folder, or `license` in `plugin.json` | met: both (MIT) | [Checklist] |
| Regular files only: no symlinks, submodules, LFS pointers or OS junk files | met | [Checklist] |
| Size and file-count limits; no binaries | met: three Markdown files | [Checklist] |
| Skill frontmatter parses, with `description` as text | met | [Checklist] |
| `claude plugin validate` passes | met: passes with Claude Code 2.1.302 | [CLI] |
| §1.C, §1.D: collect only what the function needs, no extra conversation data | met: collects nothing | [Policy] |
| §1.F: doesn't query or extract memory, chat history, summaries or user files | met: reads nothing itself; Claude reads the project's code and git history only as the user asks | [Policy] |
| §2.A, §2.B: narrow description that matches what it does | met: the description says what it does and that it sends nothing | [Policy] |
| §2.D, §2.F, §2.G: no unrequested external calls, no instructions fetched from elsewhere, no hidden or encoded instructions | met | [Policy] |
| §3.A privacy policy link | met once public: [PRIVACY.md](../PRIVACY.md#causal-bug-proof) | [Policy], [Terms] |
| §3.B support channel | met: GitHub issues; security reports pending private vulnerability reporting (above) | [Policy] |
| §3.C documentation of how it works, its purpose and troubleshooting | met: README "What it contains, runs and sends", "Where it works", "What it can't prove" | [Policy] |
| §3.D testing account with sample data | unknown: there is no service or account to test; ask whether it applies | [Policy] |
| §3.E at least three working example prompts | met: README "Try it" | [Policy] |
| §3.F endpoints owned or controlled | met: it uses none | [Policy] |
| §4 unsupported uses (payments, media generation, advertising) | met: none | [Policy] |
| Security scan: no undisclosed sends, hidden code or permission changes | met: nothing runs | [Checklist] |

## learned-skills

| Requirement | Status | Source |
| --- | --- | --- |
| `.claude-plugin/plugin.json` in the plugin folder | met | [Checklist] |
| `name` format, not reserved | met (taken or not: unknown until the portal checks) | [Checklist] |
| `description`, `author` and `version` set | met | [Checklist] |
| README of at least 40 words | met | [Checklist] |
| `LICENSE` in the folder or `license` in `plugin.json` | met: both (MIT) | [Checklist] |
| Regular files only; size and file-count limits; no binaries | met: Python scripts and Markdown only, none over 256 KiB | [Checklist] |
| Every file a hook uses is inside the plugin folder, referenced through `${CLAUDE_PLUGIN_ROOT}` | met | [Checklist] |
| `hooks/hooks.json` valid, documented events (`Stop`, `UserPromptSubmit`) and types only; not listed in `plugin.json`'s `hooks` field | met | [Checklist] |
| No package launchers or installs in hooks | met: `python3` from the standard library; PyYAML used only if already installed | [Checklist] |
| Command and skill frontmatter parses | met | [Checklist] |
| `claude plugin validate` passes | met: passes with Claude Code 2.1.302 | [CLI] |
| §1.C, §1.D: only the data the function needs; no extra conversation data, even for logging | unknown: it reads only the text since the last review, removes credential shapes, and logs only its own decisions and the reviewer's reply, but the review log keeps those indefinitely | [Policy] |
| §1.F: doesn't query or extract chat history or memory | **unknown: the main open question**; see below | [Policy] |
| §2.A, §2.B: narrow description that matches what it does | met: the description names the Stop hook, the background `claude -p` review of the transcript, the account it runs on, and the opt-in | [Policy] |
| §2.D: no external calls the user didn't request | unknown: the review run is started by a hook, not by a prompt, though only in projects the user opted in, and as the README discloses | [Policy] |
| §2.F: no behavioural instructions pulled from external sources | met as we read it: learned skills are local files in the user's project, reviewed by the user, and undoable | [Policy] |
| §2.G: no hidden or encoded instructions | met: the review prompts are plain Markdown in `scripts/` | [Policy] |
| §3.A privacy policy link | met once public: [PRIVACY.md](../PRIVACY.md#learned-skills) | [Policy], [Terms] |
| §3.B support channel | met: GitHub issues; security pending private vulnerability reporting | [Policy] |
| §3.C documentation and troubleshooting | met: README, `learned-status`, `learned-log`, the bundled `learned-skills` skill | [Policy] |
| §3.D testing account with sample data | unknown: no service or account; a reviewer would need an opted-in project and a few turns | [Policy] |
| §3.E at least three working example prompts | met: README "Try it" | [Policy] |
| §3.F endpoints owned or controlled | unknown: the only endpoints are Anthropic's, through the user's own `claude`, and an optional git remote the user names | [Policy] |
| §4 unsupported uses | met: none | [Policy] |
| Security scan: sends disclosed, no hidden code, no permission changes | likely met, unknown until scanned: both outbound paths (the review run and the optional sink) are in the README and the manifest description, each with an off switch; the `UserPromptSubmit` hook does nothing unless the project has opted in; the review run gets fewer permissions, not more | [Checklist] |

## learned-skills and §1.F

§1.F of the [Policy] says: "Software must not query or extract data from Claude's memory, chat
history, conversation summaries, or user-generated or uploaded files." §1.D adds: "Software must
only collect data from the user's context that is necessary to perform their function. Software
must not collect extraneous conversation data, even for logging purposes."

### What learned-skills reads

- **Transcripts, locally, on `Stop`.** The `Stop` hook receives the current session's transcript
  path from Claude Code and remembers it (up to 50 per project). When a review is due, it reads
  each remembered transcript of that project from where the last completed review stopped:
  user and assistant messages of the main session, with tool calls and results cut short. So
  besides the current session, it also reads unreviewed turns of earlier sessions in the same
  project, all of which ran with the plugin enabled. It never reads other projects' transcripts.
- **Optionally, memory files.** `context_files` (empty by default) lets a user hand the review
  copies of files such as a memory file, so it doesn't duplicate them.
- **What it does with them.** It redacts credential shapes, writes a digest to a private local
  directory, and gives it to a second `claude -p` run on the user's own account. That run may
  write `learned-*` skills into the project. Nothing goes to us or to any third party; a git
  sink, if the user configures one, receives the skills and records, never the transcript.

### Why it may count as chat-history extraction

- The plain wording covers it: the plugin reads chat history, and that is its core function.
- The data leaves the session it came from, into another model run and a log file, and with
  `context_files` it can read memory as well.
- It runs from a hook, in the background, not on a user's request in the moment.

### Why it may not

- The rule reads as aimed at software that pulls conversation data out of Claude's product for
  another party. Here the data stays on the user's machine and with Anthropic, under the user's
  own account; no one else receives it.
- It is off until the user opts a project in with a config file, discloses its reads, sends and
  cost in the README and the manifest description, and can be turned off by deleting that file.
- What it produces is shown to the user after every change, can be undone in one command, and is
  limited to skill files in the user's own project.

### The question to ask Anthropic

Send to Anthropic's directory team before submitting learned-skills (check [Submit] for the
address; at the time of writing, directory@anthropic.com):

> Our plugin learned-skills is off by default. When a user enables it for a project, its Stop
> hook records the path of that project's session transcripts, which Claude Code keeps locally.
> Every few turns it reads the new turns of those transcripts, redacts credential-shaped
> strings, and gives that text to a second `claude -p` run on the same machine and the user's
> own account. That run may write reusable skill files into the project, which the user is shown
> and can undo. Nothing is sent to us or to any third party. Optionally, the user can also list
> local memory files for the review to read. Does this count as "query or extract data from
> Claude's memory, chat history, conversation summaries" under §1.F of the Software Directory
> Policy, or as "extraneous conversation data" under §1.D? If it does, would any of these
> changes make it acceptable: reading only the current session; dropping the memory-file
> option; or running the review only when the user asks for it, not from a hook?
