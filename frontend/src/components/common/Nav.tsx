import { Link, NavLink, useLocation, useNavigate } from 'react-router-dom'
import { getStoredUser, isAdmin, logout } from '@/services/auth'
import { Icon } from '@/components/ui/Icon'

const BI_LINKS = [
  { to: '/dashboard', label: 'Dashboard', icon: 'grid' },
  { to: '/datasets', label: 'Dataset Manager', icon: 'data' },
  { to: '/analytics', label: 'Analytics', icon: 'chart' },
  { to: '/ml', label: 'Machine Learning', icon: 'model' },
  { to: '/insights', label: 'AI Insights', icon: 'spark' },
  { to: '/reports', label: 'Reports', icon: 'report' },
]

const ADMIN_LINKS = [
  { to: '/admin/users', label: 'Users', icon: 'users' },
  { to: '/admin/health', label: 'System Health', icon: 'pulse' },
  { to: '/admin/data', label: 'Data / ETL', icon: 'data' },
  { to: '/admin/warehouse', label: 'Warehouse', icon: 'data' },
  { to: '/admin/ml', label: 'ML Admin', icon: 'model' },
  { to: '/admin/settings', label: 'Settings', icon: 'settings' },
]

export default function Nav({ onNavigate }: { onNavigate?: () => void }) {
  const user = getStoredUser()
  const navigate = useNavigate()
  const location = useLocation()

  const signOut = () => {
    logout()
    navigate('/login')
  }

  return (
    <nav aria-label="Main navigation">
      <div className="abi-navigation-scroll">
        <p className="abi-nav-label">Workspace</p>
        {BI_LINKS.map((l) => (
          <NavLink className="abi-nav-link" key={l.to} to={l.to + location.search} onClick={onNavigate}>
            <Icon name={l.icon} />{l.label}
          </NavLink>
        ))}
      {isAdmin() && (
        <div>
          <p className="abi-nav-label">Administration</p>
          {ADMIN_LINKS.map((l) => (
            <NavLink className="abi-nav-link" key={l.to} to={l.to} onClick={onNavigate}>
              <Icon name={l.icon} />{l.label}
            </NavLink>
          ))}
        </div>
      )}
      </div>
      {user ? (
        <div className="abi-account">
          <span className="abi-avatar" aria-hidden="true">{user.username.slice(0, 2)}</span>
          <span className="abi-account-name">{user.username}<small>{user.role}</small></span>
          <button onClick={signOut} className="abi-icon-button" aria-label="Sign out" title="Sign out"><Icon name="exit" size={16} /></button>
        </div>
      ) : (
        <Link to="/login" className="text-blue-400">
          Sign in
        </Link>
      )}
    </nav>
  )
}
