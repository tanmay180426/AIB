# AI-Powered Business Intelligence and Predictive Analytics Platform (sem-5)

Semester 5 academic project: AI, Data Warehousing & Mining, and Software
Engineering integrated into one working platform. Supports private uploaded
structured datasets alongside the Olist Brazilian E-Commerce reference.

## Dataset workflow

Sign in, open **Dataset Manager**, upload CSV, a single-sheet XLSX/XLS workbook,
or a JSON array of flat records, then select a READY dataset in the header.
Dashboard, analytics, filters, reports, ML compatibility and AI context follow
that selection. Existing trained models are reused when compatible; uploads do
not trigger retraining. Incompatible data receives a reasoned Not Applicable
result without fabricated predictions.

See [Universal datasets](docs/UNIVERSAL_DATASETS.md) for limits, semantic
corrections, isolation, model requirements and supported structures.

## Project status

- Includes private uploaded-dataset analytics, the optional Olist reference warehouse, and an isolated experimental seasonal forecast demo.
- Local databases, source datasets, generated experiment outputs, and serialized models are not part of the source release.
- Experimental seasonal results use a working series with a package-declared source window through 2018-10-17 and generated values outside that window; they are not independent real-world validation.

## Stack (delivered)
- Frontend: React + TypeScript + Vite + TailwindCSS + Recharts + Framer Motion
  (routes code-split; ESLint configured; Vitest + Playwright tests)
- Backend: FastAPI + Pydantic + SQLAlchemy (JWT auth/RBAC, CSVs, admin APIs)
- DB/WH: SQLite for dev, PostgreSQL as documented target (star schema)
- ML: pandas, numpy, scikit-learn, joblib (5 features; real metrics)
- AI: provider-agnostic LLM (Ollama preferred) with deterministic fallback

## Setup (local)

Prerequisites: Python 3.11 or newer, Node.js/npm, and Git. See [setup](docs/SETUP.md) for environment configuration.

1. Create and activate a backend virtual environment, then install `backend/requirements.txt`.
2. Install frontend dependencies with `cd frontend; npm install`.
3. Copy `.env.example` to a local `.env`; replace `SECRET_KEY`, `AUTH_ADMIN_PASSWORD`, and `AUTH_ANALYST_PASSWORD` with private values before the first start. The example file contains placeholders only. Keep `.env` private.
4. Start the API from `backend` with `python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`.
5. Start the UI from `frontend` with `npm run dev -- --host 127.0.0.1 --port 5173`.
6. The optional warehouse ETL reads local Olist CSVs from `OLIST_DIR`; review the dataset notes below before running it.

## Data provenance and limitations

The original [Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) is licensed CC BY-NC-SA 4.0. Download it from the official source and review its terms before use. This repository does not redistribute the raw tables: they contain stable identifiers, granular location fields, and review text. Attribute Olist when using the source data and follow the license's noncommercial and share-alike terms.

The local extended package used in forecasting experiments is not included. Its generation summary declares a synthetic extension beginning 2018-10-18; that package does not independently authenticate earlier records, and its original transaction-generation procedure is not present here. The seasonal demo's working series and model artifacts are local-only. Its 2025 outputs use a model cutoff of 2024-12-31 and are historical estimates, not current forecasts or real-world accuracy evidence.

## Testing
```powershell
cd backend; python -m pytest -q          # Isolated API/integration tests; optional reference fixtures
cd ml;      python -m pytest -q          # ML pipeline tests
cd frontend; npm test                    # Component/API tests (Vitest)
cd frontend; npm run e2e                 # Real browser workflows (Playwright)
cd frontend; npm run lint; npm run build
```

## Roles (two only â€” see `docs/RBAC.md`)
| Role | Can do | Cannot do |
|---|---|---|
| `analyst` | Dashboard, analytics, ML models + metrics, AI insights, reports & CSV exports | Users, roles, system health, ETL, warehouse/ML admin, settings |
| `admin` | Everything above **plus** platform administration | â€” |

First-run admin and analyst accounts require private passwords configured in the local environment; no default login credentials are distributed.
There is no viewer role; legacy `viewer` accounts become `analyst`. Authorization
is enforced by the backend (frontend guards are UX only).

## Docs
See `docs/` for architecture, API, analytics, data, database, ML, PostgreSQL,
RBAC, setup and testing documentation.

## Notes
- Folder/ZIP bundles accept a 200 MiB payload and separate bounded processing
  budgets. Recognized Olist bundles support an order-grain Dashboard; see
  `docs/UNIVERSAL_DATASETS.md`.
- ML and website were developed in parallel and integrated via documented interfaces.
- AI assistant uses authorized backend data only (no arbitrary SQL).
- `AUTH_REQUIRED` and `VITE_AUTH_REQUIRED` default to `true` (login required).
- No secrets or raw dataset committed.
