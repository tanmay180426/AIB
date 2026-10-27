import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import Insights from '@/pages/Insights'
import { queryInsights, setDatasetScope, type InsightsResponse } from '@/services/api'
import { logout } from '@/services/auth'

const state = vi.hoisted(() => ({ filters: {} as Record<string, string> }))
vi.mock('@/hooks/useFilters', () => ({ useFilters: () => ({ filters: state.filters }) }))
vi.mock('@/components/FilterBar', () => ({ default: () => null }))
vi.mock('@/services/api', async importOriginal => ({ ...await importOriginal<typeof import('@/services/api')>(), queryInsights: vi.fn() }))

let complete: Array<(value: InsightsResponse) => void>
beforeEach(() => {
  localStorage.clear(); logout(); setDatasetScope('a'); state.filters = {}; complete = []
  vi.mocked(queryInsights).mockImplementation(() => new Promise(resolve => { complete.push(resolve) }))
})
afterEach(() => { cleanup(); vi.clearAllMocks() })
async function finish(index: number, answer: string) {
  await act(async () => { complete[index]({ answer, sources: [], status: 'available', provider: 'computed', role: 'analyst', dataset_id: 'a' }) })
}

it('keeps B when B finishes before A', async () => {
  render(<Insights />)
  fireEvent.click(screen.getByRole('button', { name: 'What is the total revenue and average order value?' }))
  fireEvent.click(screen.getByRole('button', { name: 'How many unique customers and orders are there?' }))
  await finish(1, 'new B answer')
  await finish(0, 'old A answer')
  expect(screen.getByText('new B answer')).toBeVisible()
  expect(screen.queryByText('old A answer')).not.toBeInTheDocument()
})

it('discards a pending answer after filters change', async () => {
  const view = render(<Insights />)
  fireEvent.click(screen.getByRole('button', { name: 'Ask', exact: true }))
  state.filters = { category: 'Books' }; view.rerender(<Insights />)
  await finish(0, 'old filters')
  expect(screen.queryByText('old filters')).not.toBeInTheDocument()
})

it('clears an existing answer on a filter change', async () => {
  const view = render(<Insights />)
  fireEvent.click(screen.getByRole('button', { name: 'Ask', exact: true }))
  await finish(0, 'completed answer')
  state.filters = { category: 'Books' }; view.rerender(<Insights />)
  expect(screen.queryByText('completed answer')).not.toBeInTheDocument()
})

it('discards a pending answer after dataset generation changes', async () => {
  const view = render(<Insights />)
  fireEvent.click(screen.getByRole('button', { name: 'Ask', exact: true }))
  setDatasetScope('b'); view.rerender(<Insights />)
  await finish(0, 'old dataset')
  expect(screen.queryByText('old dataset')).not.toBeInTheDocument()
})

it('discards a pending answer after logout even before another render', async () => {
  render(<Insights />)
  fireEvent.click(screen.getByRole('button', { name: 'Ask', exact: true }))
  logout()
  await finish(0, 'old session')
  expect(screen.queryByText('old session')).not.toBeInTheDocument()
})

it('discards a pending answer when the question is edited', async () => {
  render(<Insights />)
  fireEvent.click(screen.getByRole('button', { name: 'Ask', exact: true }))
  fireEvent.change(screen.getByLabelText('Question'), { target: { value: 'different question' } })
  await finish(0, 'old question')
  expect(screen.queryByText('old question')).not.toBeInTheDocument()
})
