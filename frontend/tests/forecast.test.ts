import { expect, it } from 'vitest'
import { forecastDate, forecastNumber, forecastPoints } from '@/services/forecast'

const history = [{ date: '2025-01-01', orders: 4 }, { date: '2025-01-02', orders: 7 }]
const future = [{ date: '2025-01-03', orders: 8 }, { date: '2025-01-04', orders: -1 }]
it('orders dates and keeps historical/future values separate without clamping model output', () => {
  const points = forecastPoints([...history].reverse(), future, 'orders')
  expect(points.map(p => [p.date, p.historical, p.forecast])).toEqual([
    ['2025-01-01',4,null],['2025-01-02',7,null],['2025-01-03',null,8],['2025-01-04',null,-1],
  ])
  expect(forecastDate(points[0].time)).toBe('2025-01-01')
  expect(points[0]).not.toHaveProperty('interval')
  expect(points[0]).not.toHaveProperty('backtest')
})
it.each([NaN, Infinity, undefined, null])('rejects missing or nonfinite values (%s) without zero imputation', value => {
  expect(() => forecastPoints(history, [{ date: '2025-01-03', orders: value as number }], 'orders')).toThrow()
})
it.each(['2025-02-30','invalid','2025-01-02','2025-01-05'])('rejects invalid, overlapping and misaligned forecast dates (%s)', date => {
  expect(() => forecastPoints(history, [{ date, orders: 9 }], 'orders')).toThrow()
})
it('rejects duplicate and gapped historical dates', () => {
  expect(() => forecastPoints([history[0],history[0]], future, 'orders')).toThrow(/duplicate/)
  expect(() => forecastPoints([history[0],{date:'2025-01-03',orders:4}], [{date:'2025-01-04',orders:5}], 'orders')).toThrow(/gaps/)
})
it('formats only confirmed monetary units and keeps fractional order estimates', () => {
  expect(forecastNumber(10.25, 'revenue', 'BRL')).toContain('10.25')
  expect(forecastNumber(10.25, 'revenue')).toBe('10.25')
  expect(forecastNumber(10.25, 'orders')).toBe('10.25')
})
