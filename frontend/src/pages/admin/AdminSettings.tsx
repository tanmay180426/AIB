import { useEffect, useState } from 'react'
import { getSystemSettings, type SystemSettings } from '@/services/api'

export default function AdminSettings() {
  const [settings, setSettings] = useState<SystemSettings | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getSystemSettings()
      .then(setSettings)
      .catch(() => setError('Could not load system settings.'))
  }, [])

  if (error) return <div className="text-red-400 text-sm">{error}</div>
  if (!settings) return <div className="text-neutral-400 text-sm">Loading settings…</div>

  return (
    <div className="space-y-4">
      <div className="abi-panel border border-neutral-800 rounded-lg p-4">
        <h2 className="font-medium mb-3">Application</h2>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
          <div>
            <div className="text-neutral-500 text-xs uppercase">Version</div>
            {settings.app} v{settings.version}
          </div>
          <div>
            <div className="text-neutral-500 text-xs uppercase">Environment</div>
            {settings.env}
          </div>
          <div>
            <div className="text-neutral-500 text-xs uppercase">Auth required</div>
            {String(settings.auth_required)}
          </div>
          <div>
            <div className="text-neutral-500 text-xs uppercase">Roles</div>
            {settings.roles.join(', ')}
          </div>
          <div className="col-span-2">
            <div className="text-neutral-500 text-xs uppercase">Dataset</div>
            {settings.dataset}
          </div>
          <div>
            <div className="text-neutral-500 text-xs uppercase">Access token TTL</div>
            {settings.access_token_expire_minutes} min
          </div>
          <div>
            <div className="text-neutral-500 text-xs uppercase">Refresh token TTL</div>
            {settings.refresh_token_expire_minutes} min
          </div>
        </div>
      </div>

      <div className="abi-panel border border-neutral-800 rounded-lg p-4">
        <h2 className="font-medium mb-3">AI assistant</h2>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
          <div>
            <div className="text-neutral-500 text-xs uppercase">Enabled</div>
            {String(settings.llm.enabled)}
          </div>
          <div>
            <div className="text-neutral-500 text-xs uppercase">Provider</div>
            {settings.llm.provider}
          </div>
          <div>
            <div className="text-neutral-500 text-xs uppercase">Timeout</div>
            {settings.llm.timeout_seconds}s
          </div>
        </div>
      </div>

      <div className="abi-panel border border-neutral-800 rounded-lg p-4">
        <h2 className="font-medium mb-3">Reports enabled</h2>
        <div className="flex flex-wrap gap-2">
          {settings.reports.map((r) => (
            <span key={r} className="text-xs bg-neutral-800 rounded px-2 py-1">
              {r}
            </span>
          ))}
        </div>
      </div>

      <div className="abi-panel border border-neutral-800 rounded-lg p-4 text-sm text-neutral-500">
        Secrets are never returned by this endpoint: no signing keys, passwords, tokens or
        environment values are exposed.
      </div>
    </div>
  )
}
