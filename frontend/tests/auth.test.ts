import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  getStoredUser,
  getToken,
  isAdmin,
  isAnalyst,
  isAdminOrAnalyst,
  login,
  logout,
  refreshAccessToken,
} from '@/services/auth'

describe('auth service', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('login stores access token, refresh token, and user', async () => {
    const payload = {
      access_token: 'access-123',
      refresh_token: 'refresh-456',
      token_type: 'bearer',
      user: { id: 1, username: 'admin', role: 'admin' },
    }
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, json: async () => payload }),
    )

    const user = await login('admin', 'abi_test_admin_only')

    expect(user.role).toBe('admin')
    expect(getToken()).toBe('access-123')
    expect(localStorage.getItem('sem5_refresh')).toBe('refresh-456')
    expect(getStoredUser()?.username).toBe('admin')
  })

  it('login throws on invalid credentials', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: false, status: 401, json: async () => ({}) }),
    )
    await expect(login('admin', 'wrong')).rejects.toThrow('Invalid credentials')
  })

  it('logout clears stored state', async () => {
    const payload = {
      access_token: 'a',
      refresh_token: 'r',
      token_type: 'bearer',
      user: { id: 1, username: 'admin', role: 'admin' },
    }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => payload }))
    await login('admin', 'abi_test_admin_only')

    logout()

    expect(getToken()).toBeNull()
    expect(getStoredUser()).toBeNull()
    expect(localStorage.getItem('sem5_refresh')).toBeNull()
  })

  it('discards refresh after logout', async () => {
    localStorage.setItem('sem5_refresh', 'refresh-a')
    let finish!: (response: Response) => void
    vi.stubGlobal('fetch', vi.fn(() => new Promise<Response>(resolve => { finish = resolve })))
    const pending = refreshAccessToken()
    logout()
    finish(new Response(JSON.stringify({ access_token: 'late-a' }), { status: 200 }))
    expect(await pending).toBeNull()
    expect(getToken()).toBeNull()
  })

  it('discards old refresh after a newer login', async () => {
    localStorage.setItem('sem5_refresh', 'refresh-a')
    let finish!: (response: Response) => void
    vi.stubGlobal('fetch', vi.fn().mockImplementationOnce(() => new Promise<Response>(resolve => { finish = resolve }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ access_token: 'b', refresh_token: 'refresh-b', user: { id: 2, username: 'b', role: 'analyst' } }), { status: 200 })))
    const pending = refreshAccessToken()
    await login('b', 'password')
    finish(new Response(JSON.stringify({ access_token: 'late-a' }), { status: 200 }))
    expect(await pending).toBeNull()
    expect(getToken()).toBe('b')
  })

  it('refreshes a restored browser session normally', async () => {
    localStorage.setItem('sem5_refresh', 'restored-refresh')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ access_token: 'renewed' }), { status: 200 })))
    expect(await refreshAccessToken()).toBe('renewed')
    expect(getToken()).toBe('renewed')
  })

  it('preserves authentication during a temporary refresh service failure', async () => {
    localStorage.setItem('sem5_refresh', 'refresh-a')
    localStorage.setItem('sem5_token', 'existing')
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 503 })))
    expect(await refreshAccessToken()).toBeNull()
    expect(getToken()).toBe('existing')
  })
})

describe('role helpers', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  function store(role: string) {
    localStorage.setItem(
      'sem5_user',
      JSON.stringify({ id: 1, username: role, role }),
    )
  }

  it('identifies the admin role', () => {
    store('admin')
    expect(isAdmin()).toBe(true)
    expect(isAnalyst()).toBe(false)
    expect(isAdminOrAnalyst()).toBe(true)
  })

  it('identifies the analyst role', () => {
    store('analyst')
    expect(isAdmin()).toBe(false)
    expect(isAnalyst()).toBe(true)
    expect(isAdminOrAnalyst()).toBe(true)
  })

  it('ignores unknown/retired roles such as viewer', () => {
    store('viewer')
    expect(getStoredUser()).toBeNull()
    expect(isAdmin()).toBe(false)
    expect(isAnalyst()).toBe(false)
    expect(isAdminOrAnalyst()).toBe(false)
  })

  it('defaults to auth being required', () => {
    vi.unstubAllEnvs()
    expect(import.meta.env.VITE_AUTH_REQUIRED).not.toBe('false')
  })
})
