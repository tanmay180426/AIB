import type { CSSProperties } from 'react'

const paths: Record<string, string> = {
  grid: 'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
  chart: 'M4 3v17h17 M8 15l4-5 4 2 5-7',
  data: 'M3 7c0-5 18-5 18 0s-18 5-18 0 M3 7v10c0 5 18 5 18 0V7 M3 12c0 5 18 5 18 0',
  model: 'M12 3l9 5v8l-9 5-9-5V8z M3 8l9 5 9-5 M12 13v8',
  spark: 'M12 3l2.4 6.6L21 12l-6.6 2.4L12 21l-2.4-6.6L3 12l6.6-2.4z',
  report: 'M5 3h10l4 4v14H5z M14 3v5h5 M8 12h8 M8 16h6',
  users: 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M9 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M17 4a4 4 0 0 1 0 8 M22 21v-2a4 4 0 0 0-3-3.8',
  pulse: 'M2 12h5l3-8 4 16 3-8h5',
  settings: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M12 2v3 M12 19v3 M2 12h3 M19 12h3 M5 5l2 2 M17 17l2 2 M5 19l2-2 M17 7l2-2',
  arrow: 'M5 12h14 M13 6l6 6-6 6',
  chevron: 'M9 5l7 7-7 7',
  menu: 'M4 6h16 M4 12h16 M4 18h16',
  close: 'M5 5l14 14 M19 5L5 19',
  exit: 'M9 4H4v16h5 M10 12h12 M17 7l5 5-5 5',
  filter: 'M3 5h18l-7 8v6l-4 2v-8z',
  lock: 'M6 10h12v11H6z M8 10V6a4 4 0 0 1 8 0v4',
  check: 'M5 12l4 4L19 6',
}

export function Icon({ name, size = 18, style }: { name: string; size?: number; style?: CSSProperties }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false" style={style}><path d={paths[name] || paths.grid} /></svg>
}
