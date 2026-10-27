import { useEffect, useState } from 'react'
import { getMlAdminStatus, type MlAdminStatus } from '@/services/api'

export default function AdminMl() {
  const [ml, setMl] = useState<MlAdminStatus | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getMlAdminStatus()
      .then(setMl)
      .catch(() => setError('Could not load ML administration status.'))
  }, [])

  if (error) return <div className="text-red-400 text-sm">{error}</div>
  if (!ml) return <div className="text-neutral-400 text-sm">Loading ML status…</div>

  return (
    <div className="space-y-4">
      <div className="abi-panel border border-neutral-800 rounded-lg p-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-medium">Model artifacts</h2>
          <span className="text-xs text-neutral-500">{ml.artifact_count} deployed</span>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm mb-4">
          <div>
            <div className="text-neutral-500 text-xs uppercase">Metadata entries</div>
            {ml.metadata_entries}
          </div>
          <div>
            <div className="text-neutral-500 text-xs uppercase">Training data</div>
            {ml.data_dir_exists ? 'present' : 'missing'}
          </div>
          <div className="col-span-2">
            <div className="text-neutral-500 text-xs uppercase">Retraining</div>
            {ml.retraining}
          </div>
        </div>

        {ml.artifacts.length > 0 ? (
          <table className="w-full text-sm">
            <thead className="text-neutral-500 text-xs uppercase">
              <tr>
                <th className="text-left py-1">Artifact</th>
                <th className="text-right py-1">Size</th>
                <th className="text-right py-1">Last modified</th>
              </tr>
            </thead>
            <tbody>
              {ml.artifacts.map((a) => (
                <tr key={a.file} className="border-t border-neutral-800">
                  <td className="py-1">{a.file}</td>
                  <td className="py-1 text-right">{(a.size_bytes / 1024).toFixed(1)} kB</td>
                  <td className="py-1 text-right">{a.modified_at.slice(0, 19).replace('T', ' ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="text-sm text-neutral-500">No trained artifacts found on disk.</div>
        )}
        <div className="text-xs text-neutral-500 mt-3">{ml.models_dir}</div>
      </div>

      <div className="abi-panel border border-neutral-800 rounded-lg p-4">
        <h2 className="font-medium mb-3">Deployment status</h2>
        <table className="w-full text-sm">
          <thead className="text-neutral-500 text-xs uppercase">
            <tr>
              <th className="text-left py-1">Feature</th>
              <th className="text-left py-1">Status</th>
              <th className="text-left py-1">Models</th>
            </tr>
          </thead>
          <tbody>
            {ml.features.map((f) => (
              <tr key={f.name} className="border-t border-neutral-800">
                <td className="py-1">{f.name}</td>
                <td className="py-1">{f.status}</td>
                <td className="py-1 text-neutral-500">
                  {f.models.map((m) => `${m.algorithm ?? '—'}${m.artifact_available ? '' : ' (no artifact)'}`).join(', ') || '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
