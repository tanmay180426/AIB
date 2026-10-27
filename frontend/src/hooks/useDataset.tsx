import { createContext, useContext } from 'react'
import type { Dataset } from '@/services/api'

export interface DatasetContextValue {
  datasets: Dataset[]; active: Dataset | null; busy: boolean
  reload: () => Promise<void>; select: (id: string, destination?: string) => Promise<void>
}
export const DatasetContext = createContext<DatasetContextValue>({ datasets: [], active: null, busy: false, reload: async () => {}, select: async () => {} })
export function useDataset() { return useContext(DatasetContext) }
