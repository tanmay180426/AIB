# SRS.md (draft)

## Purpose
AI-Powered BI & Predictive Analytics Platform using Olist dataset.

## Scope
Dashboards, analytics, warehouse/ETL, ML (planned), AI assistant (controlled), RBAC.

## User Classes
Admin, Analyst. (Two roles only; see docs/RBAC.md.)

- Analyst: business intelligence (dashboards, analytics, ML, AI insights,
  reports/exports).
- Admin: business intelligence + platform administration (users, roles, system
  health, ETL, warehouse, ML administration, settings).

## Functional (key)
- Auth/RBAC enforced backend
- KPIs from verified data
- Filters, charts (Recharts)
- ML status honest; no fake outputs
- AI uses authorized data only
- Reports (CSV) permission-aware

## Non-functional
- Responsive, accessible, reduced-motion respected
- Modular, typed, testable
- No secrets in repo; external data preserved
- ML/LLM optional (graceful fallback)
