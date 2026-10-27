"""Disposable test storage; an optional reference is read only and never reused."""
from contextlib import contextmanager, closing
from datetime import date, timedelta
from pathlib import Path
import sqlite3
import tempfile

WAREHOUSE_TABLES = {'dim_customer', 'dim_product', 'dim_seller', 'dim_date', 'fact_orders', 'fact_order_items'}


@contextmanager
def test_storage(reference=None):
    with tempfile.TemporaryDirectory(prefix='sem5-pytest-') as directory:
        path = Path(directory) / 'tests.db'
        if reference:
            original = Path(reference).resolve(strict=True)
            with closing(sqlite3.connect(f'file:{original.as_posix()}?mode=ro', uri=True)) as source, closing(sqlite3.connect(path)) as copy:
                source.backup(copy)
                # Only the reference warehouse is relevant. Application users,
                # selections and private uploads must not enter the test run.
                tables = copy.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                for (name,) in tables:
                    if name not in WAREHOUSE_TABLES and not name.startswith('sqlite_'):
                        copy.execute('DROP TABLE "' + name.replace('"', '""') + '"')
                copy.commit()
        yield path


def seed_synthetic_warehouse(engine):
    from sqlalchemy.orm import Session
    from app.database.session import Base
    from app.models.warehouse import DimCustomer, DimProduct, DimSeller, DimDate, FactOrders, FactOrderItems
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(DimCustomer(customer_unique_id='test-customer', customer_state='SP'))
        db.add(DimProduct(product_id='test-product', product_category_name_en='books', product_weight_g=100))
        db.add(DimSeller(seller_id='test-seller', seller_state='SP'))
        for i in range(45):
            day = date(2025, 1, 1) + timedelta(days=i)
            db.add(DimDate(date_key=day, year=day.year, month=day.month, day=day.day,
                           quarter=(day.month-1)//3+1, weekday=day.weekday()))
            db.add(FactOrders(order_id=f'test-{i}', customer_unique_id='test-customer', purchase_date=day,
                order_status='delivered', item_revenue=10+i, freight_value=2, payment_type='credit_card',
                payment_installments=1, review_score=5, delivery_days=2, delivered_customer_date=day+timedelta(days=2),
                estimated_delivery_date=day+timedelta(days=3), is_late=False))
            db.add(FactOrderItems(order_id=f'test-{i}', order_item_id=1, product_id='test-product',
                seller_id='test-seller', customer_unique_id='test-customer', purchase_date=day,
                price=10+i, freight_value=2, product_category_name_en='books'))
        db.commit()
