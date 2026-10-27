import { PageHeader } from '@/components/ui/Workspace'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import FilterBar from '@/components/FilterBar'

const TABS = [
  { to: '/analytics/sales', label: 'Sales' },
  { to: '/analytics/orders', label: 'Orders' },
  { to: '/analytics/customers', label: 'Customers' },
  { to: '/analytics/products', label: 'Products' },
  { to: '/analytics/sellers', label: 'Sellers' },
  { to: '/analytics/delivery', label: 'Delivery' },
]

export default function AnalyticsLayout() {
  const location = useLocation()
  return (
    <div className="space-y-6">
      <div>
        <PageHeader title="Analytics" />
        <p className="text-sm text-neutral-500">
          In-depth analysis of the active dataset.
        </p>
      </div>

      <div className="abi-tabs">
        {TABS.map((t) => (
          <NavLink
            key={t.to}
            to={t.to + location.search}
            className={({ isActive }) =>
              `text-sm font-medium transition-colors ${
                isActive ? 'text-blue-400' : 'text-neutral-400 hover:text-neutral-200'
              }`
            }
          >
            {t.label}
          </NavLink>
        ))}
      </div>

      <FilterBar showGrain={true} />

      <div className="pt-2">
        <Outlet />
      </div>
    </div>
  )
}
