import { PageHeader } from '@/components/ui/Workspace'
import { useEffect, useState } from 'react'
import {
  getMlStatus,
  type MlFeature,
} from '@/services/api'
import { useFilters } from '@/hooks/useFilters'
import FilterBar from '@/components/FilterBar'
import ModelAudit from '@/components/ModelAudit'
import { Link } from 'react-router-dom'
import { ForecastExperience } from './RevenueForecast'
import { useDataset } from '@/hooks/useDataset'

const statusColor: Record<string, string> = {
  available: 'text-emerald-400',
  integration: 'text-amber-400',
  failed: 'text-red-400',
  planned: 'text-neutral-500',
}

function metricValues(metrics: Record<string, unknown>, prefix = '', depth = 0): [string, string | number][] {
  return Object.entries(metrics).flatMap(([key, value]): [string, string | number][] => {
    const label = prefix ? `${prefix} / ${key}` : key
    if (typeof value === 'number' || typeof value === 'string') return [[label,value]]
    if (value && typeof value === 'object' && !Array.isArray(value) && depth < 2) return metricValues(value as Record<string,unknown>,label,depth+1)
    return []
  }).slice(0,64)
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`text-xs font-medium uppercase ${statusColor[status] ?? 'text-neutral-400'}`}>
      {status}
    </span>
  )
}

export default function MlMetrics() {
  const { active } = useDataset()
  const [target, setTarget] = useState<'orders' | 'revenue'>('orders')
  const { filters } = useFilters()
  const [features, setFeatures] = useState<MlFeature[]>([])
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')

  useEffect(() => {
    let current = true
    setState('loading')
    getMlStatus(filters)
      .then((s) => {
        if (!current) return
        setFeatures([...s.features,...(s.source_candidates || [])])
        setState('ready')
      })
      .catch(() => { if (current) setState('error') })
    return () => { current = false }
  }, [filters, active?.dataset_id, active?.updated_at])

  const actionable = features.filter(feature => feature.models.some(model => model.runtime_ready === true))
  const diagnostics = features.filter(feature => feature.status !== 'blocked' && feature.models.length > 0 && !feature.models.some(model => model.runtime_ready === true))
  const blockedCandidates = features.filter(feature => feature.status === 'blocked')


  return (
    <div className="space-y-6">
      <FilterBar />
      <div>
      <PageHeader title="Model Status" />
        <p className="text-sm text-neutral-500">
          Run a genuine forecast for the selected data. Model catalog and offline evaluation remain below.
        </p>
      </div>

      <ForecastExperience key={`${active?.dataset_id}:${active?.updated_at}`} target={target} onTargetChange={setTarget} />
      <h2 className="text-xl font-medium">Ready models</h2>
      {state === 'loading' && <p role="status">Loading ML models…</p>}
      {state === 'error' && <p role="alert">Could not load the model catalog. Check the backend and trusted artifact path.</p>}

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 items-start">
        {state === 'ready' && actionable.map((f) => (
          <div key={f.name} className="abi-panel p-4 rounded-lg border border-neutral-800">
            <div className="flex items-center justify-between mb-4">
              <div className="font-medium capitalize text-lg">{f.name.replace(/_/g, ' ')}</div>
              <StatusBadge status={f.status} />
            </div>

            <div className="space-y-4">
              {f.models.map((m) => (
                <div key={m.name} className="border-t border-neutral-800 pt-4 first:border-0 first:pt-0">
                  <div className="text-sm font-medium text-neutral-300 mb-1">{m.name.replace(/_/g, ' ')}</div>
                  <div className="text-xs text-neutral-500 mb-3">{m.algorithm || 'Algorithm pending'}</div>
                  <p className="text-xs text-neutral-400 mb-2">{m.metrics_scope}</p>
                  <p className="text-xs mb-2">Runtime: {m.runtime_ready === true ? 'Loaded and serving contract validated' : m.runtime_ready === false ? m.runtime_reason : 'Not checked'}{m.version ? ` · version ${m.version}` : ''}</p>
                  {m.compatibility && <div className="text-sm mb-3"><span className={m.compatibility.compatible ? 'text-emerald-400' : 'text-amber-400'}>{m.compatibility.compatible ? 'Compatible with active dataset' : 'Not Applicable to active dataset'}</span>{m.compatibility.reasons.map(reason => <p key={reason} className="text-xs text-neutral-400 mt-1">{reason}</p>)}</div>}
                  {m.compatibility && !m.compatibility.compatible && <Link className="inline-block text-xs text-blue-400 mb-3" to="/datasets">Review dataset mapping →</Link>}

                  {m.metrics && (
                    <details className="border-t border-neutral-800 mt-3 pt-1"><summary>Historical evaluation metrics</summary><div className="grid grid-cols-2 gap-2 mt-2">
                      {metricValues(m.metrics).map(([k, v]) => {
                        return (
                          <div key={k} className="bg-neutral-800/50 p-2 rounded">
                            <div className="text-[10px] text-neutral-500 uppercase tracking-wider">{k.replace(/_/g, ' ')}</div>
                            <div className="text-sm font-mono text-neutral-200">
                              {typeof v === 'number' ? Number.isInteger(v) ? v : v.toFixed(4) : String(v)}
                            </div>
                          </div>
                        )
                      })}
                    </div></details>
                  )}

                  {m.name !== 'abi_gradient_boosting_revenue' && <ModelAudit name={m.name} />}

                  <div className="text-xs text-neutral-500 mt-3 flex flex-wrap gap-2 justify-between">
                    <span>Artifact: {m.artifact_available ? 'Present' : 'Missing'} · Inference runs on the task page</span>
                    {m.trained_at && <span>{new Date(m.trained_at).toLocaleDateString()}</span>}
                  </div>
                </div>
              ))}

              {f.models.length === 0 && (
                <div className="text-xs text-neutral-500 italic">No models registered yet</div>
              )}
            </div>
          </div>
        ))}
      </div>
      {state === 'ready' && actionable.length === 0 && <p className="text-sm text-neutral-400">No legacy model artifact is currently ready for live inference. The isolated Seasonal Forecast Demo remains available on the revenue and orders forecast pages.</p>}
      {state === 'ready' && diagnostics.length > 0 && <details className="abi-panel p-4 space-y-3">
        <summary className="cursor-pointer">Unavailable legacy integrations and diagnostics ({diagnostics.reduce((count, feature) => count + feature.models.length, 0)})</summary>
        <p className="text-xs text-neutral-400 mt-2">These metadata records remain available for audit. Missing artifacts or failed serving contracts prevent inference; recorded historical metrics are not live results.</p>
        {diagnostics.map(feature => <section className="border-t border-neutral-800 pt-3 mt-3" key={feature.name}>
          <h3 className="font-medium capitalize">{feature.name.replace(/_/g, ' ')} · {feature.status}</h3>
          {feature.models.map(model => <div className="mt-2 pl-3 border-l border-neutral-700" key={model.name}>
            <p>{model.name.replace(/_/g, ' ')} · {model.algorithm || 'algorithm unrecorded'}</p>
            <p className="text-xs text-amber-300">{model.artifact_available ? 'Artifact file exists, but runtime compatibility is not verified.' : 'Trained artifact is missing.'}{model.runtime_reason ? ` ${model.runtime_reason}` : ''}</p>
            {model.metrics && <p className="text-xs text-neutral-400">Historical metadata metrics are retained as reference only; not verified for current serving.</p>}
            <ModelAudit name={model.name} />
          </div>)}
        </section>)}
        {blockedCandidates.map(feature => <section className="border-t border-neutral-800 pt-3 mt-3" key={feature.name}>
          <h3 className="font-medium capitalize">{feature.name.replace(/_/g, ' ')} · blocked source candidate</h3>
          {feature.models.map(model => <div key={model.name}><p>{model.name.replace(/_/g, ' ')} · {model.runtime_reason || 'Inactive source candidate.'}</p></div>)}
        </section>)}
      </details>}
    </div>
  )
}
