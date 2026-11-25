/** What configureApiClient installs, which nothing type-checks the presence
 * of. Without the error interceptor every failure reaches the UI as a raw
 * object: an `instanceof Error` check misses, the page renders
 * "[object Object]", and the 401 handling never sees a status, so an
 * expired session never redirects. Without the CSRF header every signed-in
 * call is a 403. All of these are silent to the compiler. */
import { expect, test } from 'vitest'

import { ApiError, configureApiClient } from './api-client'
import { client } from './api/client.gen'
import { getMe } from './api/sdk.gen'

const BODY = { status: 422, detail: 'email: value is not a valid email address' }

/** Drive the client's real error path with a stubbed fetch. An absolute
 * baseUrl only because Node's Request constructor rejects relative URLs —
 * the browser resolves them against the document, which is the whole point
 * of the relative-path test below. */
async function failWithRaw(status: number, text: string, contentType = 'application/json') {
  configureApiClient()
  return await client.request({
    baseUrl: 'https://test',
    method: 'GET',
    url: '/api/clients',
    fetch: async () => new Response(text, { status, headers: { 'Content-Type': contentType } }),
  })
}

const failWith = (status: number, body: unknown = BODY) => failWithRaw(status, JSON.stringify(body))

test('the generated client needs no configuration to build relative URLs', () => {
  // Set when the client is generated, so there is no window in which the
  // client exists pointing at the schema filename.
  expect(client.buildUrl({ url: '/api/clients' })).toBe('/api/clients')
})

test('a failed response arrives as an ApiError carrying the status', async () => {
  const { error } = await failWith(422)

  expect(error).toBeInstanceOf(ApiError)
  expect((error as ApiError).message).toBe(BODY.detail)
  expect((error as ApiError).status).toBe(422)
})

test('the response body survives on the error', async () => {
  // Flattening to `detail` is lossy by design; `body` is what lets a call
  // site read a field the sentence cannot carry.
  const { error } = await failWith(422)

  expect((error as ApiError).body).toEqual(BODY)
})

test('an unparseable body is still kept as-is', async () => {
  // Not every failure is JSON. Whatever arrived is preserved rather than
  // silently replaced, so a call site can tell "no detail" from "no body".
  const { error } = await failWithRaw(502, '502 Bad Gateway', 'text/plain')

  expect((error as ApiError).body).toBe('502 Bad Gateway')
  expect((error as ApiError).message).toBe('Something went wrong talking to the API.')
})

test('a body without a detail still produces a renderable one', async () => {
  const { error } = await failWith(500, {})

  expect((error as ApiError).message).toBe('Something went wrong talking to the API.')
})

test('a generated call sends the CSRF header', async () => {
  // Without it the API answers every signed-in call with a 403.
  configureApiClient()
  let sent: Request | undefined
  await getMe({
    baseUrl: 'https://test',
    fetch: async (input) => {
      sent = new Request(input)
      return Response.json({})
    },
  })

  expect(sent?.headers.get('X-CSRF')).toBe('1')
})

test('configuring twice does not stack interceptors', async () => {
  // A second interceptor would receive the first's ApiError instead of a
  // response body, and flatten every message to the fallback.
  configureApiClient()
  configureApiClient()
  const { error } = await failWith(422)

  expect((error as ApiError).message).toBe(BODY.detail)
})
