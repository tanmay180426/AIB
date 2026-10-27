import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { getToken, isAuthRequired } from '@/services/auth'
import { useSession } from '@/hooks/useSession'

export default function RequireAuth() {
  useSession()
  const location = useLocation()
  if (isAuthRequired() && !getToken()) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />
  }
  return <Outlet />
}
