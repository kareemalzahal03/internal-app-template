import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'

import { ErrorAlert, QueryBoundary } from '../components/QueryBoundary'
import {
  createOrderMutation,
  deleteClientMutation,
  deleteOrderMutation,
  getClientOptions,
  listClientOrdersOptions,
} from '../lib/api/@tanstack/react-query.gen'
import type { OrderStatus } from '../lib/api/types.gen'
import { StatusBadge } from './StatusBadge'

export default function ClientDetailPage() {
  const { clientId } = useParams<{ clientId: string }>()
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const clientQuery = useQuery(getClientOptions({ path: { client_id: clientId! } }))
  const ordersQuery = useQuery(
    listClientOrdersOptions({ path: { client_id: clientId! }, query: { limit: 50 } }),
  )

  // Mutations invalidate the whole cache rather than naming keys: generated
  // query keys are per-operation, so "everything about this client" isn't a
  // single key. Refetching every mounted query is cheap at this size and
  // impossible to get wrong.
  const deleteClient = useMutation({
    ...deleteClientMutation(),
    onSuccess: () => {
      queryClient.invalidateQueries()
      navigate('/')
    },
  })
  const deleteOrder = useMutation({
    ...deleteOrderMutation(),
    onSuccess: () => queryClient.invalidateQueries(),
  })

  return (
    <QueryBoundary query={clientQuery}>
      {(client) => (
        <div className="space-y-8">
          <div className="flex items-start justify-between">
            <div>
              <h1 className="text-xl font-semibold">{client.name}</h1>
              <p className="text-sm text-gray-500">{client.email}</p>
              <div className="mt-1">
                <StatusBadge status={client.status} />
              </div>
            </div>
            <div className="flex gap-2">
              <Link
                to={`/clients/${client.id}/edit`}
                className="rounded border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-100 dark:border-gray-700 dark:hover:bg-gray-900"
              >
                Edit
              </Link>
              <button
                onClick={() => {
                  if (window.confirm('Delete this client and all of its orders?')) {
                    deleteClient.mutate({ path: { client_id: clientId! } })
                  }
                }}
                className="rounded border border-red-300 px-3 py-1.5 text-sm text-red-700 hover:bg-red-50 dark:border-red-800 dark:text-red-400 dark:hover:bg-red-950"
              >
                Delete
              </button>
            </div>
          </div>
          {deleteClient.isError && <ErrorAlert error={deleteClient.error} />}

          <section>
            <h2 className="mb-2 font-medium">Contacts</h2>
            {client.contacts.length === 0 ? (
              <p className="text-sm text-gray-500">No contacts.</p>
            ) : (
              <ul className="space-y-1 text-sm">
                {client.contacts.map((contact, i) => (
                  <li key={i}>
                    <span className="font-medium">{contact.name}</span>
                    <span className="text-gray-500">
                      {' '}
                      — {contact.role}, {contact.phone}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section>
            <h2 className="mb-2 font-medium">Orders</h2>
            {deleteOrder.isError && <ErrorAlert error={deleteOrder.error} />}
            <QueryBoundary query={ordersQuery}>
              {(page) => (
                <table className="w-full border-collapse text-sm">
                  <thead>
                    <tr className="border-b border-gray-300 text-left text-gray-500 dark:border-gray-700 dark:text-gray-400">
                      <th className="py-2 pr-4 font-medium">Description</th>
                      <th className="py-2 pr-4 font-medium">Qty</th>
                      <th className="py-2 pr-4 font-medium">Unit price</th>
                      <th className="py-2 pr-4 font-medium">Status</th>
                      <th className="py-2 pr-4 font-medium">Created</th>
                      <th className="py-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {page.items.map((order) => (
                      <tr key={order.id} className="border-b border-gray-200 dark:border-gray-800">
                        <td className="py-2 pr-4">{order.description}</td>
                        <td className="py-2 pr-4">{order.quantity}</td>
                        <td className="py-2 pr-4">${order.unit_price.toFixed(2)}</td>
                        <td className="py-2 pr-4">
                          <StatusBadge status={order.status} />
                        </td>
                        <td className="py-2 pr-4">
                          {new Date(order.created_at).toLocaleDateString()}
                        </td>
                        <td className="py-2 text-right">
                          <button
                            onClick={() => deleteOrder.mutate({ path: { order_id: order.id } })}
                            className="text-xs text-red-600 hover:underline dark:text-red-400"
                          >
                            delete
                          </button>
                        </td>
                      </tr>
                    ))}
                    {page.items.length === 0 && (
                      <tr>
                        <td colSpan={6} className="py-4 text-center text-gray-500">
                          No orders yet.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              )}
            </QueryBoundary>
          </section>

          <NewOrderForm clientId={client.id} />
        </div>
      )}
    </QueryBoundary>
  )
}

function NewOrderForm({ clientId }: { clientId: string }) {
  const queryClient = useQueryClient()
  const [description, setDescription] = useState('')
  const [quantity, setQuantity] = useState('1')
  const [unitPrice, setUnitPrice] = useState('')
  const [status, setStatus] = useState<OrderStatus>('draft')

  const mutation = useMutation({
    ...createOrderMutation(),
    onSuccess: () => {
      queryClient.invalidateQueries()
      setDescription('')
      setQuantity('1')
      setUnitPrice('')
      setStatus('draft')
    },
  })

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    mutation.mutate({
      body: {
        client_id: clientId,
        description,
        // Sent as typed by the user; the backend is the validator, and its
        // 422 detail is what ErrorAlert renders below.
        quantity: Number(quantity),
        unit_price: Number(unitPrice),
        status,
      },
    })
  }

  return (
    <section>
      <h2 className="mb-2 font-medium">New order</h2>
      <form onSubmit={handleSubmit} className="flex flex-wrap items-end gap-3 text-sm">
        <label className="flex flex-col gap-1">
          Description
          <input
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            className="w-56 rounded border border-gray-300 bg-white px-2 py-1 dark:border-gray-700 dark:bg-gray-900"
          />
        </label>
        <label className="flex flex-col gap-1">
          Quantity
          <input
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            className="w-20 rounded border border-gray-300 bg-white px-2 py-1 dark:border-gray-700 dark:bg-gray-900"
          />
        </label>
        <label className="flex flex-col gap-1">
          Unit price
          <input
            value={unitPrice}
            onChange={(e) => setUnitPrice(e.target.value)}
            className="w-24 rounded border border-gray-300 bg-white px-2 py-1 dark:border-gray-700 dark:bg-gray-900"
          />
        </label>
        <label className="flex flex-col gap-1">
          Status
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as OrderStatus)}
            className="rounded border border-gray-300 bg-white px-2 py-1 dark:border-gray-700 dark:bg-gray-900"
          >
            <option value="draft">draft</option>
            <option value="submitted">submitted</option>
            <option value="fulfilled">fulfilled</option>
          </select>
        </label>
        <button
          type="submit"
          disabled={mutation.isPending}
          className="rounded bg-blue-600 px-3 py-1.5 font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          Add order
        </button>
      </form>
      {mutation.isError && <ErrorAlert error={mutation.error} />}
    </section>
  )
}
