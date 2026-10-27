import { useState } from 'react'
import { getModelDetail } from '@/services/api'
import { useFilters } from '@/hooks/useFilters'
import { useDataset } from '@/hooks/useDataset'

const number = (value: number | null | undefined) => value == null ? 'Unavailable' : value.toLocaleString('en-US', {maximumFractionDigits:4})

/** Explicit read-only replay, separate from selected-data inference and fitting. */
export default function ModelAudit({ name }: { name: string }) {
  const { filters } = useFilters(), { active } = useDataset()
  const stamp = `${name}:${active?.dataset_id}:${active?.updated_at}:${JSON.stringify(filters)}`
  const [result,setResult] = useState<{stamp:string;value?:any;error?:string}|null>(null)
  const [pending,setPending] = useState(false)
  const data = result?.stamp === stamp ? result.value : null
  const load = async () => {
    setPending(true)
    try { setResult({stamp,value:await getModelDetail(name,filters)}) }
    catch(error) { setResult({stamp,error:error instanceof Error ? error.message : 'Audit failed.'}) }
    finally { setPending(false) }
  }
  const audit=data?.audit, evaluation=audit?.evaluation, readiness=data?.compatibility?.readiness
  const candidates=data?.candidate_evidence
  return <section className="text-xs space-y-3 min-w-0" aria-label="Model provenance audit">
    <button disabled={pending} onClick={()=>void load()} className="text-blue-400">{pending ? 'Replaying saved model…' : 'Inspect provenance and evaluation'}</button>
    {result?.stamp===stamp&&result.error&&<p role="alert">{result.error}</p>}
    {data&&<>
      <p>Target: {data.target} · version {data.version || 'unrecorded'}. Features: {data.features_schema?.join(', ') || 'Unrecorded'}.</p>
      <p>Contract: {data.contract?.transformations || data.notes || 'No preprocessing description recorded'} · {data.contract?.currency_code || 'No monetary-unit requirement'}.</p>
      {readiness&&<p>Selected history: {readiness.observations} observed days · {readiness.from}–{readiness.to} · {readiness.missing_calendar_days} missing calendar days. Latest 30-day window: {readiness.latest_window_consecutive?'consecutive':'incomplete'}. Gaps are never filled.</p>}
      <p>{audit?.provenance || audit?.reason || 'Reproducible audit unavailable.'}</p>
      {audit?.date_profile&&<p>Training-source coverage: {audit.date_profile.from}–{audit.date_profile.to}; {audit.source_rows} rows, {audit.date_profile.missing_calendar_days} missing calendar days, {audit.date_profile.duplicate_dates} duplicate dates.</p>}
      {audit?.artifact_sha256&&<p className="break-all">Audited artifact SHA-256: {audit.artifact_sha256}</p>}
      <p>Original fitted training cutoff: {audit?.training_cutoff || 'Not recorded; not independently verified'}.</p>
      {candidates&&<section aria-label="Candidate model comparison" className="space-y-2">
        <h3 className="font-medium">Candidate comparison</h3>
        {!candidates.available ? <p>{candidates.reason}</p> : <>
          <p>Validation selected {candidates.winner}. Existing production model retained. Selection uses validation only; the separate holdout is reported as evidence, not used to select.</p>
          {[...candidates.rows].map((row:any)=><div key={`${row.phase}-${row.horizon}`} className="overflow-auto">
            <table className="w-full"><caption>{row.phase} · {row.horizon}-day · {row.origins} origins / {row.points} aligned predictions</caption>
              <thead><tr><th>Model</th><th>MAE</th><th>RMSE</th><th>R²</th><th>MAPE %</th><th>WAPE %</th><th>Inference sec</th></tr></thead>
              <tbody>{Object.entries(row.metrics).map(([model,metrics]:any)=><tr key={model}>
                <td>{model}</td><td>{number(metrics.mae)}</td><td>{number(metrics.rmse)}</td><td>{number(metrics.r2)}</td>
                <td>{number(metrics.mape_nonzero_pct)}</td><td>{number(metrics.wape_pct)}</td><td>{number(metrics.inference_time_seconds)}</td>
              </tr>)}</tbody>
            </table>
          </div>)}
          {candidates.reasons?.map((reason:string)=><p key={reason} className="text-amber-400">{reason}</p>)}
          {candidates.limitations?.map((note:string)=><p key={note} className="text-neutral-400">{note}</p>)}
        </>}
      </section>}
      {evaluation&&<>
        <p>{evaluation.protocol}</p>
        {evaluation.declared_training_cutoff&&<p>Source-declared split reconstruction: training through {evaluation.declared_training_cutoff}, evaluation {evaluation.evaluation_from}–{evaluation.evaluation_to}; {evaluation.n_train} train / {evaluation.n_test} test observations.</p>}
        {evaluation.legacy_one_step&&<p>Legacy one-step replay: MAE {number(evaluation.legacy_one_step.mae)}, RMSE {number(evaluation.legacy_one_step.rmse)}, WAPE {number(evaluation.legacy_one_step.wape_pct)}%. Recorded MAE/RMSE reproduced: {evaluation.recorded_mae_rmse_reproduced?'yes':'no'}.</p>}
        {!!evaluation.recursive_calendar_windows?.length&&<><p>MAE/RMSE use target units. WAPE = sum absolute error / sum absolute actual × 100. MASE uses the training-span seven-calendar-day absolute-difference mean. MAPE excludes exact-zero actuals; near-zero actuals remain and can dominate it. Each baseline uses the same held-out points as its model row.</p><div className="overflow-auto"><table className="w-full"><caption>Frozen-model recursive calendar windows; disjoint targets, no retraining</caption><thead><tr><th>Days</th><th>Windows / points</th><th>MAE</th><th>RMSE</th><th>WAPE %</th><th>MASE</th><th>Last-value MAE</th><th>Seasonal MAE</th><th>Comparison on MAE</th></tr></thead><tbody>{evaluation.recursive_calendar_windows.map((row:any)=><tr key={row.horizon}><td>{row.horizon}</td><td>{row.origins} / {row.model?.n || 0}</td><td>{number(row.model?.mae)}</td><td>{number(row.model?.rmse)}</td><td>{number(row.model?.wape_pct)}</td><td>{number(row.model?.mase)}</td><td>{number(row.last_value_baseline?.mae)}</td><td>{number(row.seasonal_naive_baseline?.mae)}</td><td>{!row.model ? 'Insufficient complete windows' : row.model.mae < row.last_value_baseline.mae && row.model.mae < row.seasonal_naive_baseline.mae ? 'Lower MAE than both baselines; provenance still unverified' : 'Does not beat both baselines; review before business use'}</td></tr>)}</tbody></table></div>{evaluation.recursive_calendar_windows.map((row:any)=><p key={row.horizon}>{row.horizon}-day evaluation: {row.first_test_date || 'Unavailable'}–{row.last_test_date || 'Unavailable'} · {row.excluded_test_observations ?? 'Unrecorded'} holdout observations outside complete disjoint windows. No missing date was filled.</p>)}</>}
        {evaluation.metrics&&<p>Saved checkout pipeline replay: MAE {number(evaluation.metrics.mae)}, RMSE {number(evaluation.metrics.rmse)}, WAPE {number(evaluation.metrics.wape_pct)}% · {evaluation.metrics.n} observations.</p>}
        {evaluation.cluster_counts&&<p>Saved cluster assignment replay: {Object.entries(evaluation.cluster_counts).map(([key,value])=>`cluster ${key}: ${value}`).join(' · ')}. These are training-source counts.</p>}
        {evaluation.flagged_days!=null&&<p>Training-source anomaly replay: {evaluation.flagged_days}/{evaluation.n_days} flagged days. No supervised accuracy is claimed.</p>}
        {evaluation.limitations?.map((note:string)=><p key={note} className="text-neutral-400">{note}</p>)}
      </>}
    </>}
  </section>
}
