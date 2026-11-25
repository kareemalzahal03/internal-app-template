# Testing the API

The tests run the real application in process, the whole stack minus the
network, against the `appdb_test` database in the Compose Mongo. A fake
identity provider answers in process too, so no provider runs in the tests
or in CI.

```sh
just test-api services/api/tests/core/auth/test_sign_in.py -k name   # one test
just test-api services/api/tests/core/auth                           # one folder
```

## Layout

The folders follow the app:

| Folder | Tests |
|---|---|
| `tests/` | Startup and the database |
| `tests/core/` | What every request passes through: errors, logging, the SPA, security headers |
| `tests/core/auth/` | Sign-in, sessions, sign-out, logout from the provider, and what the provider is told |
| `tests/domain/` | The example domain. A copy replaces it with its own |
| `tests/repo/` | The repo's other files: docs, the domain seam, the build |

The shared pieces sit at the top. `conftest.py` holds the fixtures,
`parties.py` the browser and the provider, and `helpers.py` what a test
calls directly. Each docstring says what it gives.

## How a test is written

**A test plays a browser.** It makes the SPA's API calls, which carry the
`X-CSRF` header, or navigates as the address bar does, following redirects
across the app and the provider. The `browser` fixture is signed in with a
real session cookie, not a dependency override, so every test also
exercises the cookie and the session lookup. A test that needs a second
person makes another browser.

**Some fixtures are always there, others are asked for.** The ones that are
always there are what the app depends on: its settings, the provider, the
network and the database. The others are who a test plays. Each test reads
its settings anew, so a test changes one with `monkeypatch.setenv` alone.

**A test changes the provider, not the app.** The fake provider is
registered with the app's own metadata, and checks what a real one does:
`state`, the nonce and PKCE make the round trip, and the client's signed
assertion is verified against the key the app serves. So a sign-in in a
test is a whole one. To test a failure, change what the provider's
discovery says, who signs in, which key signs, or whether it answers at
all. Patch the app's own code only when nothing outside it can cause the
case, such as the database failing mid-sign-in.

**Nothing leaves the process.** Every HTTP client made during a test,
Authlib's included, reaches only the app and the provider. Any other host
fails with an error naming it.

**An unhandled error is a 500, not an exception.** It comes back as a
browser would see it, and its traceback is in the logs, which pytest prints
for a failing test.

Test data uses `example.com`, which RFC 2606 reserves so examples never
reach a real domain. `email-validator` accepts it, but rejects other
reserved names such as `.test`.

The round trip against a real provider is checked by hand, with `just up`.
