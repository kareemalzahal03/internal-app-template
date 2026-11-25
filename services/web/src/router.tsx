import { createBrowserRouter, type RouteObject } from 'react-router'

import Layout from './components/Layout'
import RequireAuth from './components/RequireAuth'
import RouteError from './components/RouteError'
import { routes as domainRoutes } from './domain/routes'
import LoginPage from './pages/LoginPage'

export const routes: RouteObject[] = [
  {
    // Every route sits under this one, so an unknown address or a crash
    // anywhere ends on its error page.
    ErrorBoundary: RouteError,
    children: [
      // Outside the guard, and outside Layout: signing in should not render
      // a header full of actions that need a session.
      { path: '/login', Component: LoginPage },
      {
        // A pathless route, so it adds a check without adding a URL segment.
        Component: RequireAuth,
        children: [
          {
            path: '/',
            Component: Layout,
            // The domain's pages.
            children: domainRoutes,
          },
        ],
      },
    ],
  },
]

export const router = createBrowserRouter(routes)
