import { useEffect, useState } from 'react'
import { getSystemStatus, getAdminHealth, type SystemStatus, type AdminHealthStatus } from '@/services/api'

export default function AdminHealth() {
  const [system, setSystem] = useState<SystemStatus | null>(null)
  const [health, setHealth] = useState<AdminHealthStatus | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = () => {
    Promise.all([getSystemStatus(), getAdminHealth()])
      .then(([s, h]) => {
        setSystem(s)
        setHealth(h)
      })
      .catch(() => setError('Could not load system health.'))
  }

  useEffect(() => {
    load()
  }, [])

  if (error) return <div className="text-red-400 text-sm">{error}</div>
  if (!system || !health) return <div className="text-neutral-400 text-sm">Loading system health…</div>

  return (
    <div className="space-y-4">
      <div className="flex justify-end mb-2">
        <button onClick={load} className="text-sm bg-neutral-800 hover:bg-neutral-700 px-3 py-1.5 rounded">
          Refresh
        </button>
      </div>

      <div className="abi-panel border border-neutral-800 rounded-lg p-4">
        <h2 className="font-medium mb-3">Service Health</h2>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4 text-sm">
          <div>
            <div className="text-neutral-500 text-xs uppercase mb-1">Backend</div>
            <div className="flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full ${health.backend === 'Healthy' ? 'bg-emerald-400' : 'bg-red-400'}`}></div>
              {health.backend}
            </div>
          </div>
          <div>
            <div className="text-neutral-500 text-xs uppercase mb-1">Database</div>
            <div className="flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full ${health.database === 'Healthy' ? 'bg-emerald-400' : 'bg-red-400'}`}></div>
              {health.database}
            </div>
          </div>
          <div>
            <div className="text-neutral-500 text-xs uppercase mb-1">Warehouse</div>
            <div className="flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full ${health.warehouse === 'Healthy' ? 'bg-emerald-400' : health.warehouse === 'Degraded' ? 'bg-amber-400' : 'bg-red-400'}`}></div>
              {health.warehouse}
            </div>
          </div>
          <div>
            <div className="text-neutral-500 text-xs uppercase mb-1">Authentication</div>
            <div className="flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full ${health.authentication === 'Healthy' ? 'bg-emerald-400' : 'bg-red-400'}`}></div>
              {health.authentication}
            </div>
          </div>
          <div>
            <div className="text-neutral-500 text-xs uppercase mb-1">ML Models</div>
            <div className="flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full ${health.ml_models.includes('Warning') ? 'bg-amber-400' : health.ml_models.startsWith('0') ? 'bg-red-400' : 'bg-emerald-400'}`}></div>
              {health.ml_models}
            </div>
          </div>
        </div>
      </div>

      <div className="abi-panel border border-neutral-800 rounded-lg p-4">
        <h2 className="font-medium mb-3">System Information</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
          <div>
            <div className="text-neutral-500 text-xs uppercase">App</div>
            {system.app} v{system.version}
          </div>
          <div>
            <div className="text-neutral-500 text-xs uppercase">Env</div>
            {system.env}
          </div>
          <div>
            <div className="text-neutral-500 text-xs uppercase">Database Config</div>
            {system.database}
          </div>
          <div>
            <div className="text-neutral-500 text-xs uppercase">Auth required</div>
            {String(system.auth_required)}
          </div>
          <div>
            <div className="text-neutral-500 text-xs uppercase">Python</div>
            {system.python}
          </div>
          <div className="col-span-2">
            <div className="text-neutral-500 text-xs uppercase">Platform</div>
            {system.platform}
          </div>
          <div>
            <div className="text-neutral-500 text-xs uppercase">Uptime</div>
            {Math.round(system.uptime_seconds)}s
          </div>
        </div>
      </div>

      <div className="abi-panel border border-neutral-800 rounded-lg p-4 text-sm text-neutral-500">
        Secrets (JWT signing key, database credentials, environment values) are deliberately not
        exposed here.
      </div>
    </div>
  )
}
