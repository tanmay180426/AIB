export function KpiCard({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="abi-panel abi-kpi">
      <div className="abi-kpi-label">{label}</div>
      <div className="abi-kpi-value">{value}</div>
      {hint && <div className="abi-kpi-hint">{hint}</div>}
    </div>
  )
}
