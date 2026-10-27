import DatasetResults from '@/components/DatasetResults'
import { useEffect, useState } from 'react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts'
import { getAnalyticsProducts } from '@/services/api'
import { useFilters } from '@/hooks/useFilters'
import { KpiCard } from '@/components/KpiCard'
import { fmtMoney } from '@/services/format'

export default function Products() {
  const { filters } = useFilters()
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')

  useEffect(() => {
    let current = true
    setState('loading')
    getAnalyticsProducts(filters)
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
    return <div className="text-neutral-400">Loading products data...</div>
  }

  const {
    kpis,
    by_category,
    top_by_revenue,
    top_by_quantity,
  } = data

  if ('metric_cards' in data) return <DatasetResults data={data} />

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard label="Products Sold" value={kpis.products_sold.toLocaleString()} />
        <KpiCard label="Categories Sold" value={kpis.category_count.toLocaleString()} hint={`out of ${kpis.catalog.categories}`} />
        <KpiCard label="Avg Price" value={fmtMoney(kpis.avg_price)} />
        <KpiCard label="Items Sold" value={kpis.items_sold.toLocaleString()} />
      </div>

      <div className="grid grid-cols-1 gap-6">
        <div className="abi-panel p-4 rounded-lg border border-neutral-800">
          <h2 className="mb-3 font-medium">Revenue by Category</h2>
          {by_category && by_category.length > 0 ? (
            <ResponsiveContainer width="100%" height={400}>
              <BarChart data={by_category.slice(0, 20)} layout="vertical" margin={{ left: 100 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--border))" horizontal={false} />
                <XAxis type="number" stroke="rgb(var(--muted))" fontSize={11} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
                <YAxis type="category" dataKey="category" stroke="rgb(var(--muted))" fontSize={10} width={100} />
                <Tooltip
                  formatter={(v: number, name: string) => [name === 'revenue' ? fmtMoney(v) : v, name]}
                  contentStyle={{ background: 'rgb(var(--surface-raised))', border: '1px solid rgb(var(--border))' }}
                />
                <Bar dataKey="revenue" fill="var(--chart-1)" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[400px] flex items-center justify-center text-neutral-500">No data available</div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        <div className="abi-panel p-4 rounded-lg border border-neutral-800">
          <h2 className="mb-3 font-medium">Category Details</h2>
          <div className="space-y-3 overflow-y-auto max-h-[300px] pr-2 custom-scrollbar">
            {by_category?.map((c: any) => (
              <div key={c.category} className="flex flex-col text-sm border-b border-neutral-800 pb-2">
                <span className="font-medium text-neutral-200 capitalize">{c.category.replace(/_/g, ' ')}</span>
                <div className="flex justify-between mt-1 text-xs">
                  <span className="text-neutral-500">{c.quantity} items</span>
                  <span className="text-neutral-500">{fmtMoney(c.avg_price)} avg price</span>
                  <span className="text-blue-400 font-medium">{fmtMoney(c.revenue)}</span>
                </div>
              </div>
            ))}
            {!by_category?.length && <div className="text-neutral-500 text-sm">No data available</div>}
          </div>
        </div>

        <div className="abi-panel p-4 rounded-lg border border-neutral-800">
          <h2 className="mb-3 font-medium">Top Products (Revenue)</h2>
          <div className="space-y-3 overflow-y-auto max-h-[300px] pr-2 custom-scrollbar">
            {top_by_revenue?.map((p: any) => (
              <div key={p.product} className="flex flex-col text-sm border-b border-neutral-800 pb-2">
                <span className="font-medium text-neutral-200">ID: {p.product}</span>
                <span className="text-neutral-500 text-xs truncate capitalize">{p.category.replace(/_/g, ' ')}</span>
                <div className="flex justify-between mt-1">
                  <span className="text-neutral-400">{p.orders} orders</span>
                  <span className="text-green-500 font-medium">{fmtMoney(p.revenue)}</span>
                </div>
              </div>
            ))}
            {!top_by_revenue?.length && <div className="text-neutral-500 text-sm">No data available</div>}
          </div>
        </div>

        <div className="abi-panel p-4 rounded-lg border border-neutral-800">
          <h2 className="mb-3 font-medium">Top Products (Quantity)</h2>
          <div className="space-y-3 overflow-y-auto max-h-[300px] pr-2 custom-scrollbar">
            {top_by_quantity?.map((p: any) => (
              <div key={p.product} className="flex flex-col text-sm border-b border-neutral-800 pb-2">
                <span className="font-medium text-neutral-200">ID: {p.product}</span>
                <span className="text-neutral-500 text-xs truncate capitalize">{p.category.replace(/_/g, ' ')}</span>
                <div className="flex justify-between mt-1">
                  <span className="text-neutral-400">{p.quantity} items sold</span>
                  <span className="text-neutral-400">{fmtMoney(p.revenue)}</span>
                </div>
              </div>
            ))}
            {!top_by_quantity?.length && <div className="text-neutral-500 text-sm">No data available</div>}
          </div>
        </div>
      </div>
    </div>
  )
}
