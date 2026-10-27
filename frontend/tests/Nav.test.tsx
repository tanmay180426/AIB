import { fireEvent, render, screen, cleanup } from '@testing-library/react'
import { MemoryRouter, useLocation } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import Nav from '@/components/common/Nav'

const auth = vi.hoisted(() => ({ admin: false, logout: vi.fn() }))
vi.mock('@/services/auth', () => ({ getStoredUser: () => ({ username: 'test-user', role: auth.admin ? 'admin' : 'analyst' }), isAdmin: () => auth.admin, logout: auth.logout }))
afterEach(() => { cleanup(); auth.admin = false; auth.logout.mockClear() })
function Location() { return <output aria-label="Current route">{useLocation().pathname}</output> }
function view(onNavigate = vi.fn()) {
  render(<MemoryRouter initialEntries={['/analytics/sales?date_from=2025-01-01']}><Nav onNavigate={onNavigate} /><Location /></MemoryRouter>)
  return onNavigate
}
describe('workspace navigation', () => {
  it('keeps the active section and scoped query while closing a mobile menu on navigation', () => {
    const close = view()
    expect(screen.getByRole('link', { name: 'Analytics' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('link', { name: 'Dataset Manager' })).toHaveAttribute('href', '/datasets?date_from=2025-01-01')
    fireEvent.click(screen.getByRole('link', { name: 'Dataset Manager' }))
    expect(close).toHaveBeenCalledOnce()
    expect(screen.getByLabelText('Current route')).toHaveTextContent('/datasets')
    expect(screen.queryByRole('link', { name: 'Users' })).not.toBeInTheDocument()
  })
  it('preserves every existing administration destination for an admin', () => {
    auth.admin = true; view()
    for (const name of ['Users', 'System Health', 'Data / ETL', 'Warehouse', 'ML Admin', 'Settings']) expect(screen.getByRole('link', { name })).toBeVisible()
  })
  it('uses the existing logout handler and returns to the real login route', () => {
    view(); fireEvent.click(screen.getByRole('button', { name: 'Sign out' }))
    expect(auth.logout).toHaveBeenCalledOnce()
    expect(screen.getByLabelText('Current route')).toHaveTextContent('/login')
  })
})
