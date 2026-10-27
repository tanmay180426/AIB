import { PageHeader } from '@/components/ui/Workspace'
import { useEffect, useRef, useState } from 'react'
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from 'recharts'
import { forecastDate } from '@/services/forecast'
import FilterBar from '@/components/FilterBar'
import { useFilters } from '@/hooks/useFilters'
import { getAnomalies, getCustomerSegments, getRequestContext, predictSales,
  type AnomaliesResponse, type CustomerSegmentsResponse, type SalesPredictionResponse } from '@/services/api'

function useResults<T>(load: (filters: Record<string, string>) => Promise<T>) {
  const { filters } = useFilters()
  const [result, setResult] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let current = true
    setResult(null); setError(null)
    load(filters).then(value => { if (current) setResult(value) })
      .catch(e => { if (current) setError(e instanceof Error ? e.message : 'Model request failed.') })
    return () => { current = false }
  }, [filters, load])
  return { result, error }
}

function Outcome({ result, error }: { result: { status: string; reason?: string } | null; error: string | null }) {
  if (error) return <p role="alert" className="text-red-400">{error}</p>
  if (!result) return <p role="status">Running model…</p>
  if (result.status === 'not_applicable') return <section role="status"><h2>Not Applicable</h2><p>{result.reason}</p></section>
  return null
}

export function CustomerSegments() {
  const { result, error } = useResults<CustomerSegmentsResponse>(getCustomerSegments)
  return <div className="space-y-4"><FilterBar /><PageHeader title="Customer Segments" />
    <p>Saved K-Means model and scaler applied to customer recency, order frequency and monetary value in the selected dataset.</p>
    <Outcome result={result} error={error} />
    {result?.status === 'available' && result.segments.length > 0 && <section className="abi-panel p-5 min-w-0"><h2>Observed customers by trained segment</h2><p className="text-xs text-neutral-400 mb-4">Cluster membership from the saved RFM scaler and K-Means model. Segments are not future customer counts.</p><ResponsiveContainer width="100%" height={260}><BarChart data={result.segments}><CartesianGrid stroke="rgb(var(--border))" /><XAxis dataKey="segment" /><YAxis allowDecimals={false} /><Tooltip contentStyle={{background:'rgb(var(--surface-raised))'}} /><Bar isAnimationActive={false} dataKey="customers" fill="var(--chart-1)" /></BarChart></ResponsiveContainer></section>}
    {result?.status === 'available' && <table className="w-full text-sm"><thead><tr><th scope="col">Segment</th><th scope="col">Customers</th><th scope="col">Monetary total (BRL)</th></tr></thead>
      <tbody>{result.segments.map(s => <tr key={s.segment}><td>{s.segment}</td><td>{s.customers}</td><td>{s.monetary.toLocaleString()}</td></tr>)}</tbody></table>}
  </div>
}

export function Anomalies() {
  const { result, error } = useResults<AnomaliesResponse>(getAnomalies)
  return <div className="space-y-4"><FilterBar /><PageHeader title="Anomaly Detection" />
    <p>Saved Isolation Forest applied to daily orders and revenue after selected filters. Scores are decision-function values, not probabilities.</p>
    <Outcome result={result} error={error} />
    {result?.status === 'available' && <><p role="status" aria-label="Anomaly summary">{result.n_anomalies} anomalous days out of {result.n_days} analyzed.</p>
      {result.anomalies.length > 0 && <section className="abi-panel p-5 min-w-0"><h2>Observed anomaly timeline</h2><p className="text-xs text-neutral-400 mb-4">Up to 100 flagged days returned by the existing model, sorted by date for display. Omitted days are not plotted as zero. Decision scores are not probabilities.</p><ResponsiveContainer width="100%" height={280}><ScatterChart><CartesianGrid stroke="rgb(var(--border))" /><XAxis dataKey="time" name="Date" type="number" domain={['dataMin','dataMax']} tickFormatter={forecastDate} minTickGap={65} /><YAxis dataKey="score" type="number" name="Decision score" /><Tooltip formatter={(value: number, name: string) => name === 'Date' ? [forecastDate(value),name] : [value,name]} contentStyle={{background:'rgb(var(--surface-raised))'}} /><Scatter isAnimationActive={false} name="Flagged days" data={result.anomalies.map(point => ({...point,time:Date.parse(`${point.date}T00:00:00Z`)})).sort((a,b)=>a.time-b.time)} fill="var(--chart-3)" /></ScatterChart></ResponsiveContainer></section>}
      {result.anomalies.length ? <table className="w-full text-sm"><thead><tr><th scope="col">Date</th><th scope="col">Orders</th><th scope="col">Revenue (BRL)</th><th scope="col">Score</th></tr></thead>
        <tbody>{result.anomalies.map(a => <tr key={a.date}><td>{a.date}</td><td>{a.orders}</td><td>{a.revenue.toLocaleString()}</td><td>{a.score.toFixed(4)}</td></tr>)}</tbody></table>
        : <p>No anomalous days were returned for the selected filters.</p>}</>}
  </div>
}

export function SalesPrediction() {
  const { filters } = useFilters()
  const [result, setResult] = useState<SalesPredictionResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const generation = useRef(0)
  useEffect(() => {
    generation.current += 1; setResult(null); setError(null); setBusy(false)
    return () => { generation.current += 1 }
  }, [filters])
  const submit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const context = getRequestContext()
    const operation = ++generation.current
    const current = () => operation === generation.current && context === getRequestContext()
    setBusy(true); setResult(null); setError(null)
    try {
      const response = await predictSales({ purchase_month: Number(form.get('purchase_month')),
        purchase_weekday: Number(form.get('purchase_weekday')), purchase_hour: Number(form.get('purchase_hour')),
        n_items: Number(form.get('n_items')), customer_state: String(form.get('customer_state')),
        product_category_name: String(form.get('product_category_name')) }, filters)
      if (current()) setResult(response)
    } catch (e) { if (current()) setError(e instanceof Error ? e.message : 'Prediction failed.') }
    finally { if (current()) setBusy(false) }
  }
  return <div className="space-y-4"><FilterBar /><PageHeader title="Sales Prediction" />
    <p>Enter checkout features for the existing item-revenue model. The selected dataset must satisfy the trained commerce and BRL contract. Shared filters check input compatibility; the estimate uses the checkout features entered below.</p>
    <form onSubmit={e => void submit(e)} className="grid sm:grid-cols-2 gap-3">
      {[['purchase_month', 'Purchase month', 1, 12], ['purchase_weekday', 'Purchase weekday (Monday = 0)', 0, 6],
        ['purchase_hour', 'Purchase hour', 0, 23], ['n_items', 'Basket item count', 1, undefined]].map(([name, label, min, max]) =>
        <label key={String(name)} className="flex flex-col">{label}<input name={String(name)} aria-label={String(label)} type="number" min={min} max={max} step="1" required className="bg-neutral-900 p-2 rounded" /></label>)}
      <label className="flex flex-col">Customer state<input name="customer_state" required className="bg-neutral-900 p-2 rounded" /></label>
      <label className="flex flex-col">Product category<input name="product_category_name" required className="bg-neutral-900 p-2 rounded" /></label>
      <button disabled={busy} className="bg-blue-600 p-2 rounded disabled:opacity-50">{busy ? 'Predicting…' : 'Predict item revenue'}</button>
    </form>
    {error && <p role="alert" className="text-red-400">{error}</p>}
    {result?.status === 'not_applicable' && <section role="status"><h2>Not Applicable</h2><p>{result.reason}</p></section>}
    {result?.status === 'available' && <p role="status" aria-label="Sales prediction result">Predicted item revenue: {result.predicted_item_revenue.toLocaleString()} {result.currency}</p>}
  </div>
}
