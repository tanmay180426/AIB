import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import DatasetResults from '@/components/DatasetResults'

afterEach(() => { cleanup(); vi.unstubAllGlobals() })
beforeEach(() => { vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} }) })
describe('semantic analytics content', () => {
  it('uses full selected revenue for category shares and full status totals without unavailable KPI cards',()=>{
    render(<MemoryRouter><DatasetResults dashboard monetaryFields={['Item revenue']} data={{status:'available',grain:'orders',kpis:{total_revenue:200,total_orders:4},metric_cards:[{label:'Item revenue',value:200},{label:'Distinct orders',value:4}],distributions:[{field:'order status',series:[{label:'delivered',rows:3},{label:'canceled',rows:1}]}],entities:[{label:'Top category',rows:1,amount:50}]}} /></MemoryRouter>)
    expect(screen.getByLabelText('Order status shares')).toHaveTextContent('delivered · 3 orders · 75.00%')
    expect(screen.getByLabelText('Order status shares')).toHaveTextContent('canceled · 1 orders · 25.00%')
    expect(screen.getByRole('row',{name:/Top category/})).toHaveTextContent('25.00%')
    expect(screen.queryByText('Total Profit')).not.toBeInTheDocument()
    expect(screen.queryByText('Profit Margin')).not.toBeInTheDocument()
  })
  it('renders observed student measures with neutral units', () => {
    render(<DatasetResults data={{ status: 'available', dataset_name: 'Students', metric_cards: [{ label: 'Average marks', value: 70 }] }} />)
    expect(screen.getByText('Average marks')).toBeVisible()
    expect(screen.getByText('70')).toBeVisible()
    expect(screen.queryByText(/R\$/)).not.toBeInTheDocument()
    expect(screen.queryByText(/customers/i)).not.toBeInTheDocument()
  })
  it('explains unavailable capabilities without displaying fake cards', () => {
    render(<DatasetResults data={{ status: 'not_applicable', reason: 'No delivery date field was confirmed.', metric_cards: [] }} />)
    expect(screen.getByRole('status')).toHaveTextContent('Not available for this dataset.')
    expect(screen.getByText('No delivery date field was confirmed.')).toBeVisible()
    expect(screen.queryByText('0')).not.toBeInTheDocument()
  })
  it('distinguishes zero matching rows while omitting unsupported measures', () => {
    render(<DatasetResults data={{ status: 'available', metric_cards: [{ label: 'Rows', value: 0 }, { label: 'Total value', value: null }] }} />)
    expect(screen.getByText('0')).toBeVisible()
    expect(screen.queryByText('No observed values')).not.toBeInTheDocument()
    expect(screen.queryByText('Total value')).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('No rows match')
  })
  it('removes old dataset values when content switches', () => {
    const { rerender } = render(<DatasetResults data={{ status: 'available', dataset_name: 'A', metric_cards: [{ label: 'Total revenue', value: 1000 }] }} />)
    rerender(<DatasetResults data={{ status: 'available', dataset_name: 'B', metric_cards: [{ label: 'Total revenue', value: 5000 }] }} />)
    expect(screen.queryByText('1,000')).not.toBeInTheDocument()
    expect(screen.getByText('5,000')).toBeVisible()
  })
  it('uses mapped monetary units and semantic availability, not label guessing', () => {
    render(<MemoryRouter><DatasetResults dashboard revenueAvailable monetaryFields={['sales']} data={{status:'available',currency_code:'USD',metric_cards:[{label:'Rows',value:2},{label:'Total sales',value:1000}]}} /></MemoryRouter>)
    expect(screen.getByText('$1,000.00')).toBeVisible()
    expect(screen.queryByText(/Revenue unavailable/)).not.toBeInTheDocument()
  })
  it('shows an actionable state instead of an empty orders graph when the order target is missing', () => {
    render(<MemoryRouter><DatasetResults dashboard data={{
      status:'available', dataset_name:'Sales export',
      metric_cards:[{label:'Rows',value:366}],
      time_series:[{period:'2024-01',rows:366}],
      order_series_quality:{available:false,reason:'No order ID or daily order-count field is mapped.'},
    }} /></MemoryRouter>)
    expect(screen.getByRole('region',{name:'Order chart unavailable'})).toHaveTextContent('No order ID or daily order-count field is mapped.')
    expect(screen.getByRole('link',{name:/Review date and order field mappings/})).toHaveAttribute('href','/datasets')
  })
  it('discloses missing daily order values without replacing them with zero', () => {
    render(<MemoryRouter><DatasetResults dashboard data={{
      status:'available', dataset_name:'Partial daily orders',
      metric_cards:[{label:'Rows',value:2}],
      time_series:[{period:'2024-01-01',rows:1,orders:4},{period:'2024-01-02',rows:1,orders:null}],
      order_series_quality:{available:true,reason:'One dated row has a missing order value; it remains unknown.',order_count_field:'orders'},
    }} /></MemoryRouter>)
    expect(screen.getByRole('note')).toHaveTextContent('it remains unknown')
    expect(screen.getByText('Summed mapped daily order counts by the selected chart grain. Realized history only.')).toBeVisible()
  })
  it('hides generation metadata and incomplete cards from the default KPI view', () => {
    render(<MemoryRouter><DatasetResults dashboard data={{status:'available',metric_cards:[
      {label:'Rows',value:3},{label:'Total generation_seed',value:7},{label:'Total profit',value:null},
    ]}} /></MemoryRouter>)
    expect(screen.getByText('3')).toBeVisible()
    expect(screen.queryByText(/generation_seed/i)).not.toBeInTheDocument()
    expect(screen.queryByText(/profit/i)).not.toBeInTheDocument()
  })
})
