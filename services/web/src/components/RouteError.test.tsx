/** Both ways a visitor reaches the error page. The first runs the app's own
 * routes, so it also checks that the error page wraps all of them. */
import { render, screen } from '@testing-library/react'
import { createMemoryRouter, RouterProvider } from 'react-router'
import { expect, test, vi } from 'vitest'

import { routes } from '../router'
import RouteError from './RouteError'

test('an unknown address shows the not-found page', async () => {
  render(
    <RouterProvider router={createMemoryRouter(routes, { initialEntries: ['/no/such/page'] })} />,
  )
  expect(await screen.findByText('Page not found')).toBeInTheDocument()
})

test('a page that crashes shows the error page', async () => {
  // React reports the crash on the console; keep it out of the test output.
  vi.spyOn(console, 'error').mockImplementation(() => {})
  function Broken(): never {
    throw new Error('boom')
  }
  const router = createMemoryRouter([{ path: '/', Component: Broken, ErrorBoundary: RouteError }])

  render(<RouterProvider router={router} />)
  expect(await screen.findByText('Something went wrong')).toBeInTheDocument()
  vi.restoreAllMocks()
})
