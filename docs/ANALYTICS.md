# Analytics Documentation

## Shared Filter System

The BI section uses a shared filter system (`frontend/src/hooks/useFilters.ts` and `frontend/src/components/FilterBar.tsx`). These filters are synchronized with the URL query parameters and sent directly to the backend API.

Supported filters:
- `date_from`, `date_to`: ISO date strings (e.g. `2018-01-01`).
- `category`: Product category name.
- `customer_state`, `seller_state`: 2-letter state abbreviations.
- `order_status`: Order status string.
- `payment_type`: Payment type string.
- `review_score`: Integer from 1 to 5.
- `grain`: `day`, `week`, `month`, `quarter`, `year` on supported series endpoints.
- `column_filters`: validated JSON field/value pairs for uploaded datasets.

## Backend Endpoints

All endpoints are mounted under `/api/analytics` and require authenticated access (`auth` or `analyst_auth`).

- `GET /api/analytics/filters`: Returns valid options for categories, states, dates, and review scores to populate the filter bar dropdowns.
- `GET /api/analytics/overview`: High-level metrics, monthly revenue series, top states, top categories.
- `GET /api/analytics/sales`: Revenue-focused KPIs, revenue series, top products by revenue.
- `GET /api/analytics/orders`: Order-focused KPIs, order status distribution, items per order.
- `GET /api/analytics/customers`: Customer behavior KPIs, repeat rates, spend distribution, order frequency.
- `GET /api/analytics/products`: Product performance KPIs, revenue and quantity by category.
- `GET /api/analytics/sellers`: Seller performance KPIs, revenue by seller state, active seller counts.
- `GET /api/analytics/delivery`: Delivery times (average, median), late rates, delivery duration distribution.

## Frontend Usage

Analytics pages (`/analytics/sales`, `/analytics/orders`, etc.) are mounted under `AnalyticsLayout.tsx`.
They consume the `useFilters()` hook to retrieve the current filter state and pass it to API calls (e.g. `getAnalyticsSales(filters)`). Data is visualized using Recharts components. All KPIs are standardized using the shared `KpiCard` component.

These detailed business measures describe the reference warehouse adapter.
Uploads use the same routes and metric layer with observed numeric summaries,
entity counts, distributions and trends. Sections without required semantic fields
return reasoned unavailable states. Active dataset ownership is checked before
queries; switching clears old filters and content. See UNIVERSAL_DATASETS.md.
