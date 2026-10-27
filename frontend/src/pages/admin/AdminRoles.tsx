import { useEffect, useState } from 'react'
import { getRoleMetadata, type RoleMetadata } from '@/services/api'

export default function AdminRoles() {
  const [roles, setRoles] = useState<RoleMetadata[]>([])
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getRoleMetadata()
      .then((r) => {
        setRoles(r.roles)
        setState('ready')
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Could not load roles.')
        setState('error')
      })
  }, [])

  if (state === 'loading') return <div className="text-neutral-400 text-sm">Loading roles…</div>
  if (state === 'error') return <div className="text-red-400 text-sm">{error}</div>

  return (
    <div className="space-y-6">
      <p className="text-neutral-400 text-sm max-w-none">
        The platform operates on a strict two-role model. Viewer does not exist.
        Administrative operations are securely protected by the backend.
      </p>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {roles.map((r) => (
          <div key={r.name} className="abi-panel border border-neutral-800 rounded-lg p-5">
            <h2 className="text-lg font-semibold uppercase tracking-wide text-neutral-200 mb-2">
              <span className={r.name === 'admin' ? 'text-amber-400' : 'text-emerald-400'}>
                {r.name}
              </span>
            </h2>
            <p className="text-sm text-neutral-400 mb-4 h-10">{r.description}</p>

            <div className="text-sm border-t border-neutral-800 pt-3">
              <h3 className="font-medium text-neutral-300 mb-2">Effective Permissions</h3>
              <ul className="space-y-1">
                {Object.entries(r.permissions).map(([perm, granted]) => (
                  <li key={perm} className="flex items-center justify-between py-1 border-b border-neutral-800/50 last:border-0">
                    <span className="text-neutral-400">{perm}</span>
                    {granted ? (
                      <span className="text-emerald-400 font-medium">✓</span>
                    ) : (
                      <span className="text-neutral-600 font-medium">✗</span>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
