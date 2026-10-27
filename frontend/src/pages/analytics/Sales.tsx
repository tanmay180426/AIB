import DatasetResults from '@/components/DatasetResults'
import SeasonalityHeatmap from '@/components/SeasonalityHeatmap'
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
import { getAnalyticsSales } from '@/services/api'
import { useFilters } from '@/hooks/useFilters'
import { KpiCard } from '@/components/KpiCard'
import { fmtMoney } from '@/services/format'

export default function Sales() {
  const { filters } = useFilters()
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')

  useEffect(() => {
    let current = true
    setState('loading')
    getAnalyticsSales(filters)
      .then((res) => {
        if (!current) return
        setData(res)
        setState('ready')
      })
      .catch(e => { if (current) { setError(e.message); setState('error') } })
    return () => { current = false }
  }, [filters])

  if (state === 'error') {
    return (
      <div className="text-red-400">
        {error || 'Could not load data.'}
      </div>
    )
  }

  if (state === 'loading' || !data) {
    return <div className="text-neutral-400">Loading sales data...</div>
  }

  if ('metric_cards' in data) return <div className="space-y-6"><DatasetResults data={data} /><SeasonalityHeatmap points={data.time_series || []} grain={filters.grain || 'month'} currency={data.currency_code} /></div>

  const { kpis, revenue_series, top_categories, revenue_by_customer_state, top_products, top_sellers } = data

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      <SeasonalityHeatmap points={revenue_series || []} grain={filters.grain || 'month'} currency="BRL" />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard label="Total Revenue" value={fmtMoney(kpis.total_revenue)} />
        <KpiCard label="Total Orders" value={kpis.total_orders.toLocaleString()} />
        <KpiCard label="Avg Order Value" value={fmtMoney(kpis.avg_order_value)} />
        <KpiCard label="Items Sold" value={kpis.items_sold.toLocaleString()} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="abi-panel p-4 rounded-lg border border-neutral-800">
          <h2 className="mb-3 font-medium">Revenue Over Time</h2>
          {revenue_series && revenue_series.length > 0 ? (
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={revenue_series}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--border))" />
                <XAxis dataKey="period" stroke="rgb(var(--muted))" fontSize={11} />
                <YAxis stroke="rgb(var(--muted))" fontSize={11} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
                <Tooltip
                  formatter={(v: number) => fmtMoney(v)}
                  contentStyle={{ background: 'rgb(var(--surface-raised))', border: '1px solid rgb(var(--border))' }}
                />
                <Line type="monotone" dataKey="revenue" stroke="var(--chart-1)" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[300px] flex items-center justify-center text-neutral-500">No data available</div>
          )}
        </div>

        <div className="abi-panel p-4 rounded-lg border border-neutral-800">
          <h2 className="mb-3 font-medium">Top Categories by Revenue</h2>
          {top_categories && top_categories.length > 0 ? (
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={top_categories} layout="vertical" margin={{ left: 80 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--border))" horizontal={false} />
                <XAxis type="number" stroke="rgb(var(--muted))" fontSize={11} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
                <YAxis type="category" dataKey="category" stroke="rgb(var(--muted))" fontSize={10} width={80} />
                <Tooltip
                  formatter={(v: number) => fmtMoney(v)}
                  contentStyle={{ background: 'rgb(var(--surface-raised))', border: '1px solid rgb(var(--border))' }}
                />
                <Bar dataKey="revenue" fill="var(--chart-2)" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[300px] flex items-center justify-center text-neutral-500">No data available</div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="abi-panel p-4 rounded-lg border border-neutral-800">
          <h2 className="mb-3 font-medium">Top Products</h2>
          <div className="space-y-3">
            {top_products?.slice(0, 5).map((p: any) => (
              <div key={p.product} className="flex flex-col text-sm border-b border-neutral-800 pb-2">
                <span className="font-medium text-neutral-200">ID: {p.product}</span>
                <span className="text-neutral-500 text-xs truncate">{p.category}</span>
                <div className="flex justify-between mt-1">
                  <span className="text-neutral-400">{p.orders} orders</span>
                  <span className="text-blue-400 font-medium">{fmtMoney(p.revenue)}</span>
                </div>
              </div>
            ))}
            {!top_products?.length && <div className="text-neutral-500 text-sm">No data available</div>}
          </div>
        </div>

        <div className="abi-panel p-4 rounded-lg border border-neutral-800">
          <h2 className="mb-3 font-medium">Top Sellers</h2>
          <div className="space-y-3">
            {top_sellers?.slice(0, 5).map((s: any) => (
              <div key={s.seller} className="flex flex-col text-sm border-b border-neutral-800 pb-2">
                <span className="font-medium text-neutral-200">ID: {s.seller}</span>
                <span className="text-neutral-500 text-xs uppercase">{s.state}</span>
                <div className="flex justify-between mt-1">
                  <span className="text-neutral-400">{s.orders} orders</span>
                  <span className="text-blue-400 font-medium">{fmtMoney(s.revenue)}</span>
                </div>
              </div>
            ))}
            {!top_sellers?.length && <div className="text-neutral-500 text-sm">No data available</div>}
          </div>
        </div>

        <div className="abi-panel p-4 rounded-lg border border-neutral-800">
          <h2 className="mb-3 font-medium">Revenue by Customer State</h2>
          <div className="space-y-3">
            {revenue_by_customer_state?.slice(0, 5).map((s: any) => (
              <div key={s.state} className="flex justify-between items-center text-sm border-b border-neutral-800 pb-2">
                <span className="text-neutral-300 font-medium uppercase">{s.state}</span>
                <span className="text-neutral-400">{fmtMoney(s.revenue)} ({s.share_pct}%)</span>
              </div>
            ))}
            {!revenue_by_customer_state?.length && <div className="text-neutral-500 text-sm">No data available</div>}
          </div>
        </div>
      </div>
    </div>
  )
}
