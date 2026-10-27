import { useEffect, useState } from 'react'
import { getWarehouseStatus, type WarehouseStatus } from '@/services/api'

export default function AdminWarehouse() {
  const [wh, setWh] = useState<WarehouseStatus | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getWarehouseStatus()
      .then(setWh)
      .catch(() => setError('Could not load warehouse status.'))
  }, [])

  if (error) return <div className="text-red-400 text-sm">{error}</div>
  if (!wh) return <div className="text-neutral-400 text-sm">Loading warehouse status…</div>

  return (
    <div className="space-y-4">
      <div className="abi-panel border border-neutral-800 rounded-lg p-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-medium">Warehouse</h2>
          <span
            className={`text-xs uppercase ${wh.complete ? 'text-emerald-400' : 'text-amber-400'}`}
          >
            {wh.complete ? 'complete' : `${wh.loaded_tables}/${wh.expected_tables} tables`}
          </span>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm mb-4">
          <div>
            <div className="text-neutral-500 text-xs uppercase">Engine</div>
            {wh.dialect}
          </div>
          <div>
            <div className="text-neutral-500 text-xs uppercase">Tables loaded</div>
            {wh.loaded_tables} / {wh.expected_tables}
          </div>
          <div>
            <div className="text-neutral-500 text-xs uppercase">Rows</div>
            {wh.total_rows.toLocaleString()}
          </div>
          <div>
            <div className="text-neutral-500 text-xs uppercase">Schema objects</div>
            {wh.schema_tables.length}
          </div>
        </div>

        {wh.min_date && wh.max_date && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm mb-4 bg-neutral-800/30 p-3 rounded">
            <div>
              <div className="text-neutral-500 text-xs uppercase">Earliest Data</div>
              {new Date(wh.min_date).toLocaleDateString()}
            </div>
            <div>
              <div className="text-neutral-500 text-xs uppercase">Latest Data</div>
              {new Date(wh.max_date).toLocaleDateString()}
            </div>
            <div>
              <div className="text-neutral-500 text-xs uppercase">Freshness</div>
              {Math.floor((Date.now() - new Date(wh.max_date).getTime()) / (1000 * 60 * 60 * 24))} days ago
            </div>
          </div>
        )}

        <table className="w-full text-sm mt-4">
          <thead className="text-neutral-500 text-xs uppercase">
            <tr>
              <th className="text-left py-1">Business Entity</th>
              <th className="text-right py-1">Record Count</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(wh.warehouse_tables).map(([table, count]) => {
              const friendlyName = table
                .replace('fact_', '')
                .replace('dim_', '')
                .split('_')
                .map(word => word.charAt(0).toUpperCase() + word.slice(1))
                .join(' ')

              return (
                <tr key={table} className="border-t border-neutral-800">
                  <td className="py-1">{friendlyName}</td>
                  <td className="py-1 text-right">{count == null ? '—' : count.toLocaleString()}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      <div className="abi-panel border border-neutral-800 rounded-lg p-4 text-sm text-neutral-500">
        Schema objects: {wh.schema_tables.join(', ') || 'none'}
        <div className="mt-1">Reference warehouse source: {wh.source}</div>
      </div>
    </div>
  )
}
