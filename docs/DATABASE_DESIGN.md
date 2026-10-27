# DATABASE_DESIGN.md (draft)

## Purpose
Design analytical warehouse (star schema) aligned to Olist. Read-only raw from external olist dir; ETL loads into PostgreSQL warehouse.

## Core entities (from dataset)
- customers, geolocation, orders, order_items, order_payments, order_reviews, products, sellers, product_category_name_translation

## Facts (proposed)
- fact_order_items (grain: 1 row per order_item_id). Measures: price, freight_value. Dimensions: order, product, seller, date (purchase/shipping), customer.
- fact_order_payments (grain: 1 row per payment line; order can have multiple payments). Measures: payment_value, installments.
- fact_orders (optional aggregate) or derive from items/payments. Prefer fact_order_items as primary for revenue.

## Dimensions (proposed)
- dim_date (date key, day/month/quarter/year, weekday)
- dim_customer (customer_unique_id level + location)
- dim_product (product_id + category_en, dims)
- dim_seller (seller_id + location)
- dim_location (zip prefix normalized city/state)
- dim_order_status (status lookup)

## Keys
- fact_order_items: order_item_id PK, order_id FK, product_id FK, seller_id FK, customer_id FK (via order), date keys.
- Surrogate keys recommended; preserve natural keys.

## Metrics (documented)
- Revenue (item-level): sum(price).
- AOV: revenue / distinct orders (define consistently).
- Freight: sum(freight_value).
- Delivery time (days): order_delivered_customer_date - order_purchase_timestamp (exclude nulls).
- Repeat customers: count distinct orders by customer_unique_id >1.

## Notes
- Do not claim margin/profit/inventory.
- Historical dataset only.
- Referential integrity enforced on load; handle missing delivery timestamps by documented rules.
- No PII beyond business identifiers present.
