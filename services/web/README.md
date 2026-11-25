# web

The frontend: a single-page app built with Vite, React, TypeScript and
TanStack Query, styled with Tailwind. It talks only to its own API, through
a client generated from that API. This file explains how the pieces fit:
the generated client, one origin, errors, auth and server state.

## The generated API client

`src/lib/api/` is a TypeScript client generated from the backend's OpenAPI
schema. Never edit it by hand; it is rewritten on every run.

Hand-written `fetch` calls and interfaces are copies of what the backend
already knows, and copies drift: rename a field in a Pydantic DTO and a
hand-written interface still compiles. Generated, the backend's types are
the frontend's types, so the same rename breaks `tsc` on every line that
needs updating.

Pages never write a URL, a `fetch`, a `queryKey` or a `queryFn`. They spread
a generated options object into a TanStack hook:

```ts
const query = useQuery(listClientOrdersOptions({ path: { client_id: clientId } }))
```

The name comes from the route's `operation_id` (`list_client_orders`).

The schema and the client are committed, so a fresh clone builds without
Python or a running backend. When the API changes:

```
edit a router or DTO → `just generate-api` → fix the TypeScript errors → commit both
```

## One origin, in every mode

The browser talks to one origin in every environment, so there is no CORS
configuration anywhere. The generated client builds relative paths:
`listClients()` requests `/api/clients` from whatever origin served the
page, and the built bundle holds no hostname. Something then routes `/api`
to FastAPI:

| | Serves the page | Routes `/api` to FastAPI |
|---|---|---|
| Production | FastAPI itself | Nothing: same process |
| Dev (`just up`) | FastAPI itself, from a watch build | Nothing: same process |
| Dev, HMR (`just hmr`) | Vite's dev server, on the same `:8000` | Vite's `server.proxy`, to FastAPI on `:8001` |

Under `just hmr`, the page stays same-origin with its API, so cookies and
the provider's registered URLs work exactly as under `just up`. The proxy's
target has no `VITE_` prefix, because only prefixed variables are built
into the bundle, and anything built in is public. The proxy exists only in
the dev server: a `/api` path that works under `just hmr` but 404s from a
static host expected a proxy that is never built.

One origin is a requirement, not a preference. The session is a
`SameSite=Strict` cookie, and a different port is already a different
origin, so the cookie would not be sent. The usual FastAPI template can run
Vite and the API on two ports because it keeps a token in the browser
instead.

## Errors, end to end

Every backend error has a `status` and a `detail` sentence that can be
shown as it is (`services/api/README.md`, "Errors on the wire"). So the
frontend never has to branch on an error's shape.

The generated client throws the raw response body, a plain object, not an
`Error`. An interceptor turns it into an `ApiError`, carrying `message`
(the `detail`, always a string), `status`, and `body`, the response before
flattening. Without it, every error renders as `[object Object]`, and an
expired session never redirects, because nothing sees its status.

A call site that knows which endpoint it called can cast `body` to that
operation's generated error type, to read a field the sentence cannot
carry:

```ts
const { body } = mutation.error as ApiError<CreateClientError>
'fields' in body ? body.fields : {}
```

That cast is unchecked, so it belongs where the operation is known, never
in shared code.

The generated options declare a query's error as the response body type,
but what is thrown is an `ApiError`, so the error type cannot be trusted.
Pages wrap a query in `<QueryBoundary>` and write only the happy path;
mutations render `<ErrorAlert>` beside their form. An address no route
matches, or a page that throws while rendering, ends on one error page that
wraps every route.

There is no client-side validation and no form library. Forms are
controlled inputs with `useState`, and an invalid submission shows the
backend's own message.

## Auth

The session is an `HttpOnly` cookie, which JavaScript cannot read. The
reasons are in [services/api/AUTH.md](../api/AUTH.md); what follows is what that
means for the frontend.

- **No token, ever.** Nothing goes in `localStorage`, and no
  `Authorization` header is built. The browser sends the cookie because
  every request is same-origin. The client adds one fixed header,
  `X-CSRF: 1`, to every call.
- **Auth state is server state.** The frontend cannot tell it is signed in
  without asking, so the answer is one TanStack query, `useMe()`. It
  succeeds when signed in and 401s when not. There is no auth context or
  store.
- **Signing in and out are navigations.** The browser has to visit the
  provider itself, so neither is a `fetch`, and neither is in the generated
  client. Sign-in always lands on `/`. Because the page reloads at both
  ends, nothing in the query cache survives from one user to the next.
- **Guarded pages wait for the answer.** While the session query is
  pending they show a loading state; redirecting or rendering early would
  either bounce every load through the login page or flash a guarded page.
- **A tab left open outlives its session.** Any 401 makes the session query
  ask again; when it fails, the guard sends the person to the login page.
  That is the only redirect path.

The cookie is `Secure`. Browsers exempt `http://localhost`, but reach the
dev server by a LAN address or a `.local` name and the cookie is dropped:
sign-in completes at the provider, then lands back on the sign-in page.

## Server state lives in TanStack Query

All server data is TanStack Query: fetching, caching, mutations and
invalidation. There is no Redux, Zustand or context store, because nearly
all "global state" here is a cache of what the server owns. Local UI state,
such as a form's values, stays in `useState`.

Mutations invalidate the whole cache, refetching every mounted query.
Generated keys are per operation, so "everything about this client" is not
one key prefix. Invalidating everything is cheap at this size. A larger app
would turn on the generator's `queryKeys: { tags: true }` and invalidate by
tag.

## Testing

Vitest and Testing Library, with each test beside the file it covers:
`*.test.ts` and `*.test.tsx`. Page tests mock the generated SDK and render
with a `QueryClientProvider`.
