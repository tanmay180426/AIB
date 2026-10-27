import { useSyncExternalStore } from 'react'
import { getSessionGeneration, subscribeSession } from '@/services/auth'

/** Subscribe existing guards to login/logout/expiry, including other tabs. */
export function useSession() {
  return useSyncExternalStore(subscribeSession, getSessionGeneration, getSessionGeneration)
}
