import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import RequireAuth from '@/components/RequireAuth'

function renderApp() {
  return render(
    <MemoryRouter initialEntries={['/dashboard']}>
      <Routes>
        <Route element={<RequireAuth />}>
          <Route path="/dashboard" element={<div>protected content</div>} />
        </Route>
        <Route path="/login" element={<div>login page</div>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('RequireAuth', () => {
  afterEach(() => {
    vi.unstubAllEnvs()
    localStorage.clear()
  })

  it('redirects to /login when auth is required and no token exists', () => {
    vi.stubEnv('VITE_AUTH_REQUIRED', 'true')
    localStorage.clear()
    renderApp()
    expect(screen.getByText('login page')).toBeInTheDocument()
  })

  it('renders children when auth is not required', () => {
    vi.stubEnv('VITE_AUTH_REQUIRED', 'false')
    renderApp()
    expect(screen.getByText('protected content')).toBeInTheDocument()
  })
})
