import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'

import { QueryBoundary } from '../components/QueryBoundary'
import { listClientsOptions } from '../lib/api/@tanstack/react-query.gen'
import type { ClientStatus } from '../lib/api/types.gen'
import { StatusBadge } from './StatusBadge'

const PAGE_SIZE = 10

export default function ClientListPage() {
  const [status, setStatus] = useState<ClientStatus | ''>('')
  const [offset, setOffset] = useState(0)

  const query = useQuery({
    // queryKey and queryFn both come from the generated options — the key is
    // derived from these exact arguments, so changing a filter refetches.
    ...listClientsOptions({
      query: { status: status || null, limit: PAGE_SIZE, offset },
    }),
    // Keep the previous page on screen while the next one loads.
    placeholderData: keepPreviousData,
  })

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Clients</h1>
        <select
          value={status}
          onChange={(e) => {
            setStatus(e.target.value as ClientStatus | '')
            setOffset(0)
          }}
          className="rounded border border-gray-300 bg-white px-2 py-1 text-sm dark:border-gray-700 dark:bg-gray-900"
        >
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="inactive">Inactive</option>
        </select>
      </div>

      <QueryBoundary query={query}>
        {(page) => (
          <>
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr className="border-b border-gray-300 text-left text-gray-500 dark:border-gray-700 dark:text-gray-400">
                  <th className="py-2 pr-4 font-medium">Name</th>
                  <th className="py-2 pr-4 font-medium">Email</th>
                  <th className="py-2 pr-4 font-medium">Status</th>
                  <th className="py-2 font-medium">Contacts</th>
                </tr>
              </thead>
              <tbody>
                {page.items.map((client) => (
                  <tr
                    key={client.id}
                    className="border-b border-gray-200 hover:bg-gray-100 dark:border-gray-800 dark:hover:bg-gray-900"
                  >
                    <td className="py-2 pr-4">
                      <Link
                        to={`/clients/${client.id}`}
                        className="font-medium text-blue-600 hover:underline dark:text-blue-400"
                      >
                        {client.name}
                      </Link>
                    </td>
                    <td className="py-2 pr-4">{client.email}</td>
                    <td className="py-2 pr-4">
                      <StatusBadge status={client.status} />
                    </td>
                    <td className="py-2">{client.contacts.length}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {page.items.length === 0 && (
              <p className="py-8 text-center text-gray-500">No clients yet.</p>
            )}
            <div className="mt-4 flex items-center justify-between text-sm text-gray-500">
              <span>
                {page.total === 0
                  ? '0 clients'
                  : `${page.offset + 1}–${page.offset + page.items.length} of ${page.total}`}
              </span>
              <div className="flex gap-2">
                <button
                  onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                  disabled={page.offset === 0}
                  className="rounded border border-gray-300 px-2 py-1 disabled:opacity-40 dark:border-gray-700"
                >
                  Previous
                </button>
                <button
                  onClick={() => setOffset(offset + PAGE_SIZE)}
                  disabled={page.offset + page.items.length >= page.total}
                  className="rounded border border-gray-300 px-2 py-1 disabled:opacity-40 dark:border-gray-700"
                >
                  Next
                </button>
              </div>
            </div>
          </>
        )}
      </QueryBoundary>
    </div>
  )
}
