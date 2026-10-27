import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { login } from '@/services/auth'
import { Brand } from '@/components/ui/Workspace'
import { Icon } from '@/components/ui/Icon'

export default function Login() {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const navigate = useNavigate()

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(username, password)
      navigate('/dashboard')
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="abi-auth">
      <aside className="abi-auth-story">
        <Brand />
        <div><p className="abi-eyebrow">A workspace for better decisions</p><h2>Clarity starts with your data.</h2><p>Bring your datasets, explore the evidence, and turn observed performance into your next informed decision.</p></div>
        <div className="abi-auth-evidence"><span className="abi-badge"><Icon name="lock" size={12} /> Private datasets · local analytics</span><p className="mt-5">Your selected data stays at the center of every chart, report, and computed insight.</p></div>
      </aside>
      <div className="abi-auth-form">
      <form
        onSubmit={submit}
        className="space-y-4"
      >
        <div>
          <p className="abi-eyebrow">Welcome to your workspace</p>
          <h1 className="font-semibold">Sign in</h1>
          <p className="text-sm text-neutral-400 mt-3">Continue to Autonomous Business Intelligence.</p>
        </div>

        <label className="flex flex-col gap-1 text-sm">
          Username
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="bg-neutral-800 rounded px-3 py-2"
            autoComplete="username"
            required
            placeholder="Your username"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="bg-neutral-800 rounded px-3 py-2"
            autoComplete="current-password"
            required
            placeholder="Enter your password"
          />
        </label>

        {error && <div role="alert" className="text-sm text-red-400">{error}</div>}

        <button
          type="submit"
          disabled={busy}
          className="abi-button abi-button-primary w-full disabled:opacity-50"
        >
          {busy ? 'Signing in…' : 'Sign in'}
        </button>

        <p className="text-xs text-neutral-500">
          Two roles: <span className="text-neutral-300">admin</span> (business intelligence +
          platform administration) and{' '}
          <span className="text-neutral-300">analyst</span> (business intelligence).
        </p>
      </form>
      </div>
    </div>
  )
}
