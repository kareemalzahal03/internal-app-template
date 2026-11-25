import { Link } from 'react-router'

// The domain's actions in the header, before the account display.
export default function Nav() {
  return (
    <Link
      to="/clients/new"
      className="rounded bg-blue-600 px-3 py-1.5 font-medium text-white hover:bg-blue-700"
    >
      New client
    </Link>
  )
}
