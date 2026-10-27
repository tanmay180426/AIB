import DatasetResults from '@/components/DatasetResults'
import BusinessEvidence from '@/components/BusinessEvidence'
import { useDataset } from '@/hooks/useDataset'
import { useEffect, useState } from 'react'
import {
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  ComposedChart,
} from 'recharts'
import { getAnalyticsDelivery } from '@/services/api'
import { useFilters } from '@/hooks/useFilters'
import { KpiCard } from '@/components/KpiCard'

export default function Delivery() {
  const { filters } = useFilters()
  const { active } = useDataset()
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')

  useEffect(() => {
    let current = true
    setState('loading')
    getAnalyticsDelivery(filters)
      .then((res) => {
        if (!current) return
        setData(res)
        setState('ready')
      })
      .catch(e => { if (current) { setError(e.message); setState('error') } })
    return () => { current = false }
  }, [filters, active?.dataset_id, active?.updated_at])

  if (state === 'error') {
    return (
      <div className="text-red-400">
        {error || 'Could not load data.'}
      </div>
    )
  }

  if (state === 'loading' || !data) {
    return <div className="text-neutral-400">Loading delivery data...</div>
  }

  const {
    kpis,
    data_quality,
    duration_distribution,
    over_time,
    by_state,
    by_category,
  } = data

  if ('metric_cards' in data) return <div className="space-y-6"><DatasetResults data={data} /><BusinessEvidence domain="sellers" /></div>

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      <BusinessEvidence domain="sellers" />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard label="Avg Delivery" value={kpis.avg_delivery_days != null ? `${kpis.avg_delivery_days} days` : '—'} />
        <KpiCard label="Median Delivery" value={kpis.median_delivery_days != null ? `${kpis.median_delivery_days} days` : '—'} />
        <KpiCard label="On-Time Rate" value={kpis.on_time_rate != null ? `${kpis.on_time_rate}%` : '—'} />
        <KpiCard label="Avg Delay" value={kpis.avg_delay_days != null ? `${kpis.avg_delay_days} days` : '—'} hint="Vs estimate" />
      </div>

      {data_quality && (
        <div className="bg-blue-900/20 border border-blue-900/50 p-4 rounded-lg flex flex-col gap-1 text-sm text-blue-200">
          <div className="font-medium">Data Quality Note</div>
          <div>{data_quality.note}</div>
          <div className="text-xs text-blue-400/80 mt-1">
            Excluded: {data_quality.orders_without_delivery} without delivery timestamp, {data_quality.cancelled_orders_excluded} cancelled.
            ({data_quality.orders_without_estimate} missing estimate).
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="abi-panel p-4 rounded-lg border border-neutral-800">
          <h2 className="mb-3 font-medium">Delivery Performance Over Time</h2>
          {over_time && over_time.length > 0 ? (
            <ResponsiveContainer width="100%" height={300}>
              <ComposedChart data={over_time}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--border))" />
                <XAxis dataKey="period" stroke="rgb(var(--muted))" fontSize={11} />
                <YAxis yAxisId="left" stroke="rgb(var(--muted))" fontSize={11} />
                <YAxis yAxisId="right" orientation="right" stroke="rgb(var(--muted))" fontSize={11} />
                <Tooltip contentStyle={{ background: 'rgb(var(--surface-raised))', border: '1px solid rgb(var(--border))' }} />
                <Bar yAxisId="right" dataKey="orders" fill="var(--chart-1)" opacity={0.3} />
                <Line yAxisId="left" type="monotone" dataKey="avg_delivery_days" name="Avg Days" stroke="var(--chart-2)" strokeWidth={2} dot={false} />
              </ComposedChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[300px] flex items-center justify-center text-neutral-500">No data available</div>
          )}
        </div>

        <div className="abi-panel p-4 rounded-lg border border-neutral-800">
          <h2 className="mb-3 font-medium">Delivery Duration Distribution</h2>
          {duration_distribution && duration_distribution.length > 0 ? (
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={duration_distribution}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--border))" />
                <XAxis dataKey="bucket" stroke="rgb(var(--muted))" fontSize={11} />
                <YAxis stroke="rgb(var(--muted))" fontSize={11} />
                <Tooltip contentStyle={{ background: 'rgb(var(--surface-raised))', border: '1px solid rgb(var(--border))' }} />
                <Bar dataKey="orders" fill="var(--chart-3)" />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[300px] flex items-center justify-center text-neutral-500">No data available</div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="abi-panel p-4 rounded-lg border border-neutral-800 flex flex-col">
          <h2 className="mb-3 font-medium">Delivery by Customer State</h2>
          <div className="space-y-3 flex-1 overflow-y-auto pr-2 max-h-[400px] custom-scrollbar">
            {by_state?.map((s: any) => (
              <div key={s.state} className="flex flex-col text-sm border-b border-neutral-800 pb-2">
                <div className="flex justify-between">
                  <span className="font-medium text-neutral-200 uppercase">{s.state}</span>
                  <span className="text-neutral-300 font-medium">{s.avg_delivery_days} days avg</span>
                </div>
                <div className="flex gap-4 mt-2 text-xs">
                  <span className="text-neutral-400">{s.orders} orders</span>
                  <span className="text-neutral-400">
                    {s.on_time_rate != null ? `${s.on_time_rate}% on-time` : ''}
                  </span>
                </div>
              </div>
            ))}
            {!by_state?.length && <div className="text-neutral-500 text-sm">No data available</div>}
          </div>
        </div>

        <div className="abi-panel p-4 rounded-lg border border-neutral-800 flex flex-col">
          <h2 className="mb-3 font-medium">Delivery by Category</h2>
          <div className="space-y-3 flex-1 overflow-y-auto pr-2 max-h-[400px] custom-scrollbar">
            {by_category?.map((c: any) => (
              <div key={c.category} className="flex flex-col text-sm border-b border-neutral-800 pb-2">
                <div className="flex justify-between">
                  <span className="font-medium text-neutral-200 capitalize">{c.category.replace(/_/g, ' ')}</span>
                  <span className="text-neutral-300 font-medium">{c.avg_delivery_days} days avg</span>
                </div>
                <div className="flex gap-4 mt-2 text-xs">
                  <span className="text-neutral-400">{c.orders} orders</span>
                  <span className="text-neutral-400">
                    {c.on_time_rate != null ? `${c.on_time_rate}% on-time` : ''}
                  </span>
                </div>
              </div>
            ))}
            {!by_category?.length && <div className="text-neutral-500 text-sm">No data available</div>}
          </div>
        </div>
      </div>
    </div>
  )
}
