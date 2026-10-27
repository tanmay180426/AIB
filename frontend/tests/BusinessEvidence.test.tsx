import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import BusinessEvidence from '@/components/BusinessEvidence'
import { getBusinessEvidence } from '@/services/api'

vi.mock('@/services/api', () => ({ getBusinessEvidence: vi.fn() }))
const mocks = vi.hoisted(() => ({ activeDataset: { dataset_id: 'fixture', dataset_name: 'Sample' } }))
vi.mock('@/hooks/useDataset', () => ({ useDataset: () => ({ active: mocks.activeDataset }) }))
vi.mock('@/hooks/useFilters', () => ({ useFilters: () => ({ filters: {} }) }))
afterEach(() => { cleanup(); vi.clearAllMocks() })

it('formats revenue evidence only with the source currency explicitly returned by the API', async () => {
  vi.mocked(getBusinessEvidence).mockResolvedValue({
    status: 'available', source: 'fixture', currency_code: 'BRL', measurement_window: 'Selected dates',
    cards: [{ label: 'Total revenue', value: 1234.5 }, { label: 'No value', value: null }],
    series: [], rankings: [], recommendations: [], limitations: [],
  })
  render(<BusinessEvidence domain="revenue" />)
  expect(await screen.findByText('Total revenue')).toBeVisible()
  expect(screen.getByText('R$1,234.50')).toBeVisible()
  expect(screen.queryByText('Unavailable')).not.toBeInTheDocument()
  expect(screen.getByText(/Selected dates · fixture · BRL/)).toBeVisible()
})
