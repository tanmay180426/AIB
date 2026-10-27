# API_DOCUMENTATION.md

## Base
- Base URL: `http://localhost:8000`
- Auth: JWT Bearer. Obtained via `POST /api/auth/login` (OAuth2 form).
- Backend enforces RBAC for every request. `AUTH_REQUIRED` defaults to
  **true**: business routers require an authenticated analyst/admin token and
  `/api/admin` requires admin. Development flags do not bypass the BI/Admin role
  dependencies; authenticated access remains required for those routes.

## Auth — `/api/auth`
| Method | Path | Access | Notes |
|---|---|---|---|
| POST | `/login` | public | form: username, password -> `{access_token, refresh_token, token_type, user}` |
| POST | `/refresh` | public (refresh token) | body `{refresh_token}` -> new access token; inactive users rejected |
| GET | `/me` | any authenticated | current user |
| POST | `/register` | admin | create a user `{username, password, role}` (role: `analyst`\|`admin`) -> 201 |
| GET | `/admin/users` | admin | list users (no hashes) |

## Users — `/api/users`
| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/me` | any authenticated | current profile |
| PATCH | `/me` | any authenticated | change own password (`current_password`, `new_password`) |
| GET | `""` | admin | list all users |
| PATCH | `/{username}/role` | admin | change role (`analyst`\|`admin`); `409` if it would leave zero active admins |
| PATCH | `/{username}/status` | admin | activate/deactivate; last active admin protected |
| GET | `/roles/metadata` | admin | authoritative two-role permission metadata |

## Reports (CSV export) — `/api/reports`
| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/export?report=<name>` | analyst/admin | streams `text/csv` |

Supported `report` values: `kpis`, `monthly_revenue`, `revenue_by_category`,
`orders_by_status`, `dataset_rows`, `numeric_statistics` (last two for uploaded
tabular datasets). Shared filters apply; unknown reports return `404`.

## Admin — `/api/admin` (admin only; analyst → `403`)
| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/system/status` | admin | app/version/database/uptime summary |
| GET | `/data/etl/status` | admin | warehouse row counts + `loaded` flag |
| GET | `/warehouse/status` | admin | star-schema table counts + load state |
| GET | `/ml/status` | admin | artifact/model inventory for administration |
| GET | `/settings` | admin | non-secret configuration (secrets never returned) |

## Dashboard — `/api/dashboard`
| Method | Path | Notes |
|---|---|---|
| GET | `/kpis` | shared validated analytics filters |
| GET | `/monthly-revenue` | 24 monthly points |
| GET | `/revenue-by-category` | top categories |
| GET | `/orders-by-status` | order status counts |

## Analytics — `/api/analytics`
| Method | Path | Notes |
|---|---|---|
| GET | `/filters` | selected dataset's valid filter controls |
| GET | `/overview` | dashboard aggregates |
| GET | `/sales` | sales KPIs, series and distributions |
| GET | `/orders` | order KPIs, statuses and series |
| GET | `/products` | product KPIs, category rankings |
| GET | `/customers` | customer KPIs, behavior/geography |
| GET | `/sellers` | seller KPIs and rankings |
| GET | `/delivery` | delivery KPIs and distributions |

Detailed commerce payloads above describe the reference adapter. Uploads return
dataset-scoped observed metrics or `not_applicable` with missing-field reasons.
See ANALYTICS.md and UNIVERSAL_DATASETS.md for the shared filters and semantics.

## Datasets — `/api/datasets`

Admin and Analyst can list, upload, inspect, select, correct schema and delete
their own datasets. Routes: `GET ""`, `POST /upload`, `GET /{id}`,
`POST /{id}/select`, `PATCH /{id}/schema`, `DELETE /{id}`. The registered reference
is shared/read-only. BI requests accept `X-Dataset-ID` or `dataset_id`; conflicting
IDs fail. Absent IDs use saved selection. Unauthorized private IDs return 403,
failed datasets 409, deleted IDs 404; none silently revert to reference data.

## ML — `/api/ml`
| Method | Path | Notes |
|---|---|---|
| GET | `/status` | per-feature real status + metrics |
| GET | `/models/{name}` | full metadata for one model |
| GET | `/forecast?periods=N&target=orders` | selected daily orders/revenue forecast; target `orders` or `revenue`, 1–90 periods |
| GET | `/segments/customers` | cluster sizes/means |
| GET | `/product-segmentation` | saved scaler/KMeans on compatible selected product features |
| GET | `/anomalies` | anomaly metrics + top days |
| POST | `/predict/sales` | order item revenue prediction |

## Insights (AI) — `/api/insights`
| Method | Path | Notes |
|---|---|---|
| POST | `/query` | body `{question, context_limit?}`; filters in query parameters; answer, sources and dataset ID |
| GET | `/status` | configured provider, model, `reachable` flag, fallback note |

## Contracts
- Consistent error shape: `{detail: ...}` (FastAPI default) or `{error:{code,message}}`.
- Filters validated; no arbitrary SQL from client/LLM.
- ML endpoints return `503` if the artifact is unavailable, with honest status.
- Compatibility is checked first; incompatible datasets return reasoned
  `not_applicable` without running a model. Offline metrics describe training/reference evaluation.

## Security
- RBAC enforced backend (two roles: analyst for business routes, admin for
  administration routes); CORS restricted to the frontend origin; input
  validation.
- Passwords stored as bcrypt hashes only; no secrets exposed in
  responses/logs (settings endpoint returns configuration, never credentials).
- Newly assigned passwords must fit within 72 UTF-8 bytes. Existing bcrypt hashes
  remain verifiable without automatic migration or account resets.
