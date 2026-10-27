import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'
import SeasonalityHeatmap from '@/components/SeasonalityHeatmap'
afterEach(cleanup)
it('distinguishes observed zero from absent months and labels unknown currency',()=>{
  render(<SeasonalityHeatmap grain="month" points={[{period:'2024-01',revenue:0},{period:'2024-03',revenue:300}]} />)
  expect(screen.getByTitle('2024-01: 0')).toHaveTextContent('0')
  expect(screen.getByTitle('2024-02: No observed aggregate')).toHaveTextContent('—')
  expect(screen.getByText(/currency unconfirmed/)).toBeVisible()
})
it('does not present daily points or duplicate months as a monthly comparison',()=>{
  const view=render(<SeasonalityHeatmap grain="day" points={[{period:'2024-01-01',orders:1}]} />)
  expect(screen.queryByRole('table')).not.toBeInTheDocument()
  view.rerender(<SeasonalityHeatmap grain="month" points={[{period:'2024-01',orders:1},{period:'2024-01',orders:2}]} />)
  expect(screen.getByText(/unique dated, finite monthly aggregates/)).toBeVisible()
  expect(screen.queryByRole('table')).not.toBeInTheDocument()
})
