import { isRouteErrorResponse, useRouteError } from 'react-router'

/** The page for an address no route matches, or for a page that crashed
 * while rendering. Without it, React Router shows its own screen, written
 * for developers. */
export default function RouteError() {
  const error = useRouteError()
  // An unknown address arrives as a 404 response; anything else is a bug.
  const notFound = isRouteErrorResponse(error) && error.status === 404

  return (
    <div className="mx-auto mt-24 max-w-sm px-4">
      <h1 className="mb-4 text-xl font-semibold">
        {notFound ? 'Page not found' : 'Something went wrong'}
      </h1>
      <p className="mb-4 text-sm text-gray-500 dark:text-gray-400">
        {notFound
          ? 'There is nothing at this address.'
          : 'This page hit an error. Going back to the start usually helps.'}
      </p>
      {/* A full page load, not a router link: it starts the app afresh,
          clearing whatever state led to the crash. */}
      <a href="/" className="font-medium text-blue-600 hover:underline dark:text-blue-400">
        Go to the home page
      </a>
    </div>
  )
}
