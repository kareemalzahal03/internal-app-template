# dev-idp

The identity provider `just up` runs, so sign-in works on a laptop. The app
owns no passwords, so even development needs a provider to sign in
through. This one is [node-oidc-provider][], the OpenID Foundation's
certified reference implementation, configured in one file,
`src/provider.mjs`, to publish only what the app uses: sign-in with PKCE,
RP-initiated logout and back-channel logout. It is never deployed: a
deployed app signs in through the company's own provider.

## How it is set up

- **Its identity** is `.env.dev`: the issuer and the client id. Compose
  gives the same file to the API, so the two sides agree on which provider
  and which client this is.
- **Its client**, `src/client.json`, is generated from the app's own
  metadata by `just generate-dev-idp-client`, never written by hand. The
  app's private key stays with the app; the provider fetches only its public
  half, from the app's `jwks_uri`.
- **Its users are whoever you type.** Any username signs in as its own
  person: `bob` is named bob, with the email `bob@example.com`. Type the
  username alone, not an email address. The same username is the same
  person after every restart, so a private browser window signed in as
  someone else is a second user.
- **It reloads like the other services.** It runs under nodemon with `src/`
  mounted, so saving any file there restarts it in about a second. Only a
  change to its dependencies needs `just up`.
- **It is at `http://localhost:8080`**, the issuer in `.env.dev`, for the
  browser and the API alike.

## Why it is dev-only

Each of these is commented where it happens in `provider.mjs`:

- The login form never checks the password, and every username is a
  person. Anyone can sign in as anyone.
- Signing keys and sessions are in memory, and are new after every restart.
- Consent is granted without asking, because the app is the provider's own
  first party.
- Protection against calls to private addresses is off, because
  back-channel logout is a call to the app on `localhost`.

Fixing these would not make it deployable. Running a provider properly
takes a database, backups, upgrades and at least two instances, far more
than the app it serves, for a job the company's provider already does. The
app reads only the provider's discovery document, so moving to that
provider is the `OIDC_*` settings (`services/api/AUTH.md`, "Nothing is written
against the provider").

It does not implement front-channel logout, so
`/api/auth/frontchannel-logout` is covered by the API's tests only.

[node-oidc-provider]: https://github.com/panva/node-oidc-provider
