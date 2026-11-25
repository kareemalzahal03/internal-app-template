import type { UseQueryResult } from '@tanstack/react-query'
import type { ReactNode } from 'react'

/** The one loading/error pattern used by every page. Pages wrap their
 * queries in <QueryBoundary> and only ever render the happy path. */

export function Loading() {
  return <p className="p-8 text-center text-gray-500 dark:text-gray-400">Loading…</p>
}

export function ErrorAlert({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : String(error)
  return (
    <div
      role="alert"
      className="my-2 rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200"
    >
      {message}
    </div>
  )
}

// Generic over the error type because the generated query options declare it
// as the response body type (ErrorModel), while the client's error
// interceptor actually throws an ApiError. ErrorAlert handles either.
export function QueryBoundary<T, E>({
  query,
  children,
}: {
  query: UseQueryResult<T, E>
  children: (data: T) => ReactNode
}) {
  if (query.isPending) return <Loading />
  if (query.isError) return <ErrorAlert error={query.error} />
  return <>{children(query.data)}</>
}
