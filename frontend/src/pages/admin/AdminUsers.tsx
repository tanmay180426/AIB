import { useCallback, useEffect, useState } from 'react'
import { adminCreateUser, listUsers, updateUserRole, updateUserStatus, type PublicUser } from '@/services/api'
import { getStoredUser, type Role } from '@/services/auth'

const ROLE_OPTIONS: Role[] = ['analyst', 'admin']

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message.replace('Request failed: ', 'HTTP ') : fallback
}

export default function AdminUsers() {
  const [users, setUsers] = useState<PublicUser[]>([])
  const [state, setState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const [newUsername, setNewUsername] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [newRole, setNewRole] = useState<Role>('analyst')
  const me = getStoredUser()

  const load = useCallback(() => {
    setState('loading')
    listUsers()
      .then((r) => {
        setUsers(r.users)
        setState('ready')
      })
      .catch((err) => {
        setError(errorMessage(err, 'Could not load users.'))
        setState('error')
      })
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const changeRole = async (username: string, role: Role) => {
    setError(null)
    setMessage(null)
    try {
      await updateUserRole(username, role)
      setMessage(`${username} is now ${role}.`)
      load()
    } catch (err) {
      const detail = err instanceof Error ? err.message : ''
      setError(
        errorMessage(err, 'Could not change role.') +
          (detail.includes('409') ? ' — the last admin cannot be demoted.' : ''),
      )
      load()
    }
  }

  const changeStatus = async (username: string, is_active: boolean) => {
    setError(null)
    setMessage(null)
    try {
      await updateUserStatus(username, is_active)
      setMessage(`${username} is now ${is_active ? 'active' : 'inactive'}.`)
      load()
    } catch (err) {
      const detail = err instanceof Error ? err.message : ''
      setError(
        errorMessage(err, 'Could not change status.') +
          (detail.includes('409') ? ' — the last active admin cannot be deactivated.' : ''),
      )
      load()
    }
  }

  const create = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setMessage(null)
    try {
      await adminCreateUser(newUsername.trim(), newPassword, newRole)
      setMessage(`Created ${newUsername.trim()} as ${newRole}.`)
      setNewUsername('')
      setNewPassword('')
      setNewRole('analyst')
      load()
    } catch (err) {
      setError(errorMessage(err, 'Could not create user.'))
    }
  }

  if (state === 'loading') return <div className="text-neutral-400 text-sm">Loading users…</div>
  if (state === 'error')
    return <div className="text-red-400 text-sm">{error ?? 'Could not load users.'}</div>

  return (
    <div className="space-y-6">
      <div className="abi-panel border border-neutral-800 rounded-lg p-4">
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-medium">Users</h2>
          <span className="text-xs text-neutral-500">{users.length} accounts</span>
        </div>
        <table className="w-full text-sm">
          <thead className="text-neutral-500 text-xs uppercase">
            <tr>
              <th className="text-left py-1">Username</th>
              <th className="text-left py-1">Role</th>
              <th className="text-left py-1">Status</th>
              <th className="text-left py-1">Created</th>
              <th className="text-right py-1">Actions</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.username} className="border-t border-neutral-800">
                <td className="py-2">
                  {u.username}
                  {u.username === me?.username && (
                    <span className="ml-2 text-xs text-neutral-500">you</span>
                  )}
                </td>
                <td className="py-2 uppercase text-xs">
                  <span className={u.role === 'admin' ? 'text-amber-400' : 'text-emerald-400'}>
                    {u.role}
                  </span>
                </td>
                <td className="py-2 uppercase text-xs">
                  <span className={u.is_active ? 'text-emerald-400' : 'text-red-400'}>
                    {u.is_active ? 'Active' : 'Inactive'}
                  </span>
                </td>
                <td className="py-2 text-xs text-neutral-400">
                  {u.created_at ? new Date(u.created_at).toLocaleDateString() : 'N/A'}
                </td>
                <td className="py-2 text-right space-x-2">
                  <select
                    aria-label={`role for ${u.username}`}
                    value={u.role}
                    onChange={(e) => changeRole(u.username, e.target.value as Role)}
                    className="bg-neutral-800 rounded px-2 py-1 text-sm"
                  >
                    {ROLE_OPTIONS.map((r) => (
                      <option key={r} value={r}>
                        {r}
                      </option>
                    ))}
                  </select>
                  <button
                    onClick={() => {
                      if (!u.is_active || window.confirm(`Deactivate ${u.username}?`)) {
                        changeStatus(u.username, !u.is_active)
                      }
                    }}
                    className={`rounded px-2 py-1 text-sm ${u.is_active ? 'bg-red-900/50 hover:bg-red-900 text-red-200' : 'bg-emerald-900/50 hover:bg-emerald-900 text-emerald-200'}`}
                  >
                    {u.is_active ? 'Deactivate' : 'Activate'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="text-xs text-neutral-500 mt-3">
          Only two roles exist: <span className="text-neutral-300">admin</span> (business
          intelligence + platform administration) and{' '}
          <span className="text-neutral-300">analyst</span> (business intelligence).
        </p>
      </div>

      <form
        onSubmit={create}
        className="abi-panel border border-neutral-800 rounded-lg p-4 space-y-3"
      >
        <h2 className="font-medium">Create user</h2>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-sm">
          <label className="flex flex-col gap-1">
            Username
            <input
              value={newUsername}
              onChange={(e) => setNewUsername(e.target.value)}
              minLength={3}
              maxLength={50}
              required
              className="bg-neutral-800 rounded px-3 py-1.5"
            />
          </label>
          <label className="flex flex-col gap-1">
            Password
            <input
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              minLength={6}
              maxLength={128}
              required
              className="bg-neutral-800 rounded px-3 py-1.5"
            />
          </label>
          <label className="flex flex-col gap-1">
            Role
            <select
              aria-label="New user role"
              value={newRole}
              onChange={(e) => setNewRole(e.target.value as Role)}
              className="bg-neutral-800 rounded px-3 py-1.5"
            >
              {ROLE_OPTIONS.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </label>
        </div>
        <button
          type="submit"
          className="bg-blue-600 hover:bg-blue-500 rounded px-3 py-2 text-sm font-medium"
        >
          Create
        </button>
      </form>

      {message && <div className="text-sm text-emerald-400">{message}</div>}
      {error && <div className="text-sm text-red-400">{error}</div>}
    </div>
  )
}
