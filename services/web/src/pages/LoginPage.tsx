import { useSearchParams } from 'react-router'

import { ErrorAlert } from '../components/QueryBoundary'

/** The page an anonymous visitor is sent to, without the app header.
 *
 * There is no form here, and no call to the generated client. Signing in
 * happens at the identity provider, so the button is a full-page navigation.
 */
export default function LoginPage() {
  const [params] = useSearchParams()

  function signIn() {
    window.location.href = '/api/auth/login'
  }

  return (
    <div className="mx-auto mt-24 max-w-sm px-4">
      <h1 className="mb-4 text-xl font-semibold">Sign in</h1>
      <p className="mb-4 text-sm text-gray-500 dark:text-gray-400">
        You'll be redirected to your identity provider.
      </p>
      <button
        type="button"
        onClick={signIn}
        className="w-full rounded bg-blue-600 px-4 py-1.5 font-medium text-white hover:bg-blue-700"
      >
        Continue
      </button>
      {/* A sign-in that failed at the provider comes back as a redirect, not
          as a failed fetch, so the reason arrives in the query string. It is
          rendered through the same ErrorAlert as any other failure. */}
      {params.has('error') && <ErrorAlert error={SIGN_IN_FAILED} />}
    </div>
  )
}

// One message for every code: trying again is all a visitor can do.
const SIGN_IN_FAILED = new Error('That sign-in did not complete. Please try again.')
