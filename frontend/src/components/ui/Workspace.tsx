import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Icon } from './Icon'

export function Brand({ compact = false }: { compact?: boolean }) {
  return <Link to="/" className="abi-brand" aria-label="ABI home"><span className="abi-brand-mark"><Icon name="chart" size={21} /></span><span>ABI{!compact && <small>Business intelligence</small>}</span></Link>
}

export function PageHeader({ title, description, eyebrow, action }: { title: string; description?: string; eyebrow?: string; action?: ReactNode }) {
  return <header className="abi-page-header"><div>{eyebrow && <p className="abi-eyebrow">{eyebrow}</p>}<h1>{title}</h1>{description && <p className="abi-page-description">{description}</p>}</div>{action && <div className="abi-page-action">{action}</div>}</header>
}

export function StatusBadge({ children, tone = 'neutral' }: { children: ReactNode; tone?: 'neutral' | 'success' | 'warning' | 'danger' }) {
  return <span className={`abi-badge abi-badge-${tone}`}>{children}</span>
}

export function Panel({ title, description, children, className = '' }: { title?: string; description?: string; children: ReactNode; className?: string }) {
  return <section className={`abi-panel ${className}`}>{title && <div className="abi-panel-heading"><h2>{title}</h2>{description && <p>{description}</p>}</div>}{children}</section>
}
