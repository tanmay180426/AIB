import { cleanup,render,screen,waitFor,fireEvent } from '@testing-library/react'
import { afterEach,expect,it,vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { DatasetContext } from '@/hooks/useDataset'
import { ForecastExperience } from '@/pages/ml/RevenueForecast'
import { forecastYearWindow,trailingYearPoints,fullForecastPoints,forecastDate } from '@/services/forecast'
import { getForecast } from '@/services/api'
vi.mock('@/services/api',async original=>({...await original<typeof import('@/services/api')>(),getForecast:vi.fn()}))
vi.mock('@/components/ForecastQuality',()=>({default:()=>null}))
vi.mock('@/components/BusinessEvidence',()=>({default:()=>null}))
vi.mock('@/components/ForecastChart',()=>({default:({points}:{points:unknown[]})=><div data-testid="annual-points">{JSON.stringify(points)}</div>}))
const stableFilters={}
vi.mock('@/hooks/useFilters',()=>({useFilters:()=>({filters:stableFilters})}))
afterEach(()=>{cleanup();vi.clearAllMocks()})
const active={dataset_id:'annual',dataset_name:'Annual fixture',updated_at:'1',semantics:{currency_code:null}} as never
const view=()=> <MemoryRouter><DatasetContext.Provider value={{active,datasets:[],busy:false,reload:async()=>{},select:async()=>{}}}><ForecastExperience target="orders" /></DatasetContext.Provider></MemoryRouter>
it.each([
  ['2021-12-31','2021-01-01','2022-12-31',365],
  ['2023-12-31','2023-01-01','2024-12-31',366],
  ['2020-12-31','2020-01-01','2021-12-31',365],
  ['2024-02-29','2023-03-01','2025-02-28',365],
])('uses inclusive UTC calendar anniversaries for %s',(origin,start,end,n)=>{
  const window=forecastYearWindow(origin)
  expect(forecastDate(window.historyStart)).toBe(start)
  expect(forecastDate(window.futureEnd)).toBe(end)
  expect(window.futureDays).toBe(n)
})
it('keeps precisely the trailing year and every returned future value, including null/zero history',()=>{
  const history=Array.from({length:731},(_,i)=>({date:new Date(Date.UTC(2020,0,1+i)).toISOString().slice(0,10),orders:i===370?null:i===371?0:i}))
  const future=Array.from({length:365},(_,i)=>({date:new Date(Date.UTC(2022,0,1+i)).toISOString().slice(0,10),orders:100+i*.1}))
  const points=trailingYearPoints(fullForecastPoints(history,future,'orders'))
  expect(points).toHaveLength(730);expect(points[0].date).toBe('2021-01-01')
  expect(points[364].date).toBe('2021-12-31');expect(points[365].date).toBe('2022-01-01')
  expect(points[729].date).toBe('2022-12-31')
  expect(points[4].historical).toBeNull();expect(points[5].historical).toBe(0)
  expect(points.slice(365).map(p=>p.forecast)).toEqual(future.map(p=>p.orders))
})
it('defaults to genuine 365-day requests, changes to 30 and back without retaining stale points',async()=>{
  vi.mocked(getForecast).mockImplementation(async n=>({forecast_origin:'2021-12-31',history_tail:[{date:'2021-12-31',orders:7}],forecast:Array.from({length:n!},(_,i)=>({date:new Date(Date.UTC(2022,0,1+i)).toISOString().slice(0,10),orders:20+i}))}))
  render(view())
  await screen.findByTestId('annual-points')
  expect(getForecast).toHaveBeenCalledWith(365,'orders',{})
  expect(screen.getByText('Forecast total (365d)')).toBeVisible()
  fireEvent.change(screen.getByLabelText('Forecast horizon'),{target:{value:'30'}})
  await waitFor(()=>expect(getForecast).toHaveBeenLastCalledWith(30,'orders',{}))
  await screen.findByText('Forecast total (30d)')
  fireEvent.change(screen.getByLabelText('Forecast horizon'),{target:{value:'year'}})
  await waitFor(()=>expect(getForecast).toHaveBeenLastCalledWith(365,'orders',{}))
  expect(await screen.findByText('Forecast total (365d)')).toBeVisible()
  expect(screen.getByText(/Annual forecast accuracy is unvalidated/)).toBeVisible()
})
it('requests 366 real predictions for a leap-year future instead of fabricating an extra date',async()=>{
  vi.mocked(getForecast).mockImplementation(async n=>({forecast_origin:'2023-12-31',history_tail:[{date:'2023-12-31',orders:1}],forecast:Array.from({length:n!},(_,i)=>({date:new Date(Date.UTC(2024,0,1+i)).toISOString().slice(0,10),orders:i+.25}))}))
  render(view())
  await screen.findByTestId('annual-points')
  expect(vi.mocked(getForecast).mock.calls.map(c=>c[0])).toEqual([365,366])
  expect(screen.getByTestId('annual-points')).toHaveTextContent('2024-12-31')
  expect(screen.getByText('Forecast total (366d)')).toBeVisible()
})
