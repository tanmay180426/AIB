import DatasetResults from '@/components/DatasetResults'
import { useEffect, useState } from 'react'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from 'recharts'
import { getAnalyticsOrders } from '@/services/api'
import { useFilters } from '@/hooks/useFilters'
import { KpiCard } from '@/components/KpiCard'
import { fmtMoney } from '@/services/format'

const COLORS = ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)', 'var(--chart-4)', 'var(--chart-5)', 'var(--chart-6)', 'var(--chart-7)']

export default function Orders() {
  const { filters } = useFilters()
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')

  useEffect(() => {
    let current = true
    setState('loading')
    getAnalyticsOrders(filters)
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
    return <div className="text-neutral-400">Loading orders data...</div>
  }

  const {
    kpis,
    by_status,
    orders_series,
    items_per_order,
    payment_types,
    payment_installments,
    order_value_distribution,
  } = data

  if ('metric_cards' in data) return <DatasetResults data={data} />

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard label="Total Orders" value={kpis.total_orders.toLocaleString()} />
        <KpiCard label="Delivered" value={kpis.delivered_orders.toLocaleString()} />
        <KpiCard label="Cancelled" value={kpis.cancelled_orders.toLocaleString()} />
        <KpiCard label="Avg Order Value" value={fmtMoney(kpis.avg_order_value)} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="abi-panel p-4 rounded-lg border border-neutral-800">
          <h2 className="mb-3 font-medium">Orders Over Time</h2>
          {orders_series && orders_series.length > 0 ? (
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={orders_series}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--border))" />
                <XAxis dataKey="period" stroke="rgb(var(--muted))" fontSize={11} />
                <YAxis stroke="rgb(var(--muted))" fontSize={11} />
                <Tooltip contentStyle={{ background: 'rgb(var(--surface-raised))', border: '1px solid rgb(var(--border))' }} />
                <Line type="monotone" dataKey="orders" stroke="var(--chart-2)" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[300px] flex items-center justify-center text-neutral-500">No data available</div>
          )}
        </div>

        <div className="abi-panel p-4 rounded-lg border border-neutral-800">
          <h2 className="mb-3 font-medium">Order Status Distribution</h2>
          <div className="flex h-[300px]">
            {by_status && by_status.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={by_status}
                    dataKey="orders"
                    nameKey="status"
                    cx="50%"
                    cy="50%"
                    innerRadius={70}
                    outerRadius={100}
                    paddingAngle={2}
                  >
                    {by_status.map((_: any, index: number) => (
                      <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={{ background: 'rgb(var(--surface-raised))', border: '1px solid rgb(var(--border))' }} />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex-1 flex items-center justify-center text-neutral-500">No data available</div>
            )}
            <div className="flex flex-col justify-center gap-2 pl-4">
              {by_status?.map((s: any, i: number) => (
                <div key={s.status} className="flex items-center gap-2 text-sm">
                  <div className="w-3 h-3 rounded-full" style={{ backgroundColor: COLORS[i % COLORS.length] }} />
                  <span className="text-neutral-300 capitalize">{s.status}</span>
                  <span className="text-neutral-500 ml-auto">{s.share_pct}%</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <div className="abi-panel p-4 rounded-lg border border-neutral-800">
          <h2 className="mb-3 font-medium">Payment Types</h2>
          <div className="space-y-3">
            {payment_types?.map((pt: any) => (
              <div key={pt.payment_type} className="flex justify-between items-center text-sm border-b border-neutral-800 pb-2">
                <span className="text-neutral-300 capitalize">{pt.payment_type.replace('_', ' ')}</span>
                <span className="text-neutral-400">{pt.share_pct}%</span>
              </div>
            ))}
            {!payment_types?.length && <div className="text-neutral-500 text-sm">No data available</div>}
          </div>
        </div>

        <div className="abi-panel p-4 rounded-lg border border-neutral-800">
          <h2 className="mb-3 font-medium">Payment Installments</h2>
          <div className="space-y-3">
            {payment_installments?.map((pi: any) => (
              <div key={pi.installments} className="flex justify-between items-center text-sm border-b border-neutral-800 pb-2">
                <span className="text-neutral-300">{pi.installments} inst.</span>
                <span className="text-neutral-400">{pi.share_pct}%</span>
              </div>
            ))}
            {!payment_installments?.length && <div className="text-neutral-500 text-sm">No data available</div>}
          </div>
        </div>

        <div className="abi-panel p-4 rounded-lg border border-neutral-800">
          <h2 className="mb-3 font-medium">Items per Order</h2>
          <div className="space-y-3">
            {items_per_order?.map((io: any) => (
              <div key={io.bucket} className="flex justify-between items-center text-sm border-b border-neutral-800 pb-2">
                <span className="text-neutral-300">{io.bucket}</span>
                <span className="text-neutral-400">{io.share_pct}%</span>
              </div>
            ))}
            {!items_per_order?.length && <div className="text-neutral-500 text-sm">No data available</div>}
          </div>
        </div>

        <div className="abi-panel p-4 rounded-lg border border-neutral-800">
          <h2 className="mb-3 font-medium">Order Value</h2>
          <div className="space-y-3">
            {order_value_distribution?.map((ov: any) => (
              <div key={ov.bucket} className="flex justify-between items-center text-sm border-b border-neutral-800 pb-2">
                <span className="text-neutral-300">{ov.bucket}</span>
                <span className="text-neutral-400">{ov.share_pct}%</span>
              </div>
            ))}
            {!order_value_distribution?.length && <div className="text-neutral-500 text-sm">No data available</div>}
          </div>
        </div>
      </div>
    </div>
  )
}
