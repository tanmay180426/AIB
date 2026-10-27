const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

const TOKEN_KEY = 'sem5_token'
const REFRESH_KEY = 'sem5_refresh'
const USER_KEY = 'sem5_user'
let sessionGeneration = 0
const sessionListeners = new Set<() => void>()
const notifySession = () => sessionListeners.forEach(listener => listener())
function storageChanged(event: StorageEvent) {
  if (event.key === null || [TOKEN_KEY, REFRESH_KEY, USER_KEY].includes(event.key)) {
    sessionGeneration += 1
    notifySession()
  }
}
export function subscribeSession(listener: () => void) {
  if (!sessionListeners.size) window.addEventListener('storage', storageChanged)
  sessionListeners.add(listener)
  return () => {
    sessionListeners.delete(listener)
    if (!sessionListeners.size) window.removeEventListener('storage', storageChanged)
  }
}
let refreshInFlight: { generation: number; token: string; promise: Promise<string | null> } | null = null

export function getSessionGeneration(): number { return sessionGeneration }

export type Role = 'admin' | 'analyst'

export interface AuthUser {
  id: number
  username: string
  role: Role
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function getRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY)
}

export function getStoredUser(): AuthUser | null {
  const raw = localStorage.getItem(USER_KEY)
  if (!raw) return null
  try {
    const user = JSON.parse(raw) as AuthUser
    return user.role === 'admin' || user.role === 'analyst' ? user : null
  } catch {
    return null
  }
}

/** Replace the locally cached user with an authoritative backend response. */
export function setStoredUser(user: AuthUser) {
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function isAuthRequired(): boolean {
  // Auth is on by default; only an explicit opt-out disables the route guards.
  return import.meta.env.VITE_AUTH_REQUIRED !== 'false'
}

/** Platform administration: admin only. */
export function isAdmin(): boolean {
  return getStoredUser()?.role === 'admin'
}

/** Business intelligence: both supported roles. */
export function isAnalyst(): boolean {
  return getStoredUser()?.role === 'analyst'
}

export function isAdminOrAnalyst(): boolean {
  const role = getStoredUser()?.role
  return role === 'admin' || role === 'analyst'
}

export async function login(username: string, password: string): Promise<AuthUser> {
  logout()
  const generation = sessionGeneration
  const body = new URLSearchParams({ username, password })
  const r = await fetch(`${API_BASE}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  })
  if (!r.ok) throw new Error(r.status === 401 ? 'Invalid credentials' : `Login failed: ${r.status}`)
  const data = (await r.json()) as { access_token: string; refresh_token: string; user: AuthUser }
  if (generation !== sessionGeneration) throw new Error('Session changed; stale login discarded.')
  localStorage.setItem(TOKEN_KEY, data.access_token)
  localStorage.setItem(REFRESH_KEY, data.refresh_token)
  localStorage.setItem(USER_KEY, JSON.stringify(data.user))
  notifySession()
  return data.user
}

export function refreshAccessToken(): Promise<string | null> {
  const generation = sessionGeneration
  const refresh_token = getRefreshToken()
  if (!refresh_token) return Promise.resolve(null)
  if (refreshInFlight?.generation === generation && refreshInFlight.token === refresh_token) return refreshInFlight.promise
  const promise = (async () => { try {
    const r = await fetch(`${API_BASE}/api/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token }),
    })
    if (!r.ok) {
      if ((r.status === 401 || r.status === 403) && generation === sessionGeneration && refresh_token === getRefreshToken()) logout()
      return null
    }
    const data = (await r.json()) as { access_token: string }
    if (generation !== sessionGeneration || refresh_token !== getRefreshToken()) return null
    localStorage.setItem(TOKEN_KEY, data.access_token)
    return data.access_token
  } catch {
    return null
  } })()
  refreshInFlight = { generation, token: refresh_token, promise }
  void promise.finally(() => { if (refreshInFlight?.promise === promise) refreshInFlight = null })
  return promise
}

export function expireSession(generation: number) {
  if (generation === sessionGeneration) logout()
}

export function logout() {
  sessionGeneration += 1
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(REFRESH_KEY)
  localStorage.removeItem(USER_KEY)
  notifySession()
}
