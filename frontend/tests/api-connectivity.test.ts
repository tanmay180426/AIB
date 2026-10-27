import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { downloadReport, getAnalyticsOverview, getAnomalies, getCustomerSegments, predictSales, setDatasetScope } from '@/services/api'
import { logout } from '@/services/auth'

describe('shared API transport and ML connection contracts', () => {
  beforeEach(() => {
    localStorage.clear(); localStorage.setItem('sem5_token', 'access'); localStorage.setItem('sem5_refresh', 'refresh')
    localStorage.setItem('sem5_user', JSON.stringify({ username: 'analyst', role: 'analyst' }))
    setDatasetScope('selected')
    vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:test'), revokeObjectURL: vi.fn() })
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
  })
  afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); setDatasetScope(null) })

  it('passes selected filters and dataset to customer/anomaly/sales calls', async () => {
    const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ status: 'not_applicable', reason: 'Missing semantic fields' }), { status: 200 })))
    vi.stubGlobal('fetch', fetch)
    const filters = { date_from: '2025-01-01', category: 'books', grain: 'month' }
    await getCustomerSegments(filters); await getAnomalies(filters)
    const result = await predictSales({ purchase_month: 1, purchase_weekday: 0, purchase_hour: 12,
      n_items: 1, customer_state: 'SP', product_category_name: 'books' }, filters)
    expect(result.status).toBe('not_applicable')
    for (const [url, init] of fetch.mock.calls) {
      expect(url).toContain('date_from=2025-01-01')
      expect(url).toContain('category=books')
      expect(url).not.toContain('grain=')
      expect(init.headers['X-Dataset-ID']).toBe('selected')
    }
    expect(fetch.mock.calls[2][1].method).toBe('POST')
    expect(JSON.parse(fetch.mock.calls[2][1].body).n_items).toBe(1)
  })

  it('refreshes an expired access token before downloading real CSV content', async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(new Response('{"detail":"expired"}', { status: 401 }))
      .mockResolvedValueOnce(new Response('{"access_token":"fresh"}', { status: 200 }))
      .mockResolvedValueOnce(new Response('region,revenue\nPune,200\n', { status: 200, headers: { 'Content-Type': 'text/csv' } }))
    vi.stubGlobal('fetch', fetch)
    vi.useFakeTimers()
    await downloadReport('dataset_rows', { column_filters: '{"region":"Pune"}' })
    expect(fetch.mock.calls[1][0]).toContain('/api/auth/refresh')
    expect(fetch.mock.calls[2][1].headers.Authorization).toBe('Bearer fresh')
    expect(fetch.mock.calls[2][1].headers['X-Dataset-ID']).toBe('selected')
    expect(URL.createObjectURL).toHaveBeenCalledOnce()
    expect(HTMLAnchorElement.prototype.click).toHaveBeenCalledOnce()
    vi.runOnlyPendingTimers()
    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:test')
    vi.useRealTimers()
  })

  it('does not download old-user data when logout happens during CSV body decoding', async () => {
    let finish!: (value: Blob) => void
    const response = new Response('csv', { status: 200 })
    vi.spyOn(response, 'blob').mockImplementation(() => new Promise(resolve => { finish = resolve }))
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))
    const pending = downloadReport('kpis')
    await vi.waitFor(() => expect(finish).toBeDefined())
    logout()
    finish(new Blob(['private-data']))
    await expect(pending).rejects.toThrow('session changed; export discarded')
    expect(URL.createObjectURL).not.toHaveBeenCalled()
  })

  it('rejects JSON decoded after logout even if the user snapshot is restored', async () => {
    let finish!: (value: object) => void
    const response = new Response('{}', { status: 200 })
    vi.spyOn(response, 'json').mockImplementation(() => new Promise(resolve => { finish = resolve }))
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))
    const user = localStorage.getItem('sem5_user')!
    const pending = getAnalyticsOverview()
    await vi.waitFor(() => expect(finish).toBeDefined())
    logout(); localStorage.setItem('sem5_user', user)
    finish({ private: 'old session' })
    await expect(pending).rejects.toThrow('stale response discarded')
  })

  it('keeps the chosen report authoritative over a conflicting filter parameter', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response('csv', { status: 200 }))
    vi.stubGlobal('fetch', fetch)
    vi.useFakeTimers()
    await downloadReport('kpis', { report: 'dataset_rows' })
    expect(fetch.mock.calls[0][0]).toContain('report=kpis')
    expect(fetch.mock.calls[0][0]).not.toContain('report=dataset_rows')
    vi.runOnlyPendingTimers()
    vi.useRealTimers()
  })
})
