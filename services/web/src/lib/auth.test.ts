/** The 401 policy, including the guard that keeps it from looping. Tested
 * because both failure modes are silent: a broken guard is an unbounded
 * refetch of /auth/me, and a guard that matches everything is an expired
 * session that never redirects. Neither shows up in a type error. */
import { QueryClient } from '@tanstack/react-query'
import { expect, test, vi } from 'vitest'

import { ApiError } from './api-client'
import { getMeQueryKey } from './api/@tanstack/react-query.gen'
import { handleUnauthorized } from './auth'

/** The key of some query that is not the session's. */
const anotherQueryKey = [{ _id: 'anotherQuery' }]

/** A 401 shaped the way the interceptor builds one. */
const unauthorized = () =>
  new ApiError('Unauthorized', 401, { status: 401, detail: 'Unauthorized' })

function spyOnInvalidate() {
  const queryClient = new QueryClient()
  const invalidate = vi.spyOn(queryClient, 'invalidateQueries').mockResolvedValue()
  return { queryClient, invalidate }
}

test('a 401 elsewhere re-checks the session', () => {
  const { queryClient, invalidate } = spyOnInvalidate()

  handleUnauthorized(queryClient, unauthorized(), {
    queryKey: anotherQueryKey,
  })

  expect(invalidate).toHaveBeenCalledWith({ queryKey: getMeQueryKey() })
})

test('a 401 from the session query itself is ignored', () => {
  const { queryClient, invalidate } = spyOnInvalidate()

  handleUnauthorized(queryClient, unauthorized(), {
    queryKey: getMeQueryKey(),
  })

  // Re-checking here would fail again and re-check again, without end.
  expect(invalidate).not.toHaveBeenCalled()
})

test('the session query is matched by operation id, not by baseUrl', () => {
  const { queryClient, invalidate } = spyOnInvalidate()
  // A key built when the client was configured differently is still the
  // session query. Comparing whole keys would miss this and loop.
  const key = [{ ...getMeQueryKey()[0], baseUrl: 'https://elsewhere.example' }]

  handleUnauthorized(queryClient, unauthorized(), { queryKey: key })

  expect(invalidate).not.toHaveBeenCalled()
})

test('a mutation 401 re-checks the session', () => {
  const { queryClient, invalidate } = spyOnInvalidate()

  // Mutations have no cache key, so they arrive without a query.
  handleUnauthorized(queryClient, unauthorized())

  expect(invalidate).toHaveBeenCalledWith({ queryKey: getMeQueryKey() })
})

test.each([
  ['a non-401 ApiError', new ApiError('Not found', 404, { status: 404, detail: 'Not found' })],
  ['a plain Error', new Error('network down')],
  ['a thrown non-error', 'nope'],
])('%s leaves the session alone', (_label, error) => {
  const { queryClient, invalidate } = spyOnInvalidate()

  handleUnauthorized(queryClient, error, { queryKey: anotherQueryKey })

  expect(invalidate).not.toHaveBeenCalled()
})
