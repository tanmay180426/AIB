interface MonthlyPoint { period: string; revenue?: number | null; orders?: number | null }

/** Descriptive monthly aggregates only. Absent months remain absent. */
export default function SeasonalityHeatmap({ points, grain, currency }: { points: MonthlyPoint[]; grain: string; currency?: string | null }) {
  if (grain !== 'month') return <p className="text-sm text-neutral-400">Select monthly grain to compare seasonal patterns across years.</p>
  const target = points.some(p => p.revenue != null) ? 'revenue' : 'orders'
  const values = new Map<string, number>()
  for (const point of points) {
    const month = point.period.slice(0, 7), value = point[target]
    if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(month) || values.has(month) || value == null || !Number.isFinite(value)) return <p>Monthly comparison unavailable: unique dated, finite monthly aggregates are required.</p>
    values.set(month, value)
  }
  if (!values.size) return null
  const years = [...new Set([...values.keys()].map(key => key.slice(0, 4)))].sort()
  const max = Math.max(...values.values()), min = Math.min(...values.values())
  return <section className="abi-panel p-5"><h2 className="font-medium">Seasonal patterns in observed monthly {target}</h2><p className="text-xs text-neutral-400 mt-1 mb-4">Returned monthly aggregates for the selected dates and filters · {target === 'revenue' ? currency || 'currency unconfirmed' : 'orders'}. Brighter cells indicate larger values. Missing months show —. This is descriptive history; no holiday or causal effect is inferred.</p><div className="overflow-auto"><table className="w-full text-xs min-w-[640px]"><thead><tr><th scope="col">Year</th>{['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'].map(month => <th scope="col" key={month} className="p-2">{month}</th>)}</tr></thead><tbody>{years.map(year => <tr key={year}><th scope="row">{year}</th>{Array.from({length:12},(_,index) => {
    const month=`${year}-${String(index+1).padStart(2,'0')}`, value=values.get(month)
    return <td key={month} className="p-2 text-center border border-neutral-800" title={`${month}: ${value == null ? 'No observed aggregate' : value.toLocaleString('en-US',{maximumFractionDigits:2})}`} style={value == null ? undefined : {background:`rgb(var(--primary) / ${max === min ? .25 : .08+.42*(value-min)/(max-min)})`}}>{value == null ? '—' : value.toLocaleString('en-US',{notation:'compact',maximumFractionDigits:1})}</td>
  })}</tr>)}</tbody></table></div></section>
}
