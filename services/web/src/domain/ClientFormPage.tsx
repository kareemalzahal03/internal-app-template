import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useNavigate, useParams } from 'react-router'

import { ErrorAlert, QueryBoundary } from '../components/QueryBoundary'
import {
  createClientMutation,
  getClientOptions,
  updateClientMutation,
} from '../lib/api/@tanstack/react-query.gen'
import type { ClientOut, ClientStatus, Contact } from '../lib/api/types.gen'

/** Create and edit share this page: /clients/new renders the empty form,
 * /clients/:clientId/edit loads the client first and pre-fills it. */
export default function ClientFormPage() {
  const { clientId } = useParams<{ clientId: string }>()

  if (!clientId) return <ClientForm />

  return <EditClientLoader clientId={clientId} />
}

function EditClientLoader({ clientId }: { clientId: string }) {
  const query = useQuery(getClientOptions({ path: { client_id: clientId } }))
  return <QueryBoundary query={query}>{(client) => <ClientForm initial={client} />}</QueryBoundary>
}

// A contact as the form holds it: beside an id of its own, so React keeps
// each row's inputs with that row when another row is removed. Only the
// contact is sent.
type ContactRow = { rowId: string; contact: Contact }

function toRow(contact: Contact): ContactRow {
  return { rowId: crypto.randomUUID(), contact }
}

function ClientForm({ initial }: { initial?: ClientOut }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  // Plain controlled inputs on purpose: no form or validation library. The
  // backend is the single validator; anything it rejects comes back as a
  // 422/409 response that ErrorAlert renders below the form.
  const [name, setName] = useState(initial?.name ?? '')
  const [email, setEmail] = useState(initial?.email ?? '')
  const [status, setStatus] = useState<ClientStatus>(initial?.status ?? 'active')
  const [rows, setRows] = useState<ContactRow[]>(() => (initial?.contacts ?? []).map(toRow))

  // Two hooks rather than one with a ternary: create takes no path parameter
  // and update requires one, so the generated mutations have different
  // variable types that won't unify. Both are declared unconditionally (hooks
  // rules); only one is ever fired.
  const onSuccess = (saved: ClientOut) => {
    queryClient.invalidateQueries()
    navigate(`/clients/${saved.id}`)
  }
  const createMutation = useMutation({ ...createClientMutation(), onSuccess })
  const updateMutation = useMutation({ ...updateClientMutation(), onSuccess })
  const mutation = initial ? updateMutation : createMutation

  function setContactField(index: number, field: keyof Contact, value: string) {
    setRows(
      rows.map((row, i) =>
        i === index ? { ...row, contact: { ...row.contact, [field]: value } } : row,
      ),
    )
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const body = { name, email, status, contacts: rows.map((row) => row.contact) }
    if (initial) {
      updateMutation.mutate({ path: { client_id: initial.id }, body })
    } else {
      createMutation.mutate({ body })
    }
  }

  const inputClass =
    'rounded border border-gray-300 bg-white px-2 py-1 dark:border-gray-700 dark:bg-gray-900'

  return (
    <div className="max-w-xl">
      <h1 className="mb-4 text-xl font-semibold">
        {initial ? `Edit ${initial.name}` : 'New client'}
      </h1>
      {/* noValidate: the email field's type picks the phone keyboard, but the
          backend, not the browser, decides what is valid. */}
      <form onSubmit={handleSubmit} noValidate className="space-y-4 text-sm">
        <label className="flex flex-col gap-1">
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} className={inputClass} />
        </label>
        <label className="flex flex-col gap-1">
          Email
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className={inputClass}
          />
        </label>
        <label className="flex flex-col gap-1">
          Status
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value as ClientStatus)}
            className={inputClass}
          >
            <option value="active">active</option>
            <option value="inactive">inactive</option>
          </select>
        </label>

        <fieldset className="space-y-2">
          <legend className="mb-1 font-medium">Contacts</legend>
          {rows.map(({ rowId, contact }, i) => (
            <div key={rowId} className="flex items-center gap-2">
              <input
                placeholder="Name"
                value={contact.name}
                onChange={(e) => setContactField(i, 'name', e.target.value)}
                className={`${inputClass} w-40`}
              />
              <input
                placeholder="Role"
                value={contact.role}
                onChange={(e) => setContactField(i, 'role', e.target.value)}
                className={`${inputClass} w-36`}
              />
              <input
                placeholder="Phone"
                value={contact.phone}
                onChange={(e) => setContactField(i, 'phone', e.target.value)}
                className={`${inputClass} w-32`}
              />
              <button
                type="button"
                onClick={() => setRows(rows.filter((_, j) => j !== i))}
                className="text-xs text-red-600 hover:underline dark:text-red-400"
              >
                remove
              </button>
            </div>
          ))}
          <button
            type="button"
            onClick={() => setRows([...rows, toRow({ name: '', role: '', phone: '' })])}
            className="text-xs text-blue-600 hover:underline dark:text-blue-400"
          >
            + Add contact
          </button>
        </fieldset>

        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={mutation.isPending}
            className="rounded bg-blue-600 px-4 py-1.5 font-medium text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {initial ? 'Save changes' : 'Create client'}
          </button>
          <button
            type="button"
            onClick={() => navigate(-1)}
            className="rounded border border-gray-300 px-4 py-1.5 dark:border-gray-700"
          >
            Cancel
          </button>
        </div>
      </form>
      {mutation.isError && <ErrorAlert error={mutation.error} />}
    </div>
  )
}
