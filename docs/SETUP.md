# Local setup

This guide covers a local development setup. Configure all credentials privately
before starting the backend; the repository does not provide default accounts.

## Runtime and dependencies

Use a supported Python version, Node.js/npm and the repository dependency files.
Docker and PostgreSQL are optional. From the repository root:

```powershell
cd backend
python -m pip install -r requirements-dev.txt
cd ../ml
python -m pip install -r requirements-dev.txt
cd ../frontend
npm ci
cd ..
```

## Environment

Copy `.env.example` to an ignored `.env` without overwriting an existing file.
Replace every placeholder with private values, including a unique signing key
and first-run admin and analyst passwords. Existing users keep their stored
password hashes; changing seed settings does not reset existing accounts. Never
commit `.env`, private uploads, databases or raw datasets.

## API and frontend

In one terminal, from the repository root:

```powershell
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

In another terminal:

```powershell
cd frontend
npm run dev
```

UI: http://localhost:5173. API health: http://localhost:8000/health.
API docs: http://localhost:8000/docs. Both Admin and Analyst can upload/select
private datasets in Dataset Manager. No reference warehouse or training is
required for uploaded analytics; missing model artifacts are reported honestly.

## Optional Olist reference and existing models

The Olist source tables are not included. Obtain them from the official source
and review its license before use. Set `OLIST_DIR` to a local copy, then from
`backend` explicitly run `python -m app.services.etl` to load the reference.
The ETL may replace the local warehouse; back it up and review the provenance
policy before running. Model binaries are not included, and missing models are
reported as unavailable. Training is an explicit local operation and is not
performed by upload or application startup.

## Verification

Folder/ZIP uploads accept a 200 MiB aggregate payload, with separate expansion
and row/cell/time budgets documented in UNIVERSAL_DATASETS.md. Run one API worker
for local imports. Large uploads use status-tracked jobs with cancellation and
browser resume. Existing `.env` values override defaults; verify the effective
values at `/api/datasets/upload-limits` after restart. ML artifacts must be at
`ML_MODELS_DIR` (default `ml/models`), not a metadata-only fixture directory.
Uploading data never trains or replaces a model.

Run backend tests with `python -m pytest -q` from `backend`, ML tests from `ml`,
and frontend checks from `frontend` with `npm test`, `npm run lint`, and
`npm run build`. Browser tests use `npm run e2e` when Playwright browsers are
available. Reference-specific checks require locally obtained data; model
inference tests require local model artifacts. Upload and provenance boundaries
are documented in UNIVERSAL_DATASETS.md.
