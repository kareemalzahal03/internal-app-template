const STYLES: Record<string, string> = {
  active: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
  inactive: 'bg-gray-200 text-gray-700 dark:bg-gray-800 dark:text-gray-300',
  draft: 'bg-gray-200 text-gray-700 dark:bg-gray-800 dark:text-gray-300',
  submitted: 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200',
  fulfilled: 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200',
}

export function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${STYLES[status] ?? ''}`}
    >
      {status}
    </span>
  )
}
