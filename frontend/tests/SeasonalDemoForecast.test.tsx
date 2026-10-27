import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import SeasonalDemoForecast from '@/components/SeasonalDemoForecast'
import { getSeasonalDemoForecast, type SeasonalDemoResponse } from '@/services/api'

vi.mock('@/services/api', async original => ({ ...await original<typeof import('@/services/api')>(), getSeasonalDemoForecast: vi.fn() }))

const demo = (target: 'orders'|'revenue', horizon: 30|90|365): SeasonalDemoResponse => ({
  target, horizon, artifact_horizon: horizon===365 ? 90 : horizon, training_cutoff: '2024-12-31',
  model: { name: 'lightgbm_recursive', algorithm: 'LightGBM recursive', version: 'integrated_seasonal_v1' },
  history: Array.from({length: 365}, (_, i) => ({date:new Date(Date.UTC(2024,11,31-(364-i))).toISOString().slice(0,10), actual:100+i, data_source:'synthetic_extension'})),
  forecast: Array.from({length:horizon}, (_, i) => ({date:new Date(Date.UTC(2025,0,1+i)).toISOString().slice(0,10),[target]:110+i})),
  validation_metrics:{mae:5,r2:0.7}, benchmark_metrics:{mae:6,wape_pct:4.5},
  provenance:{working_series:true,synthetic_backcast_and_extension_included:true,generated_days_in_final_benchmark_pct:100,note:'generated series'},
  warnings:['not live'],
})

beforeEach(() => {
  vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} })
  vi.mocked(getSeasonalDemoForecast).mockImplementation(async (target,horizon) => demo(target,horizon))
})
afterEach(() => { cleanup(); vi.clearAllMocks(); vi.unstubAllGlobals() })

it('loads actual API response and clearly separates experimental forecast from live forecasting', async () => {
  render(<SeasonalDemoForecast />)
  expect(await screen.findByText('lightgbm_recursive')).toBeVisible()
  expect(screen.getByText(/Experimental working-series forecast — not the live production forecast/)).toBeVisible()
  expect(screen.getByText(/Synthetic-data warning/)).toBeVisible()
  expect(screen.getByText(/This saved forecast window has passed/)).toBeVisible()
  expect(screen.getByText(/Saved demonstration dates:/)).toBeVisible()
  expect(screen.getByRole('columnheader', {name:/Historical demo estimate · orders/})).toBeVisible()
  expect(screen.getByTestId('seasonal-demo-chart')).toHaveAttribute('data-history-count','365')
  expect(screen.getByTestId('seasonal-demo-chart')).toHaveAttribute('data-history-start','2024-01-02')
  expect(screen.getByTestId('seasonal-demo-chart')).toHaveAttribute('data-history-end','2024-12-31')
  expect(screen.getByTestId('seasonal-demo-chart')).toHaveAttribute('data-forecast-start','2025-01-01')
  expect(screen.getByTestId('seasonal-demo-chart')).toHaveAttribute('data-boundary-date','2025-01-01')
  expect(screen.getByTestId('seasonal-demo-chart')).toHaveAttribute('data-prediction-count','365')
  expect(screen.getByText(/90-day artifact benchmark MAE/)).toBeVisible()
  expect(screen.getByText('2025-12-31')).toBeVisible()
})

it('starts with the target of the forecast page that contains the demo', async () => {
  render(<SeasonalDemoForecast initialTarget="revenue" />)
  await waitFor(() => expect(getSeasonalDemoForecast).toHaveBeenCalledWith('revenue',365))
  expect(await screen.findByText(/Historical demo estimate · item-price revenue/)).toBeVisible()
})

it('requests selected target and horizon and displays errors without substitute forecasts', async () => {
  render(<SeasonalDemoForecast />)
  await screen.findByText('lightgbm_recursive')
  fireEvent.change(screen.getByLabelText('Demo target'), {target:{value:'revenue'}})
  await waitFor(() => expect(getSeasonalDemoForecast).toHaveBeenLastCalledWith('revenue',365))
  expect(await screen.findByText(/Historical demo estimate · item-price revenue/)).toBeVisible()
  vi.mocked(getSeasonalDemoForecast).mockRejectedValueOnce(new Error('Artifact unavailable'))
  fireEvent.change(screen.getByLabelText('Demo horizon'), {target:{value:'90'}})
  expect(await screen.findByRole('alert')).toHaveTextContent('Artifact unavailable')
  expect(screen.queryByTestId('seasonal-demo-chart')).not.toBeInTheDocument()
})

it('rejects missing historical data without drawing a chart', async () => {
  const invalid = demo('orders',365)
  invalid.history = []
  vi.mocked(getSeasonalDemoForecast).mockResolvedValueOnce(invalid)
  render(<SeasonalDemoForecast />)
  expect(await screen.findByRole('alert')).toHaveTextContent('historical working-series data is unavailable')
  expect(screen.queryByTestId('seasonal-demo-chart')).not.toBeInTheDocument()
})

it('rejects non-consecutive prediction dates without drawing a chart', async () => {
  const invalid = demo('orders',365)
  invalid.forecast[4].date = invalid.forecast[3].date
  vi.mocked(getSeasonalDemoForecast).mockResolvedValueOnce(invalid)
  render(<SeasonalDemoForecast />)
  expect(await screen.findByRole('alert')).toHaveTextContent('non-consecutive dates')
  expect(screen.queryByTestId('seasonal-demo-chart')).not.toBeInTheDocument()
})

it('requests the 365-day recursive extension and labels its limits', async () => {
  render(<SeasonalDemoForecast />)
  await screen.findByText('lightgbm_recursive')
  fireEvent.change(screen.getByLabelText('Seasonal demo horizon'), {target:{value:'365'}})
  await waitFor(() => expect(getSeasonalDemoForecast).toHaveBeenLastCalledWith('orders',365))
  expect(await screen.findByText(/90-day artifact benchmark MAE \(not 365-day performance\)/)).toBeVisible()
  expect(screen.getByText(/365-day recursive extension uses the saved 90-day LightGBM artifact/)).toBeVisible()
  expect(screen.getByRole('columnheader', {name:/Historical demo estimate · orders/})).toBeVisible()
  expect(screen.getByTestId('seasonal-demo-chart')).toHaveAttribute('data-prediction-count','365')
})
