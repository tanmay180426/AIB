import { PageHeader } from '@/components/ui/Workspace'
import { NavLink, Outlet } from 'react-router-dom'

const TABS = [
  { to: '/admin/users', label: 'User Management' },
  { to: '/admin/roles', label: 'Role Management' },
  { to: '/admin/health', label: 'System Health' },
  { to: '/admin/data', label: 'Data / ETL' },
  { to: '/admin/warehouse', label: 'Warehouse' },
  { to: '/admin/ml', label: 'ML Administration' },
  { to: '/admin/settings', label: 'System Settings' },
]

export default function AdminLayout() {
  return (
    <div className="space-y-6">
      <div>
        <div className="text-xs uppercase tracking-wide text-neutral-500">Administration</div>
        <PageHeader title="Platform Administration" />
      </div>

      <nav className="abi-tabs">
        {TABS.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            className={({ isActive }) =>
              `px-3 py-2 text-sm rounded-t border-b-2 -mb-px ${
                isActive
                  ? 'border-blue-500 text-neutral-100'
                  : 'border-transparent text-neutral-500 hover:text-neutral-300'
              }`
            }
          >
            {t.label}
          </NavLink>
        ))}
      </nav>

      <Outlet />
    </div>
  )
}
