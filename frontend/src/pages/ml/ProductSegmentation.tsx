import { PageHeader } from '@/components/ui/Workspace'
import { useEffect, useState } from 'react'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from 'recharts'
import { useFilters } from '@/hooks/useFilters'
import FilterBar from '@/components/FilterBar'
import { KpiCard } from '@/components/KpiCard'
import { getProductSegments, type ProductSegmentationResponse } from '@/services/api'

const COLORS = ['var(--chart-1)', 'var(--chart-5)', '#ec4899', 'var(--chart-3)', 'var(--chart-2)', 'var(--chart-5)']

const fmtMoney = (n: number) =>
  `R$ ${n.toLocaleString('en-US', { maximumFractionDigits: 0 })}`

export default function ProductSegmentation() {
  const { filters } = useFilters()
  const [data, setData] = useState<ProductSegmentationResponse | null>(null)
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let current = true
    setState('loading')
    getProductSegments(filters)
      .then((res) => {
        if (!current) return
        setData(res)
        setState('ready')
      })
      .catch(e => { if (current) { setError(e.message); setState('error') } })
    return () => { current = false }
  }, [filters])

  return (
    <div className="space-y-6">
      <FilterBar />

      <div>
        <PageHeader title="Product Segmentation" />
        <p className="text-sm text-neutral-500">
          K-Means clustering on product engagement (revenue, quantity, price, weight).
          Applies your current filters before inference with the existing trained model.
        </p>
      </div>

      {state === 'loading' && <div className="text-neutral-400">Loading segments...</div>}

      {state === 'error' && (
        <div className="text-red-400">
          {error || 'Failed to load product segments.'}
        </div>
      )}

      {state === 'ready' && data?.status === 'not_applicable' && <div role="status" className="bg-neutral-900 border border-neutral-800 rounded p-4"><h2>Not Applicable</h2><p className="text-neutral-400">{data.reason}</p></div>}
      {state === 'ready' && data && data.status !== 'not_applicable' && (
        <>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <KpiCard
              label="Products Analyzed"
              value={data.segments.reduce((acc, s) => acc + s.products, 0).toLocaleString()}
            />
            <KpiCard
              label="Segments (k)"
              value={data.k}
            />
            <KpiCard
              label="Largest Segment Size"
              value={Math.max(0, ...data.segments.map(s => s.products)).toLocaleString()}
            />
            <KpiCard
              label="Total Revenue Covered"
              value={fmtMoney(data.segments.reduce((acc, s) => acc + s.revenue, 0))}
            />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="abi-panel p-4 rounded-lg border border-neutral-800">
              <h2 className="mb-4 font-medium">Product Count by Segment</h2>
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={data.segments}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--border))" />
                  <XAxis dataKey="segment" tickFormatter={(v) => `C${v}`} stroke="rgb(var(--muted))" fontSize={11} />
                  <YAxis stroke="rgb(var(--muted))" fontSize={11} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
                  <Tooltip
                    contentStyle={{ background: 'rgb(var(--surface-raised))', border: '1px solid rgb(var(--border))' }}
                    labelFormatter={(label) => `Cluster ${label}`}
                  />
                  <Bar dataKey="products" name="Products">
                    {data.segments.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>

            <div className="abi-panel p-4 rounded-lg border border-neutral-800">
              <h2 className="mb-4 font-medium">Revenue Contribution by Segment</h2>
              <ResponsiveContainer width="100%" height={280}>
                <BarChart data={data.segments}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--border))" />
                  <XAxis dataKey="segment" tickFormatter={(v) => `C${v}`} stroke="rgb(var(--muted))" fontSize={11} />
                  <YAxis stroke="rgb(var(--muted))" fontSize={11} tickFormatter={(v) => `R$${Math.round(v / 1000)}k`} />
                  <Tooltip
                    contentStyle={{ background: 'rgb(var(--surface-raised))', border: '1px solid rgb(var(--border))' }}
                    formatter={(val: number) => fmtMoney(val)}
                    labelFormatter={(label) => `Cluster ${label}`}
                  />
                  <Bar dataKey="revenue" name="Total Revenue">
                    {data.segments.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="abi-panel p-4 rounded-lg border border-neutral-800">
            <h2 className="mb-4 font-medium">Segment Profiles</h2>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-neutral-500 text-xs uppercase border-b border-neutral-800">
                  <tr>
                    <th className="text-left py-2 font-medium">Segment</th>
                    <th className="text-right py-2 font-medium">Products</th>
                    <th className="text-right py-2 font-medium">Avg Price</th>
                    <th className="text-right py-2 font-medium">Total Quantity</th>
                    <th className="text-right py-2 font-medium">Total Revenue</th>
                    <th className="text-right py-2 font-medium">Revenue Share</th>
                  </tr>
                </thead>
                <tbody>
                  {data.segments.sort((a, b) => b.revenue - a.revenue).map((s) => (
                    <tr key={s.segment} className="border-b border-neutral-800/50 hover:bg-neutral-800/20">
                      <td className="py-3 font-medium text-neutral-300">
                        <span
                          className="inline-block w-3 h-3 rounded-full mr-2"
                          style={{ backgroundColor: COLORS[s.segment % COLORS.length] }}
                        />
                        Cluster {s.segment}
                      </td>
                      <td className="py-3 text-right text-neutral-400">{s.products.toLocaleString()}</td>
                      <td className="py-3 text-right font-mono text-neutral-300">{fmtMoney(s.avg_price)}</td>
                      <td className="py-3 text-right font-mono text-neutral-300">{s.quantity.toLocaleString()}</td>
                      <td className="py-3 text-right font-mono text-emerald-400">{fmtMoney(s.revenue)}</td>
                      <td className="py-3 text-right font-mono text-neutral-400">{s.revenue_share.toFixed(1)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="abi-panel p-4 rounded-lg border border-neutral-800">
            <h2 className="mb-4 font-medium">Top Products by Segment (Sample)</h2>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-neutral-500 text-xs uppercase border-b border-neutral-800">
                  <tr>
                    <th className="text-left py-2 font-medium">Product ID</th>
                    <th className="text-left py-2 font-medium">Category</th>
                    <th className="text-right py-2 font-medium">Segment</th>
                    <th className="text-right py-2 font-medium">Quantity</th>
                    <th className="text-right py-2 font-medium">Revenue</th>
                  </tr>
                </thead>
                <tbody>
                  {data.top_products.map((p, i) => (
                    <tr key={`${p.product}-${i}`} className="border-b border-neutral-800/50 hover:bg-neutral-800/20">
                      <td className="py-2 text-neutral-300 font-mono text-xs">{p.product}</td>
                      <td className="py-2 text-neutral-400 capitalize">{p.category.replace(/_/g, ' ')}</td>
                      <td className="py-2 text-right">
                        <span
                          className="px-2 py-0.5 rounded text-xs bg-neutral-800"
                          style={{ color: COLORS[p.segment % COLORS.length] }}
                        >
                          C{p.segment}
                        </span>
                      </td>
                      <td className="py-2 text-right font-mono text-neutral-400">{p.quantity}</td>
                      <td className="py-2 text-right font-mono text-neutral-300">{fmtMoney(p.revenue)}</td>
                    </tr>
                  ))}
                  {data.top_products.length === 0 && (
                    <tr>
                      <td colSpan={5} className="py-4 text-center text-neutral-500">No products found for the given filters.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </div>
  )
}
