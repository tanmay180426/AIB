# RBAC.md

Two roles only: **admin** and **analyst**. There is no viewer role.

```text
ANALYST = Business Intelligence
ADMIN   = Business Intelligence + Platform Administration
```

## Permission matrix (source of truth)

| Functionality | ADMIN | ANALYST |
|---|:---:|:---:|
| Dashboard | YES | YES |
| Sales Analytics | YES | YES |
| Order Analytics | YES | YES |
| Customer Analytics | YES | YES |
| Product Analytics | YES | YES |
| Seller Analytics | YES | YES |
| Delivery Analytics | YES | YES |
| ML Forecasting | YES | YES |
| Sales Prediction | YES | YES |
| Customer Segmentation | YES | YES |
| Product Segmentation | YES | YES |
| Anomaly Detection | YES | YES |
| ML Metrics | YES | YES |
| AI Business Insights | YES | YES |
| Reports | YES | YES |
| Export Reports | YES | YES |
| User Management | YES | NO |
| Role Management | YES | NO |
| System Health | YES | NO |
| ETL / Data Pipeline Management | YES | NO |
| Warehouse Administration | YES | NO |
| ML Administration | YES | NO |
| System Settings | YES | NO |

## Roles

### Analyst — Business Intelligence
Dashboard, sales/order/customer/product/seller/delivery analytics, all ML
features and their metrics, AI business insights, reports and CSV exports.
The analyst cannot administer users, roles, the warehouse, the pipeline, ML
artifacts or platform settings.

### Admin — Business Intelligence + Platform Administration
Everything the analyst can do, plus user management, role management, system
health, ETL/data pipeline status, warehouse administration, ML administration
and system settings.

## Implementation (backend)

- `app/core/security.py` — bcrypt hashing + HS256 JWT (access + refresh tokens,
  `type` claim distinguishes them).
- `app/models/user.py` + `app/services/users.py` — users in the `app_user`
  table. Single source of truth for the role model:
  - `VALID_ROLES = {analyst, admin}`, `ROLE_RANK = {analyst: 1, admin: 2}`
  - `validate_role()` rejects anything else (`viewer`, `guest`, …)
  - seed accounts: `admin` (admin) and `analyst` (analyst)
  - legacy migration: existing `viewer`/`user` rows are rewritten to `analyst`
    (never promoted to admin)
  - `LastAdminError` — the last remaining admin cannot be demoted
- `app/api/deps.py`
  - `get_current_user` — 401 without a valid Bearer token
  - `require_bi_user` — analyst/admin (applied to dashboard, analytics, ML,
    insights, reports routers)
  - `require_roles(*roles)` / `require_admin` — 403 when insufficient
  - `auth_gate` — global gate; with `AUTH_REQUIRED` (default **true**) every
    protected router rejects anonymous callers with 401
- `app/main.py` — router-level wiring:
  - business routers → `auth_gate` + `require_bi_user`
  - `/api/admin` → `auth_gate` + `require_admin`
- `app/api/routes/users.py` — `PATCH /api/users/{username}/role` is admin-only,
  validates the role server-side and returns **409** for the last-admin case.
- `app/api/routes/auth.py` — `POST /api/auth/register` is admin-only and only
  accepts `analyst` or `admin`.
- `app/api/routes/reports.py` — CSV export requires an authenticated BI user;
  every report is available to both roles.
- `app/ai_assistant/context.py` — the assistant receives business aggregates
  only; administrative data and secrets are never part of its context.
- `app/api/routes/admin.py` — admin only:
  - `GET /api/admin/system/status` (health; no secrets)
  - `GET /api/admin/data/etl/status`
  - `GET /api/admin/warehouse/status`
  - `GET /api/admin/ml/status`
  - `GET /api/admin/settings` (non-secret configuration)

Roles are always read from the database per request (`get_current_user`), never
trusted from the client. The JWT `role` claim is informational only, so a role
change takes effect immediately.

## Implementation (frontend)

- `services/auth.ts` — `isAdmin()`, `isAnalyst()`, `isAdminOrAnalyst()`;
  `isAuthRequired()` defaults to **true** (explicit `VITE_AUTH_REQUIRED=false`
  opts out). Unknown/retired roles in localStorage are ignored.
- `components/RequireAuth.tsx` — redirects anonymous users to `/login`.
- `components/RequireAdmin.tsx` — administration guard wired into the route
  config (`routes.tsx`); it asks `GET /api/users/me` for the authoritative role,
  reconciles the cached copy, and renders `AccessDenied` instead of admin
  content while/after loading. It never grants access from local state:
  `401` sends the user through the login flow, and any other failure (backend
  unreachable, 5xx) shows a retryable "could not verify access" state instead
  of trusting localStorage.
- `components/AccessDenied.tsx` — “Access Restricted” + Back to Dashboard.
- `components/common/Nav.tsx` — Business Intelligence links for everyone, a
  separate Administration group only for admins.
- `routes/routes.tsx` — `/admin/*` routes nested under `RequireAdmin`.
- `pages/admin/*` — Users, System Health, Data/ETL, Warehouse, ML
  Administration, System Settings.

Hiding navigation is UX only; the backend is what enforces authorization.

Inactive users cannot log in, use access tokens, or refresh sessions. Demotion
and deactivation preserve at least one active Admin; inactive Admin records do
not satisfy that requirement. Regression coverage is in test_release_security.py.

## Verification

```powershell
cd backend; python -m pytest -q        # includes tests/test_rbac.py
cd frontend; npm test                  # RequireAdmin + role helpers
cd frontend; npm run e2e               # analyst/admin browser flows
```

`backend/tests/test_rbac.py` checks every row of the matrix with direct
authenticated requests: analyst → 200 on business endpoints, 403 on admin
endpoints; admin → 200 everywhere; anonymous → 401.
