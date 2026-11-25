import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
/** One test to establish the wiring: mock the generated SDK module — which
 * is what the generated query options call into — render the page inside
 * real Query + Router providers, and assert data reaches the table. More
 * page tests would follow this exact shape. */
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { expect, test, vi } from 'vitest'

import ClientListPage from './ClientListPage'

vi.mock('../lib/api/sdk.gen', () => ({
  listClients: vi.fn().mockResolvedValue({
    data: {
      items: [
        {
          id: 'abc123',
          name: 'Client A',
          email: 'ops@example.com',
          status: 'active',
          contacts: [{ name: 'Jo', role: 'AP', phone: '555' }],
          created_at: '2026-01-01T00:00:00Z',
          updated_at: '2026-01-01T00:00:00Z',
        },
      ],
      total: 1,
      limit: 10,
      offset: 0,
    },
    error: undefined,
    response: new Response(),
  }),
}))

test('renders clients returned by the API', async () => {
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <MemoryRouter>
        <ClientListPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )

  expect(await screen.findByText('Client A')).toBeInTheDocument()
  expect(screen.getByText('ops@example.com')).toBeInTheDocument()
  expect(screen.getByText('1–1 of 1')).toBeInTheDocument()
})
