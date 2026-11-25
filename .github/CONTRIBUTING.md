# Contributing

How to change the template, or your own copy of it. The README says what
the template is and how to start it. This file is the workflow, the
principles behind the design, and the specs it follows. Agents read
`AGENTS.md` instead.

## Workflow

- Run `just lint` and `just test` before every commit. There are no
  pre-commit hooks; CI runs the same checks.
- Keep each change to about one idea, small enough to review whole.
- Keep moves apart from rewrites, so the diff of a move shows only the move.
- Say in the commit what was considered and why, and cite the docs it
  followed.
- After changing a router or a schema, run `just generate-api` and commit
  the regenerated client with it.

## Principles

The template is for internal web apps whose users sign in with their
company account. It is not for public sign-up, for callers other than a
browser, or for pages rendered on the server (`docs/adopting.md`, "Is it a
fit?"). A tool that only another kind of app needs is out of scope, not a
gap.

Within that scope there are six principles, ranked: when two pull in
different directions, the earlier one wins.

### 1. Secure by design

Security wins over every other principle, including less code. The browser
holds a session cookie, never a token. The app never sees a password.
Tokens are checked at sign-in and discarded. Every response carries a
strict Content Security Policy. Data the app does not use is not kept. The
reasons are in `services/api/AUTH.md`.

### 2. Mistakes are caught early, and seen clearly

A rule that a test, a type or a lint can enforce is enforced that way.
Settings have no defaults, and a piece that cannot start stops the process,
so whoever deployed the mistake finds it, not the first user. Every request
ends in an answer a person can act on, and one log line. See
`services/api/README.md`, "Configuration and startup" and "Logging".

### 3. Build on what exists

Where a spec covers a problem, follow it, and cite its section on the line
that meets it ("Standards", below). A choice rests on evidence: the tool's
own docs, how two or three comparable projects do it, and a trial in this
code. Use few tools, each fully, at current stable versions pinned in
files. Remove one when something else in the stack does its job better.
Record what was decided, including rejections, in `docs/decisions.md`.

### 4. Right shape, right place

Decide where code belongs and what form it takes before writing it, then
refactor until it reads plainly from top to bottom. Each fact has one
source: commands in the justfile, the TypeScript client generated from the
API. The example domain stays removable (`docs/adopting.md`, "Replacing the
example domain").

### 5. Written down, and kept true

Docs are for a capable newcomer: plain words, short sentences, the concrete
thing before the abstract one. A doc says what the code cannot: the idea,
the reason, the trade-off. A comment describes only the code beside it, and
never another part of the repo, because that goes stale when the other part
changes and nothing checks it. A link between parts that matters is
enforced by a test instead. Every doc link, cited section and `just`
command is checked.

### 6. A development loop you can hold in your head

One command (`just up`), one hostname (`localhost`), and one rule for what
reloads. Development runs the shape of production: one Dockerfile, one
origin, the same headers, so a bug in cookies, the CSP or routing shows up
on a developer's machine first. See `docs/adopting.md`, "Day to day".

## Standards

The design follows these specs. Code that meets a requirement cites its
section on that line, so a search for the section finds it.
`services/api/AUTH.md` goes through RFC 10017 §6.1 requirement by
requirement.

| Area | Spec |
|---|---|
| Architecture | [RFC 10017](https://www.rfc-editor.org/rfc/rfc10017.html) §6.1, OAuth 2.0 for Browser-Based Applications |
| OAuth security | [RFC 9700](https://www.rfc-editor.org/rfc/rfc9700.html), OAuth 2.0 Security Best Current Practice; [RFC 7636](https://www.rfc-editor.org/rfc/rfc7636), PKCE |
| Sign-in | [OpenID Connect Core 1.0](https://openid.net/specs/openid-connect-core-1_0.html) and [Discovery 1.0](https://openid.net/specs/openid-connect-discovery-1_0.html) |
| Sign-out | OpenID Connect [RP-Initiated](https://openid.net/specs/openid-connect-rpinitiated-1_0.html), [Back-Channel](https://openid.net/specs/openid-connect-backchannel-1_0.html) and [Front-Channel](https://openid.net/specs/openid-connect-frontchannel-1_0.html) Logout 1.0 |
| Client registration | [RFC 7591](https://www.rfc-editor.org/rfc/rfc7591) and [OpenID Connect Registration 1.0](https://openid.net/specs/openid-connect-registration-1_0.html) |
| Cookies | [RFC 6265bis](https://datatracker.ietf.org/doc/draft-ietf-httpbis-rfc6265bis/) and [layered cookies](https://datatracker.ietf.org/doc/draft-ietf-httpbis-layered-cookies/) (both drafts): `SameSite` and the `__Host-Http-` prefix |
| HTTP | [RFC 9110](https://www.rfc-editor.org/rfc/rfc9110), HTTP Semantics: status codes |
| Errors | [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457), Problem Details for HTTP APIs: the member names `status` and `detail` |
| Security headers | [CSP Level 3](https://www.w3.org/TR/CSP3/); [RFC 6797](https://www.rfc-editor.org/rfc/rfc6797), HSTS |
| API contract | [OpenAPI 3.1](https://spec.openapis.org/oas/v3.1.0) |
| Configuration | [The Twelve-Factor App](https://12factor.net/config), III: config in the environment |

What the template does not yet meet, and what it leaves out on purpose, are
listed in `docs/decisions.md`.
