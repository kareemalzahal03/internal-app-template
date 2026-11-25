import { client } from './api/client.gen'
import type { ErrorModel } from './api/types.gen'

/**
 * A failed API call: the backend's detail as the message, the status, and the
 * body itself.
 *
 * `message` is always a string — it is what gets rendered, and the fallback
 * covers a failure with no parseable body at all. `body` is that response
 * unflattened, kept so a call site that knows which endpoint it called can
 * read fields a flattened string cannot carry. Generic because only that
 * call site knows the shape:
 *
 *     const { body } = error as ApiError<LoginError>
 *
 * That is a cast, not a check — nothing validates it at runtime — so it
 * belongs where the operation is known, never in shared code.
 */
export class ApiError<T = unknown> extends Error {
  readonly status: number
  readonly body: T

  constructor(message: string, status: number, body: T) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

// The generated query/mutation options request throwOnError, and the client
// then throws the raw parsed response body — a plain object, not an Error.
// TanStack Query stores whatever it is given, so this is not for its
// benefit: it is the UI's `instanceof Error` check, the stack trace, and
// every logger that assumes Error.
//
// Named rather than inline so installation can check whether it is already
// present. The status is what makes the 401 handling possible: it is only
// available here, on the response — the thrown body carries no status.
function toApiError(error: unknown, response: Response | undefined): ApiError {
  const body = error as ErrorModel | undefined
  return new ApiError(
    body?.detail ?? 'Something went wrong talking to the API.',
    response?.status ?? 0,
    // Passed through rather than picked apart: which shape it has depends on
    // the endpoint, and this interceptor is global — it cannot know which.
    error,
  )
}

/** Install the CSRF header and the error interceptor. Call once, before the first request. */
export function configureApiClient(): void {
  // The API refuses a signed-in call without it (RFC 10017 §6.1.3.3.2).
  client.setConfig({ headers: { 'X-CSRF': '1' } })
  if (client.interceptors.error.exists(toApiError)) return
  client.interceptors.error.use(toApiError)
}
