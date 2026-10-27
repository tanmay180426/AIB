import { useEffect, useState } from 'react'
import { getFilterOptions, type FilterOptions } from '@/services/api'
import { useFilters } from '@/hooks/useFilters'

const legacyFields = [
  ['category', 'Category', 'categories'], ['customer_state', 'Customer State', 'customer_states'],
  ['seller_state', 'Seller State', 'seller_states'], ['order_status', 'Order Status', 'order_statuses'],
  ['payment_type', 'Payment Type', 'payment_types'], ['review_score', 'Review Score', 'review_scores'],
] as const
const inputClass = 'bg-neutral-950 border border-neutral-800 rounded px-2 py-1.5 text-sm max-w-[180px]'

export default function FilterBar({ showGrain = false }: { showGrain?: boolean }) {
  const { filters, setFilters, resetFilters } = useFilters()
  const [options, setOptions] = useState<FilterOptions | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let current = true
    getFilterOptions().then(value => { if (current) setOptions(value) }).catch(e => { if (current) setError(e.message) })
    return () => { current = false }
  }, [])
  if (error) return <p role="alert" className="text-red-400">{error}</p>
  if (!options) return <div role="status" className="h-14 flex items-center text-sm text-neutral-400">Loading filters…</div>
  let columnFilters: Record<string, string> = {}
  try { columnFilters = JSON.parse(filters.column_filters || '{}') } catch { /* malformed URL is rejected by the API */ }
  const setColumn = (field: string, value: string) => {
    const next = { ...columnFilters }
    if (value) next[field] = value
    else delete next[field]
    setFilters({ column_filters: Object.keys(next).length ? JSON.stringify(next) : null })
  }
  return <div className="abi-panel abi-filterbar" aria-label="Dataset filters">
    {options.has_date !== false && ['date_from', 'date_to'].map(field => <label key={field} className="flex flex-col gap-1 text-xs text-neutral-400">{field === 'date_from' ? 'Date From' : 'Date To'}
      <input aria-label={field === 'date_from' ? 'Date From' : 'Date To'} type="date" className={inputClass} value={filters[field] || ''} min={options.date_range.min.slice(0, 10)} max={options.date_range.max.slice(0, 10)} onChange={e => setFilters({ [field]: e.target.value || null })} />
    </label>)}
    {showGrain && options.has_date !== false && <label className="flex flex-col gap-1 text-xs text-neutral-400">Grain
      <select aria-label="Grain" className={inputClass} value={filters.grain || 'month'} onChange={e => setFilters({ grain: e.target.value })}>{['day', 'week', 'month', 'quarter', 'year'].map(g => <option key={g}>{g}</option>)}</select>
    </label>}
    {options.dynamic ? options.dynamic.map(d => <label key={d.field} className="flex flex-col gap-1 text-xs text-neutral-400">{d.label}
      <select aria-label={`Filter ${d.field}`} className={inputClass} value={columnFilters[d.field] || ''} onChange={e => setColumn(d.field, e.target.value)}><option value="">All</option>{d.values.map(v => <option key={v}>{v}</option>)}</select>
    </label>) : legacyFields.map(([field, label, optionKey]) => <label key={field} className="flex flex-col gap-1 text-xs text-neutral-400">{label}
      <select aria-label={label} className={inputClass} value={filters[field] || ''} onChange={e => setFilters({ [field]: e.target.value || null })}><option value="">All</option>{options[optionKey].map(v => <option key={v}>{v}</option>)}</select>
    </label>)}
    <button onClick={resetFilters} className="ml-auto bg-neutral-800 hover:bg-neutral-700 text-sm px-4 py-1.5 rounded">Reset</button>
  </div>
}
