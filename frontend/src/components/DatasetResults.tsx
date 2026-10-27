import { Cell, Pie, PieChart, Legend, Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Link } from 'react-router-dom'

import { KpiCard } from '@/components/KpiCard'

import SpecialistCharts, { type SpecialistChart } from './SpecialistCharts'



interface Results {

  kpis?: { total_revenue?: number | null; total_orders?: number | null; avg_delivery_days?: number | null; completed_delivery_orders?: number | null; delivery_completion_pct?: number | null }

  product_highlights?: { by_revenue: { product: string; revenue: number; quantity: number }[]; by_quantity: { product: string; revenue: number; quantity: number }[] }

  specialist_charts?: SpecialistChart[]

  grain?: string

  date_range?: {min:string|null;max:string|null}
  order_series_quality?: { available: boolean; reason?: string | null; order_observations?: number; date_observations?: number; order_count_field?: string | null }
  provenance?: { rows: number; origin_field?: string | null; origins?: { value: string; rows: number }[]; synthetic_field?: string | null; synthetic_rows?: number | null; synthetic_share_pct?: number | null }

  currency_code?: string | null

  status: string; reason?: string; dataset_name?: string

  metric_cards: { label: string; value: number | null }[]

  numeric_statistics?: { field: string; count: number; sum: number | null; mean: number | null; median: number | null; min: number | null; max: number | null }[]

  distributions?: { field: string; measure?: 'rows' | 'amount'; series: { label: string; rows: number; amount?: number }[] }[]

  time_series?: { period: string; rows: number; revenue?: number; amount?: number }[]

  entities?: { label: string; rows: number; amount?: number }[]

}

const format = (v: number | null | undefined) => v == null ? 'No observed values' : v.toLocaleString('en-US', { maximumFractionDigits: 2 })



/** Semantic content slot reused inside the existing dashboard and analytics pages. */

export default function DatasetResults({ data, dashboard = false, monetaryFields = [], revenueAvailable }: { data: Results; dashboard?: boolean; monetaryFields?: string[]; revenueAvailable?: boolean }) {

  if (data.status === 'not_applicable') return <div role="status" className="abi-panel border border-neutral-800 rounded-lg p-5"><h2 className="font-medium">Not available for this dataset.</h2><p className="text-neutral-400 mt-2">{data.reason}</p></div>

  const monetary = (label: string) => monetaryFields.some(field => label === field || label === `Total ${field}` || label === `Average ${field}`)

  const priority = (label: string) => monetary(label) ? 0 : label.startsWith('Total ') || label.startsWith('Average ') ? 2 : 1

  const executive=['Item revenue','Distinct orders','Average order value','Items sold','Unique customers','Active sellers']

  const usefulCards = data.metric_cards.filter(card => {
    const normalized = card.label.replace(/[^a-z0-9]/gi, '').toLowerCase()
    const technical = ['generationseed','sourcedataflag','sourceflag','dataorigin','datasource','generationversion','syntheticversion','synthetic','issynthetic','syntheticflag','generationflag','generatedflag','rowid','index'].includes(normalized) || normalized.endsWith('generationseed')
    return !technical && typeof card.value === 'number' && Number.isFinite(card.value)
  })
  const cards = dashboard && data.grain === 'orders' ? executive.flatMap(label=>usefulCards.filter(card=>card.label===label)) : dashboard ? [...usefulCards].sort((a, b) => priority(a.label) - priority(b.label)).slice(0, 8) : usefulCards

  const definitions: Record<string,string> = {'Item revenue':'Sum of qualifying item prices; excludes freight and payments.','Distinct orders':'Distinct matching order_id values.','Average order value':'Qualifying item revenue / matching distinct orders.','Items sold':'Count of validated matching item rows, not order count.','Unique customers':'Distinct customer_unique_id through the validated customer relationship.','Active sellers':'Distinct seller_id on matching items.'}

  const orderSeries=data.time_series as ({ period:string; orders?:number|null }[] | undefined)

  return <div className="space-y-6">

    <p className="text-sm text-neutral-400">Calculated from {data.dataset_name} with the current filters.</p>

    {((data.provenance?.synthetic_rows || 0) > 0 || (data.provenance?.origins?.length || 0) > 0) && <p role="note" className="text-xs text-amber-300">Provenance: {data.provenance?.synthetic_rows != null ? `${data.provenance.synthetic_rows.toLocaleString()} of ${data.provenance.rows.toLocaleString()} rows (${data.provenance.synthetic_share_pct}%) are marked synthetic` : 'source labels are available'}. {(data.provenance?.synthetic_rows || 0) > 0 ? 'Generated rows are not verified transactions.' : 'Origin labels are input metadata, not independently verified provenance.'}{data.provenance?.origins?.length ? ` ${data.provenance.origins.map(origin=>`${origin.value}: ${origin.rows.toLocaleString()}`).join(' · ')}` : ''}</p>}

    {data.date_range?.min && data.date_range.max && <p className="text-sm text-neutral-400">Source date coverage: {data.date_range.min.slice(0,10)} to {data.date_range.max.slice(0,10)}</p>}

    {!!cards.length && <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">{cards.map(c => <KpiCard key={c.label} label={c.label} value={monetary(c.label) && data.currency_code ? new Intl.NumberFormat('en-US', { style: 'currency', currency: data.currency_code }).format(c.value!) : format(c.value)} hint={dashboard ? `${definitions[c.label] || `Observed values in ${data.grain === 'orders' ? 'matching bundle scope' : 'selected table'} and filters`}${monetary(c.label) && !data.currency_code ? ' · currency unconfirmed' : ''}` : undefined} />)}</div>}

    {dashboard && data.grain==='orders' && <div className="grid sm:grid-cols-3 gap-4">{data.kpis?.avg_delivery_days!=null && <KpiCard label="Average observed delivery time" value={`${format(data.kpis.avg_delivery_days)} days`} hint="Observed delivery minus purchase; excludes missing and negative intervals."/>}{data.kpis?.completed_delivery_orders!=null && <KpiCard label="Valid completed deliveries" value={format(data.kpis.completed_delivery_orders)} hint="Delivered status and valid nonnegative purchase-to-delivery interval."/>}{data.kpis?.delivery_completion_pct!=null && <KpiCard label="Delivery completion coverage" value={`${format(data.kpis.delivery_completion_pct)}%`} hint="Valid completed deliveries / all matching orders. Missing dates are excluded from the numerator."/>}</div>}
    {!!data.specialist_charts?.length && <SpecialistCharts charts={data.specialist_charts} currency={data.currency_code} />}

    {dashboard && <div className="flex flex-wrap gap-3 text-sm text-neutral-400 border-l-2 border-blue-500 pl-4"><span>{data.grain === 'orders' ? 'Measures use validated bundle relationships and order-grain aggregates.' : 'Measures use the current table only.'}</span>{!(revenueAvailable ?? data.metric_cards.some(c => /revenue/i.test(c.label))) && <span>Revenue unavailable: no revenue field is confirmed.</span>}{data.currency_code && <span>Currency: {data.currency_code}</span>}</div>}

    {data.metric_cards[0]?.value === 0 && <p role="status">No rows match the selected filters.</p>}

    {!!data.time_series?.length && <div className="min-w-0 overflow-hidden abi-panel border border-neutral-800 rounded-xl p-5"><h2 className="mb-1 font-medium">{dashboard && data.time_series.some(p=>p.revenue!=null) ? 'Observed revenue over time' : 'Time trend'}</h2><p className="mb-4 text-xs text-neutral-400">Observed {data.time_series.some(p => p.revenue != null) ? 'revenue' : data.time_series.some(p => p.amount != null) ? 'amount' : 'row count'} by period{data.currency_code ? ` · ${data.currency_code}` : data.time_series.some(p=>p.revenue!=null) ? ' · currency unconfirmed' : ''}</p>

      <ResponsiveContainer width="100%" height={260}><LineChart data={data.time_series} margin={{ top: 10, bottom: 20 }}><CartesianGrid stroke="rgb(var(--border))" /><XAxis dataKey="period" stroke="rgb(var(--muted))" label={{ value: 'Period', position: 'insideBottom', offset: -15, fill: 'rgb(var(--muted))' }} /><YAxis stroke="rgb(var(--muted))" /><Tooltip contentStyle={{ background: 'rgb(var(--surface-raised))', border: '1px solid rgb(var(--border))' }} /><Line isAnimationActive={false} dataKey={data.time_series.some(p => p.revenue != null) ? 'revenue' : data.time_series.some(p => p.amount != null) ? 'amount' : 'rows'} stroke="var(--chart-1)" dot={data.time_series.length===1?{r:3}:false} /></LineChart></ResponsiveContainer>

    </div>}

    {dashboard && !!orderSeries?.some(point=>point.orders!=null) && <section className="abi-panel p-5 min-w-0 overflow-hidden"><h2 className="font-medium">Observed order volume</h2><p className="text-xs text-neutral-400 mb-4">{data.order_series_quality?.order_count_field ? 'Summed mapped daily order counts' : 'Distinct matching order IDs'} by the selected chart grain. Realized history only.</p>{data.order_series_quality?.reason && <p role="note" className="text-xs text-amber-300 mb-3">{data.order_series_quality.reason}</p>}<ResponsiveContainer width="100%" height={260}><LineChart data={orderSeries}><CartesianGrid stroke="rgb(var(--border))"/><XAxis dataKey="period" minTickGap={45}/><YAxis allowDecimals={false}/><Tooltip contentStyle={{background:'rgb(var(--surface-raised))'}}/><Line isAnimationActive={false} dataKey="orders" name="Observed orders" stroke="var(--chart-2)" dot={{r:2}} /></LineChart></ResponsiveContainer></section>}
    {dashboard && !orderSeries?.some(point=>point.orders!=null) && <section className="abi-panel border border-dashed border-neutral-700 rounded-xl p-5" aria-label="Order chart unavailable"><h2 className="font-medium">Order volume chart unavailable</h2><p className="text-sm text-neutral-400 mt-2">{data.order_series_quality?.reason || 'A confirmed order identifier or daily order-count field and date field are required. No missing values are displayed as zero.'}</p><Link className="inline-block mt-3 text-sm text-blue-400" to="/datasets">Review date and order field mappings →</Link></section>}

    {dashboard && !data.time_series?.length && <div className="border border-dashed border-neutral-700 rounded-xl p-6"><h2 className="font-medium">Time trend unavailable</h2><p className="text-sm text-neutral-400 mt-1">A validated date field and matching observations are required. Confirm the table schema or change filters.</p></div>}

    <div className="grid md:grid-cols-2 gap-4">{data.distributions?.map(d => <div key={d.field} className="min-w-0 overflow-hidden abi-panel border border-neutral-800 rounded-lg p-4"><h2 className="mb-4 font-medium">{d.measure === 'amount' ? 'Category item revenue' : `${d.field} distribution`}</h2>

      <p className="text-xs text-neutral-400 mb-2">{d.measure === 'amount' ? `Qualifying item prices · ${data.currency_code || 'currency unconfirmed'}` : `Matching rows by ${d.field}`}</p><ResponsiveContainer width="100%" height={d.measure === 'amount' ? 340 : 240}>{d.field === 'order status' ? <PieChart><Pie isAnimationActive={false} data={d.series} dataKey="rows" nameKey="label" innerRadius={55} outerRadius={80}>{d.series.map((row, i) => <Cell key={row.label} fill={`var(--chart-${i % 7 + 1})`} />)}</Pie><Tooltip formatter={(value: number) => `${format(value)} orders · ${d.series.reduce((sum,row)=>sum+row.rows,0) > 0 ? (value/d.series.reduce((sum,row)=>sum+row.rows,0)*100).toFixed(2) : '—'}%`} contentStyle={{ background: 'rgb(var(--surface-raised))' }} /><Legend /></PieChart> : <BarChart data={d.series} layout={d.measure === 'amount' ? 'vertical' : 'horizontal'}><CartesianGrid stroke="rgb(var(--border))" /><XAxis type={d.measure === 'amount' ? 'number' : 'category'} dataKey={d.measure === 'amount' ? undefined : 'label'} stroke="rgb(var(--muted))" /><YAxis type={d.measure === 'amount' ? 'category' : 'number'} dataKey={d.measure === 'amount' ? 'label' : undefined} width={d.measure === 'amount' ? 135 : 60} tick={d.measure === 'amount' ? {fontSize:10} : undefined} interval={d.measure === 'amount' ? 0 : undefined} allowDecimals={false} stroke="rgb(var(--muted))" /><Tooltip contentStyle={{ background: 'rgb(var(--surface-raised))', border: '1px solid rgb(var(--border))' }} /><Bar isAnimationActive={false} dataKey={d.measure || 'rows'} fill="var(--chart-1)" /></BarChart>}</ResponsiveContainer>

      {dashboard && d.field === 'order status' && <ul className="flex flex-wrap gap-3 text-xs text-neutral-400 mt-3" aria-label="Order status shares">{d.series.map(row=><li key={row.label}>{row.label || 'Missing status'} · {format(row.rows)} orders · {d.series.reduce((sum,r)=>sum+r.rows,0) > 0 ? (row.rows/d.series.reduce((sum,r)=>sum+r.rows,0)*100).toFixed(2) : '—'}%</li>)}</ul>}

    </div>)}</div>

    {!!data.numeric_statistics?.length && <div className="overflow-auto border border-neutral-800 rounded-lg"><table className="w-full text-sm text-left"><thead className="bg-neutral-900"><tr>{['Field', 'Count', 'Total', 'Average', 'Median', 'Min', 'Max'].map(h => <th className="p-3" key={h}>{h}</th>)}</tr></thead><tbody>{data.numeric_statistics.map(s => <tr key={s.field} className="border-t border-neutral-800"><td className="p-3">{s.field}</td>{[s.count, s.sum, s.mean, s.median, s.min, s.max].map((v, i) => <td className="p-3" key={i}>{format(v)}</td>)}</tr>)}</tbody></table></div>}

    {!!data.entities?.length && <div className="overflow-auto border border-neutral-800 rounded-lg"><table className="w-full text-sm text-left"><thead><tr><th className="p-3">Entity</th><th>Rows</th><th>Amount</th>{dashboard && data.grain === 'orders' && <th>Share of all selected item revenue</th>}</tr></thead><tbody>{data.entities.map(r => <tr key={r.label}><td className="p-3">{r.label}</td><td>{r.rows}</td><td>{format(r.amount)}</td>{dashboard && data.grain === 'orders' && <td>{r.amount != null && data.kpis?.total_revenue != null && data.kpis.total_revenue > 0 ? `${(r.amount / data.kpis.total_revenue * 100).toFixed(2)}%` : 'Unavailable'}</td>}</tr>)}</tbody></table></div>}

  </div>

}
