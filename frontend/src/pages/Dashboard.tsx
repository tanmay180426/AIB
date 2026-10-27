import DatasetResults from '@/components/DatasetResults'
import BusinessEvidence from '@/components/BusinessEvidence'
import ExecutiveOutlook from '@/components/ExecutiveOutlook'
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
  PieChart,
  Pie,
  Cell,
} from 'recharts'
import { getAnalyticsOverview } from '@/services/api'
import { useFilters } from '@/hooks/useFilters'
import FilterBar from '@/components/FilterBar'

import { KpiCard } from '@/components/KpiCard'
import { fmtMoney } from '@/services/format'
import { useDataset } from '@/hooks/useDataset'
import { Link, useLocation } from 'react-router-dom'
import { PageHeader, StatusBadge } from '@/components/ui/Workspace'
import { Icon } from '@/components/ui/Icon'

const COLORS = ['var(--chart-1)', 'var(--chart-2)', 'var(--chart-3)', 'var(--chart-4)', 'var(--chart-5)', 'var(--chart-6)', 'var(--chart-7)']

export default function Dashboard() {
  const location = useLocation()
  const { filters, resetFilters } = useFilters()
  const { active, datasets } = useDataset()
  const activeId = active?.dataset_id
  const [retry, setRetry] = useState(0)
  const [refreshedAt, setRefreshedAt] = useState<string | null>(null)
  const [data, setData] = useState<any>(null)
  const [error, setError] = useState<string | null>(null)
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')

  useEffect(() => {
    let current = true
    if (!activeId) { setData(null); setState('ready'); return () => { current = false } }
    setState('loading')
    setData(null); setError(null)
    getAnalyticsOverview(filters)
      .then((res) => {
        if (!current) return
        setData(res)
        setRefreshedAt(new Date().toLocaleString())
        setState('ready')
      })
      .catch(e => { if (current) { setError(e.message); setState('error') } })
    return () => { current = false }
  }, [filters, activeId, active?.updated_at, retry])

  if (!active) return <section className="border border-neutral-800 rounded-2xl p-8 space-y-4"><h1 className="text-3xl font-semibold">Dashboard</h1><h2 className="text-lg">Start with your data</h2><p className="text-neutral-400">Upload a file or CSV folder, inspect its schema and choose a table to see observed metrics.</p><Link className="inline-block bg-blue-600 rounded-lg px-4 py-2" to="/datasets">Upload your first dataset</Link></section>

  if (state === 'error') {
    return (
      <div className="border border-red-900 bg-red-950/20 rounded-xl p-6 space-y-3" role="alert">
        <PageHeader title="Dashboard" />
        <p>{error || 'Could not load data.'}</p>
        <button className="px-4 py-2 bg-neutral-800 rounded" onClick={() => setRetry(r => r + 1)}>Retry dashboard</button>
        <Link to="/datasets" className="block text-blue-400">Choose a dataset in Dataset Manager</Link>
      </div>
    )
  }

  const renderContent = () => {
    if (state === 'loading' || !data) {
      return <div role="status" className="space-y-4"><p className="text-neutral-400">Loading dataset metrics...</p><div className="grid grid-cols-2 lg:grid-cols-4 gap-4 animate-pulse">{[1, 2, 3, 4].map(i => <div key={i} className="h-28 rounded-xl bg-neutral-900 border border-neutral-800" />)}</div></div>
    }

    if ('metric_cards' in data) return <div className="space-y-5">
      <DatasetResults data={data} dashboard revenueAvailable={!!active?.semantics.fields?.revenue} monetaryFields={active.tables ? ['Item revenue','Average order value','Payment total'] : [active?.semantics.fields?.revenue, active?.semantics.fields?.currency, active?.semantics.fields?.price].filter((field): field is string => !!field)} />
      {data.revenue_definition && <details className="abi-panel p-4"><summary>Metric definitions and validated relationships</summary><div className="text-xs text-neutral-400 space-y-2 pt-3"><p>{data.revenue_definition}</p><p>Currency: {data.currency_code || 'Unconfirmed — confirm in Dataset Manager'}. Grain: orders. Every metric uses the current filters.</p><p>Missing values: {active.tables?.reduce((n,t) => n+(t.quality.missing_values || 0),0).toLocaleString()}. Tables: {active.tables?.length}. Uploaded record provenance is unverified.</p>{data.relationships?.relationships?.map((r: any,i: number) => <p key={i}>{r.from_table} → {r.to_table}: {r.enabled ? 'Enabled' : r.reason} · unmatched {r.unmatched_rows ?? 'not applicable'} · null keys {r.null_keys ?? 'not applicable'}</p>)}</div></details>}
    </div>

    const { kpis, revenue_series, revenue_by_category, orders_by_status, top_customer_states, delivery } = data

    return (
      <div className="space-y-6 animate-in fade-in duration-300">
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
          <KpiCard label="Total Revenue" value={fmtMoney(kpis.total_revenue)} hint="Sum of item prices" />
          <KpiCard label="Total Orders" value={kpis.total_orders.toLocaleString()} />
          <KpiCard label="Units Sold" value={kpis.items_sold.toLocaleString()} hint="Qualifying item rows; independent of distinct order count." />
          <KpiCard label="Unique Customers" value={kpis.unique_customers.toLocaleString()} />
          <KpiCard label="Products Sold" value={kpis.products_sold.toLocaleString()} />
          <KpiCard label="Active Sellers" value={kpis.active_sellers.toLocaleString()} />
          <KpiCard label="Avg Order Value" value={fmtMoney(kpis.avg_order_value)} />
          <KpiCard label="Avg Review Score" value={kpis.avg_review_score?.toFixed(2) || '—'} hint="out of 5" />
          <KpiCard label="On-time Delivery" value={delivery.kpis.on_time_rate != null ? `${delivery.kpis.on_time_rate}%` : '—'} />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="abi-panel p-4 rounded-lg border border-neutral-800">
            <h2 className="mb-3 font-medium">Revenue Over Time</h2>
            {revenue_series && revenue_series.length > 0 ? (
              <ResponsiveContainer width="100%" height={260}>
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
              <div className="h-[260px] flex items-center justify-center text-neutral-500">No data available</div>
            )}
          </div>

          <div className="abi-panel p-4 rounded-lg border border-neutral-800">
            <h2 className="mb-3 font-medium">Orders Over Time</h2>
            {revenue_series && revenue_series.length > 0 ? (
              <ResponsiveContainer width="100%" height={260}>
                <LineChart data={revenue_series}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--border))" />
                  <XAxis dataKey="period" stroke="rgb(var(--muted))" fontSize={11} />
                  <YAxis stroke="rgb(var(--muted))" fontSize={11} />
                  <Tooltip contentStyle={{ background: 'rgb(var(--surface-raised))', border: '1px solid rgb(var(--border))' }} />
                  <Line type="monotone" dataKey="orders" stroke="var(--chart-2)" strokeWidth={2} dot={false} />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[260px] flex items-center justify-center text-neutral-500">No data available</div>
            )}
          </div>

          <div className="abi-panel p-4 rounded-lg border border-neutral-800">
            <h2 className="mb-3 font-medium">Revenue by Category (Top 10)</h2>
            {revenue_by_category && revenue_by_category.length > 0 ? (
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={revenue_by_category.slice(0, 10)} layout="vertical" margin={{ left: 80 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--border))" horizontal={false} />
                  <XAxis type="number" stroke="rgb(var(--muted))" fontSize={11} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
                  <YAxis type="category" dataKey="category" stroke="rgb(var(--muted))" fontSize={10} width={80} />
                  <Tooltip
                    formatter={(v: number) => fmtMoney(v)}
                    contentStyle={{ background: 'rgb(var(--surface-raised))', border: '1px solid rgb(var(--border))' }}
                  />
                  <Bar dataKey="revenue" fill="var(--chart-1)" radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[300px] flex items-center justify-center text-neutral-500">No data available</div>
            )}
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <div className="abi-panel p-4 rounded-lg border border-neutral-800 flex flex-col">
              <h2 className="mb-3 font-medium">Order Status</h2>
              <div className="flex-1 flex items-center justify-center">
                {orders_by_status && orders_by_status.length > 0 ? (
                  <ResponsiveContainer width="100%" height={200}>
                    <PieChart>
                      <Pie
                        data={orders_by_status}
                        dataKey="orders"
                        nameKey="status"
                        cx="50%"
                        cy="50%"
                        innerRadius={60}
                        outerRadius={80}
                        paddingAngle={2}
                      >
                        {orders_by_status.map((_: any, index: number) => (
                          <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                        ))}
                      </Pie>
                      <Tooltip contentStyle={{ background: 'rgb(var(--surface-raised))', border: '1px solid rgb(var(--border))' }} />
                    </PieChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="text-neutral-500">No data available</div>
                )}
              </div>
            </div>

            <div className="abi-panel p-4 rounded-lg border border-neutral-800">
              <h2 className="mb-3 font-medium">Top States (Customers)</h2>
              <div className="space-y-3">
                {top_customer_states?.slice(0, 5).map((s: any) => (
                  <div key={s.state} className="flex justify-between items-center text-sm">
                    <span className="text-neutral-300 font-medium uppercase">{s.state}</span>
                    <span className="text-neutral-400">{s.customers.toLocaleString()} customers</span>
                  </div>
                ))}
                {!top_customer_states?.length && (
                  <div className="text-neutral-500 text-sm">No data available</div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6 abi-dashboard">
      <div>
        <PageHeader title="Dashboard" eyebrow="01 / Performance overview" description="The numbers that matter, grounded in your selected data." action={<Link className="abi-button" to="/datasets"><Icon name="data" size={15} />Change data source</Link>} />
        <div className="abi-dashboard-context"><StatusBadge>{active?.bundle_id ? datasets.find(d => d.dataset_id === active.bundle_id)?.dataset_name : active?.dataset_name || 'No selected dataset'}</StatusBadge>{active?.bundle_id && <StatusBadge>Table: {active.relative_path || active.dataset_name}</StatusBadge>}<StatusBadge tone={active?.status === 'READY' ? 'success' : 'neutral'}>{active?.status || 'Select a source'}</StatusBadge></div>
        {active?.bundle_id && <p className="mt-3 text-xs text-neutral-400">Analysis grain: rows in the selected table. Cross-table joins are unavailable; no totals are combined across tables.</p>}
      </div>
      <div className="flex flex-wrap justify-between gap-3 text-xs text-neutral-400"><span>{state === 'loading' ? 'Refreshing selected metrics…' : refreshedAt ? `Metrics last refreshed: ${refreshedAt}` : 'No successful metric refresh yet'}</span><button className="text-blue-400" disabled={state === 'loading'} onClick={()=>setRetry(value=>value+1)}>Refresh metrics</button></div>
      <FilterBar />
      <div className="flex flex-wrap items-center justify-between gap-3 text-xs text-neutral-400" aria-label="Active filter summary"><span>{Object.keys(filters).length ? `Active filters: ${Object.entries(filters).map(([k, v]) => `${k.replace(/_/g, ' ')} = ${v}`).join(' · ')}` : 'All available records · no active filters'}</span>{Object.keys(filters).length > 0 && <button onClick={resetFilters} className="text-blue-400">Clear all filters</button>}</div>
      {active?.quality.warnings?.length ? <div className="border border-amber-900/60 bg-amber-950/20 rounded-xl p-4 text-sm text-amber-300">{active.quality.warnings.map(w => <p key={w}>{w}</p>)}</div> : null}
      {renderContent()}
      {state === 'ready' && data && <>
        {!!data.product_highlights?.by_revenue?.length && <section className="abi-panel p-5"><h2 className="font-medium">Product performance highlights</h2><p className="text-xs text-neutral-400 mb-4">Top five products per measure · qualifying item prices and item counts · {data.currency_code || 'currency unconfirmed'}. No payments/reviews fan-out.</p><div className="grid lg:grid-cols-2 gap-5">{[['by_revenue','Top products by item revenue','revenue'],['by_quantity','Top products by units sold','quantity']].map(([key,title,value])=><div key={key}><h3>{title}</h3><div className="overflow-auto"><table className="w-full text-sm"><thead><tr><th className="text-left">Product key</th><th className="text-right">{value === 'revenue' ? 'Product revenue' : 'Units'}</th></tr></thead><tbody>{data.product_highlights[key].map((row:any)=><tr key={row.product} className="border-t border-neutral-800"><td className="py-2 break-all">{row.product}</td><td className="text-right">{row[value] == null ? 'Unavailable' : row[value].toLocaleString('en-US',{maximumFractionDigits:2})}</td></tr>)}</tbody></table></div></div>)}</div><Link className="text-blue-400 text-sm" to={'/analytics/products'+location.search}>Open detailed product analysis →</Link></section>}
        <BusinessEvidence domain="revenue" compact />
        {(active.source_type === 'bundle' && active.relational_analysis?.supported || active.source_type === 'warehouse') && <div className="grid xl:grid-cols-2 gap-6"><BusinessEvidence domain="customers" compact /><BusinessEvidence domain="sellers" compact /></div>}
        <ExecutiveOutlook />
        <nav className="abi-panel p-4 flex flex-wrap gap-4 text-sm" aria-label="Investigate business performance">{['sales','products','customers','delivery','sellers'].map(section=><Link key={section} className="text-blue-400 capitalize" to={'/analytics/'+section+location.search}>{section} details →</Link>)}<Link className="text-blue-400" to={'/ml/metrics'+location.search}>Full forecast and model evidence →</Link></nav>
      </>}
      <section className="abi-dashboard-quality"><p className="abi-eyebrow">Source context / before filters</p>
      {active && <div className="grid sm:grid-cols-3 gap-3"><div className="border border-neutral-800 rounded-xl p-4"><p className="text-xs uppercase text-neutral-500">Source volume</p><p className="mt-2 font-semibold">{active.tables ? `${active.row_count.toLocaleString()} source rows · ${active.tables.length} tables · ${active.column_count} table columns` : `${active.row_count.toLocaleString()} rows · ${active.column_count} fields`}</p><p className="text-xs text-neutral-500 mt-1">{active.tables ? 'All separate tables before filters; repeated keys are not business totals' : 'Whole table before filters'}</p></div><div className="border border-neutral-800 rounded-xl p-4"><p className="text-xs uppercase text-neutral-500">Profile quality</p><p className="mt-2">{active.quality.missing_values ?? 'Unknown'} missing values · {active.quality.duplicate_rows ?? 'Unknown'} duplicate rows</p><p className="text-xs text-neutral-500 mt-1">{active.tables ? 'Sum of per-table profiles; duplicates are retained' : 'Whole-table profile; duplicates are retained'}</p></div><div className="border border-neutral-800 rounded-xl p-4"><p className="text-xs uppercase text-neutral-500">Monetary units</p><p className="mt-2">{active.semantics.currency_code || 'Currency unconfirmed'}</p><p className="text-xs text-neutral-500 mt-1">Values retain source units; no conversion</p></div></div>}
      </section>
    </div>
  )
}
