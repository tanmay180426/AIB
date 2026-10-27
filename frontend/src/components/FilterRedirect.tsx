import { Navigate, useLocation } from 'react-router-dom'

export default function FilterRedirect({ to }: { to: string }) {
  const { search } = useLocation()
  return <Navigate to={{ pathname: to, search }} replace />
}
