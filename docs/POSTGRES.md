# POSTGRES.md — running against PostgreSQL

The backend defaults to a local SQLite database for development
(`DATABASE_URL=sqlite:///./sem5.db`). The schema and queries are written to be
portable, so switching to PostgreSQL is configuration-only.

## 1. Provision a database
Using Docker (recommended for local parity):

```powershell
docker run --name sem5-pg -e POSTGRES_PASSWORD=postgres `
  -e POSTGRES_DB=sem5_bi -p 5432:5432 -d postgres:16
```

## 2. Set the connection string
In `backend/.env` (or the environment):

```
DATABASE_URL=postgresql+psycopg2://postgres:postgres@localhost:5432/sem5_bi
```

The `psycopg2-binary` driver is already in `backend/requirements.txt`.

## 3. Create the schema and load data
```powershell
cd backend
python -m app.services.etl      # creates tables (SQLAlchemy) and loads Olist
```

The ETL uses SQLAlchemy `create_all` + typed columns, so no manual DDL is
required.

## 4. Run the API / tests
```powershell
python -m uvicorn app.main:app --reload
python -m pytest -q
```

## Portability notes
- **Date formatting**: `app/analytics/kpis.py:month_expr` emits dialect-aware
  SQL — `strftime('%Y-%m', …)` for SQLite and `to_char(…, 'YYYY-MM')` for
  PostgreSQL (plus MySQL/MariaDB `date_format`). No other query is
  dialect-specific.
- **Types**: the warehouse uses `Date`, `Float`, `Integer`, `Boolean`, `String`
  — all natively supported by PostgreSQL.
- **Case sensitivity**: PostgreSQL folds unquoted identifiers to lower case;
  table/column names here are already lower snake_case, so no changes needed.
- **Idempotency**: re-running the ETL clears and reloads fact/dim tables, so it
  is safe to repeat against an existing database.
