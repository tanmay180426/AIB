import DatasetResults from '@/components/DatasetResults'
import BusinessEvidence from '@/components/BusinessEvidence'
import { useDataset } from '@/hooks/useDataset'
import { useEffect, useState } from 'react'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
} from 'recharts'
import { getAnalyticsSellers } from '@/services/api'
import { useFilters } from '@/hooks/useFilters'
import { KpiCard } from '@/components/KpiCard'
import { fmtMoney } from '@/services/format'

const COLORS = ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)', 'var(--chart-4)', 'var(--chart-5)', 'var(--chart-6)', 'var(--chart-7)']

export default function Sellers() {
  const { filters } = useFilters()
  const { active } = useDataset()
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')

  useEffect(() => {
    let current = true
    setState('loading')
    getAnalyticsSellers(filters)
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
    return <div className="text-neutral-400">Loading sellers data...</div>
  }

  const {
    kpis,
    by_state,
    top_sellers,
    top_sellers_series,
  } = data

  // Group top_sellers_series by period for LineChart
  const seriesByPeriod = top_sellers_series?.reduce((acc: any, curr: any) => {
    const period = acc.find((p: any) => p.period === curr.period)
    if (period) {
      period[curr.seller] = curr.revenue
    } else {
      acc.push({ period: curr.period, [curr.seller]: curr.revenue })
    }
    return acc
  }, []) || []

  // Extract unique seller IDs from series
  const seriesSellers = Array.from(new Set(top_sellers_series?.map((s: any) => s.seller) || [])) as string[]

  if ('metric_cards' in data) return <div className="space-y-6"><DatasetResults data={data} /><BusinessEvidence domain="sellers" /></div>

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      <BusinessEvidence domain="sellers" />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard label="Active Sellers" value={kpis.active_sellers.toLocaleString()} />
        <KpiCard label="Avg Revenue / Seller" value={fmtMoney(kpis.avg_revenue_per_seller)} />
        <KpiCard label="Avg Orders / Seller" value={kpis.avg_orders_per_seller.toFixed(1)} />
        <KpiCard label="Avg Review Score" value={kpis.avg_review_per_seller?.toFixed(2) || '—'} hint="out of 5" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="abi-panel p-4 rounded-lg border border-neutral-800">
          <h2 className="mb-3 font-medium">Top Sellers Revenue Over Time</h2>
          <p className="text-xs text-neutral-400 mb-3">Leaders ranked across all selected item revenue; up to 400 latest seller-period points shown. Missing points are not zero.</p>
          {seriesByPeriod && seriesByPeriod.length > 0 ? (
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={seriesByPeriod}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--border))" />
                <XAxis dataKey="period" stroke="rgb(var(--muted))" fontSize={11} />
                <YAxis stroke="rgb(var(--muted))" fontSize={11} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
                <Tooltip
                  formatter={(v: number) => fmtMoney(v)}
                  contentStyle={{ background: 'rgb(var(--surface-raised))', border: '1px solid rgb(var(--border))' }}
                />
                {seriesSellers.map((seller, idx) => (
                  <Line
                    key={seller}
                    type="monotone"
                    dataKey={seller}
                    name={`Seller ${seller}`}
                    stroke={COLORS[idx % COLORS.length]}
                    strokeWidth={2}
                    dot={false}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[300px] flex items-center justify-center text-neutral-500">No data available</div>
          )}
        </div>

        <div className="abi-panel p-4 rounded-lg border border-neutral-800">
          <h2 className="mb-3 font-medium">Top States by Seller Revenue</h2>
          {by_state && by_state.length > 0 ? (
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={by_state.slice(0, 10)} layout="vertical" margin={{ left: 40 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--border))" horizontal={false} />
                <XAxis type="number" stroke="rgb(var(--muted))" fontSize={11} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
                <YAxis type="category" dataKey="state" stroke="rgb(var(--muted))" fontSize={10} width={40} />
                <Tooltip
                  formatter={(v: number) => fmtMoney(v)}
                  contentStyle={{ background: 'rgb(var(--surface-raised))', border: '1px solid rgb(var(--border))' }}
                />
                <Bar dataKey="revenue" fill="var(--chart-5)" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[300px] flex items-center justify-center text-neutral-500">No data available</div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="abi-panel p-4 rounded-lg border border-neutral-800 overflow-hidden flex flex-col">
          <h2 className="mb-3 font-medium">Top Sellers</h2>
          <div className="space-y-3 flex-1 overflow-y-auto pr-2 max-h-[400px] custom-scrollbar">
            {top_sellers?.map((s: any) => (
              <div key={s.seller} className="flex flex-col text-sm border-b border-neutral-800 pb-2">
                <div className="flex justify-between">
                  <span className="font-medium text-neutral-200">ID: {s.seller}</span>
                  <span className="text-blue-400 font-medium">{fmtMoney(s.revenue)}</span>
                </div>
                <span className="text-neutral-500 text-xs uppercase mt-1">State: {s.state}</span>
                <div className="flex gap-4 mt-2 text-xs">
                  <span className="text-neutral-400">{s.orders} orders</span>
                  <span className="text-neutral-400">{s.quantity} items</span>
                  <span className="text-neutral-400">★ {s.avg_review_score?.toFixed(1) || '-'}</span>
                  <span className="text-neutral-400">
                    {s.on_time_rate != null ? `${s.on_time_rate}% on-time` : ''}
                  </span>
                </div>
              </div>
            ))}
            {!top_sellers?.length && <div className="text-neutral-500 text-sm">No data available</div>}
          </div>
        </div>

        <div className="abi-panel p-4 rounded-lg border border-neutral-800 overflow-hidden flex flex-col">
          <h2 className="mb-3 font-medium">Seller Demographics (States)</h2>
          <div className="space-y-3 flex-1 overflow-y-auto pr-2 max-h-[400px] custom-scrollbar">
            {by_state?.map((s: any) => (
              <div key={s.state} className="flex flex-col text-sm border-b border-neutral-800 pb-2">
                <div className="flex justify-between">
                  <span className="font-medium text-neutral-200 uppercase">{s.state}</span>
                  <span className="text-neutral-300 font-medium">{fmtMoney(s.revenue)}</span>
                </div>
                <div className="flex gap-4 mt-2 text-xs">
                  <span className="text-neutral-400">{s.sellers} sellers</span>
                  <span className="text-neutral-400">{s.orders} orders</span>
                  <span className="text-neutral-400">{fmtMoney(s.revenue_per_seller)} / seller</span>
                  <span className="text-neutral-500 ml-auto">{s.share_pct}% rev</span>
                </div>
              </div>
            ))}
            {!by_state?.length && <div className="text-neutral-500 text-sm">No data available</div>}
          </div>
        </div>
      </div>
    </div>
  )
}
