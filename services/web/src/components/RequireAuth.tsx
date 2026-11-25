import { Navigate, Outlet } from 'react-router'

import { useMe } from '../lib/auth'
import { Loading } from './QueryBoundary'

/** A layout route that renders its children only for a signed-in user.
 * It has no path of its own — it exists purely to wrap the routes it
 * guards. */
export default function RequireAuth() {
  const me = useMe()

  // The pending branch is load-bearing. On the first render the answer has
  // not arrived: falling through to <Outlet /> flashes a protected page
  // before redirecting, and falling through to the redirect bounces every
  // load — including a signed-in one — through /login.
  if (me.isPending) return <Loading />

  // replace, so the guarded URL does not stay in history: otherwise "back"
  // from the login page returns here and redirects forward again, which
  // looks like a broken back button.
  if (me.isError) return <Navigate to="/login" replace />

  return <Outlet />
}
