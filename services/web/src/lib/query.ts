import { MutationCache, QueryCache, QueryClient } from '@tanstack/react-query'

import { handleUnauthorized } from './auth'

// Annotated explicitly: the handlers below close over queryClient, so its
// type cannot be inferred from its own initializer.
export const queryClient: QueryClient = new QueryClient({
  // Cache-level handlers, so an expired session is caught wherever it
  // surfaces rather than once per page. Both caches route their failures to
  // the 401 handler, which decides what a 401 means.
  queryCache: new QueryCache({
    onError: (error, query) => handleUnauthorized(queryClient, error, query),
  }),
  mutationCache: new MutationCache({
    onError: (error) => handleUnauthorized(queryClient, error),
  }),
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 30_000,
    },
  },
})
