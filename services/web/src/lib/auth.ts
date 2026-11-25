import { useQuery, type QueryClient } from '@tanstack/react-query'

import { ApiError } from './api-client'
import { getMeOptions, getMeQueryKey } from './api/@tanstack/react-query.gen'

// The session cookie is HttpOnly, so JavaScript cannot read it and the
// frontend has no local copy of "am I signed in". The server is the only one
// who knows, which makes auth state *server* state — so it lives in TanStack
// Query like everything else, and there is no auth context or store.
//
//   query succeeds -> signed in, and its data is the user
//   query 401s     -> signed out
//
// Nothing attaches the cookie by hand: fetch sends it because every request
// is same-origin.

/** The signed-in user, or an error if there isn't one. */
export function useMe() {
  return useQuery({
    ...getMeOptions(),
    // A 401 is an answer, not a failure.
    retry: false,
    staleTime: 5 * 60_000,
  })
}

/** Sign out: a full-page navigation, the mirror image of signing in.
 *
 * Not a mutation, and not a `fetch`. Ending the session at the identity
 * provider means the *browser* has to go there — only a top-level navigation
 * carries the provider's own cookies, and a `fetch` would follow the server's
 * redirect invisibly, cross-origin, with nothing to show for it. The server
 * revokes the local session and redirects on from there.
 *
 * Nothing clears the query cache, because nothing survives to need clearing:
 * this tears down the page, the query client and the whole JS heap.
 */
export function signOut(): void {
  window.location.href = '/api/auth/logout'
}

/** Is this the cache entry that fetches /auth/me? */
function isMeQueryKey(queryKey: readonly unknown[]): boolean {
  // Matched on the operation id alone: the generated key also carries the client's
  // baseUrl, and comparing that would tie this check to when the key was built.
  return (queryKey[0] as { _id?: string } | undefined)?._id === getMeQueryKey()[0]._id
}

/** Handle when a request returns ApiError 401. */
export function handleUnauthorized(
  queryClient: QueryClient,
  error: unknown,
  query?: { queryKey: readonly unknown[] },
): void {
  if (!(error instanceof ApiError && error.status === 401)) return
  // A 401 from the session check is its answer: signed out.
  if (query && isMeQueryKey(query.queryKey)) return
  // Any other 401 means the session may have ended, so check it again.
  void queryClient.invalidateQueries({ queryKey: getMeQueryKey() })
}
