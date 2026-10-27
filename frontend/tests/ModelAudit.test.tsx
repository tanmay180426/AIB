import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import ModelAudit from '@/components/ModelAudit'
import { getModelDetail } from '@/services/api'

vi.mock('@/services/api', () => ({getModelDetail:vi.fn()}))
const active={dataset_id:'synthetic',updated_at:'1'}
vi.mock('@/hooks/useDataset',()=>({useDataset:()=>({active})}))
vi.mock('@/hooks/useFilters',()=>({useFilters:()=>({filters:{}})}))
afterEach(()=>{cleanup();vi.clearAllMocks();active.updated_at='1'})

it('shows weaker baseline comparisons and undefined evaluation honestly',async()=>{
  vi.mocked(getModelDetail).mockResolvedValue({audit:{evaluation:{recursive_calendar_windows:[
    {horizon:30,origins:1,model:{n:30,mae:10,rmse:12,wape_pct:20,mase:2},last_value_baseline:{mae:5},seasonal_naive_baseline:{mae:15},excluded_test_observations:1},
    {horizon:90,origins:0,model:null}
  ]}}} as never)
  render(<ModelAudit name="sales_forecast_orders"/>);fireEvent.click(screen.getByRole('button'))
  expect(await screen.findByText('Does not beat both baselines; review before business use')).toBeVisible()
  expect(screen.getByText('Last-value MAE')).toBeVisible()
  expect(screen.getByText('Insufficient complete windows')).toBeVisible()
  expect(screen.getByText(/near-zero actuals remain/)).toBeVisible()
})

it('invalidates displayed audit when dataset schema version changes',async()=>{
  vi.mocked(getModelDetail).mockResolvedValue({audit:{artifact_sha256:'fixture-checksum'}} as never)
  const view=render(<ModelAudit name="sales_forecast_orders"/>);fireEvent.click(screen.getByRole('button'))
  expect(await screen.findByText(/fixture-checksum/)).toBeVisible()
  active.updated_at='2';view.rerender(<ModelAudit name="sales_forecast_orders"/>)
  expect(screen.queryByText(/fixture-checksum/)).not.toBeInTheDocument()
})
