import { useSearchParams } from 'react-router-dom'
import { useMemo } from 'react'

export function useFilters() {
  const [searchParams, setSearchParams] = useSearchParams()

  const filters = useMemo(() => {
    const f: Record<string, string> = {}
    for (const [key, value] of searchParams.entries()) {
      if (value) {
        f[key] = value
      }
    }
    return f
  }, [searchParams])

  const setFilter = (key: string, value: string | null) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      if (value) {
        next.set(key, value)
      } else {
        next.delete(key)
      }
      // when filter changes, usually we want to keep date, but maybe reset page? We don't have pagination yet.
      return next
    })
  }

  const setFilters = (newFilters: Record<string, string | null>) => {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev)
      for (const [key, value] of Object.entries(newFilters)) {
        if (value) {
          next.set(key, value)
        } else {
          next.delete(key)
        }
      }
      return next
    })
  }

  const resetFilters = () => {
    setSearchParams(new URLSearchParams())
  }

  return { filters, setFilter, setFilters, resetFilters }
}
