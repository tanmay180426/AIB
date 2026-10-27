# Architecture

## Overview
React+TS+Vite+Tailwind (FE), FastAPI+SQLAlchemy (BE), SQLite (verified local DB;
PostgreSQL documented target), scikit-learn (saved ML models), and an optional
Ollama/provider-agnostic assistant. Private uploads coexist with the external
Olist reference warehouse.

## Data Flow
1. Raw CSVs in %USERPROFILE%\Downloads\olist (read-only)
2. ETL validates/cleans -> warehouse (star schema)
3. APIs serve aggregated KPIs/analytics
4. FE renders dashboards/charts
5. ML interfaces return honest status; predictions only when available
6. AI uses controlled backend tools with RBAC

Uploaded CSV/JSON/single-sheet Excel data is validated, profiled and registered
in the same database with a private generated typed table. Per-user selection
and explicit request IDs resolve an authorized dataset. The existing shared
metric layer chooses the reference or tabular adapter, and filters precede
analytics, reports, AI and compatible saved-model inference. Missing capabilities
remain unavailable; uploads never retrain models. See UNIVERSAL_DATASETS.md for
the complete contract and boundaries.

## Principles
- Contracts first (API/ML I/O)
- ML/LLM optional
- Backend-enforced authZ
- No secrets in repo
- Parallel dev
