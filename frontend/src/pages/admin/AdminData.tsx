import { useEffect, useState } from 'react'
import { getEtlStatus, type EtlStatus } from '@/services/api'

export default function AdminData() {
  const [etl, setEtl] = useState<EtlStatus | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getEtlStatus()
      .then(setEtl)
      .catch(() => setError('Could not load ETL status.'))
  }, [])

  if (error) return <div className="text-red-400 text-sm">{error}</div>
  if (!etl) return <div className="text-neutral-400 text-sm">Loading ETL status…</div>

  return (
    <div className="space-y-4">
      <div className="abi-panel border border-neutral-800 rounded-lg p-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-medium">Data pipeline / ETL</h2>
          <span className={`text-xs uppercase ${etl.loaded ? 'text-emerald-400' : 'text-amber-400'}`}>
            {etl.loaded ? 'loaded' : 'not loaded'}
          </span>
        </div>
        <table className="w-full text-sm">
          <thead className="text-neutral-500 text-xs uppercase">
            <tr>
              <th className="text-left py-1">Table</th>
              <th className="text-right py-1">Rows</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(etl.tables).map(([table, count]) => (
              <tr key={table} className="border-t border-neutral-800">
                <td className="py-1">{table}</td>
                <td className="py-1 text-right">{count == null ? '—' : count.toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="text-xs text-neutral-500 mt-3">Reference warehouse source: {etl.olist_dir}</div>
      </div>

      <div className="abi-panel border border-neutral-800 rounded-lg p-4 text-sm text-neutral-500">
        Status only — re-running the pipeline is an offline operation:{' '}
        <code className="text-neutral-300">python -m app.services.etl</code>
      </div>
    </div>
  )
}
