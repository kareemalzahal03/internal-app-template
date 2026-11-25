import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
/** The guard's two outcomes. Worth testing where the page tests aren't:
 * a wrong branch here doesn't fail loudly, it either flashes protected
 * content or makes the whole app unreachable. Mocks the generated SDK and
 * renders in real providers. */
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { expect, test, vi } from 'vitest'

import { getMe } from '../lib/api/sdk.gen'
import RequireAuth from './RequireAuth'

vi.mock('../lib/api/sdk.gen', () => ({ getMe: vi.fn() }))

function renderGuarded() {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter initialEntries={['/secret']}>
        <Routes>
          <Route element={<RequireAuth />}>
            <Route path="/secret" element={<p>protected</p>} />
          </Route>
          <Route path="/login" element={<p>sign in</p>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

test('renders the guarded route for a signed-in user', async () => {
  vi.mocked(getMe).mockResolvedValue({
    data: { id: 'u1', email: 'admin@example.com' },
    response: new Response(),
    // Cast: the SDK's return type is wider than this test needs.
  } as never)

  renderGuarded()
  expect(await screen.findByText('protected')).toBeInTheDocument()
})

test('redirects to the login page when the session query fails', async () => {
  vi.mocked(getMe).mockRejectedValue(new Error('Unauthorized'))

  renderGuarded()
  expect(await screen.findByText('sign in')).toBeInTheDocument()
  // The point of the pending branch: the guarded route must never have
  // rendered on the way to the redirect.
  expect(screen.queryByText('protected')).not.toBeInTheDocument()
})
