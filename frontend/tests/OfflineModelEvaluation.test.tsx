import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { cloneElement, type ReactElement } from 'react'
import OfflineModelEvaluation from '@/components/OfflineModelEvaluation'
import { getForecast, getOfflineModelEvaluation } from '@/services/api'

vi.mock('@/services/api', async original => ({
  ...await original<typeof import('@/services/api')>(),
  getForecast: vi.fn(),
  getOfflineModelEvaluation: vi.fn(),
}))
vi.mock('recharts', async original => ({
  ...await original<typeof import('recharts')>(),
  ResponsiveContainer: ({ children }: { children: ReactElement }) => cloneElement(children, { width: 900, height: 320 }),
}))
afterEach(() => { cleanup(); vi.clearAllMocks() })

const result = (target: 'orders' | 'revenue' | 'profit', horizon: 30 | 90, model: string) => ({
  target, horizon, model, available: true as const, quality_status: 'validation_only' as const,
  semantic_status: target === 'profit' ? 'provisional' : 'documented_definition_currency_unverified',
  target_definition: target === 'profit' ? 'Summed item_profit; formula and units are unverified.' : target === 'orders' ? 'Unified daily order count.' : 'Item-price sum excluding freight.',
  unit: target === 'profit' ? 'Unverified experiment units' : target === 'orders' ? 'Orders' : 'Item-price units; currency unconfirmed.',
  evaluation_period: { from: '2023-05-03', to: '2023-05-04' },
  points: [
    { date: '2023-05-03', actual: 10, prediction: 11, data_origin: 'source_observed' as const },
    { date: '2023-05-04', actual: 12, prediction: 13, data_origin: 'synthetic_extension' as const },
  ],
  metrics: { mae: 1, rmse: 1, r2: 0.75 }, origin_count: 20,
  ...(target === 'orders' ? { peak_definition: 'Peak q90; dips q10.', peak_metrics: { precision: 0.5, recall: 0.4, magnitude_mae: 2, normal_period_mae: 1, timing_mae_days: 3 }, points: [
    { date: '2023-05-03', actual: 10, prediction: 11, data_origin: 'source_observed' as const, peak_threshold: 9, dip_threshold: 3, prediction_peak: 11, prediction_dip: null },
    { date: '2023-05-04', actual: 12, prediction: 13, data_origin: 'synthetic_extension' as const, peak_threshold: 9, dip_threshold: 3, prediction_peak: 13, prediction_dip: null },
  ] } : {}),
  provenance: { source_observed_points: 1, synthetic_extension_points: 1 },
  warnings: ['1 of 2 scored dates use generated synthetic targets; these scores do not establish real-world accuracy.'],
})

it('shows date-aligned offline metrics and provenance without requesting a live forecast', async () => {
  vi.mocked(getOfflineModelEvaluation).mockResolvedValueOnce({
    status: 'available', label: 'Experimental validation results — not live forecasts.',
    experiment: 'fixture', validation_protocol: 'chronological validation, no holdout',
    results: [result('orders', 30, 'peak_weighted_histgradient_recursive'), result('orders', 90, 'lightgbm_recursive'), result('revenue', 30, 'lightgbm_recursive'), result('revenue', 90, 'peak_weighted_direct_ridge'), result('profit', 30, 'lightgbm_recursive'), result('profit', 90, 'lightgbm_recursive')],
  })
  render(<OfflineModelEvaluation />)
  expect(await screen.findByText('lightgbm_recursive')).toBeVisible()
  expect(screen.getByText('Experimental validation results — not live forecasts.')).toBeVisible()
  expect(screen.getByText('2023-05-03–2023-05-04')).toBeVisible()
  expect(screen.getByText(/synthetic targets/)).toBeVisible()
  expect(screen.getByText(/R²/)).toBeVisible()
  expect(screen.getAllByText(/Revenue · currency unverified/)).toHaveLength(2)
  expect(screen.getByText(/source\/model units/)).toBeVisible()
  expect(screen.getAllByText('1')).toHaveLength(2)
  expect(screen.getByTestId('offline-evaluation-chart')).toBeVisible()
  expect(getOfflineModelEvaluation).toHaveBeenCalledTimes(1)
  expect(getForecast).not.toHaveBeenCalled()
})

it('labels profit as provisional with unknown units', async () => {
  vi.mocked(getOfflineModelEvaluation).mockResolvedValueOnce({
    status: 'available', label: 'Experimental validation results — not live forecasts.',
    experiment: 'fixture', validation_protocol: 'chronological validation, no holdout',
    results: [result('orders', 30, 'peak_weighted_histgradient_recursive'), result('orders', 90, 'lightgbm_recursive'), result('revenue', 30, 'lightgbm_recursive'), result('revenue', 90, 'peak_weighted_direct_ridge'), result('profit', 30, 'lightgbm_recursive'), result('profit', 90, 'lightgbm_recursive')],
  })
  render(<OfflineModelEvaluation />)
  await screen.findByText('lightgbm_recursive')
  fireEvent.change(screen.getByLabelText('Offline evaluation target'), { target: { value: 'profit' } })
  expect(await screen.findByText(/Provisional profit series/)).toBeVisible()
  expect(screen.getByTestId('offline-model-evaluation')).toHaveTextContent('formula and units are unverified')
  expect(screen.getAllByText('Profit · provisional units unknown')).toHaveLength(2)
  expect(screen.getByText(/profit formula and units are provisional/)).toBeVisible()
})

it('shows the selected peak-aware orders validation and diagnostic metrics', async () => {
  vi.mocked(getOfflineModelEvaluation).mockResolvedValueOnce({
    status: 'available', label: 'Experimental validation results — not live forecasts.',
    experiment: 'fixture', validation_protocol: 'chronological validation, no holdout',
    results: [result('orders', 30, 'peak_weighted_histgradient_recursive')],
  })
  render(<OfflineModelEvaluation />)
  await screen.findByText('Saved evaluation is unavailable.')
  fireEvent.change(screen.getByLabelText('Offline evaluation target'), { target: { value: 'orders' } })
  expect(await screen.findByText('peak_weighted_histgradient_recursive')).toBeVisible()
  expect(screen.getByText(/Peak precision/)).toBeVisible()
  expect(screen.getByText('Predicted peak · origin q90')).toBeVisible()
  expect(screen.getAllByText('Orders')).toHaveLength(2)
  expect(screen.queryByText(/\$1\.00/)).not.toBeInTheDocument()
})

it('shows an unavailable state for a missing saved horizon', async () => {
  vi.mocked(getOfflineModelEvaluation).mockResolvedValueOnce({
    status: 'available', label: 'Experimental validation results — not live forecasts.',
    experiment: 'fixture', validation_protocol: 'chronological validation, no holdout',
    results: [{ ...result('revenue', 30, 'lightgbm_recursive'), available: false, reason: 'Saved predictions missing.' }],
  })
  render(<OfflineModelEvaluation />)
  expect(await screen.findByText('Saved predictions missing.')).toBeVisible()
  expect(screen.queryByTestId('offline-evaluation-chart')).not.toBeInTheDocument()
})
