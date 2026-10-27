# KPIs (verified definitions and values)

All KPIs are computed from the loaded Olist warehouse via
`backend/app/analytics/kpis.py` and exposed at `GET /api/dashboard/kpis`.
Values are real data outputs — nothing is fabricated.

| KPI | Definition | Implementation |
|---|---|---|
| Total Orders | Count of rows in `fact_orders` (one row per order) | `COUNT(*)` |
| Total Revenue | Sum of item prices | `SUM(item_revenue)` — item-level price only, excludes freight |
| Total Freight | Sum of freight charges | `SUM(freight_value)` |
| Avg Order Value | Total revenue / total orders | `total_revenue / total_orders` |
| Unique Customers | Distinct `customer_unique_id` | `COUNT(DISTINCT customer_unique_id)` |
| Items Sold | Count of order lines (line grain) | `COUNT(*)` on `fact_order_items` |
| Products Sold | Distinct `product_id` sold | `COUNT(DISTINCT product_id)` |
| Active Sellers | Distinct `seller_id` with sales | `COUNT(DISTINCT seller_id)` |
| Avg Review Score | Mean `review_score` where present | `AVG(review_score)` |
| Avg Delivery Days | `delivered_customer_date - purchase_timestamp` in days; NULLs excluded | `AVG(delivery_days)` |

## Notes / limitations
- Revenue uses item prices only; cross-check against `order_payments.payment_value`
  is possible but payments can include vouchers/installments. The two differ slightly.
- Historical dataset only (Sep 2016 – Oct 2018). Not live data.
- No profit, margin, or inventory KPIs because the dataset does not support them.
- Delivery metrics exclude ~2,965 orders without a delivered timestamp.

## Verified baseline (full dataset, no filters)
Produced by the ETL + KPI service on the local dataset:

- Total Orders: 99,441
- Total Revenue: R$ 13,591,643.70
- Total Freight: R$ 2,251,909.54
- Avg Order Value: R$ 136.68
- Unique Customers: 96,096
- Items Sold: 112,650
- Products Sold: 32,951
- Active Sellers: 3,095
- Avg Review Score: 4.087
- Avg Delivery Days: 12.56
