import { useCallback, useEffect, useState } from 'react'
import { Link, Navigate, Outlet, useLocation } from 'react-router-dom'
import AccessDenied from '@/components/AccessDenied'
import { useSession } from '@/hooks/useSession'
import { getMe } from '@/services/api'
import { getToken, getStoredUser, isAuthRequired, setStoredUser } from '@/services/auth'

type State = 'checking' | 'allowed' | 'denied' | 'unauthenticated' | 'error'

function statusOf(err: unknown): number {
  const match = /Request failed:\s*(\d{3})/.exec(String((err as Error)?.message ?? ''))
  return match ? Number(match[1]) : 0
}

/**
 * Administration guard (route-level, admin only).
 *
 * The backend is the authorization boundary: we ask `/api/users/me` which role
 * the server actually sees, reconcile the cached copy, and only render admin
 * content once the answer is known (no restricted content flash while loading).
 *
 * Local role state is never used to grant access:
 * - 401 (expired/invalid session) -> authentication flow
 * - any other failure (backend unreachable, 5xx) -> fail safe: admin content
 *   stays hidden behind a retryable error instead of trusting localStorage
 */
export default function RequireAdmin() {
  useSession()
  const location = useLocation()
  const [state, setState] = useState<State>('checking')
  const [attempt, setAttempt] = useState(0)
  const needsLogin = isAuthRequired() && !getToken()

  useEffect(() => {
    if (needsLogin) return undefined
    let cancelled = false
    setState('checking')

    getMe()
      .then(({ user }) => {
        if (cancelled) return
        setStoredUser(user)
        setState(user.role === 'admin' ? 'allowed' : 'denied')
      })
      .catch((err: unknown) => {
        if (cancelled) return
        const status = statusOf(err)
        setState(status === 401 ? 'unauthenticated' : 'error')
      })

    return () => {
      cancelled = true
    }
  }, [needsLogin, attempt])

  const retry = useCallback(() => setAttempt((n) => n + 1), [])

  if (needsLogin || state === 'unauthenticated') {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }

  if (state === 'checking') {
    return <div className="text-neutral-500 text-sm">Checking access…</div>
  }

  if (state === 'denied' || !getStoredUser()) {
    return <AccessDenied section="Platform Administration" />
  }

  if (state === 'error') {
    return (
      <div className="min-h-[50vh] flex items-center justify-center">
        <div className="max-w-md text-center space-y-3">
          <div className="text-2xl font-semibold tracking-tight">
            Could not verify access
          </div>
          <p className="text-sm text-neutral-500">
            The server did not respond, so administration content is hidden.
          </p>
          <div className="flex items-center justify-center gap-3 pt-1">
            <button
              type="button"
              onClick={retry}
              className="px-4 py-2 rounded bg-blue-600 hover:bg-blue-500 text-sm font-medium"
            >
              Try again
            </button>
            <Link to="/dashboard" className="text-sm text-neutral-400 hover:text-neutral-200">
              Back to Dashboard
            </Link>
          </div>
        </div>
      </div>
    )
  }

  return <Outlet />
}
