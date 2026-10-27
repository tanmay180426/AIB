import type { ForecastPoint } from './api'

export type ForecastTarget = 'orders' | 'revenue'
export interface ChartPoint { time: number; date: string; historical: number | null; forecast: number | null; kind?: 'historical' | 'forecast' }
const DAY = 86400000

/** Fail closed rather than invent zeros, deduplicate ambiguously or align by index. */
export function forecastPoints(history: ForecastPoint[], future: ForecastPoint[], target: ForecastTarget): ChartPoint[] {
  const seen = new Set<string>()
  const convert = (points: ForecastPoint[], kind: 'historical' | 'forecast') => points.map(point => {
    const time = Date.parse(`${point.date}T00:00:00Z`), value = point[target]
    if (!/^\d{4}-\d{2}-\d{2}$/.test(point.date) || !Number.isFinite(time) || new Date(time).toISOString().slice(0, 10) !== point.date || typeof value !== 'number' || !Number.isFinite(value) || seen.has(point.date)) {
      throw new Error('Forecast response contains duplicate dates, missing values or invalid observations. No chart was drawn.')
    }
    seen.add(point.date)
    return { time, date: point.date, historical: kind === 'historical' ? value : null, forecast: kind === 'forecast' ? value : null }
  }).sort((a, b) => a.time - b.time)
  const actual = convert(history, 'historical'), predicted = convert(future, 'forecast')
  if (!actual.length || !predicted.length) throw new Error('No historical and future observations are available for this selection.')
  if (actual.some((p, i) => i > 0 && p.time !== actual[i - 1].time + DAY)) throw new Error('Historical daily observations contain gaps; no missing date was filled with zero.')
  if (predicted[0].time !== actual[actual.length - 1].time + DAY || predicted.some((p, i) => i > 0 && p.time !== predicted[i - 1].time + DAY)) throw new Error('Forecast dates do not follow the historical boundary at daily intervals.')
  return [...actual, ...predicted]
}

export const forecastDate = (time: number) => new Date(time).toISOString().slice(0, 10)

/** UTC anniversary; Feb 29 clamps to Feb 28 in non-leap years. */
export function forecastYearWindow(origin: string) {
  const time=Date.parse(origin+'T00:00:00Z')
  if(!Number.isFinite(time)||forecastDate(time)!==origin)throw new Error('Invalid forecast origin date.')
  const day=new Date(time),month=day.getUTCMonth(),date=day.getUTCDate(),year=day.getUTCFullYear()
  const anniversary=(offset:number)=>Date.UTC(year+offset,month,Math.min(date,new Date(Date.UTC(year+offset,month+1,0)).getUTCDate()))
  return {origin:time,historyStart:anniversary(-1)+DAY,futureEnd:anniversary(1),futureDays:(anniversary(1)-time)/DAY}
}

/** Display one trailing calendar year; preserve every genuine future point. */
export function trailingYearPoints(points: ChartPoint[]): ChartPoint[] {
  const history=points.filter(p=>p.kind==='historical'||(p.kind==null&&p.historical!==null))
  if(!history.length)return points
  const window=forecastYearWindow(history[history.length-1].date)
  return points.filter(p=>p.time>=window.historyStart)
}

/** Full display history permits explicit unknowns; model input validation stays separate. */
export function fullForecastPoints(history: ForecastPoint[], future: ForecastPoint[], target: ForecastTarget): ChartPoint[] {
  const seen = new Set<number>()
  const convert = (rows: ForecastPoint[], kind: 'historical'|'forecast') => rows.map(row => {
    const time = Date.parse(`${row.date}T00:00:00Z`), value = row[target]
    if (!/^\d{4}-\d{2}-\d{2}$/.test(row.date) || !Number.isFinite(time) || forecastDate(time)!==row.date || seen.has(time) ||
      (value !== null && (typeof value !== 'number' || !Number.isFinite(value))) || (kind==='forecast' && value===null)) {
      throw new Error('Full forecast response contains duplicate/invalid dates or target values. No substitute values were drawn.')
    }
    seen.add(time)
    return {date:row.date,time,historical:kind==='historical'?value!:null,forecast:kind==='forecast'?value!:null,kind}
  }).sort((a,b)=>a.time-b.time)
  const actual=convert(history,'historical'), predicted=convert(future,'forecast')
  if (!actual.length) { if(predicted.length) throw new Error('Future predictions have no historical boundary.');return [] }
  const start=actual[0].time,end=actual[actual.length-1].time
  if ((end-start)/DAY+1>100000) throw new Error('Historical timeline exceeds the supported bound.')
  const byDate=new Map(actual.map(p=>[p.time,p]))
  const calendar:ChartPoint[]=[]
  for(let time=start;time<=end;time+=DAY) calendar.push(byDate.get(time)||{time,date:forecastDate(time),historical:null,forecast:null,kind:'historical'})
  if(predicted.some((p,i)=>p.time!==(i?predicted[i-1].time:end)+DAY)) throw new Error('Forecast dates do not follow the historical boundary at daily intervals.')
  return [...calendar,...predicted]
}
export function formatUsdAmount(value: unknown): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'Unavailable'
  return new Intl.NumberFormat('en-US', {
    style: 'currency', currency: 'USD', minimumFractionDigits: 2, maximumFractionDigits: 2,
  }).format(value)
}

export function formatMetricNumber(value: unknown): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'Unavailable'
  return value.toLocaleString('en-US', { maximumFractionDigits: 2 })
}

/** Use a source currency only when metadata explicitly supplies a valid code. */
export function forecastNumber(value: number, target: ForecastTarget, sourceCurrency?: string | null) {
  if (target !== 'revenue') return formatMetricNumber(value)
  if (sourceCurrency && /^[A-Z]{3}$/.test(sourceCurrency)) {
    try {
      return new Intl.NumberFormat('en-US', { style: 'currency', currency: sourceCurrency,
        minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value)
    } catch { /* Unknown/unsupported currency codes remain neutral. */ }
  }
  return formatMetricNumber(value)
}
