import { useEffect, useMemo, useState } from 'react'
import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { getSeasonalDemoForecast, type SeasonalDemoResponse } from '@/services/api'

type Target = 'orders' | 'revenue'
type MetricRow = Record<string, string | number | boolean | null> | null

function metric(row: MetricRow, key: string) {
  const value = row?.[key]
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

export default function SeasonalDemoForecast({ initialTarget = 'orders' }: { initialTarget?: Target }) {
  const [target, setTarget] = useState<Target>(initialTarget)
  const [horizon, setHorizon] = useState<30 | 90 | 365>(365)
  const [result, setResult] = useState<SeasonalDemoResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    let current = true
    setLoading(true); setError(null); setResult(null)
    getSeasonalDemoForecast(target, horizon).then(value => {
      if (!current) return
      if (value.target !== target || value.horizon !== horizon || value.forecast.length !== horizon) throw new Error('Seasonal response target or horizon did not match the request.')
      if (!value.model?.name || !value.history?.length || value.history.some(point => !Number.isFinite(point.actual))) throw new Error('Model identity or historical working-series data is unavailable.')
      const dateNumber = (date: string) => /^\d{4}-\d{2}-\d{2}$/.test(date) ? Date.parse(`${date}T00:00:00Z`) : NaN
      const expectedStart = dateNumber(value.training_cutoff) + 86400000
      if (!Number.isFinite(expectedStart) || dateNumber(value.forecast[0]?.date) !== expectedStart) throw new Error('Forecast dates do not begin on the day after the training cutoff.')
      if (value.forecast.some((point, i) => !Number.isFinite(point[target]) || dateNumber(point.date) !== expectedStart + i * 86400000)) throw new Error('Forecast contains invalid values or non-consecutive dates.')
      if (value.history.some((point, i) => !Number.isFinite(dateNumber(point.date)) || (i > 0 && dateNumber(point.date) !== dateNumber(value.history[i - 1].date) + 86400000))) throw new Error('Historical working-series dates are empty, invalid, or non-consecutive.')
      if (dateNumber(value.history[value.history.length - 1]?.date) !== dateNumber(value.training_cutoff)) throw new Error('Historical working-series data does not end at the frozen model training cutoff.')
      setResult(value)
    }).catch(reason => { if (current) setError(reason instanceof Error ? reason.message : 'Seasonal demo forecast is unavailable.') })
      .finally(() => { if (current) setLoading(false) })
    return () => { current = false }
  }, [target, horizon])

  const points = useMemo(() => result ? [
    ...result.history.map(point => ({ date: point.date, actual: point.actual, forecast: null as number | null, dataSource: point.data_source })),
    ...result.forecast.map(point => ({ date: point.date, actual: null as number | null, forecast: point[target] as number, dataSource: 'model_estimate' })),
  ] : [], [result, target])
  const forecastWindowEnded = Boolean(result && Date.parse(`${result.forecast[result.forecast.length - 1]?.date}T23:59:59Z`) < Date.now())
  const format = (value: unknown) => typeof value === 'number' && Number.isFinite(value)
    ? target === 'orders' ? Math.round(value).toLocaleString() : value.toLocaleString(undefined, { maximumFractionDigits: 2 })
    : 'Unavailable'

  return <section className="abi-panel p-5 space-y-4" aria-label="Seasonal demo forecast">
    <div className="flex flex-wrap justify-between gap-3 items-start">
      <div><h2 className="font-semibold text-lg">Seasonal Forecast Demo</h2><p className="text-xs text-amber-300 mt-1">Experimental working-series forecast — not the live production forecast</p></div>
      <div className="flex gap-3">
        <label className="text-sm">Demo target <select aria-label="Seasonal demo target" className="bg-neutral-900 border border-neutral-700 rounded p-2 ml-2" value={target} onChange={event => setTarget(event.target.value as Target)}><option value="orders">Orders</option><option value="revenue">Revenue</option></select></label>
        <label className="text-sm">Demo horizon <select aria-label="Seasonal demo horizon" className="bg-neutral-900 border border-neutral-700 rounded p-2 ml-2" value={horizon} onChange={event => setHorizon(Number(event.target.value) as 30 | 90 | 365)}><option value={30}>30 days</option><option value={90}>90 days</option><option value={365}>365 days · recursive extension</option></select></label>
      </div>
    </div>
    <p className="text-xs text-neutral-300">This isolated demo loads a frozen trained artifact. It does not change the selected dataset, registry, or live forecast endpoint.</p>
    {loading && <p role="status">Loading the saved seasonal model and generating its forecast…</p>}
    {error && <p role="alert" className="text-amber-300">Seasonal demo unavailable: {error}</p>}
    {result && <>
      <div className="grid sm:grid-cols-2 gap-3 text-sm">
        <p>Model: <strong>{result.model.name}</strong></p><p>Forecast origin / training cutoff: <strong>{result.training_cutoff}</strong></p>
        <p>{forecastWindowEnded ? 'Saved demonstration dates' : 'Forecast dates'}: <strong>{result.forecast[0]?.date} – {result.forecast[result.forecast.length - 1]?.date}</strong></p>
        <p>Horizon: <strong>{horizon} daily {forecastWindowEnded ? 'historical model estimates' : 'predictions'}</strong></p>
        <p>{horizon === 365 ? `${result.artifact_horizon}-day artifact benchmark MAE (not 365-day performance)` : '2024 benchmark MAE'}: <strong>{format(metric(result.benchmark_metrics, 'mae'))}</strong> · WAPE <strong>{format(metric(result.benchmark_metrics, 'wape_pct'))}{metric(result.benchmark_metrics, 'wape_pct') == null ? '' : '%'}</strong></p>
      </div>
      {horizon === 365 && <p role="note" className="text-xs text-amber-300">365-day recursive extension uses the saved 90-day LightGBM artifact. This horizon was not evaluated; the dates remain a historical demonstration from the artifact's 2024-12-31 cutoff.</p>}
      {forecastWindowEnded && <p role="note" className="text-amber-300 text-xs">This saved forecast window has passed. It is a dated model demonstration, not a current business forecast.</p>}
      <div data-testid="seasonal-demo-chart" data-history-count={result.history.length} data-history-start={result.history[0]?.date} data-history-end={result.history[result.history.length - 1]?.date} data-forecast-start={result.forecast[0]?.date} data-boundary-date={result.forecast[0]?.date} data-prediction-count={result.forecast.length} data-origin={result.training_cutoff}>
        <ResponsiveContainer width="100%" height={300}><LineChart data={points} margin={{ top: 12, right: 20, left: 8, bottom: 8 }}>
          <CartesianGrid stroke="rgb(var(--border))" strokeDasharray="3 3" vertical={false} />
          <XAxis dataKey="date" minTickGap={65} tick={{ fontSize: 10 }} stroke="rgb(var(--muted))" />
          <YAxis tickFormatter={value => format(Number(value))} width={90} stroke="rgb(var(--muted))" fontSize={11} />
          <Tooltip formatter={(value, name) => [format(Number(value)), name]} labelFormatter={label => {
            const point = points.find(item => item.date === label)
            return `${label} · ${point?.dataSource === 'model_estimate' ? (forecastWindowEnded ? 'historical model estimate' : 'forecast prediction') : point?.dataSource || 'working-series history'}`
          }} />
          <Legend />
          <ReferenceLine x={result.forecast[0]?.date} stroke="rgb(var(--muted))" strokeDasharray="3 3" label={{ value: 'Forecast boundary', fill: 'rgb(var(--muted))', fontSize: 10, position: 'insideTopRight' }} />
          <Line dataKey="actual" name="Working-series history" stroke="var(--chart-1)" strokeWidth={1.8} dot={false} connectNulls={false} isAnimationActive={false} />
          <Line dataKey="forecast" name={forecastWindowEnded ? 'Historical model estimate · dated demo' : 'Future forecast · model prediction'} stroke="var(--chart-3)" strokeWidth={2} strokeDasharray="6 4" dot={false} connectNulls={false} isAnimationActive={false} />
        </LineChart></ResponsiveContainer>
      </div>
      <p className="text-xs text-amber-300">Synthetic-data warning: the displayed 2024 history is generated working-series data; 2025 outputs are estimates from a model trained on that series, not observed transactions. The package-declared Olist source window ends on 2018-10-17. The 2024 benchmark is generated data and does not establish real-world forecast accuracy. Revenue is item-price sum; source currency is unverified.</p>
      <details className="text-xs text-neutral-300"><summary>Forecast metadata and limitations</summary>{result.warnings.map(warning => <p className="mt-2" key={warning}>{warning}</p>)}<p className="mt-2">Validation MAE: {format(metric(result.validation_metrics, 'mae'))}; R²: {format(metric(result.validation_metrics, 'r2'))}. These metrics are from chronological 2023 working-series origins.</p></details>
      <div className="overflow-auto max-h-56"><table aria-label="Seasonal model estimates" className="w-full text-sm"><thead><tr><th className="text-left p-2">Date</th><th className="text-right p-2">{forecastWindowEnded ? 'Historical demo estimate' : 'Forecast estimate'} · {target === 'orders' ? 'orders' : 'item-price revenue'}</th></tr></thead><tbody>{result.forecast.map(point => <tr key={point.date}><td className="p-2">{point.date}</td><td className="text-right p-2 font-mono">{format(point[target])}</td></tr>)}</tbody></table></div>
    </>}
  </section>
}
