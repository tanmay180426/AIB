import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { getAnalyticsOverview, setDatasetScope, uploadDataset } from '@/services/api'

describe('dataset request scoping', () => {
  beforeEach(() => { localStorage.clear(); localStorage.setItem('sem5_token', 'test-token'); setDatasetScope(null) })
  afterEach(() => { vi.unstubAllGlobals(); setDatasetScope(null) })
  it('attaches the explicit dataset to analytical requests', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ rows: 2 }), { status: 200 }))
    vi.stubGlobal('fetch', fetch)
    setDatasetScope('dataset-a')
    await getAnalyticsOverview()
    expect(fetch.mock.calls[0][1].headers['X-Dataset-ID']).toBe('dataset-a')
    expect(fetch.mock.calls[0][1].headers.Authorization).toBe('Bearer test-token')
  })
  it('coalesces only concurrent reads within the same user and dataset generation', async () => {
    let finish!: (r: Response) => void
    const fetch = vi.fn(() => new Promise<Response>(resolve => { finish = resolve }))
    vi.stubGlobal('fetch', fetch)
    setDatasetScope('a')
    const first = getAnalyticsOverview()
    const duplicate = getAnalyticsOverview()
    expect(fetch).toHaveBeenCalledTimes(1)
    finish(new Response('{}', { status: 200 }))
    await Promise.all([first, duplicate])
    const next = getAnalyticsOverview()
    expect(fetch).toHaveBeenCalledTimes(2)
    finish(new Response('{}', { status: 200 }))
    await next
  })
  it('rejects a response from A that completes after B is selected', async () => {
    let finish!: (r: Response) => void
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(resolve => { finish = resolve })))
    setDatasetScope('a')
    const old = getAnalyticsOverview()
    setDatasetScope('b')
    finish(new Response(JSON.stringify({ revenue: 1000 }), { status: 200 }))
    await expect(old).rejects.toThrow('stale response discarded')
  })
  it('rejects a response after a different user logs in', async () => {
    let finish!: (r: Response) => void
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(resolve => { finish = resolve })))
    localStorage.setItem('sem5_user', 'user-a')
    const old = getAnalyticsOverview()
    localStorage.setItem('sem5_user', 'user-b')
    finish(new Response('{}', { status: 200 }))
    await expect(old).rejects.toThrow('stale response discarded')
  })
  it('surfaces safe backend validation messages', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'Duplicate column names were detected.' }), { status: 422 })))
    await expect(uploadDataset(new File(['a,a\n1,2'], 'bad.csv'), 'Bad')).rejects.toThrow('Duplicate column names')
  })
  it('sends a multipart upload without forcing a JSON content type', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ status: 'READY' }), { status: 201 }))
    vi.stubGlobal('fetch', fetch)
    const file = new File(['date,value\n2025-01-01,1'], 'minimal.csv')
    await uploadDataset(file, 'Minimal')
    const init = fetch.mock.calls[0][1]
    expect(init.body).toBeInstanceOf(FormData)
    expect(init.body.get('name')).toBe('Minimal')
    expect(init.headers['Content-Type']).toBeUndefined()
  })
})
