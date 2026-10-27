import { Outlet, NavLink, useLocation } from 'react-router-dom'

const nav = [
  { name: 'Model Status', path: '/ml/metrics' },
  { name: 'Revenue Forecast', path: '/ml/revenue-forecast' },
  { name: 'Order Forecast', path: '/ml/order-forecast' },
]

export default function MlLayout() {
  const location = useLocation()
  return (
    <div className="space-y-6">
      <div className="abi-tabs">
        {nav.map((n) => (
          <NavLink
            key={n.name}
            to={n.path + location.search}
            className={({ isActive }) =>
              `pb-3 border-b-2 font-medium transition-colors ${
                isActive
                  ? 'border-indigo-500 text-indigo-400'
                  : 'border-transparent text-neutral-400 hover:text-neutral-200 hover:border-neutral-700'
              }`
            }
          >
            {n.name}
          </NavLink>
        ))}
      </div>
      <Outlet />
    </div>
  )
}
