import { fireEvent, render, screen, cleanup } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import FilterBar from '@/components/FilterBar'
import { getFilterOptions } from '@/services/api'

vi.mock('@/services/api', () => ({ getFilterOptions: vi.fn() }))
afterEach(() => { cleanup(); vi.clearAllMocks() })
function Location() { return <output>{useLocation().search}</output> }
const options = { dynamic: [{ field: 'department', label: 'department', values: ['CS', 'EE'] }], has_date: false, date_range: { min: '', max: '' }, categories: [], customer_states: [], seller_states: [], order_statuses: [], payment_types: [], review_scores: [] }
describe('dataset filters', () => {
  it('shows processing and then dataset-derived controls', async () => {
    vi.mocked(getFilterOptions).mockResolvedValue(options)
    render(<MemoryRouter><FilterBar /></MemoryRouter>)
    expect(screen.getByRole('status')).toHaveTextContent('Loading filters')
    expect(await screen.findByLabelText('Filter department')).toBeVisible()
    expect(screen.queryByLabelText('Date From')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Customer State')).not.toBeInTheDocument()
  })
  it('writes selected fields into the existing shared filter URL and resets them', async () => {
    vi.mocked(getFilterOptions).mockResolvedValue(options)
    render(<MemoryRouter><FilterBar /><Location /></MemoryRouter>)
    fireEvent.change(await screen.findByLabelText('Filter department'), { target: { value: 'CS' } })
    expect(screen.getByRole('status')).toHaveTextContent('column_filters')
    fireEvent.click(screen.getByRole('button', { name: 'Reset' }))
    expect(screen.getByRole('status')).toHaveTextContent('')
  })
  it('shows a failed metadata request explicitly', async () => {
    vi.mocked(getFilterOptions).mockRejectedValue(new Error('You do not have access to this dataset.'))
    render(<MemoryRouter><FilterBar /></MemoryRouter>)
    expect(await screen.findByRole('alert')).toHaveTextContent('You do not have access')
  })
})
