import { Link, Outlet } from 'react-router'

import Nav from '../domain/Nav'
import { signOut, useMe } from '../lib/auth'

export default function Layout() {
  const me = useMe()

  return (
    <div className="min-h-screen">
      <header className="border-b border-gray-200 bg-white dark:border-gray-800 dark:bg-gray-900">
        <div className="mx-auto flex max-w-4xl items-center justify-between px-4 py-3">
          <Link to="/" className="text-lg font-semibold">
            Internal App
          </Link>
          <div className="flex items-center gap-3 text-sm">
            <Nav />
            {/* email first, name as the fallback: both claims are optional
                in OIDC and a provider may send either, neither or both. */}
            <span className="text-gray-500 dark:text-gray-400">
              {me.data?.email ?? me.data?.name}
            </span>
            <button
              type="button"
              onClick={signOut}
              className="rounded border border-gray-300 px-3 py-1.5 dark:border-gray-700"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-4xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  )
}
