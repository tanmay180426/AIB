import { useEffect, useState } from 'react'
import { getModelDetail } from '@/services/api'
import { useDataset } from '@/hooks/useDataset'
import { useFilters } from '@/hooks/useFilters'
import { formatMetricNumber } from '@/services/forecast'

const number = (value: number | null | undefined, _target: 'orders' | 'revenue') => formatMetricNumber(value)

/** Aggregate offline evidence, explicitly separate from selected-data forecasts. */
export default function ForecastQuality({ target }: { target: 'orders' | 'revenue' }) {
  const { active } = useDataset(), { filters } = useFilters()
  const datasetId = active?.dataset_id
  const stamp = `${target}:${active?.dataset_id}:${active?.updated_at}:${JSON.stringify(filters)}`
  const [result, setResult] = useState<{ stamp: string; data?: any; error?: string } | null>(null)
  useEffect(() => {
    let current = true
    if (datasetId) getModelDetail(`sales_forecast_${target}`, filters).then(data => {
      if (current) setResult({ stamp, data })
    }).catch(() => { if (current) setResult({ stamp, error: 'Evaluation unavailable. Successful inference alone does not establish accuracy.' }) })
    return () => { current = false }
  }, [stamp, datasetId, filters, target])
  const data = result?.stamp === stamp ? result.data : null
  const evidence = data?.candidate_evidence
  const synthetic = data?.selected_synthetic_forecast
  if (synthetic?.status === 'synthetic_demo') return <section className="abi-panel p-4 space-y-3" aria-label="Forecast quality">
    <h3 className="font-medium">Synthetic forecast quality · offline source evaluation</h3>
    {target === 'revenue' && <p role="note" className="text-xs text-amber-300">Revenue metrics are shown in model/source units. Original currency is unverified; no currency symbol or conversion is applied.</p>}
    <p className="text-amber-400">Experimental synthetic-data forecast · {synthetic.algorithm_label || synthetic.algorithm} · {synthetic.version}. {synthetic.quality?.qualified_synthetic_demo ? 'Synthetic-demo gate passed.' : 'Unqualified experimental preview; acceptance gate failed.'} Real-world accuracy is unverified.</p>
    <p className="text-xs">{synthetic.provenance} Source coverage: {synthetic.coverage?.join('–')}. Final refit cutoff: {synthetic.training_cutoff}. Units: {synthetic.unit}. {synthetic.historical_mode}</p>
    <p className="text-xs">{synthetic.missing_policy} With no date filter, inference uses the latest eligible observations from this selected bundle. Earlier fitting and evaluation windows remain separate.</p>
    <ul className="list-disc pl-5 text-xs text-amber-300">{synthetic.quality?.reasons?.map((reason:string)=><li key={reason}>{reason}</li>)}</ul>
    <div className="overflow-auto"><table className="w-full text-xs"><caption>2020 validation and 2021 reserved holdout · MAE / RMSE · synthetic source only</caption><thead><tr><th>Phase / days</th><th>Origins / points</th><th>Last value</th><th>Weekly naive</th><th>Selected model</th></tr></thead><tbody>{['validation','holdout'].flatMap(phase=>Object.entries(synthetic.evaluation?.[phase] || {}).map(([h,value])=>{
      const row=value as any
      const format=(name:string)=>`${number(row.metrics[name]?.mae,target)} / ${number(row.metrics[name]?.rmse,target)}`
      return <tr key={`${phase}:${h}`}><td>{phase} / {h}d</td><td>{row.origins} / {row.points}</td><td>{format('last_value')}</td><td>{format('seasonal_naive')}</td><td>{format(synthetic.algorithm)}</td></tr>
    }))}</tbody></table></div>
    <p className="text-xs">Training: before 2020. Validation: 2020. Final holdout: 2021, scored before refitting. These are not live filtered-dataset scores or independently verified real-market performance.</p>
  </section>
  return <section className="abi-panel p-4 space-y-3" aria-label="Forecast quality">
    <h3 className="font-medium">Forecast quality · offline evidence</h3>
    {target === 'revenue' && <p role="note" className="text-xs text-amber-300">Revenue metrics use source units. Original transaction currency is unverified; values are displayed without a currency symbol or conversion.</p>}
    <p className="text-sm text-amber-400">Quality is unqualified for the selected dataset. A loaded artifact or successful prediction does not establish forecast accuracy.</p>
    {result?.stamp === stamp && result.error && <p role="status">{result.error}</p>}
    {!data && !result?.error && <p role="status">Loading evaluation evidence…</p>}
    {data && <>
      <p className="text-xs">Original serving-model fit cutoff: {data.audit?.training_cutoff || 'not independently recorded'}. Source-declared cutoff: {data.audit?.evaluation?.declared_training_cutoff || 'unavailable'}.</p>
      {data.compatibility?.readiness && <p className="text-xs">Selected date-scope coverage: {data.compatibility.readiness.from}–{data.compatibility.readiness.to}; {data.compatibility.readiness.observations} observed days. Contract compatible: {data.compatibility.compatible ? 'yes' : 'no'}. This is separate from successful inference and quality qualification.</p>}
      {!evidence?.available ? <p className="text-sm">{evidence?.reason || 'Candidate evaluation is not configured.'}</p> : <>
        <p className="text-sm">Validation-selected candidate: {evidence.winner}. {evidence.status}. {evidence.qualified_in_experiment ? 'Experimental gate passed; no automatic promotion.' : 'Candidate did not qualify for production.'}</p>
        <p className="text-xs">Train: {evidence.train?.slice(0, 2).join('–')}; validation: {evidence.validation?.slice(0, 2).join('–')}; final holdout: {evidence.holdout?.slice(0, 2).join('–')}. Daily target units. Revenue currency remains unverified.</p>
        <ul className="text-xs text-amber-300 list-disc pl-5">{evidence.reasons?.map((reason: string) => <li key={reason}>{reason}</li>)}</ul>
        <div className="overflow-auto"><table className="w-full text-xs"><caption>Same dates per horizon · MAE / RMSE{target === 'revenue' ? ' (USD $, assumed display)' : ''} · offline source, not selected-data accuracy</caption><thead><tr><th>Phase / horizon</th><th>Origins / points</th><th>Last value</th><th>Weekly naive</th><th>Legacy</th><th>Selected candidate</th></tr></thead><tbody>{evidence.rows?.map((row: any) => {
          const format = (name: string) => `${number(row.metrics[name]?.mae,target)} / ${number(row.metrics[name]?.rmse,target)}`
          return <tr key={`${row.phase}:${row.horizon}`}><td>{row.phase} / {row.horizon}d</td><td>{row.origins} / {row.points}</td><td>{format('last_value')}</td><td>{format('seasonal_naive')}</td><td>{format(row.phase === 'holdout' ? 'legacy_frozen' : 'legacy_refit')} ({row.phase === 'holdout' ? 'frozen' : 'refitted'})</td><td>{format(evidence.winner)}</td></tr>
        })}</tbody></table></div>
        {evidence.limitations?.map((note: string) => <p className="text-xs text-neutral-400" key={note}>{note}</p>)}
      </>}
    </>}
  </section>
}
