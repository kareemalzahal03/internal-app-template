import type { RouteObject } from 'react-router'

import ClientDetailPage from './ClientDetailPage'
import ClientFormPage from './ClientFormPage'
import ClientListPage from './ClientListPage'

// The domain's pages, mounted under the signed-in layout at '/'.
export const routes: RouteObject[] = [
  { index: true, Component: ClientListPage },
  { path: 'clients/new', Component: ClientFormPage },
  { path: 'clients/:clientId', Component: ClientDetailPage },
  { path: 'clients/:clientId/edit', Component: ClientFormPage },
]
