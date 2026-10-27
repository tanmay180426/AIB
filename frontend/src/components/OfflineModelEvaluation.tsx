import { useEffect, useMemo, useState } from 'react'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { getOfflineModelEvaluation, type OfflineEvaluationResponse, type OfflineEvaluationResult } from '@/services/api'
import { formatMetricNumber } from '@/services/forecast'

const number = (value: number | null | undefined) => formatMetricNumber(value)

export default function OfflineModelEvaluation() {
  const [data, setData] = useState<OfflineEvaluationResponse | null>(null)
  const [error, setError] = useState('')
  const [target, setTarget] = useState<'orders' | 'revenue' | 'profit'>('revenue')
  const [horizon, setHorizon] = useState<30 | 90>(30)

  useEffect(() => {
    let current = true
    getOfflineModelEvaluation()
      .then(result => { if (current) setData(result) })
      .catch(() => { if (current) setError('Saved offline evaluation is unavailable.') })
    return () => { current = false }
  }, [])

  const result = useMemo<OfflineEvaluationResult | undefined>(
    () => data?.results.find(item => item.target === target && item.horizon === horizon),
    [data, target, horizon],
  )

  return <section className="abi-panel p-5 space-y-4" aria-labelledby="offline-model-evaluation-title" data-testid="offline-model-evaluation">
    <header>
      <h2 id="offline-model-evaluation-title" className="text-lg font-medium">Offline Model Evaluation</h2>
      <p role="note" className="mt-2 rounded border border-amber-500/40 bg-amber-500/10 p-3 text-sm font-semibold text-amber-300">
        Experimental validation results — not live forecasts.
      </p>
      <p className="mt-2 text-xs text-neutral-400">Saved chronological validation predictions from the Olist seasonal experiment. These dates were used for model selection; no independent holdout was used. This section reads saved evaluation output and does not call live forecast inference.</p>
    </header>

    <div className="flex flex-wrap gap-4">
      <label className="text-sm">Evaluation target
        <select aria-label="Offline evaluation target" className="ml-2 rounded border border-neutral-700 bg-neutral-900 p-2" value={target} onChange={event => setTarget(event.target.value as 'orders' | 'revenue' | 'profit')}>
          <option value="orders">Orders</option>
          <option value="revenue">Revenue · currency unverified</option>
          <option value="profit">Profit · provisional units unknown</option>
        </select>
      </label>
      <label className="text-sm">Evaluation horizon
        <select aria-label="Offline evaluation horizon" className="ml-2 rounded border border-neutral-700 bg-neutral-900 p-2" value={horizon} onChange={event => setHorizon(Number(event.target.value) as 30 | 90)}>
          <option value={30}>30 days</option>
          <option value={90}>90 days</option>
        </select>
      </label>
    </div>

    {error && <p role="status">{error}</p>}
    {!error && !data && <p role="status">Loading saved evaluation…</p>}
    {data && (!result || !result.available) && <p role="status">{result?.reason || 'Saved evaluation is unavailable.'}</p>}
    {data && result?.available && result.points && result.metrics && <>
      {result.target !== 'orders' && <p role="note" className="text-xs text-amber-300">Values use source/model units. Revenue currency is unverified and the profit formula and units are provisional; no currency symbol or conversion is applied.</p>}
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <p><span className="text-xs text-neutral-400">Target</span><br />{result.target === 'revenue' ? 'Revenue · currency unverified' : result.target === 'profit' ? 'Profit · provisional units unknown' : 'Orders'}</p>
        <p><span className="text-xs text-neutral-400">Selected validation model</span><br />{result.model}</p>
        <p><span className="text-xs text-neutral-400">Horizon</span><br />{result.horizon} days · {result.origin_count} origins</p>
        <p><span className="text-xs text-neutral-400">Evaluation period</span><br />{result.evaluation_period?.from}–{result.evaluation_period?.to}</p>
        <p><span className="text-xs text-neutral-400">MAE · {result.target === 'orders' ? 'orders' : 'source units'}</span><br />{number(result.metrics.mae)}</p>
        <p><span className="text-xs text-neutral-400">RMSE · {result.target === 'orders' ? 'orders' : 'source units'}</span><br />{number(result.metrics.rmse)}</p>
        <p><span className="text-xs text-neutral-400">R²</span><br />{number(result.metrics.r2)}</p>
        <p><span className="text-xs text-neutral-400">Target definition</span><br />{result.target_definition}</p>
      </div>

      {result.warnings?.map(warning => <p key={warning} role="note" className="text-sm text-amber-300">{warning}</p>)}
      {result.target === 'profit' && <p role="note" className="text-sm font-medium text-amber-300">Provisional profit series: calculation and units have not been verified. Do not interpret these values as a validated currency amount or profit measure.</p>}
      {result.peak_metrics && <>
        <p className="text-xs text-neutral-400">{result.peak_definition} Predictions are recursive or direct validation outputs according to the selected model, not live forecasts. Non-order metrics use the recorded target units; revenue currency and profit semantics remain unverified.</p>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5" aria-label="Peak-specific validation metrics">
          <p><span className="text-xs text-neutral-400">Peak precision</span><br />{number(result.peak_metrics.precision)}</p>
          <p><span className="text-xs text-neutral-400">Peak recall</span><br />{number(result.peak_metrics.recall)}</p>
          <p><span className="text-xs text-neutral-400">Peak magnitude MAE · {result.target === 'orders' ? 'orders' : 'source units'}</span><br />{number(result.peak_metrics.magnitude_mae)}</p>
          <p><span className="text-xs text-neutral-400">Normal-period MAE · {result.target === 'orders' ? 'orders' : 'source units'}</span><br />{number(result.peak_metrics.normal_period_mae)}</p>
          <p><span className="text-xs text-neutral-400">Peak timing MAE · days</span><br />{number(result.peak_metrics.timing_mae_days)}</p>
        </div>
      </>}

      <div data-testid="offline-evaluation-chart" aria-label={`${result.target} actual values against ${result.model} validation predictions`}>
        <ResponsiveContainer width="100%" height={320}>
          <LineChart data={result.points} margin={{ top: 12, right: 20, left: 8, bottom: 8 }}>
            <CartesianGrid stroke="rgb(var(--border))" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="date" minTickGap={60} stroke="rgb(var(--muted))" fontSize={11} />
            <YAxis width={result.target === 'orders' ? 85 : 110} tickFormatter={value => number(Number(value))} stroke="rgb(var(--muted))" fontSize={11} />
            <Tooltip labelFormatter={label => `Validation date: ${label}`} formatter={(value, name) => [number(Number(value)), name]} />
            <Legend />
            <Line dataKey="actual" name="Actual · saved validation" stroke="var(--chart-1)" strokeWidth={2} dot={false} isAnimationActive={false} />
            <Line dataKey="prediction" name={`Prediction · ${result.model}`} stroke="var(--chart-3)" strokeWidth={2} strokeDasharray="6 4" dot={false} isAnimationActive={false} />
            {result.peak_metrics && <Line dataKey="prediction_peak" name="Predicted peak · origin q90" stroke="transparent" strokeWidth={0} dot={{ r: 4, fill: '#dc2626', stroke: '#dc2626' }} connectNulls={false} isAnimationActive={false} />}
            {result.peak_metrics && <Line dataKey="prediction_dip" name="Predicted dip · origin q10" stroke="transparent" strokeWidth={0} dot={{ r: 4, fill: '#059669', stroke: '#059669' }} connectNulls={false} isAnimationActive={false} />}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="text-xs text-neutral-400">Provenance: {result.provenance?.source_observed_points.toLocaleString()} source-observed scored dates and {result.provenance?.synthetic_extension_points.toLocaleString()} synthetic-extension scored dates. {result.provenance?.synthetic_extension_points ? 'Synthetic dates contribute to the metrics; they do not establish real-world forecast accuracy.' : ''}</p>
    </>}
  </section>
}
