import { useEffect, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { getBusinessEvidence, type BusinessEvidenceResponse } from '@/services/api'
import { useDataset } from '@/hooks/useDataset'
import { useFilters } from '@/hooks/useFilters'
import { formatMetricNumber, forecastNumber } from '@/services/forecast'
import { KpiCard } from './KpiCard'

export default function BusinessEvidence({ domain, compact = false }: { domain: 'revenue' | 'customers' | 'sellers'; compact?: boolean }) {
  const { active } = useDataset(), { filters } = useFilters()
  const stamp = `${active?.dataset_id}:${active?.updated_at}:${JSON.stringify(filters)}:${domain}`
  const [result, setResult] = useState<{ stamp: string; data?: BusinessEvidenceResponse; error?: string } | null>(null)
  useEffect(() => {
    let current = true
    if (active) getBusinessEvidence(domain, filters).then(data => { if (current) setResult({ stamp, data }) }).catch(error => { if (current) setResult({ stamp, error: error.message }) })
    return () => { current = false }
  }, [stamp, domain, filters, active])
  if (!active) return null
  const data = result?.stamp === stamp ? result.data : undefined
  return <section aria-label={`${domain} business evidence`} className="space-y-4 min-w-0">
    <div><h2 className="text-xl font-medium">{domain === 'sellers' ? 'Seller Delivery Performance' : domain === 'customers' ? 'Customer retention signals' : 'Revenue observations and actions'}</h2><p className="text-sm text-neutral-400">Observed analysis of {active.dataset_name}. {domain !== 'revenue' && 'No approved future-volume or delay forecasting model is available.'}</p></div>
    {result?.stamp === stamp && result.error ? <p role="alert">Evidence unavailable: {result.error}</p> : !data ? <p role="status">Calculating selected-data evidence…</p> : <>
      <p className="text-xs text-neutral-400">{data.measurement_window || 'Current selected dates'} · {data.source} · {data.currency_code || 'currency unconfirmed; values shown in source units'}</p>
      <div className="grid sm:grid-cols-3 gap-4">{data.cards.filter(card => typeof card.value === 'number' && Number.isFinite(card.value)).map(card => <KpiCard key={card.label} label={card.label} value={domain === 'revenue' ? forecastNumber(card.value!, 'revenue', data.currency_code) : formatMetricNumber(card.value)} />)}</div>
      {domain === 'customers' && !!data.series.length && <div className="abi-panel p-5 min-w-0 overflow-hidden"><h3>First-time versus returning customer item revenue</h3><p className="text-xs text-neutral-400 mb-4">Monthly, using the first observed purchase in the complete dataset · {data.currency_code || 'currency unconfirmed'}</p><ResponsiveContainer width="100%" height={270}><BarChart data={compact ? data.series.slice(-6) : data.series}><CartesianGrid stroke="rgb(var(--border))" /><XAxis dataKey="period" minTickGap={35} /><YAxis /><Tooltip contentStyle={{ background: 'rgb(var(--surface-raised))' }} /><Legend /><Bar isAnimationActive={false} dataKey="first_time" name="First-time revenue" stackId="revenue" fill="var(--chart-1)" /><Bar isAnimationActive={false} dataKey="returning" name="Returning revenue" stackId="revenue" fill="var(--chart-3)" /></BarChart></ResponsiveContainer></div>}
      {!compact && domain === 'customers' && !!data.frequency?.length && <div className="abi-panel p-5"><h3>Customer purchase frequency</h3><ResponsiveContainer width="100%" height={240}><BarChart data={data.frequency}><XAxis dataKey="orders" label={{ value: 'Distinct matching orders', position: 'insideBottom', offset: -4 }} height={45} /><YAxis /><Tooltip /><Bar isAnimationActive={false} dataKey="customers" fill="var(--chart-2)" /></BarChart></ResponsiveContainer></div>}
      {domain === 'sellers' && !!data.rankings.length && <div className="abi-panel p-5 overflow-auto"><h3>Seller late-delivery ranking · minimum 20 eligible orders</h3><table className="w-full text-sm mt-4"><thead><tr><th className="text-left">Seller group</th><th>Eligible orders</th><th>Late orders</th><th>Late rate</th><th>Mean late days</th></tr></thead><tbody>{(compact ? data.rankings.slice(0,5) : data.rankings).map(row => <tr className="border-t border-neutral-800" key={row.label}><td className="p-2 break-all">{row.label}</td><td className="text-center">{row.orders}</td><td className="text-center">{row.late}</td><td className="text-center">{row.value.toFixed(2)}%</td><td className="text-center">{row.mean_late_days?.toFixed(2) ?? 'Unavailable'}</td></tr>)}</tbody></table></div>}
      {data.recommendations.length ? <div className="grid lg:grid-cols-2 gap-4">{(compact ? data.recommendations.slice(0,1) : data.recommendations).map(rec => <article key={rec.id} className="abi-panel p-5 space-y-2"><p className="abi-eyebrow">Evidence priority: {rec.priority}</p><h3 className="font-medium">{rec.title}</h3><p>{rec.observation}</p><p className="text-sm text-neutral-300">Suggested action: {rec.suggested_action}</p><p className="text-xs text-neutral-400">Window: {rec.measurement_window} · {rec.metric_source}</p><p className="text-xs text-neutral-400">{rec.limitations}</p><details><summary>Measured evidence</summary><pre className="overflow-auto text-xs mt-2">{JSON.stringify(rec.evidence, null, 2)}</pre></details></article>)}</div> : <p role="status" className="text-sm text-neutral-400">No actionable signal meets the evidence rules for this selection.</p>}
      <div className="text-xs text-neutral-400 space-y-1">{data.limitations.map(note => <p key={note}>{note}</p>)}</div>
    </>}
  </section>
}
