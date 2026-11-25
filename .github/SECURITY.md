# Security

## Reporting a flaw

Report a security flaw privately: open this repository's **Security** tab
and choose **Report a vulnerability**. Please don't open a public issue.
Say what is affected, how to reproduce it, and what an attacker gains.

## What is covered

The template as it is on `main`: the API, the frontend and the image. Only
the latest commit is supported. There are no
releases, so there is nothing to backport to.

Not covered:

- **Copies of the template.** Each copy belongs to whoever made it
  (`docs/adopting.md`, "Your copy is yours"). Report a flaw in a copy to its
  owners. If the flaw came from the template's code, report it here too.
- **The dev identity provider in `services/dev-idp/`.** It accepts any password on
  purpose, and it never ships.
- **The known gaps in `docs/decisions.md`, "Current gaps".** They are already
  known. A report with a better fix is still welcome.

## What happens next

The flaw is fixed on `main` and published as a GitHub security advisory
that names the commit with the fix, so the owners of copies can port it.
Responses are best effort, with no fixed time.
