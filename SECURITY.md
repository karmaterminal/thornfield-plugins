# Security policy

## Reporting a vulnerability

Please report security issues privately, through GitHub's private vulnerability reporting:
open the repository's **Security** tab and choose **Report a vulnerability**. Please don't open a
public issue for a security problem.

Useful things to include: the plugin and version, what an attacker controls (for example, text
in a session transcript, a repository's contents, or a config file), what happens, and steps to
reproduce. Use fake data in any example.

We aim to acknowledge a report within a week, and to agree on a fix and a disclosure date with
you.

## Scope

In scope: the plugins in `plugins/`, their hooks, scripts and commands, and the marketplace
manifest. For `learned-skills`, that includes a way to get a credential-shaped string, a
symlink, or frontmatter beyond `name` and `description` into a project's skills; a way for the
review run to read or write outside its state directory; or a way to make a hook block or fail
a session.

Known limits, not vulnerabilities: `learned-skills` redacts credentials by pattern, so an opaque
secret such as a plain password is not detected; and a review can learn a wrong or steered step,
which the notice and undo are there to catch. Its README covers both.

## Supported versions

Only the latest release of each plugin gets fixes.
