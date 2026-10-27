import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import RequireAdmin from '@/components/RequireAdmin'
import { getMe } from '@/services/api'
import type { AuthUser } from '@/services/auth'

vi.mock('@/services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/services/api')>()
  return { ...actual, getMe: vi.fn() }
})

const mockedGetMe = vi.mocked(getMe)

function store(role: 'admin' | 'analyst', token = 'token') {
  localStorage.setItem('sem5_token', token)
  localStorage.setItem(
    'sem5_user',
    JSON.stringify({ id: 1, username: role, role } satisfies AuthUser),
  )
}

function renderAdmin() {
  return render(
    <MemoryRouter initialEntries={['/admin/users']}>
      <Routes>
        <Route element={<RequireAdmin />}>
          <Route path="/admin/users" element={<div>admin content</div>} />
        </Route>
        <Route path="/login" element={<div>login page</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('RequireAdmin', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    vi.clearAllMocks()
    localStorage.clear()
  })

  it('renders admin content when the backend confirms an admin', async () => {
    vi.stubEnv('VITE_AUTH_REQUIRED', 'true')
    store('admin')
    mockedGetMe.mockResolvedValue({
      user: { id: 1, username: 'admin', role: 'admin' },
    })

    renderAdmin()
    expect(await screen.findByText('admin content')).toBeInTheDocument()
  })

  it('shows access denied for an analyst', async () => {
    vi.stubEnv('VITE_AUTH_REQUIRED', 'true')
    store('analyst')
    mockedGetMe.mockResolvedValue({
      user: { id: 2, username: 'analyst', role: 'analyst' },
    })

    renderAdmin()
    expect(await screen.findByText('Access Restricted')).toBeInTheDocument()
    expect(screen.queryByText('admin content')).not.toBeInTheDocument()
  })

  it('trusts the backend over a stale local admin role', async () => {
    vi.stubEnv('VITE_AUTH_REQUIRED', 'true')
    store('admin')
    mockedGetMe.mockResolvedValue({
      user: { id: 1, username: 'admin', role: 'analyst' },
    })

    renderAdmin()
    expect(await screen.findByText('Access Restricted')).toBeInTheDocument()
    expect(screen.queryByText('admin content')).not.toBeInTheDocument()
  })

  it('redirects to login when auth is required and there is no token', () => {
    vi.stubEnv('VITE_AUTH_REQUIRED', 'true')
    localStorage.clear()

    renderAdmin()
    expect(screen.getByText('login page')).toBeInTheDocument()
    expect(mockedGetMe).not.toHaveBeenCalled()
  })

  it('redirects to login when the backend rejects the session (401)', async () => {
    vi.stubEnv('VITE_AUTH_REQUIRED', 'true')
    store('admin')
    mockedGetMe.mockRejectedValue(new Error('Request failed: 401'))

    renderAdmin()
    expect(await screen.findByText('login page')).toBeInTheDocument()
    expect(screen.queryByText('admin content')).not.toBeInTheDocument()
  })

  it('fails safe when the backend cannot be reached: never trusts localStorage', async () => {
    vi.stubEnv('VITE_AUTH_REQUIRED', 'true')
    store('admin')
    mockedGetMe.mockRejectedValue(new Error('Failed to fetch'))

    renderAdmin()
    expect(await screen.findByText('Could not verify access')).toBeInTheDocument()
    expect(screen.queryByText('admin content')).not.toBeInTheDocument()

    // a retry that succeeds still renders admin content for a real admin
    mockedGetMe.mockResolvedValue({ user: { id: 1, username: 'admin', role: 'admin' } })
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('admin content')).toBeInTheDocument()
  })
})
