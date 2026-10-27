import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { KpiCard } from '@/components/KpiCard'
import ForecastChart from '@/components/ForecastChart'
import BusinessEvidence from '@/components/BusinessEvidence'
import ForecastQuality from '@/components/ForecastQuality'
import OfflineModelEvaluation from '@/components/OfflineModelEvaluation'
import SeasonalDemoForecast from '@/components/SeasonalDemoForecast'
import { getForecast, getAnalyticsOverview, type ForecastResponse } from '@/services/api'
import { forecastPoints, fullForecastPoints, forecastNumber, forecastYearWindow, trailingYearPoints, type ChartPoint, type ForecastTarget } from '@/services/forecast'
import { useFilters } from '@/hooks/useFilters'
import { useDataset } from '@/hooks/useDataset'
import FilterBar from '@/components/FilterBar'

export function ForecastExperience({ target, onTargetChange }: { target: ForecastTarget; onTargetChange?: (target: ForecastTarget) => void }) {
  const { active, select, busy } = useDataset()
  const Heading = onTargetChange ? 'h2' : 'h1'
  const { filters } = useFilters()
  const [horizon, setHorizon] = useState<number|'year'>('year')
  const [mode, setMode] = useState('latest')
  const requestFilters = useMemo(() => mode === 'latest' ? Object.fromEntries(Object.entries(filters).filter(([key]) => !['date_from', 'date_to'].includes(key))) : filters, [filters, mode])
  const stamp = `${active?.dataset_id}:${active?.updated_at}:${JSON.stringify(filters)}:${target}:${horizon}:${mode}`
  const [result, setResult] = useState<{ stamp: string; points?: ChartPoint[]; reason?: string; model?: { name?: string; version?: string; algorithm?: string }; warnings?: string[]; synthetic?:boolean; unit?:string; coverage?: {from:string;to:string;observed_days:number}; registration?:ForecastResponse['synthetic_registration']; comparison?: {date:string; actual:number|null; predicted:number}[]; comparisonError?:string } | null>(null)
  const currencyCode = result?.unit && /^[A-Z]{3}$/.test(result.unit) ? result.unit : active?.semantics.currency_code
  const unit = target === 'orders' ? 'orders' : currencyCode ? currencyCode : 'source units; currency unverified'
  const format = (n: number) => forecastNumber(n, target, currencyCode)
  useEffect(() => {
    let current = true
    if (active) getForecast(horizon==='year'?365:horizon, target, requestFilters).then(async response => {
      if (!current) return
      // Derive leap-year length from the actual serving origin. Never stretch
      // the first response; request the extra real prediction when required.
      if(horizon==='year'&&response.status!=='not_applicable') {
        const days=forecastYearWindow(response.forecast_origin||response.history_tail[response.history_tail.length-1].date).futureDays
        if(days!==365) {
          response=await getForecast(days,target,requestFilters)
          if(!current)return
        }
      }
      if(response.selected_scope && response.selected_scope.dataset_id!==active.dataset_id) throw new Error('Forecast response scope differs from the selected dataset; stale series discarded.')
      const complete = response.historical_series!==undefined
        ? fullForecastPoints(response.historical_series,response.forecast_series||response.forecast||[],target)
        : response.status==='not_applicable'?[]:forecastPoints(response.history_tail,response.forecast,target)
      const points=trailingYearPoints(complete)
      if (response.status === 'not_applicable') setResult({ stamp, points, registration:response.synthetic_registration, reason: response.reason || 'Model requirements are not satisfied.' })
      else {
        const expected=horizon==='year'?forecastYearWindow(response.forecast_origin||response.history_tail[response.history_tail.length-1].date).futureDays:horizon
        if (response.forecast.length !== expected) throw new Error('The returned horizon does not match the requested daily forecast.')
        if(points.filter(p=>p.forecast!==null).length!==expected) throw new Error('The chart prediction series does not match the requested horizon.')
        let comparison: {date:string; actual:number|null; predicted:number}[] | undefined, comparisonError: string | undefined
        if (mode === 'historical') {
          try {
            const later = await getAnalyticsOverview({...filters, date_from: response.forecast[0].date, date_to: response.forecast[response.forecast.length-1].date, grain:'day'})
            const byDate = new Map<string, number>()
            const observations = later.time_series ?? later.revenue_series
            if (!Array.isArray(observations)) throw new Error('Later observation contract unavailable.')
            for (const point of observations) {
              if (byDate.has(point.period) || typeof point[target] !== 'number' || !Number.isFinite(point[target])) throw new Error('Invalid later observations; no comparison was drawn.')
              byDate.set(point.period, point[target])
            }
            comparison = response.forecast.map(p => ({date:p.date, predicted:p[target]!, actual:byDate.get(p.date) ?? null}))
          } catch { comparisonError = 'Later observed values are unavailable. Missing dates are not filled with zero.' }
        }
        if (!current) return
        const metadata = response as typeof response & {synthetic?:boolean;unit?:string;data_coverage?: {from:string;to:string;observed_days:number}}
        setResult({ stamp, points, registration:response.synthetic_registration, model: response.model, warnings: response.warnings, coverage:metadata.data_coverage, synthetic:metadata.synthetic, unit:metadata.unit, comparison, comparisonError })
      }
    }).catch(error => { if (current) setResult({ stamp, reason: error.message }) })
    return () => { current = false }
  }, [stamp, active, filters, requestFilters, horizon, target, mode])
  const points = useMemo(() => result?.stamp === stamp ? result.points || [] : [], [result, stamp])
  const historical = points.filter(p => p.historical !== null), future = points.filter(p => p.forecast !== null)
  const historyCalendar=points.filter(p=>p.kind==='historical'||(p.kind==null&&p.historical!==null))
  const latest = historical[historical.length - 1], first = future[0], last = future[future.length - 1]
  const total = future.reduce((sum, p) => sum + p.forecast!, 0)
  const prior=historyCalendar.slice(-future.length)
  const baseline = future.length && prior.length===future.length && prior.every(p=>p.historical!==null) ? prior.reduce((sum,p)=>sum+p.historical!,0) : null
  const change = baseline != null && baseline > 0 ? (total / baseline - 1) * 100 : null
  const negative = future.some(p => p.forecast! < 0)
  return <div className="space-y-5">
    <div className="flex flex-wrap gap-4 justify-between items-start">
      <div><Heading className="text-2xl font-semibold">{target === 'orders' ? 'Order Forecast' : 'Revenue Forecast'}</Heading><p className="text-sm text-neutral-400 mt-1">{active?.dataset_name || 'Select a dataset'} · genuine daily model inference{target==='revenue' ? ` · ${unit}` : ''}</p></div>
      <div className="flex flex-wrap gap-3 items-center">
        {onTargetChange && <label className="text-sm">Forecast target <select aria-label="Forecast target" className="bg-neutral-900 border border-neutral-700 rounded p-2 ml-2" value={target} onChange={e => onTargetChange(e.target.value as ForecastTarget)}><option value="orders">Orders</option><option value="revenue">Revenue</option></select></label>}
        <label className="text-sm">Horizon <select aria-label="Forecast horizon" className="bg-neutral-900 border border-neutral-700 rounded p-2 ml-2" value={horizon} onChange={e => setHorizon(e.target.value==='year'?'year':Number(e.target.value))}><option value="year">1 Year (365/366 Days)</option>{[7, 14, 30, 90].map(n => <option value={n} key={n}>{n} Days</option>)}</select></label>
        <label className="text-sm">Origin mode <select aria-label="Forecast origin mode" className="bg-neutral-900 border border-neutral-700 rounded p-2 ml-2" value={mode} onChange={e => setMode(e.target.value)}><option value="selected">Selected date scope</option><option value="latest">Latest-data forecast</option><option value="historical">Historical comparison</option></select></label>
      </div>
      {change != null && <p className="text-sm text-neutral-300">Model-estimated change versus the preceding {future.length} observed days: {change.toFixed(2)}%. Equal-length adjacent windows; this is a forecast comparison, not realized growth.</p>}
    </div>
    {target === 'revenue' && !currencyCode && <p role="note" className="text-xs text-amber-300">The source currency is unverified. Values use neutral numeric formatting; no currency conversion is performed.</p>}
    <p className="text-xs text-neutral-400">{mode === 'latest' ? 'Latest-data mode removes date filters for this request and retains all other selected-scope filters. An incomplete latest window blocks inference.' : mode === 'historical' ? 'Historical comparison uses the selected date cutoff, then requests later observed values with the same dimension filters. Original fit cutoff is unverified: this is not an independent holdout accuracy claim.' : 'Selected date filters set the historical forecast origin; they do not move old observations to today.'}</p>
    {!active ? <p>Select a dataset in <Link to="/datasets">Dataset Manager</Link>.</p> : result?.stamp !== stamp ? <p role="status">Running forecast model…</p> : <>
      {result.registration && result.registration.status!=='matches' && <section aria-label="Registered forecast dataset" className="abi-panel p-5 space-y-3">
        <p>Current selection: {active.dataset_name}. {result.registration.status==='different_dataset'?'This selection does not match the registered synthetic model scope.':result.registration.status==='revision_mismatch'?'The registered bundle revision no longer matches. Source verification is required.':'No synthetic forecast registry is configured in this API process.'}</p>
        {result.registration.datasets.map(ds=><div key={ds.dataset_id}><p>Registered compatible bundle: {ds.dataset_name} · {ds.table}</p><button className="text-blue-400" disabled={busy} onClick={()=>void select(ds.dataset_id).catch(()=>{})}>Select {ds.dataset_name} for forecasting</button></div>)}
        <p className="text-xs text-neutral-400">Your dataset stays selected until you choose another. No predictions from a different bundle are displayed. You can also use Active Dataset → Bundle overview.</p>
      </section>}
      {result.reason&&<div role="status" className="abi-panel p-5"><h3>Not Applicable</h3><p className="text-xs text-neutral-400">Forecast unavailable for this selection; recorded history remains visible when supported.</p><p>{result.reason}</p><Link className="text-blue-400 text-sm" to="/datasets">Review dataset mapping and coverage →</Link></div>}
      {future.length>0&&<>
      <div className="grid sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <KpiCard label={target === 'orders' ? 'Latest Actual Orders' : `Latest Actual Revenue · ${unit}`} value={format(latest.historical!)} hint={latest.date} />
        <KpiCard label={target === 'orders' ? 'First future prediction' : `First Forecast Revenue · ${unit}`} value={format(first.forecast!)} hint={first.date} />
        <KpiCard label={target === 'orders' ? 'Horizon-end prediction' : `Horizon-end Forecast Revenue · ${unit}`} value={format(last.forecast!)} hint={last.date} />
        <KpiCard label={target === 'orders' ? `Forecast total (${future.length}d)` : `Forecast Revenue total (${future.length}d) · ${unit}`} value={format(total)} hint={`Daily average ${format(total / future.length)} · ${unit}`} />
      </div>
      <p className="text-xs text-neutral-400">{result?.synthetic ? `Experimental synthetic-data forecast · ${result.model?.algorithm}` : 'Model: Linear Regression (Daily)'}</p>
      <p className="text-xs text-neutral-400">Serving artifact: {result?.model?.algorithm || 'algorithm not returned'} · version {result?.model?.version || 'not returned'}</p>
      <p className="text-sm">Forecast origin / last actual: {latest.date}. Prediction dates: {first.date}–{last.date}. Horizon: {future.length} daily estimates. Display: trailing calendar year. Source coverage: {result?.coverage ? `${result.coverage.from}–${result.coverage.to} (${result.coverage.observed_days} observed days)` : 'Full source coverage metadata unavailable'}.</p>
      {Date.now() - latest.time > 90 * 86400000 && <p role="status" className="text-amber-400">Old data warning: this forecast starts after {latest.date}, not today. It does not establish current business activity.</p>}
      <p className="text-xs text-amber-400">Experimental/unqualified model output. Annual forecast accuracy is unvalidated; no calibrated intervals. {unit}.</p>
      {result?.warnings?.length ? <details className="text-xs text-amber-400"><summary>Forecast provenance, coverage and quality warnings</summary>{result.warnings.map(warning=><p className="mt-2" key={warning}>{warning}</p>)}</details> : null}
      </>}
      {points.length>0&&<ForecastChart points={points} format={format} unit={unit} scope={active.dataset_name} model={result.model} experimental={result.synthetic} />}
      {mode === 'historical' && <section className="abi-panel p-4 space-y-2"><h3>Historical comparison · not independent validation</h3><p className="text-xs">Actuals are matched by date after the selected origin. Unknown/missing values remain unavailable. The original artifact fit cutoff is unverified, so these are not certified out-of-sample results.{target === 'revenue' ? ` Revenue values use ${unit}; no conversion is performed.` : ''}</p>{result?.comparisonError && <p role="status">{result.comparisonError}</p>}<div className="overflow-auto max-h-64"><table className="w-full text-sm"><thead><tr><th>Date</th><th>{target === 'orders' ? 'Later observed actual' : `Later observed actual · ${unit}`}</th><th>{target === 'orders' ? 'Model estimate' : `Model estimate · ${unit}`}</th></tr></thead><tbody>{result?.comparison?.map(row => <tr key={row.date}><td>{row.date}</td><td>{row.actual == null ? 'Unavailable' : format(row.actual)}</td><td>{format(row.predicted)}</td></tr>)}</tbody></table></div></section>}
      {negative && <p role="status" className="text-amber-400">The existing unconstrained model returned negative estimates. They are shown unchanged and require review before business use.</p>}
      {historyCalendar.length>0&&<p className="text-xs text-neutral-400">Historical window: {historyCalendar[0].date}–{historyCalendar[historyCalendar.length-1].date}. Historical points: {historyCalendar.length}; prediction points: {future.length}. {first&&`Forecast: ${first.date}–${last.date}.`} No aligned out-of-sample prediction series or validated intervals are returned, so neither is plotted. Offline evaluation remains in the model catalog.</p>}
      {future.length>0&&<section className="abi-panel p-4"><h3 className="mb-3 font-medium">Forecast Data Table</h3><div className="overflow-auto max-h-64"><table aria-label="Forecast data" className="w-full text-sm"><thead><tr><th className="text-left p-2">Date</th><th className="text-right">{target === 'orders' ? `Future forecast · ${unit}` : `Forecast Revenue · ${unit}`}</th></tr></thead><tbody>{future.map(p => <tr key={p.date}><td className="p-2">{p.date}</td><td className="text-right font-mono">{format(p.forecast!)}</td></tr>)}</tbody></table></div></section>}
    </>}
    {active && <ForecastQuality target={target} />}
    <SeasonalDemoForecast key={target} initialTarget={target} />
    <OfflineModelEvaluation />
    {target === 'revenue' && <BusinessEvidence domain="revenue" />}
    <details className="abi-panel p-4"><summary>Model coverage and limitations</summary><p className="text-xs text-neutral-400 mt-3">The registered synthetic/extended bundle uses its separate versioned preview model with past-only lag, rolling and calendar features. Its source-unit revenue contract applies only to the audited imported bundle; other datasets retain the existing commerce/BRL contract. At least 30 consecutive daily observations are required. No unknown date or missing revenue is silently zero-filled. Date and dimension filters select inference history; chart grain does not change daily model inputs. With no date filter the forecast starts after the latest eligible selected-scope observation. Dates may precede today. Predictions are uncertain estimates. No customer-volume or seller-delay model is registered.</p></details>
  </div>
}

export default function RevenueForecast({ target = 'revenue' }: { target?: ForecastTarget }) {
  const { active } = useDataset()
  return <div className="space-y-6"><FilterBar /><ForecastExperience key={`${active?.dataset_id}:${active?.updated_at}`} target={target} /></div>
}
export function OrderForecast() { return <RevenueForecast target="orders" /> }
