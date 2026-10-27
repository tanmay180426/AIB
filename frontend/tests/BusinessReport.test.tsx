import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import Reports from '@/pages/Reports'
import { downloadBusinessReport } from '@/services/api'
vi.mock('@/services/api',()=>({downloadReport:vi.fn(),downloadBusinessReport:vi.fn()}))
vi.mock('@/services/auth',()=>({getStoredUser:()=>({username:'analyst',role:'analyst'})}))
vi.mock('@/hooks/useDataset',()=>({useDataset:()=>({active:{dataset_id:'fixture',dataset_name:'Synthetic sales',updated_at:'1'}})}))
const filters={date_from:'2021-01-01',date_to:'2021-12-31'}
vi.mock('@/hooks/useFilters',()=>({useFilters:()=>({filters})}))
vi.mock('@/components/FilterBar',()=>({default:()=>null}))
afterEach(()=>{cleanup();vi.resetAllMocks()})

it('prevents duplicate generation and reports success only after the download completes',async()=>{
  let finish!:(value:{filename:string;bytes:number;generatedAt:string})=>void
  vi.mocked(downloadBusinessReport).mockReturnValueOnce(new Promise(done=>{finish=done}))
  render(<Reports />)
  const button=screen.getByRole('button',{name:'Generate Business Sales Report (.docx)'})
  fireEvent.click(button);expect(button).toBeDisabled()
  expect(downloadBusinessReport).toHaveBeenCalledWith(filters)
  expect(screen.queryByText(/Downloaded/)).not.toBeInTheDocument()
  finish({filename:'business-sales-analysis.docx',bytes:10000,generatedAt:'2026-10-15T00:00:00Z'})
  expect(await screen.findByText(/Downloaded business-sales-analysis.docx/)).toBeVisible()
  expect(screen.getByText('Monthly Revenue')).toBeVisible()
})
it('shows server errors and an actionable retry without claiming a document exists',async()=>{
  vi.mocked(downloadBusinessReport).mockRejectedValueOnce(new Error('Report generation is busy. Retry.'))
  render(<Reports />)
  fireEvent.click(screen.getByRole('button',{name:'Generate Business Sales Report (.docx)'}))
  expect(await screen.findByRole('alert')).toHaveTextContent('Report generation is busy')
  expect(screen.getByRole('button',{name:'Retry Word Report (.docx)'})).toBeEnabled()
  expect(screen.queryByText(/Downloaded/)).not.toBeInTheDocument()
})
