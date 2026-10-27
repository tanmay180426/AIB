import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { cloneElement, type ReactElement } from 'react'
import { fullForecastPoints } from '@/services/forecast'
import ForecastChart from '@/components/ForecastChart'

vi.mock('recharts',async original=>({...await original<typeof import('recharts')>(),ResponsiveContainer:({children}:{children:ReactElement})=>cloneElement(children,{width:900,height:350})}))
afterEach(cleanup)
const history=Array.from({length:60},(_,i)=>({date:new Date(Date.UTC(2021,10,2+i)).toISOString().slice(0,10),orders:i===10?null:i===11?0:i+1}))
const future=[{date:'2022-01-01',orders:22.5},{date:'2022-01-02',orders:20.2}]
it('renders real full history with disconnected unknown gaps, separate forecast and the actual boundary',()=>{
  const points=fullForecastPoints([...history].reverse(),future,'orders')
  const view=render(<ForecastChart points={points} unit="expected orders" scope="Extended fixture" format={String} model={{algorithm:'Ridge',version:'synthetic-v1'}} experimental />)
  const chart=screen.getByTestId('forecast-chart')
  expect(chart).toHaveAttribute('data-history-points','60')
  expect(chart).toHaveAttribute('data-history-start','2021-11-02')
  expect(chart).toHaveAttribute('data-history-end','2021-12-31')
  expect(chart).toHaveAttribute('data-history-gaps','1')
  expect(chart).toHaveAttribute('data-forecast-start','2022-01-01')
  expect(screen.getByText('Historical actual · Observed history')).toBeVisible()
  expect(screen.getByText('Future forecast · Model prediction')).toBeVisible()
  const line=view.container.querySelector('.recharts-line-curve')!
  expect(line.getAttribute('d')!.match(/M/g)?.length).toBe(2)
  expect(points[10].historical).toBeNull();expect(points[11].historical).toBe(0)
})
it('preserves absent calendar dates as null without imputing into the model or hiding history-only data',()=>{
  const points=fullForecastPoints([history[0],history[2]],[],'orders')
  expect(points).toHaveLength(3);expect(points[1].historical).toBeNull()
  render(<ForecastChart points={points} unit="orders" format={String} />)
  expect(screen.getByTestId('forecast-chart')).toHaveAttribute('data-forecast-points','0')
  expect(screen.getByText(/No future line/)).toBeVisible()
})
it('rejects duplicate, invalid and fabricated future data while retaining explicit historical nulls',()=>{
  expect(()=>fullForecastPoints([history[0],history[0]],[],'orders')).toThrow(/duplicate/)
  expect(()=>fullForecastPoints(history,[{date:'2022-01-01',orders:null}],'orders')).toThrow()
  expect(()=>fullForecastPoints(history,[{date:'2022-01-02',orders:1}],'orders')).toThrow(/boundary/)
  expect(()=>fullForecastPoints([{date:'2021-02-30',orders:1}],[],'orders')).toThrow()
})
