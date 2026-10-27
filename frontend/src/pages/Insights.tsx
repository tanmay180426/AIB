import { PageHeader } from '@/components/ui/Workspace'
import { useEffect, useRef, useState } from 'react'
import { getRequestContext, queryInsights, type InsightsResponse } from '@/services/api'
import { useFilters } from '@/hooks/useFilters'
import FilterBar from '@/components/FilterBar'

const EXAMPLES = [
  'What is the total revenue and average order value?',
  'How many unique customers and orders are there?',
  'What is the average review score and delivery time?',
]

export default function Insights() {
  const { filters } = useFilters()
  const [question, setQuestion] = useState(EXAMPLES[0])
  const [result, setResult] = useState<InsightsResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const filterKey = JSON.stringify(filters)
  const context = getRequestContext()
  const generation = useRef(0)
  const current = useRef({ question, filterKey })
  current.current = { question, filterKey }
  useEffect(() => {
    generation.current += 1
    setResult(null); setError(null); setBusy(false)
    return () => { generation.current += 1 }
  }, [filterKey, context])

  const ask = async (q: string) => {
    const request = ++generation.current
    const scope = getRequestContext()
    const selectedFilters = filterKey
    current.current.question = q
    const isCurrent = () => request === generation.current && scope === getRequestContext() &&
      selectedFilters === current.current.filterKey && q === current.current.question
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const r = await queryInsights(q, 20, filters)
      if (isCurrent()) setResult(r)
    } catch (err) {
      if (isCurrent()) setError(err instanceof Error ? err.message : 'Request failed')
    } finally {
      if (isCurrent()) setBusy(false)
    }
  }

  return (
    <div className="space-y-6 max-w-none">
      <div>
        <PageHeader title="AI Business Insights" />
        <p className="text-sm text-neutral-500">
          Numerical answers use the selected dataset and current filters. Optional local
          language generation adds explanations when available.
        </p>
      </div>

      <FilterBar />
      <form
        onSubmit={(e) => {
          e.preventDefault()
          ask(question)
        }}
        className="space-y-3"
      >
        <textarea
          aria-label="Question"
          value={question}
          onChange={(e) => { generation.current += 1; setResult(null); setError(null); setBusy(false); setQuestion(e.target.value) }}
          rows={3}
          className="w-full abi-panel border border-neutral-800 rounded-lg p-3 text-sm"
          placeholder="Ask about KPIs, categories, orders, or model status…"
        />
        <div className="flex flex-wrap gap-2">
          {EXAMPLES.map((ex) => (
            <button
              type="button"
              key={ex}
              onClick={() => {
                setQuestion(ex)
                ask(ex)
              }}
              className="text-xs bg-neutral-800 hover:bg-neutral-700 rounded px-2 py-1"
            >
              {ex}
            </button>
          ))}
        </div>
        <button
          type="submit"
          disabled={busy || !question.trim()}
          className="bg-blue-600 hover:bg-blue-500 disabled:opacity-50 rounded px-4 py-2 text-sm font-medium"
        >
          {busy ? 'Thinking…' : 'Ask'}
        </button>
      </form>

      {error && <div className="text-red-400 text-sm">{error}</div>}

      {result && (
        <div className="abi-panel border border-neutral-800 rounded-lg p-4 space-y-3">
          <div className="flex items-center gap-3 text-xs">
            <span className="uppercase text-neutral-500">status: {result.status}</span>
            {result.provider && <span className="text-neutral-500">provider: {result.provider}</span>}
            <span className="text-neutral-500">role: {result.role}</span>
          </div>
          <pre className="whitespace-pre-wrap text-sm">{result.answer}</pre>
          {result.sources.length > 0 && (
            <div className="text-xs text-neutral-500">Sources: {result.sources.join(', ')}</div>
          )}
        </div>
      )}
    </div>
  )
}
