import { afterEach, expect, it, vi } from 'vitest'
import { getCustomerSegments, getAnomalies, setDatasetScope } from '@/services/api'

const compatibility = { compatible: true, reasons: [], contract: {}, training_domain: 'commerce', dataset_id: 'a', artifact_available: true }
const customers: Awaited<ReturnType<typeof getCustomerSegments>> = { status: 'available', dataset_id: 'a', compatibility,
  segments: [{ segment: 1, customers: 2, monetary: 100 }] }
const anomalies: Awaited<ReturnType<typeof getAnomalies>> = { status: 'available', dataset_id: 'a', compatibility,
  n_days: 30, n_anomalies: 1, anomalies: [{ date: '2025-01-01', orders: 2, revenue: 100, anomaly: -1, score: -.1 }] }
const unavailable: Awaited<ReturnType<typeof getAnomalies>> = { status: 'not_applicable', dataset_id: 'a',
  reason: 'Missing fields', compatibility: { ...compatibility, compatible: false, reasons: ['Missing fields'] } }
afterEach(() => { vi.unstubAllGlobals(); setDatasetScope(null) })

it('reads current customer inference fields', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(customers))))
  const result = await getCustomerSegments()
  if (result.status !== 'available') throw new Error('Expected available')
  expect(result.segments[0].monetary).toBe(100)
})
it('reads current anomaly inference fields', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(anomalies))))
  const result = await getAnomalies()
  if (result.status !== 'available') throw new Error('Expected available')
  expect(result.anomalies[0].score).toBe(-.1)
})
it('handles Not Applicable for both helpers', async () => {
  vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify(unavailable)))))
  for (const result of [await getCustomerSegments(), await getAnomalies()]) {
    if (result.status !== 'not_applicable') throw new Error('Expected Not Applicable')
    expect(result.reason).toBe('Missing fields')
  }
})
it('surfaces inference HTTP errors rather than treating them as success', async () => {
  vi.stubGlobal('fetch', vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ detail: 'Artifact unavailable' }), { status: 503 }))))
  await expect(getCustomerSegments()).rejects.toThrow('Artifact unavailable')
  await expect(getAnomalies()).rejects.toThrow('Artifact unavailable')
})
