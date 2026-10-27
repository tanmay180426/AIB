import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import Dashboard from '@/pages/Dashboard'
import { DatasetContext } from '@/hooks/useDataset'
import { getAnalyticsOverview, getBusinessEvidence } from '@/services/api'
vi.mock('@/services/api', () => ({ getAnalyticsOverview:vi.fn(), getBusinessEvidence:vi.fn(async () => ({cards:[],series:[],rankings:[],recommendations:[],limitations:[],source:'Observed',status:'available'})) }))
vi.mock('@/components/FilterBar', () => ({default:() => <div>Shared filters</div>}))
vi.mock('@/hooks/useFilters', () => { const filters = {}; return { useFilters: () => ({ filters, resetFilters: vi.fn() }) } })
const dataset = {dataset_id:'a',dataset_name:'Synthetic',status:'READY',row_count:2,column_count:3,quality:{missing_values:1,duplicate_rows:0},semantics:{fields:{},currency_code:null},updated_at:null} as never
const result = {status:'available',dataset_name:'Synthetic',metric_cards:[{label:'Rows',value:2},{label:'Total revenue',value:1000}],time_series:[]}
const wrapper = (child: React.ReactNode) => <MemoryRouter><DatasetContext.Provider value={{datasets:[dataset],active:dataset,busy:false,reload:async()=>{},select:async()=>{}}}>{child}</DatasetContext.Provider></MemoryRouter>
beforeEach(() => { vi.resetAllMocks(); vi.mocked(getAnalyticsOverview).mockResolvedValue(result); vi.mocked(getBusinessEvidence).mockResolvedValue({cards:[],series:[],rankings:[],recommendations:[],limitations:[],source:'Observed',status:'available'}) })
afterEach(() => {cleanup();vi.clearAllMocks()})
it('shows real context, quality, unknown currency and observed metrics', async () => {
  render(wrapper(<Dashboard />))
  await waitFor(() => expect(screen.getByText('1,000')).toBeVisible())
  expect(screen.getByText('2 rows · 3 fields')).toBeVisible()
  expect(screen.getByText('Currency unconfirmed')).toBeVisible()
  expect(screen.getByText(/1 missing values/)).toBeVisible()
  expect(screen.getByText('Time trend unavailable')).toBeVisible()
})
it('offers recovery on API failure then retries', async () => {
  vi.mocked(getAnalyticsOverview).mockRejectedValueOnce(new Error('Temporary error')).mockResolvedValueOnce(result)
  render(wrapper(<Dashboard />))
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Temporary error'))
  fireEvent.click(screen.getByRole('button',{name:'Retry dashboard'}))
  await waitFor(() => expect(screen.getByText('1,000')).toBeVisible())
})
it('does not render fabricated values while a request is pending', () => {
  vi.mocked(getAnalyticsOverview).mockReturnValue(new Promise(()=>{}))
  render(wrapper(<Dashboard />))
  expect(screen.getByRole('status')).toHaveTextContent('Loading dataset metrics')
  expect(screen.queryByText('1,000')).not.toBeInTheDocument()
})
it('shows zero observations distinctly from absent numeric values', async () => {
  vi.mocked(getAnalyticsOverview).mockResolvedValue({ ...result,metric_cards:[{label:'Rows',value:0},{label:'Total value',value:null}] })
  render(wrapper(<Dashboard />))
  await waitFor(() => expect(screen.getByText('No rows match the selected filters.')).toBeVisible())
  expect(screen.queryByText('No observed values')).not.toBeInTheDocument()
  expect(screen.getByText(/Revenue unavailable/)).toBeVisible()
})
it('offers upload-first guidance without requesting fake analytics', () => {
  render(<MemoryRouter><Dashboard /></MemoryRouter>)
  expect(screen.getByText('Start with your data')).toBeVisible()
  expect(getAnalyticsOverview).not.toHaveBeenCalled()
})
