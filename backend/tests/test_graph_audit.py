"""Full-scope counts must not inherit display limits from ranking charts."""
from sqlalchemy import text
from app.analytics import metrics
from app.analytics.filters import Filters
from tests.test_forensic_correctness import warehouse  # noqa: F401


def test_category_kpi_counts_beyond_top_twenty(warehouse):
    for index in range(21):
        warehouse.execute(text("""INSERT INTO fact_order_items
            (order_id,order_item_id,product_id,seller_id,customer_unique_id,purchase_date,price,freight_value,product_category_name_en)
            VALUES ('test-0',:item,'test-product','test-seller','test-customer','2025-01-01',1,0,:category)"""),
            {'item': index+2, 'category': f'category-{index:02}'})
    result = metrics.products(warehouse, Filters())
    assert len(result['by_category']) == 20
    assert result['kpis']['category_count'] == 22
    filtered = metrics.products(warehouse, Filters(category='books'))
    assert filtered['kpis']['category_count'] == 1


def test_seller_leaders_are_ranked_before_chart_limit(warehouse):
    warehouse.execute(text('UPDATE fact_order_items SET price=1'))
    warehouse.execute(text("UPDATE fact_orders SET purchase_date='2024-01-01' WHERE order_id='test-0'"))
    warehouse.execute(text("UPDATE fact_order_items SET seller_id='historical-leader',price=10000,purchase_date='2024-01-01' WHERE order_id='test-0'"))
    rows = metrics.top_sellers_series(warehouse, Filters(), top_n=1, limit=1)
    assert rows == [{'period':'2024-01','seller':'historical-leader','revenue':10000}]
