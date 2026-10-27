import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useDataset } from '@/hooks/useDataset'
import { useFilters } from '@/hooks/useFilters'
import { getAnomalies, getForecast, type AnomaliesResponse } from '@/services/api'
import { forecastNumber, forecastPoints, type ForecastTarget } from '@/services/forecast'

/** Explicitly requested inference keeps expensive full-bundle scans off every KPI refresh. */
export default function ExecutiveOutlook() {
  const { active }=useDataset(), { filters }=useFilters(), location=useLocation()
  const [run,setRun]=useState(0)
  const stamp=`${active?.dataset_id}:${active?.updated_at}:${JSON.stringify(filters)}:${run}`
  const eligible=!!active && (active.relational_analysis?.supported || active.source_type==='warehouse' || !!(active.semantics.fields?.order&&active.semantics.fields?.date))
  const brl=active?.semantics.currency_code==='BRL'
  const [result,setResult]=useState<{stamp:string; forecasts:{target:ForecastTarget;last:string;first:string;end:string;total:number|null;reason?:string}[]; anomalies?:AnomaliesResponse; error?:string}|null>(null)
  useEffect(()=>{
    let current=true
    if(!run || !eligible) return ()=>{current=false}
    const targets:ForecastTarget[]=brl?['orders','revenue']:['orders']
    void Promise.all(targets.map(async target=>{
      try {
        const response=await getForecast(7,target,filters)
        if(response.status==='not_applicable')return {target,last:'',first:'',end:'',total:null,reason:response.reason||'Incompatible model inputs.'}
        if(response.forecast.length!==7)throw new Error('Forecast returned an unexpected horizon.')
        const points=forecastPoints(response.history_tail,response.forecast,target), history=points.filter(p=>p.historical!==null),future=points.filter(p=>p.forecast!==null)
        return {target,last:history[history.length-1].date,first:future[0].date,end:future[future.length-1].date,total:future.reduce((sum,p)=>sum+p.forecast!,0)}
      }catch(error){return {target,last:'',first:'',end:'',total:null,reason:error instanceof Error?error.message:'Inference failed.'}}
    })).then(async forecasts=>{
      let anomalies:AnomaliesResponse|undefined,error:string|undefined
      if(brl)try{anomalies=await getAnomalies(filters)}catch(reason){error=reason instanceof Error?reason.message:'Anomaly inference failed.'}
      if(current)setResult({stamp,forecasts,anomalies,error})
    })
    return ()=>{current=false}
  },[run,stamp,eligible,brl,filters])
  const data=result?.stamp===stamp?result:null
  return <section className="abi-panel p-5 space-y-4" aria-label="Forecast and anomaly summary"><div className="flex flex-wrap gap-3 items-center justify-between"><div><h2 className="font-medium">Forecast and anomaly outlook</h2><p className="text-xs text-neutral-400">Optional real model inference for the selected history. Forecasts are separate from realized business totals.</p></div><button className="abi-button" disabled={!eligible || (!!run&&!data)} onClick={()=>setRun(value=>value+1)}>Load 7-day model outlook</button></div>
    {!eligible && <p className="text-sm text-neutral-400">Confirmed order/date semantics and compatible history are required. Review Dataset Manager.</p>}
    {!brl && <p className="text-sm text-neutral-400">Revenue forecast and monetary anomaly inference require confirmed BRL units. No currency is assumed.</p>}
    {!!run && eligible && !data && <p role="status">Running selected-data model checks and inference…</p>}
    {data && <><div className="grid md:grid-cols-2 gap-4">{data.forecasts.map(forecast=><article className="border border-neutral-800 rounded p-4" key={forecast.target}><h3 className="capitalize">{forecast.target} forecast · next 7 days</h3>{forecast.reason?<p className="text-sm text-neutral-400">Unavailable: {forecast.reason}</p>:<><p className="text-2xl font-semibold my-2">{forecastNumber(forecast.total!,forecast.target,active?.semantics.currency_code)}</p><p className="text-xs text-neutral-400">Model-estimated total · last actual {forecast.last} · predictions {forecast.first}–{forecast.end}. Uncertain estimates; no interval returned.</p></>}</article>)}</div>
      {data.error&&<p role="alert">Anomaly summary unavailable: {data.error}</p>}
      {data.anomalies?.status==='not_applicable'&&<p>{data.anomalies.reason}</p>}
      {data.anomalies?.status==='available'&&<div><h3>Observed historical anomalies</h3><p className="text-xs text-neutral-400">{data.anomalies.n_anomalies} flagged days / {data.anomalies.n_days} analyzed. Decision scores are not probabilities. Up to five returned flagged days shown.</p>{data.anomalies.anomalies.slice(0,5).map(point=><p key={point.date} className="text-sm">{point.date} · {point.orders} observed orders · decision score {point.score.toFixed(4)}</p>)}{!data.anomalies.anomalies.length&&<p>No flagged historical days returned.</p>}</div>}
    </>}
    <Link className="text-sm text-blue-400" to={'/ml/metrics'+location.search}>Open full historical/future forecast →</Link>
  </section>
}
