import { createBrowserRouter, Navigate } from 'react-router-dom'
import FilterRedirect from '@/components/FilterRedirect'
import Landing from '@/pages/Landing'
import AppLayout from '@/components/layout/AppLayout'
import RequireAuth from '@/components/RequireAuth'
import RequireAdmin from '@/components/RequireAdmin'
import AdminLayout from '@/components/layout/AdminLayout'

export const router = createBrowserRouter([
  { path: '/', element: <Landing /> },
  {
    path: '/login',
    lazy: async () => ({ Component: (await import('@/pages/Login')).default }),
  },
  {
    element: <RequireAuth />,
    children: [
      {
        element: <AppLayout />,
        children: [
          // ---- Business intelligence (admin + analyst) ----
          { path: '/datasets', lazy: async () => ({ Component: (await import('@/pages/Datasets')).default }) },
          {
            path: '/dashboard',
            lazy: async () => ({ Component: (await import('@/pages/Dashboard')).default }),
          },
          {
            path: '/analytics',
            lazy: async () => ({ Component: (await import('@/pages/analytics/AnalyticsLayout')).default }),
            children: [
              { path: '', element: <FilterRedirect to="sales" /> },
              {
                path: 'sales',
                lazy: async () => ({ Component: (await import('@/pages/analytics/Sales')).default }),
              },
              {
                path: 'orders',
                lazy: async () => ({ Component: (await import('@/pages/analytics/Orders')).default }),
              },
              {
                path: 'customers',
                lazy: async () => ({ Component: (await import('@/pages/analytics/Customers')).default }),
              },
              {
                path: 'products',
                lazy: async () => ({ Component: (await import('@/pages/analytics/Products')).default }),
              },
              {
                path: 'sellers',
                lazy: async () => ({ Component: (await import('@/pages/analytics/Sellers')).default }),
              },
              {
                path: 'delivery',
                lazy: async () => ({ Component: (await import('@/pages/analytics/Delivery')).default }),
              },
            ],
          },
          {
            path: '/ml',
            lazy: async () => ({ Component: (await import('@/pages/ml/MlLayout')).default }),
            children: [
              { path: '', element: <FilterRedirect to="metrics" /> },
              { path: 'metrics', lazy: async () => ({ Component: (await import('@/pages/ml/MlMetrics')).default }) },
              { path: 'product-segmentation', lazy: async () => ({ Component: (await import('@/pages/ml/ProductSegmentation')).default }) },
              { path: 'revenue-forecast', lazy: async () => ({ Component: (await import('@/pages/ml/RevenueForecast')).default }) },
              { path: 'order-forecast', lazy: async () => ({ Component: (await import('@/pages/ml/RevenueForecast')).OrderForecast }) },
              { path: 'customer-segments', lazy: async () => ({ Component: (await import('@/pages/ml/MlAnalysis')).CustomerSegments }) },
              { path: 'anomalies', lazy: async () => ({ Component: (await import('@/pages/ml/MlAnalysis')).Anomalies }) },
              { path: 'sales-prediction', lazy: async () => ({ Component: (await import('@/pages/ml/MlAnalysis')).SalesPrediction }) },
            ],
          },
          {
            path: '/reports',
            lazy: async () => ({ Component: (await import('@/pages/Reports')).default }),
          },
          {
            path: '/insights',
            lazy: async () => ({ Component: (await import('@/pages/Insights')).default }),
          },
          // ---- Platform administration (admin only) ----
          {
            element: <RequireAdmin />,
            children: [
              {
                element: <AdminLayout />,
                children: [
                  {
                    path: '/admin',
                    element: <Navigate to="/admin/users" replace />,
                  },
                  {
                    path: '/admin/users',
                    lazy: async () => ({
                      Component: (await import('@/pages/admin/AdminUsers')).default,
                    }),
                  },
                  {
                    path: '/admin/roles',
                    lazy: async () => ({
                      Component: (await import('@/pages/admin/AdminRoles')).default,
                    }),
                  },
                  {
                    path: '/admin/health',
                    lazy: async () => ({
                      Component: (await import('@/pages/admin/AdminHealth')).default,
                    }),
                  },
                  {
                    path: '/admin/data',
                    lazy: async () => ({
                      Component: (await import('@/pages/admin/AdminData')).default,
                    }),
                  },
                  {
                    path: '/admin/warehouse',
                    lazy: async () => ({
                      Component: (await import('@/pages/admin/AdminWarehouse')).default,
                    }),
                  },
                  {
                    path: '/admin/ml',
                    lazy: async () => ({
                      Component: (await import('@/pages/admin/AdminMl')).default,
                    }),
                  },
                  {
                    path: '/admin/settings',
                    lazy: async () => ({
                      Component: (await import('@/pages/admin/AdminSettings')).default,
                    }),
                  },
                ],
              },
            ],
          },
          { path: '*', element: <Navigate to="/dashboard" replace /> },
        ],
      },
    ],
  },
])
