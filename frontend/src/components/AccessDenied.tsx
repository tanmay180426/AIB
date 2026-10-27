import { Link } from 'react-router-dom'

interface AccessDeniedProps {
  section?: string
}

export default function AccessDenied({ section }: AccessDeniedProps) {
  return (
    <div className="min-h-[50vh] flex items-center justify-center">
      <div className="max-w-md text-center space-y-3">
        <div className="text-4xl font-semibold tracking-tight">Access Restricted</div>
        <p className="text-neutral-400">You do not have permission to access this area.</p>
        <p className="text-sm text-neutral-500">
          {section ? `${section} is available only to Administrators.` : 'This section is available only to Administrators.'}
        </p>
        <Link
          to="/dashboard"
          className="inline-block mt-2 px-4 py-2 rounded bg-blue-600 hover:bg-blue-500 text-sm font-medium"
        >
          Back to Dashboard
        </Link>
      </div>
    </div>
  )
}
