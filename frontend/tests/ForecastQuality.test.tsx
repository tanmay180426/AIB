import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import ForecastQuality from '@/components/ForecastQuality'
import { getModelDetail } from '@/services/api'
vi.mock('@/services/api', () => ({ getModelDetail: vi.fn() }))
vi.mock('@/hooks/useDataset', () => ({ useDataset: () => ({ active: { dataset_id:'fixture', updated_at:'1' } }) }))
const filters = {}
vi.mock('@/hooks/useFilters', () => ({ useFilters: () => ({ filters }) }))
afterEach(() => { cleanup(); vi.clearAllMocks() })

it('shows failed candidate gates and comparable offline metrics without collapsing them', async () => {
  vi.mocked(getModelDetail).mockResolvedValueOnce({candidate_evidence:{available:true,winner:'forest_recursive',status:'Existing serving artifact retained',qualified_in_experiment:false,
    reasons:['holdout 14d: less than 5% MAE improvement'], rows:[{phase:'holdout',horizon:14,origins:6,points:84,metrics:{forest_recursive:{mae:11,rmse:12},last_value:{mae:10,rmse:11},seasonal_naive:{mae:9,rmse:10},legacy_frozen:{mae:14,rmse:15}}}]}})
  render(<ForecastQuality target="orders" />)
  expect(await screen.findByText(/Candidate did not qualify/)).toBeVisible()
  expect(screen.getByText('11 / 12')).toBeVisible()
  expect(screen.getByText('holdout 14d: less than 5% MAE improvement')).toBeVisible()
  expect(screen.getByText(/Quality is unqualified for the selected dataset/)).toBeVisible()
})
it('shows revenue evaluation errors in neutral source units without assuming a currency', async () => {
  vi.mocked(getModelDetail).mockResolvedValueOnce({candidate_evidence:{available:true,winner:'lightgbm_recursive',status:'Validation only',qualified_in_experiment:false,
    rows:[{phase:'validation',horizon:30,origins:20,points:600,metrics:{lightgbm_recursive:{mae:1234.5,rmse:2345.67},last_value:{mae:0,rmse:0},seasonal_naive:{mae:99,rmse:100},legacy_refit:{mae:-1234.5,rmse:1}}}]}})
  render(<ForecastQuality target="revenue" />)
  expect(await screen.findByText('1,234.5 / 2,345.67')).toBeVisible()
  expect(screen.getByText(/currency is unverified/)).toBeVisible()
  expect(screen.getByText('0 / 0')).toBeVisible()
  expect(screen.getByText(/-1,234.5 \/ 1/)).toBeVisible()
})
it('discards a late prior-target evaluation', async () => {
  let resolve!: (value: unknown) => void
  vi.mocked(getModelDetail).mockReturnValueOnce(new Promise(done => {resolve=done})).mockResolvedValueOnce({candidate_evidence:{available:false,reason:'Revenue evidence unavailable'}})
  const view = render(<ForecastQuality target="orders" />)
  view.rerender(<ForecastQuality target="revenue" />)
  expect(await screen.findByText('Revenue evidence unavailable')).toBeVisible()
  resolve({candidate_evidence:{available:false,reason:'Stale order report'}})
  await waitFor(() => expect(screen.queryByText('Stale order report')).not.toBeInTheDocument())
})
it('shows registered synthetic quality separately from legacy currency and real-market accuracy',async()=>{
  vi.mocked(getModelDetail).mockResolvedValueOnce({selected_synthetic_forecast:{status:'synthetic_demo',algorithm:'ridge',version:'synthetic-v1',unit:'source revenue units — currency unconfirmed',quality:{qualified_synthetic_demo:false,reasons:['holdout 90d: unstable']},coverage:['2016-09-04','2021-12-31'],training_cutoff:'2021-12-31',evaluation:{}}})
  render(<ForecastQuality target="revenue" />)
  expect(await screen.findByText(/Unqualified experimental preview/)).toBeVisible()
  expect(screen.getByText(/source revenue units — currency unconfirmed/)).toBeVisible()
  expect(screen.getByText('holdout 90d: unstable')).toBeVisible()
})
