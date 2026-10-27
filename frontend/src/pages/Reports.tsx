import { PageHeader } from '@/components/ui/Workspace'
import { useState } from 'react'
import { downloadReport, downloadBusinessReport } from '@/services/api'
import { getStoredUser } from '@/services/auth'
import { useFilters } from '@/hooks/useFilters'
import FilterBar from '@/components/FilterBar'
import { useDataset } from '@/hooks/useDataset'

const REPORTS = [
  { name: 'kpis', label: 'KPIs', minRole: 'Both roles' },
  { name: 'orders_by_status', label: 'Orders by Status', minRole: 'Both roles' },
  { name: 'monthly_revenue', label: 'Monthly Revenue', minRole: 'Both roles' },
  { name: 'revenue_by_category', label: 'Revenue by Category', minRole: 'Both roles' },
  { name: 'numeric_statistics', label: 'Numeric Statistics', minRole: 'Both roles' },
  { name: 'dataset_rows', label: 'Dataset Rows', minRole: 'Both roles' },
]

export default function Reports() {
  const { filters } = useFilters()
  const { active } = useDataset()
  const [documentState, setDocumentState] = useState<{stamp:string;busy?:boolean;error?:string;success?:string}|null>(null)
  const scope = `${active?.dataset_id}:${active?.updated_at}:${JSON.stringify(filters)}`
  const generateWord = async () => {
    if (documentState?.busy) return
    setDocumentState({stamp:scope,busy:true})
    try {
      const result = await downloadBusinessReport(filters)
      setDocumentState({stamp:scope,success:`Downloaded ${result.filename} (${result.bytes.toLocaleString()} bytes). Generated ${result.generatedAt}.`})
    } catch(error) { setDocumentState({stamp:scope,error:error instanceof Error ? error.message : 'Report generation failed. Retry.'}) }
  }
  const [error, setError] = useState<string | null>(null)
  const user = getStoredUser()

  const run = async (report: string) => {
    setError(null)
    try {
      await downloadReport(report, filters)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Export failed')
    }
  }

  return (
    <div className="space-y-6 max-w-none">
      <div>
        <PageHeader title="Reports" />
        <p className="text-sm text-neutral-500">
          Export the selected dataset's metrics or rows as CSV, using your current filters. Both roles can export authorized data.
        </p>
      </div>

      <div className="abi-panel border border-neutral-800 rounded-lg p-4 space-y-4">
        <FilterBar />

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {REPORTS.map((r) => (
            <button
              key={r.name}
              onClick={() => run(r.name)}
              className="bg-blue-600 hover:bg-blue-500 rounded px-3 py-2 text-sm text-left"
            >
              <div className="font-medium">{r.label}</div>
              <div className="text-xs text-blue-100/70">{r.minRole}+</div>
            </button>
          ))}
        </div>

        {user && (
          <div className="text-xs text-neutral-500">
            Signed in as <span className="text-neutral-300">{user.username}</span> ({user.role})
          </div>
        )}
        {error && <div className="text-sm text-red-400">{error}</div>}
      </div>

      <div className="abi-panel border border-neutral-800 rounded-lg p-4 text-sm text-neutral-400">
        CSV export uses the same verified warehouse aggregates as the dashboards. No fabricated
        values are written.
      </div>
      <section className="abi-panel p-5 space-y-4" aria-label="Business Sales Report">
        <h2 className="text-xl font-medium">Business Sales Report</h2>
        <p className="text-sm text-neutral-400">Generate a formatted Word report with data-derived sales analysis, actual charts, tables, business findings and recommendations for the selected dataset and current filters. Unsupported metrics and forecasts are explained rather than invented.</p>
        <p className="text-sm">Dataset or table: {active?.dataset_name || 'Select a dataset'}. Scope: {Object.entries(filters).map(([key,value])=>`${key}: ${value}`).join(' · ') || 'Full selected history; no additional filters'}.</p>
        <p className="text-xs text-neutral-400">Synthetic/extended forecasts, when registered, are labelled as demonstrations. The report works locally without Ollama or paid APIs. CSV exports above remain available.</p>
        <button className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded px-4 py-2" disabled={!active || documentState?.busy} onClick={()=>void generateWord()}>{documentState?.busy ? 'Generating Word report…' : documentState?.stamp===scope && documentState.error ? 'Retry Word Report (.docx)' : 'Generate Business Sales Report (.docx)'}</button>
        {documentState?.busy && <p role="status">Calculating authorized aggregates and rendering charts. Download starts after a valid document is returned.</p>}
        {documentState?.stamp===scope && documentState.error && <p role="alert" className="text-red-400">{documentState.error}</p>}
        {documentState?.stamp===scope && documentState.success && <p role="status">{documentState.success}</p>}
      </section>
    </div>
  )
}
