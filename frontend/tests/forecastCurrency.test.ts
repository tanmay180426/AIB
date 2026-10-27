import { describe, expect, it } from 'vitest'
import { formatMetricNumber, formatUsdAmount, forecastNumber } from '@/services/forecast'

describe('forecast currency display', () => {
  it('formats positive, zero, negative, precise and large USD values consistently', () => {
    expect(formatUsdAmount(1234.5)).toBe('$1,234.50')
    expect(formatUsdAmount(0)).toBe('$0.00')
    expect(formatUsdAmount(-1234.5)).toBe('-$1,234.50')
    expect(formatUsdAmount(1234567890.125)).toBe('$1,234,567,890.13')
  })

  it('fails safely for missing and invalid values', () => {
    for (const value of [null, undefined, NaN, Infinity, -Infinity, '123']) {
      expect(formatUsdAmount(value)).toBe('Unavailable')
      expect(formatMetricNumber(value)).toBe('Unavailable')
    }
  })

  it('keeps order counts and dimensionless metrics free of currency symbols', () => {
    expect(forecastNumber(1234, 'orders')).toBe('1,234')
    expect(formatMetricNumber(0.486)).toBe('0.49')
    expect(formatMetricNumber(23.83)).toBe('23.83')
  })

  it('formats only an explicitly supplied source currency and stays neutral when unknown', () => {
    expect(forecastNumber(1234.5, 'revenue', 'BRL')).toBe('R$1,234.50')
    expect(forecastNumber(1234.5, 'revenue', null)).toBe('1,234.5')
  })
})
