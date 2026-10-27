import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { forecastDate, type ChartPoint } from '@/services/forecast'

export default function ForecastChart({ points, format, unit, scope = 'Selected dataset', model, experimental }: {
  points: ChartPoint[]; format: (value: number) => string; unit: string; scope?:string
  model?:{name?:string;version?:string;algorithm?:string};experimental?:boolean
}) {
  const history = points.filter(p=>p.kind==='historical'||(p.kind==null && p.historical!==null))
  const actual = history.filter(p => p.historical !== null)
  const lastActual = actual[actual.length - 1]
  const historyEnd=history[history.length-1], firstForecast=points.find(p=>p.forecast!==null)
  if(!historyEnd) return null
  const tooltip=({active,label}:{active?:boolean;label?:number|string})=>{
    const point=active?points.find(p=>p.time===Number(label)):undefined
    if(!point)return null
    const predicted=point.kind==='forecast'||point.forecast!==null,value=predicted?point.forecast:point.historical
    return <div className="rounded border p-3 text-xs" style={{background:'rgb(var(--surface-raised))',borderColor:'rgb(var(--border))'}}>
      <p>{point.date} · {scope}</p>
      <p>{predicted?'Future forecast · Model prediction':'Historical actual · Observed history'}: {value===null?'No recorded target value':`${format(value)} ${unit}${value===0?' · Observed zero':''}`}</p>
      {predicted&&<p>{model?.algorithm||model?.name||'Serving model'} · {model?.version||'Version unavailable'} · {experimental?'Experimental / unqualified':'Selected-scope accuracy unverified'}</p>}
    </div>
  }
  return <section className="abi-panel p-5 min-w-0" aria-label="Historical and future forecast chart">
    <h2 className="font-medium">Historical actuals and future forecast</h2>
    <p className="text-xs text-neutral-400 mt-1 mb-5">Daily {unit}. Recorded aggregates for {scope}: {history[0].date}–{historyEnd.date}; {history.length.toLocaleString()} historical calendar points ({actual.length.toLocaleString()} recorded values, {history.length-actual.length} unknown). Unknown targets are gaps, never zero-filled. Last recorded target: {lastActual?.date||'unavailable'}. {firstForecast?`Actuals end ${historyEnd.date}; future predictions begin ${firstForecast.date}. Dashed line: trained model output.`:'No future line: inference is unavailable for this selected scope.'}</p>
    <div data-testid="forecast-chart" data-history-start={history[0].date} data-history-end={historyEnd.date} data-history-points={history.length} data-history-observations={actual.length} data-history-gaps={history.length-actual.length} data-forecast-start={firstForecast?.date||''} data-forecast-points={points.filter(p => p.forecast !== null).length}>
      <ResponsiveContainer width="100%" height={350}><LineChart data={points} margin={{ top: 25, right: 24, left: 12, bottom: 10 }}>
        <CartesianGrid stroke="rgb(var(--border))" strokeDasharray="3 3" vertical={false} />
        <XAxis type="number" dataKey="time" domain={['dataMin', 'dataMax']} tickFormatter={forecastDate} minTickGap={65} stroke="rgb(var(--muted))" fontSize={11} />
        <YAxis width={unit === 'orders' ? 85 : 115} tickFormatter={v => format(Number(v))} stroke="rgb(var(--muted))" fontSize={11} />
        <Tooltip filterNull={false} content={tooltip} />
        <Legend />
        {firstForecast&&<ReferenceLine x={(historyEnd.time + firstForecast.time) / 2} stroke="rgb(var(--muted))" strokeDasharray="3 3" label={{ value: 'Future →', position: 'insideTopRight', fill: 'rgb(var(--muted))', fontSize: 11 }} />}
        <Line dataKey="historical" name="Historical actual · Observed history" stroke="var(--chart-1)" strokeWidth={2} connectNulls={false} dot={history.length>100?false:{r:2}} isAnimationActive={false} />
        <Line dataKey="forecast" name="Future forecast · Model prediction" stroke="var(--chart-3)" strokeWidth={2} strokeDasharray="6 4" connectNulls={false} dot={points.filter(p=>p.forecast!==null).length>100?false:{r:2}} isAnimationActive={false} />
      </LineChart></ResponsiveContainer>
    </div>
  </section>
}
